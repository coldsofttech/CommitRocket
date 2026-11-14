import pytest

from commitrocket.cli import main
from commitrocket.cli.parser import DEFAULT_LIMIT_MIB, DEFAULT_RETRIES, build_parser


def test_defaults():
    args = build_parser().parse_args([])
    assert args.message is None
    assert args.repo == "."
    assert args.limit_mib == DEFAULT_LIMIT_MIB
    assert args.retries == DEFAULT_RETRIES
    assert args.resume is False
    assert args.no_attribution is False
    assert args.no_push is False
    assert args.dry_run is False


def test_resume_flag():
    assert build_parser().parse_args(["--resume"]).resume is True


@pytest.mark.parametrize("flag", ["--no-attribution", "--ignore-attribution"])
def test_attribution_flag_has_an_alias(flag):
    assert build_parser().parse_args([flag]).no_attribution is True


def test_include_and_exclude_can_be_repeated():
    args = build_parser().parse_args(
        ["--include", "a/*", "--include", "b/*", "--exclude", "*.log"]
    )
    assert args.include == ["a/*", "b/*"]
    assert args.exclude == ["*.log"]


def test_unknown_batch_type_is_rejected(capsys):
    with pytest.raises(SystemExit) as exit_info:
        build_parser().parse_args(["--batch-type", "nope"])
    assert exit_info.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_option_without_its_value_is_rejected(capsys):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--limit-mib"])
    assert "expected one argument" in capsys.readouterr().err


def test_version_is_printed(capsys):
    from commitrocket import __version__

    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_help_lists_the_resume_and_attribution_flags(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert "--resume" in out
    assert "--no-attribution" in out
