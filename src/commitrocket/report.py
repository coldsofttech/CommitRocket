import json
import os
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from commitrocket import __version__

SCHEMA_VERSION = 1

SUCCESS = "success"
DEFERRED = "completed_with_deferred_files"
DRY_RUN = "dry_run"
CANCELLED = "cancelled"
ABORTED = "aborted"
INTERRUPTED = "interrupted"
FAILED = "failed"


class RunReport:
    """Collects what a run did, for --report and for notifications."""

    def __init__(self, options=None):
        self.started_at = datetime.now(UTC)
        self._started = time.monotonic()
        self.finished_at = None
        self.duration_seconds = None
        self.status = FAILED
        self.exit_code = None
        self.error = None
        self.repo = None
        self.branch = None
        self.target = None
        self.log_file = None
        self.settings = asdict(options) if options else {}
        self.resumed = {"staged_files": 0, "unpushed_commits": 0}
        self.lfs = {"files": 0, "rules_commit": None}
        self.batches = []
        self.deferred = []

    def abort(self, reason):
        self.status = ABORTED
        self.error = reason

    def add_batch(self, number, message, files, size_bytes, lfs_files=0, commit=None):
        entry = {
            "number": number,
            "message": message,
            "commit": commit,
            "file_count": len(files),
            "size_bytes": size_bytes,
            "lfs_file_count": lfs_files,
            "pushed": False,
            "verified": False,
            "files": list(files),
        }
        self.batches.append(entry)
        return entry

    def set_deferred(self, items):
        self.deferred = [{"path": path, "size_bytes": size} for path, size in items]

    def finish(self, exit_code, log_file=None):
        self.exit_code = exit_code
        self.log_file = str(log_file) if log_file else None
        self.finished_at = datetime.now(UTC)
        self.duration_seconds = round(time.monotonic() - self._started, 3)

    @property
    def total_files(self):
        return sum(batch["file_count"] for batch in self.batches)

    @property
    def total_bytes(self):
        return sum(batch["size_bytes"] for batch in self.batches)

    def to_dict(self):
        return {
            "schema_version": SCHEMA_VERSION,
            "tool": "commitrocket",
            "version": __version__,
            "status": self.status,
            "exit_code": self.exit_code,
            "error": self.error,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_seconds": self.duration_seconds,
            "repo": self.repo,
            "branch": self.branch,
            "target": self.target,
            "dry_run": bool(self.settings.get("dry_run")),
            "no_push": bool(self.settings.get("no_push")),
            "settings": self.settings,
            "resumed": self.resumed,
            "lfs": self.lfs,
            "totals": {
                "batches": len(self.batches),
                "files": self.total_files,
                "size_bytes": self.total_bytes,
                "deferred_files": len(self.deferred),
            },
            "batches": self.batches,
            "deferred": self.deferred,
            "log_file": self.log_file,
        }

    def write(self, path):
        """Write the report as JSON, replacing any file there in one step."""
        path = Path(path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
        return path.resolve()
