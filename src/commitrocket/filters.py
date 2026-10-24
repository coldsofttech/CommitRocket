from pathlib import Path

import pathspec

from commitrocket.errors import CommitRocketError

IGNORE_FILE = ".commitrocketignore"


def read_patterns(path):
    """Pattern lines from a file; blank lines and # comments are skipped."""
    try:
        text = Path(path).expanduser().read_text(encoding="utf-8")
    except OSError as exc:
        raise CommitRocketError(f"Cannot read pattern file {path}: {exc}") from exc

    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _spec(lines):
    try:
        return pathspec.PathSpec.from_lines("gitignore", lines)
    except KeyError:
        # pathspec before 1.0 only knows the older name for the same syntax.
        return pathspec.PathSpec.from_lines("gitwildmatch", lines)


class FileFilter:
    """Keep only the files that match --include (if any) and not --exclude.

    Patterns use .gitignore syntax: '*.mp4' matches at any depth, 'raw/' a
    folder, '/notes.txt' only at the repo root, '**' any number of folders.
    Exclusion always wins over inclusion.
    """

    def __init__(self, include=(), exclude=()):
        self.include = _spec(include) if include else None
        self.exclude = _spec(exclude) if exclude else None

    @classmethod
    def from_options(cls, repo, include, exclude, include_from, exclude_from):
        include_lines = list(include)
        for path in include_from:
            include_lines += read_patterns(path)

        exclude_lines = list(exclude)
        for path in exclude_from:
            exclude_lines += read_patterns(path)

        ignore_file = Path(repo) / IGNORE_FILE
        if ignore_file.is_file():
            exclude_lines += read_patterns(ignore_file)

        return cls(include_lines, exclude_lines)

    @property
    def active(self):
        return self.include is not None or self.exclude is not None

    def keeps(self, path):
        if self.exclude is not None and self.exclude.match_file(path):
            return False
        if self.include is not None and not self.include.match_file(path):
            return False
        return True

    def apply(self, paths):
        return [path for path in paths if self.keeps(path)]
