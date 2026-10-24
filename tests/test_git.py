import pytest

from commitrocket.errors import CommitRocketError, GitError
from commitrocket.git import (
    LocalConfig,
    add_files,
    chunk_paths,
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


def test_chunk_paths_keeps_order_and_fits_the_limit():
    paths = [f"folder/file-{index:05d}.txt" for index in range(500)]

    chunks = list(chunk_paths(paths, limit=2000))

    assert [path for chunk in chunks for path in chunk] == paths
    assert len(chunks) > 1
    assert all(sum(2 * len(p) + 3 for p in chunk) <= 2000 for chunk in chunks)


def test_chunk_paths_handles_edge_cases():
    assert list(chunk_paths([])) == []
    # One path longer than the limit still goes through, alone.
    assert list(chunk_paths(["x" * 50, "y"], limit=10)) == [["x" * 50], ["y"]]


def test_add_files_stages_thousands_of_files(git_repo):
    # ~4,000 long names are far beyond a single Windows command line (32,767 chars).
    folder = git_repo / "a-folder-with-a-reasonably-long-name"
    folder.mkdir()
    names = [f"a-reasonably-long-file-name-number-{i:05d}.txt" for i in range(4000)]
    for name in names:
        (folder / name).write_text("x")
    paths = [f"{folder.name}/{name}" for name in names]

    add_files(git_repo, paths)

    assert len(get_staged_files(git_repo)) == 4000


def test_long_commands_are_shortened_in_errors(git_repo):
    # About 24,000 characters: long enough to truncate, short enough to run.
    paths = [f"missing-file-{i:05d}.txt" for i in range(1000)]

    with pytest.raises(GitError) as raised:
        run_git(git_repo, "add", "--", *paths)

    assert len(str(raised.value)) < 1500
    assert "[truncated]" in str(raised.value)


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
