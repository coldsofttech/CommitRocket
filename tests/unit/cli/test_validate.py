import pytest

from commitrocket.cli.parser import build_parser
from commitrocket.cli.validate import validate


def check(*argv):
    parser = build_parser()
    return validate(parser, parser.parse_args(list(argv)))


@pytest.mark.parametrize(
    "argv",
    [
        ["--message", "m", "--no-push", "--use-lfs"],
        ["--message", "m", "--message-template", "{nope}"],
        ["--message", "m", "--lfs-threshold-mib", "150"],
        ["--message", "m", "--lfs-threshold-mib", "-1"],
        ["--message", "m", "--retries", "-1"],
        ["--message", "m", "--limit-mib", "0"],
        ["--message", "m", "--number", "-1"],
        ["--message", "m", "--compression-threads", "-1"],
        ["--message", "m", "--lfs-threads", "0"],
        ["--message", "m", "--post-buffer-mib", "0"],
        ["--message", "m", "--lfs-batch-mib", "0"],
        ["--message", "m", "--remote", "--receive-pack=x"],
        ["--message", "m", "--remote", "origin", "--branch", "-d"],
        ["--message", "m", "--notify-webhook", "ftp://example.com"],
        ["--message", "m", "--limit-mib", "50", "--max-mib", "10"],
        ["--message", "   "],
        [],
    ],
)
def test_invalid_combinations_exit_with_usage_error(argv, capsys):
    with pytest.raises(SystemExit) as exit_info:
        check(*argv)
    assert exit_info.value.code == 2
    assert "error" in capsys.readouterr().err


def test_max_mib_defaults_to_three_times_the_limit():
    assert check("--message", "m", "--limit-mib", "40") == 120


def test_explicit_max_mib_is_kept():
    assert check("--message", "m", "--limit-mib", "40", "--max-mib", "60") == 60


def test_max_mib_equal_to_the_limit_is_allowed():
    assert check("--message", "m", "--limit-mib", "40", "--max-mib", "40") == 40
