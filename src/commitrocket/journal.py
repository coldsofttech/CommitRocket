import json
from pathlib import Path

from commitrocket.git import run_git


class Journal:
    """Remembers the batch being staged so an interrupted run can be resumed.

    It lives inside .git, is written before `git add` and removed once the commit
    exists. Staged files that match it are ours; any other staged file is not.
    """

    def __init__(self, repo):
        relative = run_git(
            repo, "rev-parse", "--git-path", "commitrocket-journal.json"
        ).stdout.strip()
        self.path = Path(repo) / relative

    def read(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def write(self, files, message, number):
        entry = {"files": list(files), "message": message, "number": number}
        self.path.write_text(json.dumps(entry), encoding="utf-8")

    def clear(self):
        self.path.unlink(missing_ok=True)
