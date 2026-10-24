import logging
import subprocess
import sys
from pathlib import Path

from rich.table import Table

from commitrocket.batching import MIB
from commitrocket.config import ConfigError, find_config
from commitrocket.errors import CommitRocketError, GitError
from commitrocket.filters import IGNORE_FILE
from commitrocket.git import (
    find_large_unpushed_blobs,
    get_file_size,
    get_pending_files,
    get_staged_files,
    get_unpushed_commits,
    resolve_target,
    run_git,
)
from commitrocket.journal import Journal
from commitrocket.lfs import HOST_LIMIT_MIB, is_lfs_available
from commitrocket.logs import default_log_dir

logger = logging.getLogger(__name__)

PASS, WARN, FAIL, SKIP = "pass", "warn", "fail", "skip"
STYLES = {PASS: "green", WARN: "yellow", FAIL: "bold red", SKIP: "dim"}
NETWORK_TIMEOUT = 60


def _first_line(text):
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return lines[0] if lines else "no details"


def _remote_check(repo, args, label):
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            text=True,
            capture_output=True,
            timeout=NETWORK_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return FAIL, f"{label} timed out after {NETWORK_TIMEOUT} s"
    if result.returncode != 0:
        return FAIL, _first_line(result.stderr or result.stdout)
    return PASS, label


def _check_log_dir():
    folder = default_log_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".doctor-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return WARN, f"{folder} is not writable ({exc})"
    return PASS, str(folder)


def collect_checks(repo, remote=None, branch=None, offline=False, config_path=None):
    """Run every check and return [(status, name, detail), ...]."""
    results = []

    def add(status, name, detail):
        results.append((status, name, detail))
        logger.info("doctor: %s %s - %s", status, name, detail)

    add(PASS, "Python", sys.version.split()[0])

    try:
        git_version = subprocess.run(
            ["git", "--version"], text=True, stdout=subprocess.PIPE
        ).stdout.strip()
    except OSError:
        add(FAIL, "Git", "git was not found on PATH")
        return results
    add(PASS, "Git", git_version)

    if is_lfs_available():
        add(PASS, "git-lfs", "installed")
    else:
        add(WARN, "git-lfs", "not installed (needed only for --use-lfs)")

    try:
        path, values = find_config(repo, config_path)
        detail = f"{path} ({len(values)} setting(s))" if path else "none (defaults)"
        add(PASS, "Config file", detail)
    except ConfigError as exc:
        add(FAIL, "Config file", str(exc))

    status, detail = _check_log_dir()
    add(status, "Log folder", detail)

    try:
        root = Path(run_git(repo, "rev-parse", "--show-toplevel").stdout.strip())
    except (GitError, OSError):
        add(FAIL, "Repository", f"{repo} is not inside a Git repository")
        return results
    add(PASS, "Repository", str(root))

    local_branch = run_git(root, "branch", "--show-current").stdout.strip()
    if not local_branch:
        add(FAIL, "Branch", "detached HEAD; check out a branch")
        return results
    add(PASS, "Branch", local_branch)

    try:
        target = resolve_target(root, local_branch, remote, branch)
    except CommitRocketError as exc:
        add(FAIL, "Push target", str(exc))
        return results
    add(PASS, "Push target", target.label)

    if offline:
        add(SKIP, "Remote access", "skipped (--offline)")
        add(SKIP, "Push permission", "skipped (--offline)")
    else:
        status, detail = _remote_check(
            root, ["ls-remote", target.remote, "HEAD"], "remote reachable"
        )
        add(status, "Remote access", detail)
        status, detail = _remote_check(
            root,
            ["push", "--dry-run", target.remote, target.refspec],
            "push accepted (dry run)",
        )
        add(WARN if status == FAIL else status, "Push permission", detail)

    staged = get_staged_files(root)
    entry = Journal(root).read()
    if staged and not (entry and set(staged) <= set(entry["files"])):
        add(WARN, "Staged files", f"{len(staged)} file(s) staged; the run would stop")
    elif staged:
        add(PASS, "Staged files", f"{len(staged)} file(s) left by an interrupted run")
    else:
        add(PASS, "Staged files", "none")

    try:
        unpushed = get_unpushed_commits(root, target.revs)
        large = find_large_unpushed_blobs(root, HOST_LIMIT_MIB * MIB, target.revs)
    except GitError:
        add(WARN, "Unpushed commits", "could not be inspected (no commits yet?)")
    else:
        if large:
            add(
                WARN,
                "Unpushed commits",
                f"{len(unpushed)} commit(s) contain files over "
                f"{HOST_LIMIT_MIB} MiB; run 'git reset --mixed {target.label}'",
            )
        else:
            add(PASS, "Unpushed commits", f"{len(unpushed)} (will be pushed first)")

    ignore = root / IGNORE_FILE
    add(PASS, IGNORE_FILE, "present" if ignore.is_file() else "not used")

    pending = get_pending_files(root)
    big = [p for p in pending if get_file_size(root, p) > HOST_LIMIT_MIB * MIB]
    if big:
        add(
            WARN,
            "Pending files",
            f"{len(pending)} file(s), {len(big)} over {HOST_LIMIT_MIB} MiB "
            "(use --use-lfs)",
        )
    else:
        add(PASS, "Pending files", f"{len(pending)} file(s)")

    return results


def run_doctor(
    console, repo, remote=None, branch=None, offline=False, config_path=None
):
    """Print a health report. Returns 1 if any check failed, else 0."""
    results = collect_checks(repo, remote, branch, offline, config_path)

    table = Table(title="CommitRocket doctor", show_lines=False)
    table.add_column("Status")
    table.add_column("Check")
    table.add_column("Details", overflow="fold")
    for status, name, detail in results:
        table.add_row(f"[{STYLES[status]}]{status.upper()}[/]", name, detail)
    console.print(table)

    failed = [name for status, name, _ in results if status == FAIL]
    warned = [name for status, name, _ in results if status == WARN]
    if failed:
        console.print(f"\n[bold red]{len(failed)} check(s) failed.[/bold red]")
        return 1
    if warned:
        console.print(f"\n[yellow]OK with {len(warned)} warning(s).[/yellow]")
    else:
        console.print("\n[bold green]All checks passed.[/bold green]")
    return 0
