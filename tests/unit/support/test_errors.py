import pytest

from commitrocket.support.errors import CommitRocketError, GitError, PushError


def test_errors_share_one_base_class():
    assert issubclass(GitError, CommitRocketError)
    assert issubclass(PushError, GitError)
    assert issubclass(CommitRocketError, RuntimeError)


def test_push_errors_are_retryable_by_default():
    assert PushError("failed").retryable is True


def test_push_errors_can_be_marked_not_retryable():
    error = PushError("rejected", retryable=False)
    assert error.retryable is False
    assert str(error) == "rejected"


def test_push_errors_are_caught_as_the_base_class():
    with pytest.raises(CommitRocketError):
        raise PushError("failed")
