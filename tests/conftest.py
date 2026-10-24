import subprocess

import pytest


@pytest.fixture
def git_repo(tmp_path):
    """An empty Git repository with a configured identity.

    It lives in a "repo" subfolder, so tmp_path itself is free for logs, reports
    and other files that must stay outside the repository.
    """
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True)

    git("init", "-q")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    return repo
