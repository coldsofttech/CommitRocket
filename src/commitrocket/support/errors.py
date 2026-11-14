class CommitRocketError(RuntimeError):
    """Base class for expected, user-reportable failures."""


class GitError(CommitRocketError):
    """A git command failed."""


class PushError(GitError):
    """A git push failed. retryable is False when trying again cannot help."""

    def __init__(self, message, retryable=True):
        super().__init__(message)
        self.retryable = retryable
