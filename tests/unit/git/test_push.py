import subprocess

import pytest
from rich.console import Console

from commitrocket.git import push
from commitrocket.git.push import parse_lfs_bytes, parse_progress_line
from commitrocket.support.errors import PushError


@pytest.mark.parametrize(
    "output",
    [
        "remote: error: GH001: Large files detected.",
        "! [remote rejected] main -> main (pre-receive hook declined)",
        "! [rejected] main -> main (fetch first)",
        "fatal: Authentication failed for 'https://example.com/r.git'",
    ],
)
def test_rejections_are_not_retryable(output):
    assert push.is_retryable(output) is False


@pytest.mark.parametrize(
    "output",
    [
        "error: RPC failed; HTTP 500 curl 22 The requested URL returned error: 500",
        "fatal: the remote end hung up unexpectedly",
        "LFS: Put https://example.com/object: connection reset by peer",
    ],
)
def test_transient_failures_are_retryable(output):
    assert push.is_retryable(output) is True


def fake_push(failures):
    calls = []

    def _push(*args, **kwargs):
        calls.append(1)
        if len(calls) <= len(failures):
            raise failures[len(calls) - 1]

    return _push, calls


def run_retries(monkeypatch, failures, retries):
    fake, calls = fake_push(failures)
    monkeypatch.setattr(push, "push_with_progress", fake)
    waits = []
    push.push_with_retries(
        ".", None, None, Console(quiet=True), retries=retries, sleep=waits.append
    )
    return calls, waits


def test_retries_transient_failures_with_backoff(monkeypatch):
    failures = [PushError("RPC failed"), PushError("RPC failed")]
    calls, waits = run_retries(monkeypatch, failures, retries=3)
    assert len(calls) == 3
    assert waits == [5, 15]


def test_gives_up_after_retries(monkeypatch):
    failures = [PushError("RPC failed")] * 3
    with pytest.raises(PushError):
        run_retries(monkeypatch, failures, retries=2)


def test_does_not_retry_rejections(monkeypatch):
    failures = [PushError("rejected", retryable=False)]
    with pytest.raises(PushError):
        run_retries(monkeypatch, failures, retries=3)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Uploading LFS objects:  50% (1/2), 52 MB | 3.2 MB/s", 52_000_000),
        ("Uploading LFS objects: 100% (1/1), 1.5 GB | 12 MB/s", 1_500_000_000),
        ("Uploading LFS objects:   0% (0/1), 0 B | 0 B/s", 0),
        ("Writing objects: 100% (6/6), 235.76 MiB | 846.00 KiB/s, done.", None),
    ],
)
def test_parse_lfs_bytes(line, expected):
    assert parse_lfs_bytes(line) == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Enumerating objects: 5, done.", ("Enumerating objects", None)),
        ("Counting objects:  40% (2/5)", ("Counting objects", 40)),
        ("Compressing objects: 100% (3/3)", ("Compressing objects", 100)),
        ("Writing objects:  50% (1/2)", ("Uploading objects", 50)),
        ("Resolving deltas: 100% (1/1)", ("Resolving deltas", 100)),
        ("To github.com:user/repo.git", ("Git push", None)),
    ],
)
def test_parse_progress_line(line, expected):
    assert parse_progress_line(line) == expected


class FakeProgress:
    def __init__(self):
        self.updates = []

    def update(self, task, **fields):
        self.updates.append(fields)


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def pushable(git_repo, tmp_path):
    """A repository with one commit and an empty bare repository as origin."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    (git_repo / "a.txt").write_text("a", encoding="utf-8")
    git(git_repo, "add", "a.txt")
    git(git_repo, "commit", "-q", "-m", "first")
    git(git_repo, "remote", "add", "origin", str(remote))
    return git_repo, remote


def test_push_with_progress_pushes_and_reports_progress(pushable):
    repo, remote = pushable
    progress = FakeProgress()
    uploads = []

    push.push_with_progress(
        repo,
        progress,
        "task",
        Console(quiet=True),
        on_upload=uploads.append,
        remote="origin",
        refspec="HEAD:refs/heads/main",
    )

    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    pushed = subprocess.run(
        ["git", "-C", str(remote), "rev-parse", "refs/heads/main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert pushed == head
    assert progress.updates[-1] == {"visible": False}
    assert {
        "description": "Git push complete",
        "completed": 100,
        "total": 100,
        "visible": True,
    } in progress.updates
    assert uploads == sorted(uploads)


def test_push_with_progress_raises_when_git_push_fails(pushable):
    repo, _ = pushable
    progress = FakeProgress()

    with pytest.raises(PushError) as exc_info:
        push.push_with_progress(
            repo,
            progress,
            "task",
            Console(quiet=True),
            remote="missing",
            refspec="HEAD:refs/heads/main",
        )

    assert "git push failed" in str(exc_info.value)
    assert any(u.get("description") == "Git push failed" for u in progress.updates)
