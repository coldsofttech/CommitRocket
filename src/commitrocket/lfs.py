import os
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

from commitrocket.errors import CommitRocketError
from commitrocket.git import get_file_size, run_git
from commitrocket.security import has_control_chars

# Git hosts reject pushes containing files larger than this.
HOST_LIMIT_MIB = 100

# Files above this size go through LFS by default (--lfs-threshold-mib; 0 = all).
LFS_THRESHOLD_MIB = HOST_LIMIT_MIB

# Files that must stay ordinary blobs even when every file goes through LFS.
LFS_EXCLUDED = (".gitattributes", ".gitignore", ".lfsconfig")


def find_lfs_candidates(repo, files, threshold_bytes, max_bytes):
    """Files above the LFS threshold that are still within the max file size."""
    return [
        path
        for path in files
        if threshold_bytes < get_file_size(repo, path) <= max_bytes
    ]


def attribute_line(path):
    """A .gitattributes-style rule that sends exactly this file through LFS."""
    if has_control_chars(path):
        # A newline here would let a file name add rules of its own.
        raise CommitRocketError(
            f"Cannot create an LFS rule for {path!r}: the file name contains "
            "control characters. Rename the file and try again."
        )
    glob_escaped = re.sub(r"([*?\[\]\\])", r"\\\1", path)
    quoted = glob_escaped.replace("\\", "\\\\").replace('"', '\\"')
    return f'"/{quoted}" filter=lfs diff=lfs merge=lfs -text'


def committed_rule_lines(paths):
    """Rules for .gitattributes: one per file extension, exact path if it has none.

    Extension rules also cover future files of the same type.
    """
    lines = set()
    for path in paths:
        pure = PurePosixPath(path)
        if pure.name in LFS_EXCLUDED:
            continue
        suffix = pure.suffix
        if suffix and not re.search(r"[\s*?\[\]\\\"]", suffix):
            lines.add(f"*{suffix} filter=lfs diff=lfs merge=lfs -text")
        else:
            lines.add(attribute_line(path))
    return sorted(lines)


def all_files_rules():
    """Rules sending every file through LFS, except the Git config files."""
    rules = ["* filter=lfs diff=lfs merge=lfs -text"]
    rules += [f"{name} !filter !diff !merge !text" for name in LFS_EXCLUDED]
    return rules


def is_lfs_available():
    result = subprocess.run(["git", "lfs", "version"], capture_output=True)
    return result.returncode == 0


def install_command():
    """Package-manager command that installs git-lfs, or None if unsupported."""
    if sys.platform == "win32" and shutil.which("winget"):
        return [
            "winget",
            "install",
            "--id",
            "GitHub.GitLFS",
            "-e",
            "--accept-source-agreements",
            "--accept-package-agreements",
        ]
    if sys.platform == "darwin" and shutil.which("brew"):
        return ["brew", "install", "git-lfs"]
    if sys.platform.startswith("linux") and shutil.which("apt-get"):
        command = ["apt-get", "install", "-y", "git-lfs"]
        if os.geteuid() != 0 and shutil.which("sudo"):
            command.insert(0, "sudo")
        return command
    return None


def ensure_git_lfs(console, force):
    """Make sure the git-lfs binary is available, installing it if needed."""
    if is_lfs_available():
        return

    command = install_command()
    if command is None:
        raise CommitRocketError(
            "git-lfs is not installed and no supported package manager was "
            "found. Install it from https://git-lfs.com and try again."
        )

    if not force:
        answer = (
            console.input(
                "[yellow]git-lfs is not installed. Run "
                f"'{' '.join(command)}'? [y/N][/yellow] "
            )
            .strip()
            .lower()
        )
        if answer not in {"y", "yes"}:
            raise CommitRocketError("git-lfs is required for --use-lfs.")

    console.print("[bold cyan]Installing git-lfs...[/bold cyan]")
    if subprocess.run(command).returncode != 0:
        raise CommitRocketError("Installing git-lfs failed.")

    if not is_lfs_available():
        raise CommitRocketError(
            "git-lfs was installed but is not on PATH yet. "
            "Restart your terminal and run the command again."
        )


class LfsSession:
    """Route large files through LFS for one run, with nothing committed.

    The rules go into .git/info/attributes, which Git honours but never
    commits, and are taken back out by close().
    """

    def __init__(self, repo):
        self.repo = repo
        self.attributes_path = None
        self.original = None
        self.installed = False

    def enable(self, paths, all_files=False):
        """Route paths through LFS, or every file when all_files is set."""
        info_path = run_git(
            self.repo, "rev-parse", "--git-path", "info/attributes"
        ).stdout.strip()
        self.attributes_path = Path(self.repo) / info_path
        self.original = (
            self.attributes_path.read_bytes() if self.attributes_path.exists() else None
        )

        self.install_hooks()

        lines = all_files_rules() if all_files else map(attribute_line, paths)
        rules = "".join(f"{line}\n" for line in lines)
        existing = (self.original or b"").decode("utf-8", errors="replace")
        if existing and not existing.endswith("\n"):
            existing += "\n"

        self.attributes_path.parent.mkdir(parents=True, exist_ok=True)
        self.attributes_path.write_text(existing + rules, encoding="utf-8")

    def install_hooks(self):
        """Install LFS in this repository only, so pushes upload LFS files."""
        run_git(self.repo, "lfs", "install", "--local")
        self.installed = True

    def write_committed_rules(self, paths):
        """Append extension rules for paths to .gitattributes, to be committed.

        Returns True if the file changed.
        """
        dirty = run_git(
            self.repo, "status", "--porcelain", "--", ".gitattributes"
        ).stdout.strip()
        if dirty:
            raise CommitRocketError(
                ".gitattributes has uncommitted changes. Commit or discard "
                "them before using --lfs-commit-rules."
            )

        target = Path(self.repo) / ".gitattributes"
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        known = {line.strip() for line in existing.splitlines()}
        missing = [line for line in committed_rule_lines(paths) if line not in known]
        if not missing:
            return False

        if existing and not existing.endswith("\n"):
            existing += "\n"
        rules = "".join(f"{line}\n" for line in missing)
        target.write_text(existing + rules, encoding="utf-8")
        return True

    def close(self, uninstall_hooks=True):
        """Restore the attributes file and remove the local LFS setup.

        Pass uninstall_hooks=False to keep the hooks, which unpushed commits
        containing LFS files still need to upload their data.
        """
        if self.attributes_path is not None:
            if self.original is None:
                self.attributes_path.unlink(missing_ok=True)
            else:
                self.attributes_path.write_bytes(self.original)
            self.attributes_path = None

        if self.installed and uninstall_hooks:
            run_git(self.repo, "lfs", "uninstall", "--local", check=False)
            self.installed = False
