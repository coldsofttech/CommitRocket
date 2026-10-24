import json

from commitrocket.options import RunOptions
from commitrocket.report import DEFERRED, SUCCESS, RunReport


def make_report(**settings):
    report = RunReport(RunOptions(message="Videos", **settings))
    report.repo = "/repo"
    report.branch = "main"
    report.target = "origin/main"
    return report


def test_report_structure_and_totals():
    report = make_report()
    entry = report.add_batch(1, "Videos #1", ["a.mp4", "b.mp4"], 3000, lfs_files=1)
    entry["pushed"] = True
    report.add_batch(2, "Videos #2", ["c.mp4"], 500)
    report.set_deferred([("huge.mp4", 9_000_000)])
    report.status = DEFERRED
    report.finish(2, "/logs/run.log")

    data = report.to_dict()
    assert data["schema_version"] == 1
    assert data["status"] == DEFERRED
    assert data["exit_code"] == 2
    assert data["target"] == "origin/main"
    assert data["log_file"] == "/logs/run.log"
    assert data["totals"] == {
        "batches": 2,
        "files": 3,
        "size_bytes": 3500,
        "deferred_files": 1,
    }
    assert data["batches"][0]["pushed"] is True
    assert data["batches"][0]["lfs_file_count"] == 1
    assert data["batches"][1]["pushed"] is False
    assert data["deferred"] == [{"path": "huge.mp4", "size_bytes": 9_000_000}]
    assert data["settings"]["message"] == "Videos"


def test_write_creates_folders_and_valid_json(tmp_path):
    report = make_report(dry_run=True)
    report.status = SUCCESS
    report.finish(0)

    path = report.write(tmp_path / "out" / "report.json")

    assert json.loads(path.read_text(encoding="utf-8"))["dry_run"] is True
    assert not list(path.parent.glob("*.tmp"))


def test_write_replaces_an_existing_file(tmp_path):
    target = tmp_path / "report.json"
    target.write_text("old")
    make_report().write(target)
    assert json.loads(target.read_text(encoding="utf-8"))["tool"] == "commitrocket"
