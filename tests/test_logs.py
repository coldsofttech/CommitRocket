import logging
from pathlib import Path

from commitrocket import logs


def test_default_dir_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(logs.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert logs.default_log_dir() == tmp_path / "CommitRocket" / "Logs"


def test_default_dir_macos(monkeypatch):
    monkeypatch.setattr(logs.sys, "platform", "darwin")
    expected = Path.home() / "Library" / "Logs" / "CommitRocket"
    assert logs.default_log_dir() == expected


def test_default_dir_linux_uses_xdg_state(monkeypatch, tmp_path):
    monkeypatch.setattr(logs.sys, "platform", "linux")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert logs.default_log_dir() == tmp_path / "commitrocket"


def test_setup_logging_writes_file_at_level(tmp_path):
    target = tmp_path / "sub" / "run.log"
    path = logs.setup_logging("INFO", target)
    try:
        logger = logging.getLogger("commitrocket.test")
        logger.debug("hidden")
        logger.info("shown")
    finally:
        logs.close_logging()

    text = path.read_text(encoding="utf-8")
    assert "shown" in text
    assert "hidden" not in text


def test_setup_logging_returns_none_when_unwritable(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert logs.setup_logging("INFO", blocker / "run.log") is None
    logs.close_logging()
