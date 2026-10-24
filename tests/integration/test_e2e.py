"""End-to-end runs against a local bare repository acting as the remote."""

import json
import subprocess

import pytest

from commitrocket.cli import main
from commitrocket.git import run_git

pytestmark = pytest.mark.integration

KIB = 1024


@pytest.fixture
def project(git_repo, tmp_path_factory):
    """A repo with one pushed commit and an upstream, plus a bare 'origin'."""
    remote = tmp_path_factory.mktemp("origin")
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    run_git(git_repo, "remote", "add", "origin", str(remote))

    (git_repo / "README.md").write_text("start")
    run_git(git_repo, "add", "-A")
    run_git(git_repo, "commit", "-m", "initial")
    branch = run_git(git_repo, "branch", "--show-current").stdout.strip()
    run_git(git_repo, "push", "-u", "origin", branch)
    return git_repo, remote, branch


def add_files(repo, count, size=600 * KIB):
    for index in range(count):
        (repo / f"file{index}.bin").write_bytes(b"x" * size)


def run_cli(repo, tmp_path, *extra):
    argv = [
        "--repo",
        str(repo),
        "--message",
        "Data",
        "--log-file",
        str(tmp_path / "run.log"),
        *extra,
    ]
    return main(argv)


def test_full_run_pushes_every_batch_and_writes_a_report(project, tmp_path):
    repo, remote, branch = project
    add_files(repo, 3)
    report_path = tmp_path / "report.json"

    code = run_cli(
        repo, tmp_path, "--force", "--limit-mib", "1", "--report", str(report_path)
    )

    assert code == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "success"
    assert [b["message"] for b in report["batches"]] == [
        "Data #1",
        "Data #2",
        "Data #3",
    ]
    assert all(b["pushed"] and b["verified"] for b in report["batches"])

    local = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    remote_head = run_git(remote, "rev-parse", f"refs/heads/{branch}").stdout.strip()
    assert local == remote_head
    assert run_git(repo, "status", "--porcelain").stdout.strip() == ""


def test_dry_run_changes_nothing(project, tmp_path):
    repo, _, _ = project
    add_files(repo, 2)
    head = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    report_path = tmp_path / "dry.json"

    code = run_cli(
        repo, tmp_path, "--dry-run", "--limit-mib", "1", "--report", str(report_path)
    )

    assert code == 0
    assert run_git(repo, "rev-parse", "HEAD").stdout.strip() == head
    assert get_staged(repo) == []
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "dry_run"
    assert report["totals"]["batches"] == 2
    assert not any(b["pushed"] for b in report["batches"])


def test_no_push_commits_locally_and_a_later_run_pushes(project, tmp_path):
    repo, remote, branch = project
    add_files(repo, 2)

    assert run_cli(repo, tmp_path, "--force", "--limit-mib", "1", "--no-push") == 0
    local = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    behind = run_git(remote, "rev-parse", f"refs/heads/{branch}").stdout.strip()
    assert local != behind

    # Nothing is pending now; the run only pushes the saved commits.
    assert run_cli(repo, tmp_path, "--force") == 0
    pushed = run_git(remote, "rev-parse", f"refs/heads/{branch}").stdout.strip()
    assert pushed == local


def test_log_and_report_inside_the_repo_are_never_committed(project, tmp_path):
    """Writing them used to create a new batch forever."""
    repo, _, _ = project
    add_files(repo, 2)
    log = repo / "run.log"
    report = repo / "out" / "report.json"

    code = main(
        [
            "--repo",
            str(repo),
            "--message",
            "Data",
            "--force",
            "--limit-mib",
            "1",
            "--log-file",
            str(log),
            "--report",
            str(report),
        ]
    )

    assert code == 0
    assert log.exists() and report.exists()
    tracked = run_git(repo, "ls-files").stdout.split()
    assert "run.log" not in tracked
    assert "out/report.json" not in tracked
    assert sorted(t for t in tracked if t.endswith(".bin")) == [
        "file0.bin",
        "file1.bin",
    ]
    assert json.loads(report.read_text(encoding="utf-8"))["totals"]["batches"] == 2


def test_include_and_exclude_filters(project, tmp_path):
    repo, _, _ = project
    (repo / "a.mp4").write_bytes(b"x" * KIB)
    (repo / "b.txt").write_bytes(b"x" * KIB)
    (repo / "c.mp4").write_bytes(b"x" * KIB)

    code = run_cli(
        repo, tmp_path, "--force", "--include", "*.mp4", "--exclude", "c.mp4"
    )

    assert code == 0
    committed = run_git(repo, "show", "--name-only", "--format=", "HEAD").stdout
    assert committed.split() == ["a.mp4"]
    assert sorted(untracked(repo)) == ["b.txt", "c.mp4"]


def get_staged(repo):
    out = run_git(repo, "diff", "--cached", "--name-only").stdout
    return out.split()


def untracked(repo):
    out = run_git(repo, "ls-files", "--others", "--exclude-standard").stdout
    return out.split()
