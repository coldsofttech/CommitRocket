import pytest
from rich.console import Console

from commitrocket import push
from commitrocket.errors import PushError


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
