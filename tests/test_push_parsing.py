import pytest

from commitrocket.push import parse_lfs_bytes, parse_progress_line


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Uploading LFS objects:  50% (1/2), 52 MB | 3.2 MB/s", 52_000_000),
        ("Uploading LFS objects: 100% (1/1), 1.5 GB | 12 MB/s", 1_500_000_000),
        ("Uploading LFS objects:   0% (0/1), 0 B | 0 B/s", 0),
        ("Writing objects: 100% (6/6), 235.76 MiB | 846.00 KiB/s, done.", None),
    ],
)
def test_parse_lfs_bytes(line, expected):
    assert parse_lfs_bytes(line) == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Enumerating objects: 5, done.", ("Enumerating objects", None)),
        ("Counting objects:  40% (2/5)", ("Counting objects", 40)),
        ("Compressing objects: 100% (3/3)", ("Compressing objects", 100)),
        ("Writing objects:  50% (1/2)", ("Uploading objects", 50)),
        ("Resolving deltas: 100% (1/1)", ("Resolving deltas", 100)),
        ("To github.com:user/repo.git", ("Git push", None)),
    ],
)
def test_parse_progress_line(line, expected):
    assert parse_progress_line(line) == expected
