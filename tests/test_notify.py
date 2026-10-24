import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from rich.console import Console

from commitrocket import notify
from commitrocket.options import RunOptions
from commitrocket.report import FAILED, SUCCESS, RunReport


def make_report(status=SUCCESS, error=None, **settings):
    report = RunReport(RunOptions(message="m", **settings))
    report.target = "origin/main"
    report.add_batch(1, "m #1", ["a", "b"], 5 * 1024 * 1024)
    report.status = status
    report.error = error
    report.finish(0 if status == SUCCESS else 1)
    return report


def test_message_for_success():
    title, body = notify.build_message(make_report())
    assert title == "CommitRocket finished"
    assert "1 batch(es) pushed, 2 file(s), 5.0 MiB" in body
    assert "to origin/main" in body


def test_message_for_failure_includes_the_first_error_line():
    report = make_report(FAILED, error="git push failed\nmore detail")
    title, body = notify.build_message(report)
    assert title == "CommitRocket failed"
    assert "git push failed" in body
    assert "more detail" not in body


def test_message_says_committed_for_no_push():
    _, body = notify.build_message(make_report(no_push=True))
    assert "committed" in body


@pytest.mark.parametrize(
    ("url", "valid"),
    [
        ("https://hooks.example.com/abc", True),
        ("http://localhost:8080/x", True),
        ("file:///etc/passwd", False),
        ("ftp://example.com/x", False),
        ("not a url", False),
    ],
)
def test_webhook_url_validation(url, valid):
    assert notify.is_valid_webhook(url) is valid


def test_desktop_falls_back_to_the_bell(monkeypatch, capsys):
    monkeypatch.setattr(notify.sys, "platform", "linux")
    monkeypatch.setattr(notify.shutil, "which", lambda name: None)

    assert notify.notify_desktop("t", "b") == "bell"
    assert "\a" in capsys.readouterr().out


def test_desktop_uses_notify_send_on_linux(monkeypatch):
    calls = []
    monkeypatch.setattr(notify.sys, "platform", "linux")
    monkeypatch.setattr(notify.shutil, "which", lambda name: "/usr/bin/" + name)

    def fake_run(command, env):
        calls.append((command, env))
        return True

    monkeypatch.setattr(notify, "_run_quietly", fake_run)

    assert notify.notify_desktop("Title", "Body") == "notify-send"
    command, env = calls[0]
    assert command[0] == "notify-send" and command[-2:] == ["Title", "Body"]
    assert env == {"CR_TITLE": "Title", "CR_BODY": "Body"}


def test_webhook_receives_a_json_summary():
    received = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            received["body"] = json.loads(self.rfile.read(length))
            received["title"] = self.headers["Title"]
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/hook"
        notify.send_notifications(Console(quiet=True), make_report(), webhook=url)
    finally:
        server.shutdown()
        server.server_close()

    body = received["body"]
    assert received["title"] == "CommitRocket finished"
    assert body["status"] == SUCCESS
    assert body["batches"] == 1
    assert body["files"] == 2
    assert body["text"].startswith("CommitRocket finished")


def test_unreachable_webhook_does_not_raise():
    # Nothing listens on port 9, so the request fails; the run must not.
    notify.send_notifications(
        Console(quiet=True), make_report(), webhook="http://127.0.0.1:9/hook"
    )
