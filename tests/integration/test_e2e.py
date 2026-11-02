"""End-to-end runs against a local bare repository acting as the remote."""

import json
import subprocess

import pytest

from commitrocket.cli import main
from commitrocket.git import run_git
from commitrocket.template import ATTRIBUTION

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
        f"Data #1\n\n{ATTRIBUTION}",
        f"Data #2\n\n{ATTRIBUTION}",
        f"Data #3\n\n{ATTRIBUTION}",
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


def commit_bodies(repo, count):
    out = run_git(repo, "log", f"-{count}", "--format=%B%x00").stdout
    return [body.strip() for body in out.split("\0") if body.strip()]


def test_commits_end_with_the_attribution(project, tmp_path):
    repo, _, _ = project
    add_files(repo, 2)

    assert run_cli(repo, tmp_path, "--force", "--limit-mib", "1") == 0

    bodies = commit_bodies(repo, 2)
    assert all(body.endswith(f"\n\n{ATTRIBUTION}") for body in bodies)
    assert all(body.count(ATTRIBUTION) == 1 for body in bodies)


def test_no_attribution_flag_leaves_messages_untouched(project, tmp_path):
    repo, _, _ = project
    add_files(repo, 2)

    code = run_cli(repo, tmp_path, "--force", "--limit-mib", "1", "--no-attribution")

    assert code == 0
    assert commit_bodies(repo, 2) == ["Data #2", "Data #1"]


def test_ignore_attribution_alias_and_dry_run_report(project, tmp_path):
    repo, _, _ = project
    add_files(repo, 1)
    plain = tmp_path / "plain.json"
    full = tmp_path / "full.json"

    run_cli(repo, tmp_path, "--dry-run", "--ignore-attribution", "--report", str(plain))
    run_cli(repo, tmp_path, "--dry-run", "--report", str(full))

    plain_msg = json.loads(plain.read_text(encoding="utf-8"))["batches"][0]["message"]
    full_msg = json.loads(full.read_text(encoding="utf-8"))["batches"][0]["message"]
    assert plain_msg == "Data #1"
    assert full_msg == f"Data #1\n\n{ATTRIBUTION}"


def test_resumed_commit_keeps_the_attribution(project, tmp_path):
    """Commits made by an earlier run keep their attribution when pushed later."""
    repo, _, _ = project
    add_files(repo, 2)
    assert run_cli(repo, tmp_path, "--force", "--limit-mib", "1", "--no-push") == 0
    assert run_cli(repo, tmp_path, "--force") == 0
    assert all(ATTRIBUTION in body for body in commit_bodies(repo, 2))


def interrupt_second_push(monkeypatch):
    """Make Ctrl+C hit while the second batch is being pushed."""
    from commitrocket import runner

    real = runner.push_target
    calls = []

    def push(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return real(*args, **kwargs)

    monkeypatch.setattr(runner, "push_target", push)
    return lambda: monkeypatch.setattr(runner, "push_target", real)


def resume_cli(repo, tmp_path, *extra):
    return main(["--repo", str(repo), "--log-file", str(tmp_path / "run.log"), *extra])


def test_resume_continues_with_the_stored_parameters(project, tmp_path, monkeypatch):
    from commitrocket.journal import Journal

    repo, remote, branch = project
    add_files(repo, 4)
    restore = interrupt_second_push(monkeypatch)

    assert run_cli(repo, tmp_path, "--force", "--limit-mib", "1") == 130
    journal = Journal(repo)
    assert journal.path.exists()
    assert journal.state()["params"]["limit_mib"] == 1
    assert journal.state()["status"] == "interrupted"
    restore()

    # No parameters needed: they come from the journal.
    assert resume_cli(repo, tmp_path, "--resume", "--force") == 0

    assert not journal.path.exists()
    bodies = commit_bodies(repo, 4)
    assert bodies[0].startswith("Data #4")
    assert [b.split("\n")[0] for b in reversed(bodies)] == [
        "Data #1",
        "Data #2",
        "Data #3",
        "Data #4",
    ]
    local = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    assert run_git(remote, "rev-parse", f"refs/heads/{branch}").stdout.strip() == local


def test_resume_accepts_identical_parameters(project, tmp_path, monkeypatch):
    repo, _, _ = project
    add_files(repo, 3)
    restore = interrupt_second_push(monkeypatch)
    assert run_cli(repo, tmp_path, "--force", "--limit-mib", "1") == 130
    restore()

    code = resume_cli(
        repo, tmp_path, "--resume", "--force", "--message", "Data", "--limit-mib", "1"
    )

    assert code == 0


def test_resume_rejects_different_parameters(project, tmp_path, monkeypatch, capsys):
    from commitrocket.journal import Journal

    repo, _, _ = project
    add_files(repo, 3)
    interrupt_second_push(monkeypatch)
    assert run_cli(repo, tmp_path, "--force", "--limit-mib", "1") == 130

    with pytest.raises(SystemExit) as exc:
        resume_cli(repo, tmp_path, "--resume", "--force", "--limit-mib", "5")

    assert exc.value.code == 2
    assert "--limit-mib" in capsys.readouterr().err
    assert Journal(repo).path.exists()


def test_resume_without_a_journal_is_a_clear_error(project, tmp_path, capsys):
    repo, _, _ = project

    with pytest.raises(SystemExit) as exc:
        resume_cli(repo, tmp_path, "--resume")

    assert exc.value.code == 2
    assert "no interrupted run" in capsys.readouterr().err


def test_resume_refuses_a_repository_that_changed(project, tmp_path, monkeypatch):
    repo, _, _ = project
    add_files(repo, 3)
    interrupt_second_push(monkeypatch)
    assert run_cli(repo, tmp_path, "--force", "--limit-mib", "1") == 130
    run_git(repo, "reset", "--hard", "HEAD~1")  # drops a recorded commit

    assert resume_cli(repo, tmp_path, "--resume", "--force") == 1


def test_plain_rerun_with_other_parameters_starts_a_new_run(
    project, tmp_path, monkeypatch
):
    from commitrocket.journal import Journal

    repo, _, _ = project
    add_files(repo, 3)
    restore = interrupt_second_push(monkeypatch)
    assert run_cli(repo, tmp_path, "--force", "--limit-mib", "1") == 130
    restore()

    code = main(
        [
            "--repo",
            str(repo),
            "--message",
            "Other",
            "--limit-mib",
            "1",
            "--force",
            "--log-file",
            str(tmp_path / "run.log"),
        ]
    )

    assert code == 0
    assert not Journal(repo).path.exists()
    assert commit_bodies(repo, 1)[0].startswith("Other #1")


def test_plain_rerun_with_the_same_parameters_continues(project, tmp_path, monkeypatch):
    repo, _, _ = project
    add_files(repo, 3)
    restore = interrupt_second_push(monkeypatch)
    assert run_cli(repo, tmp_path, "--force", "--limit-mib", "1") == 130
    restore()

    assert run_cli(repo, tmp_path, "--force", "--limit-mib", "1") == 0

    assert commit_bodies(repo, 1)[0].startswith("Data #3")


def test_dry_run_leaves_no_journal(project, tmp_path):
    from commitrocket.journal import Journal

    repo, _, _ = project
    add_files(repo, 2)

    assert run_cli(repo, tmp_path, "--dry-run", "--limit-mib", "1") == 0

    assert not Journal(repo).path.exists()
