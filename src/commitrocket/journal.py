import json
import os
from datetime import UTC, datetime
from pathlib import Path

from commitrocket.errors import CommitRocketError
from commitrocket.git import run_git
from commitrocket.security import restrict_permissions

JOURNAL_NAME = "commitrocket-journal.jsonl"
LEGACY_NAME = "commitrocket-journal.json"
JOURNAL_VERSION = 1


class JournalError(CommitRocketError):
    """The journal cannot be used (for example it is from another version)."""


class Journal:
    """An append-only log of a run, kept in .git so it is never committed.

    Each line is one JSON event: `run` (the parameters of the run, written once),
    `staged` (before `git add`), `committed`, `pushed`, `resumed` and finally
    `interrupted` or `failed`. The state of the run is rebuilt by replaying the
    lines, and a line cut short by a crash is ignored. The file is removed when a
    run finishes. Staged files that match the in-flight batch are ours; any other
    staged file is not.
    """

    def __init__(self, repo):
        self.path = self._git_path(repo, JOURNAL_NAME)
        self._legacy = self._git_path(repo, LEGACY_NAME)

    @staticmethod
    def _git_path(repo, name):
        relative = run_git(repo, "rev-parse", "--git-path", name).stdout.strip()
        return Path(repo) / relative

    # -- writing -----------------------------------------------------------

    def start(self, params, branch, target, head):
        """Begin a new journal for a run, replacing any earlier one."""
        self._legacy.unlink(missing_ok=True)
        self.path.unlink(missing_ok=True)
        self.append(
            {
                "event": "run",
                "version": JOURNAL_VERSION,
                "params": params,
                "branch": branch,
                "target": target,
                "head": head,
            }
        )

    def append(self, event):
        event = {**event, "at": datetime.now(UTC).isoformat(timespec="seconds")}
        created = not self.path.exists()
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        if created:
            restrict_permissions(self.path)

    def write(self, files, message, number):
        """Record the batch about to be staged."""
        self.append(
            {
                "event": "staged",
                "files": list(files),
                "message": message,
                "number": number,
            }
        )

    def committed(self, number, sha):
        self.append({"event": "committed", "number": number, "sha": sha})

    def pushed(self, sha):
        self.append({"event": "pushed", "sha": sha})

    def note(self, event, **details):
        """Append a status event, ignoring a journal that cannot be written."""
        try:
            self.append({"event": event, **details})
        except OSError:
            pass

    def delete(self):
        self.path.unlink(missing_ok=True)
        self._legacy.unlink(missing_ok=True)

    # -- reading -----------------------------------------------------------

    def events(self):
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return []
        events = []
        for line in text.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue  # a line cut short by a crash
            if isinstance(event, dict):
                events.append(event)
        return events

    def state(self):
        """Replay the journal. Returns None when there is no usable run in it.

        Raises JournalError if the journal was written by another version.
        """
        run = None
        inflight = None
        commits = []
        pushed = None
        status = "running"
        for event in self.events():
            kind = event.get("event")
            if kind == "run":
                run = event
            elif kind == "staged":
                inflight = event
            elif kind == "committed":
                commits.append((event.get("number"), event.get("sha")))
                if inflight and inflight.get("number") == event.get("number"):
                    inflight = None
            elif kind == "pushed":
                pushed = event.get("sha")
            elif kind in ("interrupted", "failed"):
                status = kind
        if run is None:
            return None
        if run.get("version") != JOURNAL_VERSION or not isinstance(
            run.get("params"), dict
        ):
            raise JournalError(
                f"{self.path} was written by an incompatible CommitRocket version "
                "or is damaged. Delete it and run without --resume to start over."
            )
        numbers = [n for n, _ in commits if isinstance(n, int)]
        return {
            "params": run["params"],
            "branch": run.get("branch"),
            "target": run.get("target"),
            "head": run.get("head"),
            "commits": commits,
            "pushed": pushed,
            "inflight": inflight,
            "status": status,
            "next_number": max(numbers) + 1 if numbers else 0,
        }

    def read(self):
        """The batch that was being staged when the run stopped, or None."""
        try:
            state = self.state()
        except JournalError:
            return None
        inflight = state and state["inflight"]
        if not inflight:
            return None
        return {
            "files": inflight.get("files", []),
            "message": inflight.get("message", ""),
            "number": inflight.get("number"),
        }
