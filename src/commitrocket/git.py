import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from commitrocket.errors import CommitRocketError, GitError
from commitrocket.security import redact, validate_ref_part

logger = logging.getLogger(__name__)

MAX_LOGGED_OUTPUT = 2000
MAX_LOGGED_COMMAND = 500
MAX_COMMAND_CHARS = 20000


def _logged_output(result):
    text = "\n".join(part for part in (result.stdout, result.stderr) if part.strip())
    text = text.strip().replace("\0", "|")
    if len(text) > MAX_LOGGED_OUTPUT:
        text = text[:MAX_LOGGED_OUTPUT] + "... [truncated]"
    return f"\n{text}" if text else ""


def run_git(repo, *args, check=True):
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        # File names are literal: "[ab].txt" must not also match a.txt and b.txt.
        env={**os.environ, "GIT_LITERAL_PATHSPECS": "1"},
    )
    command = _shortened(" ".join(args))
    logger.debug(
        "git %s -> exit %d%s", command, result.returncode, _logged_output(result)
    )

    if check and result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip()
        raise GitError(redact(f"git {command} failed:\n{error}"))

    return result


def _shortened(command):
    """Keep logs and errors readable when a command lists thousands of files."""
    if len(command) <= MAX_LOGGED_COMMAND:
        return command
    return command[:MAX_LOGGED_COMMAND] + "... [truncated]"


def chunk_paths(paths, limit=MAX_COMMAND_CHARS):
    """Split paths into groups that fit on one command line.

    Windows allows about 32,767 characters for a whole command, so a batch with
    thousands of files cannot be passed to git in one go. Each path is counted at
    twice its length, to leave room for the quoting Windows adds.
    """
    chunk = []
    size = 0
    for path in paths:
        cost = 2 * len(path) + 3
        if chunk and size + cost > limit:
            yield chunk
            chunk = []
            size = 0
        chunk.append(path)
        size += cost
    if chunk:
        yield chunk


def add_files(repo, paths):
    """Stage the given files, however many there are."""
    for chunk in chunk_paths(paths):
        run_git(repo, "add", "--", *chunk)


def get_paths(repo, *args):
    return [path for path in run_git(repo, *args).stdout.split("\0") if path]


def get_staged_files(repo):
    return get_paths(repo, "diff", "--cached", "--name-only", "-z")


def get_pending_files(repo):
    unstaged = get_paths(repo, "diff", "--name-only", "-z")
    untracked = get_paths(repo, "ls-files", "--others", "--exclude-standard", "-z")
    return list(dict.fromkeys(unstaged + untracked))


class LocalConfig:
    """Set repository-local Git config for a run and put the old values back.

    Only the repo's own .git/config is touched, never the global config.
    """

    def __init__(self, repo):
        self.repo = repo
        self.saved = {}

    def set(self, key, value):
        if key not in self.saved:
            current = run_git(self.repo, "config", "--local", "--get", key, check=False)
            found = current.returncode == 0
            self.saved[key] = current.stdout.strip() if found else None
        run_git(self.repo, "config", "--local", key, str(value))

    def restore(self):
        for key, old in self.saved.items():
            if old is None:
                run_git(self.repo, "config", "--local", "--unset", key, check=False)
            else:
                run_git(self.repo, "config", "--local", key, old, check=False)
        self.saved.clear()


@dataclass
class PushTarget:
    """Where a run pushes to, and how to tell what is not there yet."""

    remote: str
    branch: str
    revs: list

    @property
    def ref(self):
        return f"refs/heads/{self.branch}"

    @property
    def refspec(self):
        return f"HEAD:{self.ref}"

    @property
    def label(self):
        """Display name for the target; safe to show, log, report and send."""
        return redact(f"{self.remote}/{self.branch}")


def resolve_target(repo, local_branch, remote=None, branch=None):
    """The remote branch to push to: explicit values first, then the upstream."""
    configured_remote = run_git(
        repo, "config", "--get", f"branch.{local_branch}.remote", check=False
    ).stdout.strip()
    configured_merge = run_git(
        repo, "config", "--get", f"branch.{local_branch}.merge", check=False
    ).stdout.strip()

    remote = remote or configured_remote
    if not remote:
        raise CommitRocketError(
            "No upstream configured. Configure one, or pass --remote "
            "(and optionally --branch)."
        )

    branch = branch or configured_merge.removeprefix("refs/heads/") or local_branch

    # These end up on git command lines, so they must not look like options.
    validate_ref_part(remote, "remote")
    validate_ref_part(branch, "branch")

    tracking_ref = f"refs/remotes/{remote}/{branch}"
    exists = run_git(
        repo, "rev-parse", "--verify", "--quiet", tracking_ref, check=False
    ).returncode
    if exists == 0:
        revs = [f"{tracking_ref}..HEAD"]
    else:
        # The branch was never pushed to this remote: everything the remote
        # does not already have counts as unpushed.
        revs = ["HEAD", "--not", f"--remotes={remote}"]

    return PushTarget(remote, branch, revs)


def get_remote_url(repo, remote):
    return run_git(repo, "remote", "get-url", "--", remote).stdout.strip()


def get_remote_head(repo, remote, ref):
    """Commit the remote currently has for ref, or None if it doesn't exist."""
    fields = run_git(repo, "ls-remote", "--", remote, ref).stdout.split()
    return fields[0] if fields else None


def get_unpushed_commits(repo, revs):
    """One-line summaries of local commits that are not on the remote yet."""
    return run_git(repo, "log", "--oneline", *revs).stdout.splitlines()


def find_large_unpushed_blobs(repo, threshold_bytes, revs):
    """(path, size) of blobs above the threshold in commits not yet pushed."""
    objects = run_git(repo, "rev-list", "--objects", *revs).stdout
    if not objects.strip():
        return []

    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "cat-file",
            "--batch-check=%(objecttype) %(objectsize) %(rest)",
        ],
        input=objects,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if result.returncode != 0:
        raise GitError(f"git cat-file failed:\n{result.stderr.strip()}")

    large = {}
    for line in result.stdout.splitlines():
        kind, size, path = (line.split(" ", 2) + ["", ""])[:3]
        if kind == "blob" and int(size) > threshold_bytes:
            large[path or "(unnamed)"] = int(size)
    return sorted(large.items())


def get_file_size(repo, relative_path):
    try:
        path = Path(repo) / relative_path
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0
