import io
import logging
import os
import stat
import sys

import pytest
from rich.console import Console

from commitrocket import logs, notify
from commitrocket.errors import CommitRocketError
from commitrocket.git import resolve_target, run_git
from commitrocket.lfs import attribute_line
from commitrocket.options import RunOptions
from commitrocket.report import RunReport
from commitrocket.security import (
    has_control_chars,
    redact,
    redact_value,
    restrict_permissions,
    validate_ref_part,
)
from commitrocket.ui import print_lfs_required


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "To https://user:ghp_secret@github.com/o/r.git",
            "To https://***@github.com/o/r.git",
        ),
        ("ssh://git:pw@host/repo", "ssh://***@host/repo"),
        ("https://github.com/o/r.git", "https://github.com/o/r.git"),
        ("https://example.com/a@b", "https://example.com/a@b"),
        ("git@github.com:o/r.git", "git@github.com:o/r.git"),
    ],
)
def test_redact(text, expected):
    assert redact(text) == expected


def test_control_characters():
    assert has_control_chars("a\nb") and has_control_chars("a\x00b")
    assert not has_control_chars("normal name (1).mp4")


@pytest.mark.parametrize("value", ["--receive-pack=x", "-x", "", "a b", "a\nb"])
def test_unsafe_remote_and_branch_names_are_rejected(value):
    with pytest.raises(CommitRocketError):
        validate_ref_part(value, "remote")


def test_normal_names_are_accepted():
    assert validate_ref_part("origin", "remote") == "origin"
    assert validate_ref_part("feat/x-1", "branch") == "feat/x-1"


def test_resolve_target_rejects_option_like_names(git_repo):
    with pytest.raises(CommitRocketError):
        resolve_target(git_repo, "main", remote="--upload-pack=x")
    with pytest.raises(CommitRocketError):
        resolve_target(git_repo, "main", remote="origin", branch="-d")


def test_git_treats_file_names_literally(git_repo):
    for name in ("a.txt", "b.txt", "[ab].txt"):
        (git_repo / name).write_text(name)

    run_git(git_repo, "add", "--", "[ab].txt")

    staged = run_git(git_repo, "diff", "--cached", "--name-only").stdout.split()
    assert staged == ["[ab].txt"]


CREDENTIAL_URL = "https://me:supersecret@example.com/org/repo.git"


def test_target_label_hides_credentials_in_a_url_remote(git_repo):
    target = resolve_target(git_repo, "main", remote=CREDENTIAL_URL, branch="main")

    assert "supersecret" not in target.label
    assert target.label.startswith("https://***@example.com/")
    # The real value is still what git is given.
    assert target.remote == CREDENTIAL_URL


def test_report_never_contains_a_credentialed_remote(git_repo, tmp_path):
    options = RunOptions(message="m", remote=CREDENTIAL_URL, branch="main")
    report = RunReport(options)
    target = resolve_target(git_repo, "main", CREDENTIAL_URL, "main")
    report.target = target.label
    report.error = redact(f"push to {CREDENTIAL_URL} failed")
    report.finish(1)

    path = report.write(tmp_path / "report.json")

    assert "supersecret" not in path.read_text(encoding="utf-8")


def test_notifications_never_contain_a_credentialed_remote(git_repo):
    options = RunOptions(message="m", remote=CREDENTIAL_URL, branch="main")
    report = RunReport(options)
    report.target = resolve_target(git_repo, "main", CREDENTIAL_URL, "main").label
    report.add_batch(1, "m #1", ["a"], 10)
    report.finish(0)

    title, body = notify.build_message(report)
    assert "supersecret" not in title + body

    # Even if an unredacted target slipped in, the outgoing payload cleans it.
    report.target = CREDENTIAL_URL
    sent = {}

    def fake_urlopen(request, timeout):
        sent["body"] = request.data.decode("utf-8")
        raise OSError("stop here")

    original = notify.urllib.request.urlopen
    notify.urllib.request.urlopen = fake_urlopen
    try:
        with pytest.raises(OSError):
            notify.notify_webhook("https://hooks.example/x", title, body, report)
    finally:
        notify.urllib.request.urlopen = original

    assert "supersecret" not in sent["body"]


def test_redact_value_cleans_nested_data():
    data = {"a": [CREDENTIAL_URL, {"b": CREDENTIAL_URL}], "n": 3, "none": None}

    assert "supersecret" not in str(redact_value(data))
    assert redact_value(data)["n"] == 3


def test_lfs_rules_refuse_file_names_with_control_characters():
    with pytest.raises(CommitRocketError):
        attribute_line("x\n* filter=lfs")


def test_log_file_never_contains_url_credentials(tmp_path):
    path = logs.setup_logging("DEBUG", tmp_path / "run.log")
    try:
        logging.getLogger("commitrocket.test").info(
            "remote is https://me:supersecret@example.com/r.git"
        )
        try:
            raise RuntimeError("failed for https://me:supersecret@example.com/r.git")
        except RuntimeError:
            logging.getLogger("commitrocket.test").exception("push failed")
    finally:
        logs.close_logging()

    text = path.read_text(encoding="utf-8")
    assert "supersecret" not in text
    assert "https://***@example.com/r.git" in text


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_private_files(tmp_path):
    path = tmp_path / "secret.txt"
    path.write_text("x")
    os.chmod(path, 0o644)

    restrict_permissions(path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_report_and_log_are_private(tmp_path):
    report_path = RunReport().write(tmp_path / "report.json")
    assert stat.S_IMODE(report_path.stat().st_mode) == 0o600

    log_path = logs.setup_logging("INFO", tmp_path / "run.log")
    logs.close_logging()
    assert stat.S_IMODE(log_path.stat().st_mode) == 0o600


def test_report_leaves_no_temporary_files(tmp_path):
    RunReport().write(tmp_path / "report.json")
    assert [p.name for p in tmp_path.iterdir()] == ["report.json"]


def test_square_brackets_in_file_names_are_shown_literally(tmp_path):
    # Rich would otherwise read "[/x]" as markup and fail, or swallow "[HD]".
    # The files need not exist: a missing file is simply shown with size 0.
    names = ["[/x] clip.mp4", "Intro [HD].mp4"]

    output = io.StringIO()
    console = Console(file=output, width=200, force_terminal=False)
    print_lfs_required(console, tmp_path, names, 100)

    text = output.getvalue()
    assert "[/x] clip.mp4" in text
    assert "Intro [HD].mp4" in text
