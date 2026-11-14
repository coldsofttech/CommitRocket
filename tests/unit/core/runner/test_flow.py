import subprocess

import pytest
from rich.console import Console

from commitrocket.core.options import RunOptions
from commitrocket.core.runner import run
from commitrocket.git.journal import Journal
from commitrocket.io.report import (
    ABORTED,
    CANCELLED,
    DRY_RUN,
    FAILED,
    INTERRUPTED,
    SUCCESS,
    RunReport,
)
from commitrocket.support.errors import CommitRocketError


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(git_repo, tmp_path):
    """A repository on main with an upstream, ready for new files."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    (git_repo / "base.txt").write_text("base")
    git(git_repo, "add", "base.txt")
    git(git_repo, "commit", "-q", "-m", "base")
    git(git_repo, "branch", "-M", "main")
    git(git_repo, "remote", "add", "origin", str(remote))
    git(git_repo, "push", "-q", "-u", "origin", "main")
    return git_repo


def options_for(repo, **values):
    values = {
        "message": "m",
        "attribution": False,
        "force": True,
        "no_push": True,
        **values,
    }
    return RunOptions(repo=str(repo), **values)


def start(repo, **values):
    options = options_for(repo, **values)
    report = RunReport(options)
    console = Console(record=True, width=120)
    code = run(console, options, report)
    return code, report, console.export_text()


def add_files(repo, count):
    for number in range(count):
        (repo / f"new{number}.txt").write_text(f"data {number}")


def commit_count(repo):
    return int(git(repo, "rev-list", "--count", "HEAD"))


def test_a_missing_repository_is_an_abort(tmp_path):
    code, report, text = start(tmp_path / "missing")
    assert code == 2
    assert report.status == ABORTED
    assert "not found" in text


def test_a_detached_head_is_an_abort(repo):
    git(repo, "checkout", "-q", "--detach")

    code, report, text = start(repo)

    assert code == 1
    assert report.status == ABORTED
    assert "Detached HEAD" in text


def test_a_branch_without_an_upstream_is_an_abort(repo):
    git(repo, "checkout", "-q", "-b", "local-only")

    code, report, text = start(repo)

    assert code == 1
    assert report.status == ABORTED
    assert "No upstream" in text


def test_pending_files_are_committed_in_batches(repo):
    add_files(repo, 2)

    code, report, _ = start(repo, limit_mib=1)

    assert code == 0
    assert report.status == SUCCESS
    assert report.total_files == 2
    assert git(repo, "log", "-1", "--format=%s") == "m #1"
    assert not Journal(repo).path.exists()


def test_the_run_pushes_unless_told_not_to(repo):
    add_files(repo, 1)

    code, _, _ = start(repo, no_push=False)

    assert code == 0
    assert git(repo, "rev-parse", "origin/main") == git(repo, "rev-parse", "HEAD")


def test_a_dry_run_changes_nothing(repo):
    add_files(repo, 2)
    before = commit_count(repo)

    code, report, text = start(repo, dry_run=True)

    assert code == 0
    assert report.status == DRY_RUN
    assert commit_count(repo) == before
    assert "Dry run only" in text
    assert not Journal(repo).path.exists()


def test_declining_the_confirmation_cancels_the_run(repo, monkeypatch):
    add_files(repo, 1)
    options = options_for(repo, force=False)
    report = RunReport(options)
    console = Console(quiet=True)
    monkeypatch.setattr(console, "input", lambda *args, **kwargs: "n")
    before = commit_count(repo)

    code = run(console, options, report)

    assert code == 1
    assert report.status == CANCELLED
    assert commit_count(repo) == before


def test_confirming_lets_the_run_proceed(repo, monkeypatch):
    add_files(repo, 1)
    options = options_for(repo, force=False)
    console = Console(quiet=True)
    monkeypatch.setattr(console, "input", lambda *args, **kwargs: "y")

    assert run(console, options, RunReport(options)) == 0


def test_files_the_run_writes_itself_are_not_committed(repo):
    add_files(repo, 1)

    code, _, _ = start(repo, log_file=str(repo / "run.log"))

    assert code == 0
    assert "run.log" not in git(repo, "ls-files")


def test_a_failure_is_reported_and_journaled(repo, monkeypatch):
    add_files(repo, 1)

    def fail(*args, **kwargs):
        raise CommitRocketError("boom")

    monkeypatch.setattr("commitrocket.core.runner.batches.process_batches", fail)

    code, report, text = start(repo, params={"message": "m"})

    assert code == 1
    assert report.status == FAILED
    assert report.error == "boom"
    assert "Run the same command again" in text
    state = Journal(repo).state()
    assert state["status"] == "failed"
    assert state["params"] == {"message": "m"}


def test_an_interruption_is_reported_and_journaled(repo, monkeypatch):
    add_files(repo, 1)

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("commitrocket.core.runner.batches.process_batches", interrupt)

    code, report, text = start(repo)

    assert code == 130
    assert report.status == INTERRUPTED
    assert "Interrupted by user" in text
    assert Journal(repo).state()["status"] == "interrupted"


def test_running_again_with_the_same_parameters_continues_the_run(repo, monkeypatch):
    add_files(repo, 2)
    real = __import__(
        "commitrocket.core.runner.batches", fromlist=["process_batches"]
    ).process_batches
    calls = []

    def fail_once(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise CommitRocketError("boom")
        return real(*args, **kwargs)

    monkeypatch.setattr("commitrocket.core.runner.batches.process_batches", fail_once)

    assert start(repo, params={"message": "m"})[0] == 1
    code, report, _ = start(repo, params={"message": "m"})

    assert code == 0
    assert report.status == SUCCESS
    assert not Journal(repo).path.exists()


def test_running_again_with_other_parameters_starts_a_new_run(repo, monkeypatch):
    add_files(repo, 1)

    def fail(*args, **kwargs):
        raise CommitRocketError("boom")

    monkeypatch.setattr("commitrocket.core.runner.batches.process_batches", fail)
    start(repo, params={"message": "old"})
    monkeypatch.undo()

    code, _, text = start(repo, params={"message": "new"})

    assert code == 0
    assert "starting a new run" in text


def test_resume_without_an_interrupted_run_is_an_abort(repo):
    add_files(repo, 1)

    code, report, text = start(repo, resume=True)

    assert code == 1
    assert report.status == ABORTED
    assert "no interrupted run" in text


def test_files_over_the_host_limit_need_lfs(repo):
    big = repo / "big.bin"
    with open(big, "wb") as handle:
        handle.truncate(101 * 1024 * 1024)

    code, report, text = start(repo, max_mib=500)

    assert code == 2
    assert report.status == ABORTED
    assert "--use-lfs" in text
    assert git(repo, "status", "--porcelain").startswith("??")
