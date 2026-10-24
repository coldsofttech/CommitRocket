import pytest

from commitrocket.errors import CommitRocketError, GitError
from commitrocket.git import (
    LocalConfig,
    get_pending_files,
    get_staged_files,
    resolve_target,
    run_git,
)


def test_pending_includes_untracked_and_modified(git_repo):
    (git_repo / "tracked.txt").write_text("one")
    run_git(git_repo, "add", "tracked.txt")
    run_git(git_repo, "commit", "-m", "init")

    (git_repo / "tracked.txt").write_text("two")
    (git_repo / "new.txt").write_text("new")

    assert sorted(get_pending_files(git_repo)) == ["new.txt", "tracked.txt"]
    assert get_staged_files(git_repo) == []


def test_local_config_sets_and_restores(git_repo):
    run_git(git_repo, "config", "--local", "pack.threads", "2")

    config = LocalConfig(git_repo)
    config.set("pack.threads", 8)
    config.set("lfs.concurrenttransfers", 4)
    assert run_git(git_repo, "config", "--local", "pack.threads").stdout.strip() == "8"

    config.restore()
    assert run_git(git_repo, "config", "--local", "pack.threads").stdout.strip() == "2"
    unset = run_git(
        git_repo, "config", "--local", "lfs.concurrenttransfers", check=False
    )
    assert unset.returncode != 0


def test_resolve_target_needs_a_remote(git_repo):
    with pytest.raises(CommitRocketError, match="No upstream"):
        resolve_target(git_repo, "main")


def test_resolve_target_uses_explicit_values_and_local_branch(git_repo):
    target = resolve_target(git_repo, "feature", remote="backup")
    assert (target.remote, target.branch) == ("backup", "feature")
    assert target.ref == "refs/heads/feature"
    assert target.refspec == "HEAD:refs/heads/feature"
    assert target.label == "backup/feature"
    # Never pushed there, so everything the remote lacks counts as unpushed.
    assert target.revs == ["HEAD", "--not", "--remotes=backup"]


def test_resolve_target_reads_the_upstream_and_prefers_overrides(git_repo):
    run_git(git_repo, "config", "branch.main.remote", "origin")
    run_git(git_repo, "config", "branch.main.merge", "refs/heads/release")

    target = resolve_target(git_repo, "main")
    assert target.label == "origin/release"

    target = resolve_target(git_repo, "main", branch="other")
    assert target.label == "origin/other"


def test_run_git_raises_git_error(git_repo):
    with pytest.raises(GitError):
        run_git(git_repo, "no-such-command")
