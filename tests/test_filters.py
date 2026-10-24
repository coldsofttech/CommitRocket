import pytest

from commitrocket.errors import CommitRocketError
from commitrocket.filters import FileFilter, read_patterns

FILES = ["a.mp4", "notes.txt", "raw/b.mp4", "raw/c.zip", "docs/readme.md"]


def test_no_patterns_keeps_everything():
    file_filter = FileFilter()
    assert file_filter.active is False
    assert file_filter.apply(FILES) == FILES


def test_include_by_extension_matches_at_any_depth():
    assert FileFilter(include=["*.mp4"]).apply(FILES) == ["a.mp4", "raw/b.mp4"]


def test_exclude_folder_and_anchored_pattern():
    kept = FileFilter(exclude=["raw/", "/notes.txt"]).apply(FILES)
    assert kept == ["a.mp4", "docs/readme.md"]


def test_exclude_wins_over_include():
    kept = FileFilter(include=["*.mp4"], exclude=["raw/"]).apply(FILES)
    assert kept == ["a.mp4"]


def test_double_star_pattern():
    assert FileFilter(include=["raw/**"]).apply(FILES) == ["raw/b.mp4", "raw/c.zip"]


def test_read_patterns_skips_blanks_and_comments(tmp_path):
    file = tmp_path / "patterns.txt"
    file.write_text("# videos\n*.mp4\n\n  *.zip  \n")
    assert read_patterns(file) == ["*.mp4", "*.zip"]


def test_missing_pattern_file_is_an_error(tmp_path):
    with pytest.raises(CommitRocketError):
        read_patterns(tmp_path / "missing.txt")


def test_from_options_reads_files_and_ignore_file(tmp_path):
    (tmp_path / "inc.txt").write_text("*.mp4\n*.zip\n")
    (tmp_path / ".commitrocketignore").write_text("raw/\n")

    file_filter = FileFilter.from_options(
        tmp_path, [], [], [str(tmp_path / "inc.txt")], []
    )
    assert file_filter.apply(FILES) == ["a.mp4"]
