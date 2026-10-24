import pytest

from commitrocket.batching import MIB
from commitrocket.errors import CommitRocketError
from commitrocket.git import run_git
from commitrocket.lfs import (
    LfsSession,
    all_files_rules,
    attribute_line,
    committed_rule_lines,
    find_lfs_candidates,
)


def test_attribute_line_quotes_spaces_and_escapes_globs():
    assert attribute_line("a b [1].mp4") == (
        '"/a b \\\\[1\\\\].mp4" filter=lfs diff=lfs merge=lfs -text'
    )


def test_committed_rules_use_extensions_and_exact_paths():
    paths = ["a.mp4", "dir/b.mp4", "c.ZIP", "Makefile", "x y/.gitignore", "d e.mp4"]
    assert committed_rule_lines(paths) == [
        '"/Makefile" filter=lfs diff=lfs merge=lfs -text',
        "*.ZIP filter=lfs diff=lfs merge=lfs -text",
        "*.mp4 filter=lfs diff=lfs merge=lfs -text",
    ]


def test_write_committed_rules_appends_once(git_repo):
    (git_repo / ".gitattributes").write_text("*.txt text")
    run_git(git_repo, "add", ".gitattributes")
    run_git(git_repo, "commit", "-m", "attrs")

    session = LfsSession(git_repo)
    assert session.write_committed_rules(["a.mp4", "b.mp4"]) is True
    text = (git_repo / ".gitattributes").read_text()
    assert text == "*.txt text\n*.mp4 filter=lfs diff=lfs merge=lfs -text\n"

    run_git(git_repo, "add", ".gitattributes")
    run_git(git_repo, "commit", "-m", "rules")
    assert session.write_committed_rules(["c.mp4"]) is False


def test_write_committed_rules_refuses_dirty_gitattributes(git_repo):
    (git_repo / ".gitattributes").write_text("*.txt text")
    with pytest.raises(CommitRocketError):
        LfsSession(git_repo).write_committed_rules(["a.mp4"])


def test_zero_threshold_selects_every_non_empty_file(tmp_path):
    (tmp_path / "empty").write_bytes(b"")
    (tmp_path / "tiny").write_bytes(b"x")
    (tmp_path / "big").write_bytes(b"x" * MIB)

    files = ["empty", "tiny", "big"]
    assert find_lfs_candidates(tmp_path, files, 0, 5 * MIB) == ["tiny", "big"]


def test_all_files_rules_exclude_git_config_files():
    rules = all_files_rules()
    assert rules[0] == "* filter=lfs diff=lfs merge=lfs -text"
    assert ".gitattributes !filter !diff !merge !text" in rules


def test_session_restores_attributes_file(git_repo):
    (git_repo / ".git" / "info").mkdir(exist_ok=True)
    attributes = git_repo / ".git" / "info" / "attributes"
    attributes.write_text("*.txt text")

    session = LfsSession(git_repo)
    session.attributes_path = attributes
    session.original = attributes.read_bytes()
    attributes.write_text("*.txt text\n" + attribute_line("big.mp4") + "\n")

    session.close()
    assert attributes.read_text() == "*.txt text"


def test_candidates_are_above_threshold_and_within_max(tmp_path):
    sizes = {"small": MIB, "edge": 2 * MIB, "big": 3 * MIB, "huge": 9 * MIB}
    for name, size in sizes.items():
        (tmp_path / name).write_bytes(b"x" * size)

    files = ["small", "edge", "big", "huge"]
    assert find_lfs_candidates(tmp_path, files, 2 * MIB, 5 * MIB) == ["big"]
