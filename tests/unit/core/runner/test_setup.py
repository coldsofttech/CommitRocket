import subprocess

from rich.console import Console

from commitrocket.core.batching import MIB
from commitrocket.core.options import RunOptions
from commitrocket.core.runner import setup
from commitrocket.git.git import LocalConfig, PushTarget
from commitrocket.io.report import RunReport


def local_config(repo, key):
    result = subprocess.run(
        ["git", "-C", str(repo), "config", "--local", "--get", key],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def plan(repo, files, **option_values):
    option_values.setdefault("lfs_threshold_mib", 1)
    options = RunOptions(use_lfs=True, **option_values)
    report = RunReport(options)
    paths, scope = setup.plan_lfs(options, report, repo, files, 50 * MIB)
    return paths, scope, report


def test_plan_lfs_does_nothing_without_use_lfs(git_repo):
    options = RunOptions()
    report = RunReport(options)
    assert setup.plan_lfs(options, report, git_repo, ["a"], MIB) == ([], "")


def test_plan_lfs_picks_files_above_the_threshold(git_repo):
    (git_repo / "big.bin").write_bytes(b"x" * (2 * MIB))
    (git_repo / "small.txt").write_text("x")

    paths, scope, report = plan(git_repo, ["big.bin", "small.txt"])

    assert paths == ["big.bin"]
    assert report.lfs["files"] == 1
    assert "1 file(s) above 1 MiB" in scope
    assert ".gitattributes" in scope


def test_plan_lfs_without_committed_rules_says_so(git_repo):
    (git_repo / "big.bin").write_bytes(b"x" * (2 * MIB))

    _, scope, _ = plan(git_repo, ["big.bin"], lfs_commit_rules=False)

    assert "this run only" in scope
    assert "LFS pointer files" in scope


def test_plan_lfs_threshold_zero_means_every_file(git_repo):
    (git_repo / "a.txt").write_text("x")

    paths, scope, _ = plan(git_repo, ["a.txt"], lfs_threshold_mib=0)

    assert paths == ["a.txt"]
    assert scope.startswith("All 1 file(s)")


def test_plan_lfs_reports_when_no_file_needs_it(git_repo):
    (git_repo / "small.txt").write_text("x")

    paths, scope, report = plan(git_repo, ["small.txt"])

    assert paths == []
    assert report.lfs["files"] == 0
    assert "LFS not needed" in scope


def test_apply_local_config_sets_and_restores_thread_options(git_repo):
    options = RunOptions(compression_threads=2, lfs_threads=3)
    config = LocalConfig(git_repo)

    setup.apply_local_config(
        Console(quiet=True), options, git_repo, PushTarget("origin", "main", []), config
    )

    assert local_config(git_repo, "pack.threads") == "2"
    assert local_config(git_repo, "lfs.concurrenttransfers") == "3"
    config.restore()
    assert local_config(git_repo, "pack.threads") is None
    assert local_config(git_repo, "lfs.concurrenttransfers") is None


def test_apply_local_config_sets_the_post_buffer_for_http_remotes(git_repo):
    subprocess.run(
        ["git", "-C", str(git_repo), "remote", "add", "origin", "https://x.test/r.git"],
        check=True,
    )
    config = LocalConfig(git_repo)

    setup.apply_local_config(
        Console(quiet=True),
        RunOptions(post_buffer_mib=5),
        git_repo,
        PushTarget("origin", "main", []),
        config,
    )

    assert local_config(git_repo, "http.postBuffer") == str(5 * MIB)


def test_apply_local_config_ignores_the_post_buffer_for_other_remotes(git_repo):
    subprocess.run(
        ["git", "-C", str(git_repo), "remote", "add", "origin", "/some/where.git"],
        check=True,
    )
    console = Console(record=True, width=120)

    setup.apply_local_config(
        console,
        RunOptions(post_buffer_mib=5),
        git_repo,
        PushTarget("origin", "main", []),
        LocalConfig(git_repo),
    )

    assert local_config(git_repo, "http.postBuffer") is None
    assert "ignored" in console.export_text()


class FakeLfs:
    def __init__(self):
        self.calls = []

    def enable(self, paths, all_files=False):
        self.calls.append(("enable", paths, all_files))

    def install_hooks(self):
        self.calls.append(("install_hooks",))

    def close(self, uninstall_hooks=True):
        self.calls.append(("close", uninstall_hooks))


def test_configure_lfs_enables_lfs_for_the_run():
    lfs = FakeLfs()
    setup.configure_lfs(lfs, RunOptions(lfs_commit_rules=False), ["a"])
    assert lfs.calls == [("enable", ["a"], False)]


def test_configure_lfs_covers_every_file_with_threshold_zero():
    lfs = FakeLfs()
    options = RunOptions(lfs_commit_rules=False, lfs_threshold_mib=0)
    setup.configure_lfs(lfs, options, ["a"])
    assert lfs.calls == [("enable", ["a"], True)]


def test_configure_lfs_only_installs_hooks_when_rules_are_committed():
    lfs = FakeLfs()
    setup.configure_lfs(lfs, RunOptions(lfs_commit_rules=True), ["a"])
    assert lfs.calls == [("install_hooks",)]


def test_configure_lfs_installs_hooks_when_there_are_no_lfs_files():
    lfs = FakeLfs()
    setup.configure_lfs(lfs, RunOptions(lfs_commit_rules=False), [])
    assert lfs.calls == [("install_hooks",)]


def release(monkeypatch, completed, pointers):
    def has_pointers(repo, revs):
        if isinstance(pointers, Exception):
            raise pointers
        return pointers

    monkeypatch.setattr(
        "commitrocket.core.verify.unpushed_has_lfs_pointers", has_pointers
    )
    lfs = FakeLfs()
    console = Console(record=True, width=120)
    setup.release_lfs(
        console, ".", PushTarget("origin", "main", []), lfs, completed=completed
    )
    return lfs, console.export_text()


def test_release_lfs_removes_hooks_after_a_completed_run(monkeypatch):
    lfs, text = release(monkeypatch, completed=True, pointers=True)
    assert lfs.calls == [("close", True)]
    assert "left installed" not in text


def test_release_lfs_keeps_hooks_while_unpushed_lfs_commits_remain(monkeypatch):
    lfs, text = release(monkeypatch, completed=False, pointers=True)
    assert lfs.calls == [("close", False)]
    assert "left installed" in text


def test_release_lfs_removes_hooks_after_a_stopped_run_with_nothing_unpushed(
    monkeypatch,
):
    lfs, _ = release(monkeypatch, completed=False, pointers=False)
    assert lfs.calls == [("close", True)]


def test_release_lfs_keeps_hooks_when_unpushed_commits_cannot_be_checked(monkeypatch):
    lfs, _ = release(monkeypatch, completed=False, pointers=OSError("boom"))
    assert lfs.calls == [("close", False)]
