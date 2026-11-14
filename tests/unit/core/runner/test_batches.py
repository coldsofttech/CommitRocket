import subprocess

import pytest
from rich.console import Console

from commitrocket.core.options import RunOptions
from commitrocket.core.runner.batches import process_batches
from commitrocket.git.git import PushTarget, get_pending_files
from commitrocket.git.journal import Journal
from commitrocket.io.report import RunReport
from commitrocket.support.errors import CommitRocketError


class FakeProgress:
    def __init__(self):
        self.updates = []

    def update(self, task, **fields):
        self.updates.append(fields)


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def add_files(repo, count, size=1000):
    for number in range(count):
        (repo / f"f{number}.txt").write_bytes(bytes([65 + number]) * size)


@pytest.fixture
def pushes(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "commitrocket.core.runner.helpers.push_target",
        lambda *args, **kwargs: calls.append(kwargs),
    )
    return calls


def run_batches(repo, *, limit=1500, maximum=5000, journal=None, **kwargs):
    options = RunOptions(
        message="m", attribution=False, no_push=kwargs.pop("no_push", True)
    )
    report = RunReport(options)
    progress = FakeProgress()
    count = process_batches(
        Console(quiet=True),
        repo,
        progress,
        "task",
        "push",
        options,
        PushTarget("origin", "main", []),
        kwargs.pop("number", 1),
        limit,
        maximum,
        lambda: get_pending_files(repo),
        journal=journal,
        report=report,
        **kwargs,
    )
    return count, report, progress


def subjects(repo):
    return git(repo, "log", "--format=%s", "--reverse").splitlines()


def test_files_are_committed_in_numbered_batches(git_repo):
    add_files(git_repo, 3)

    count, report, _ = run_batches(git_repo)

    assert count == 3
    assert subjects(git_repo) == ["m #1", "m #2", "m #3"]
    assert [batch["message"] for batch in report.batches] == ["m #1", "m #2", "m #3"]
    assert get_pending_files(git_repo) == []


def test_numbering_starts_from_the_given_number(git_repo):
    add_files(git_repo, 2)

    run_batches(git_repo, number=7)

    assert subjects(git_repo) == ["m #7", "m #8"]


def test_files_that_fit_together_share_a_batch(git_repo):
    add_files(git_repo, 3, size=100)

    count, _, _ = run_batches(git_repo, limit=10_000)

    assert count == 1
    assert git(git_repo, "rev-list", "--count", "HEAD") == "1"


def test_oversized_files_are_left_uncommitted(git_repo):
    add_files(git_repo, 1, size=9000)

    count, _, _ = run_batches(git_repo, limit=1500, maximum=5000)

    assert count == 0
    assert get_pending_files(git_repo) == ["f0.txt"]


def test_nothing_pending_means_no_batches(git_repo):
    count, _, _ = run_batches(git_repo)
    assert count == 0


def test_the_journal_follows_each_commit(git_repo):
    add_files(git_repo, 2)
    journal = Journal(git_repo)
    journal.start({}, "main", "origin/main", "abc")

    run_batches(git_repo, journal=journal)

    state = journal.state()
    assert [number for number, _ in state["commits"]] == [1, 2]
    assert state["commits"][-1][1] == git(git_repo, "rev-parse", "HEAD")
    assert state["inflight"] is None
    assert state["pushed"] is None


def test_each_batch_is_pushed_and_verified(git_repo, pushes):
    add_files(git_repo, 2)
    journal = Journal(git_repo)
    journal.start({}, "main", "origin/main", "abc")
    verified = []

    _, report, _ = run_batches(
        git_repo, journal=journal, no_push=False, verify=lambda: verified.append(1)
    )

    assert len(pushes) == 2
    assert verified == [1, 1]
    assert journal.state()["pushed"] == git(git_repo, "rev-parse", "HEAD")
    assert all(batch["pushed"] and batch["verified"] for batch in report.batches)


def test_no_push_does_not_push(git_repo, pushes):
    add_files(git_repo, 1)

    _, report, _ = run_batches(git_repo, no_push=True)

    assert pushes == []
    assert not report.batches[0].get("pushed")


def test_lfs_check_runs_before_pushing(git_repo, pushes):
    add_files(git_repo, 1)
    seen = []

    def check_lfs(selected):
        seen.append((list(selected), len(pushes)))

    run_batches(git_repo, no_push=False, check_lfs=check_lfs)

    assert seen == [(["f0.txt"], 0)]


def test_a_failed_lfs_check_stops_before_pushing(git_repo, pushes):
    add_files(git_repo, 1)

    def check_lfs(selected):
        raise CommitRocketError("not pointers")

    with pytest.raises(CommitRocketError, match="not pointers"):
        run_batches(git_repo, no_push=False, check_lfs=check_lfs)

    assert pushes == []


def test_progress_is_measured_in_bytes(git_repo):
    add_files(git_repo, 2, size=1000)

    _, _, progress = run_batches(git_repo)

    assert progress.updates[0] == {"total": 2000, "completed": 0}
    assert progress.updates[-1]["completed"] == 2000
