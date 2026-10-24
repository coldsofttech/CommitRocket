import subprocess

import pytest

from commitrocket.errors import CommitRocketError
from commitrocket.git import run_git
from commitrocket.verify import (
    expected_lfs_paths,
    find_non_pointers,
    unpushed_has_lfs_pointers,
    verify_remote_head,
)

POINTER = (
    "version https://git-lfs.github.com/spec/v1\n"
    "oid sha256:" + "0" * 64 + "\nsize 123\n"
)


def commit_all(repo, message):
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", message)


@pytest.fixture
def repo_with_remote(git_repo, tmp_path_factory):
    remote = tmp_path_factory.mktemp("remote")
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    run_git(git_repo, "remote", "add", "origin", str(remote))
    (git_repo / "a.txt").write_text("one")
    commit_all(git_repo, "first")
    branch = run_git(git_repo, "branch", "--show-current").stdout.strip()
    return git_repo, branch


def test_verify_remote_head_passes_after_push(repo_with_remote):
    repo, branch = repo_with_remote
    run_git(repo, "push", "origin", branch)
    verify_remote_head(repo, "origin", f"refs/heads/{branch}")


def test_verify_remote_head_fails_when_remote_is_behind(repo_with_remote):
    repo, branch = repo_with_remote
    run_git(repo, "push", "origin", branch)
    (repo / "a.txt").write_text("two")
    commit_all(repo, "second")

    with pytest.raises(CommitRocketError, match="Push verification failed"):
        verify_remote_head(repo, "origin", f"refs/heads/{branch}")


def test_unpushed_has_lfs_pointers(repo_with_remote):
    repo, branch = repo_with_remote
    run_git(repo, "push", "origin", branch)
    revs = [f"origin/{branch}..HEAD"]
    assert unpushed_has_lfs_pointers(repo, revs) is False

    (repo / "plain.txt").write_text("not a pointer")
    commit_all(repo, "plain")
    assert unpushed_has_lfs_pointers(repo, revs) is False

    (repo / "video.bin").write_text(POINTER)
    commit_all(repo, "pointer")
    assert unpushed_has_lfs_pointers(repo, revs) is True


def test_find_non_pointers(git_repo):
    (git_repo / "pointer.bin").write_text(POINTER)
    (git_repo / "plain.bin").write_text("just a normal file")
    (git_repo / "big.bin").write_bytes(b"x" * 5000)
    commit_all(git_repo, "files")

    paths = ["pointer.bin", "plain.bin", "big.bin", "missing.bin"]
    assert sorted(find_non_pointers(git_repo, paths)) == [
        "big.bin",
        "missing.bin",
        "plain.bin",
    ]
    assert find_non_pointers(git_repo, []) == []


def test_expected_lfs_paths_skips_git_config_files():
    selected = ["a.mp4", "dir/.gitignore", "b.txt"]
    assert expected_lfs_paths(selected, ["a.mp4", "dir/.gitignore"]) == ["a.mp4"]
