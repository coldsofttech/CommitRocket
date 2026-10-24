import pytest

from commitrocket.cli import build_parser
from commitrocket.config import ConfigError, apply_config, find_config


def parse(tmp_path, toml, argv=(), name="commitrocket.toml"):
    (tmp_path / name).write_text(toml)
    parser = build_parser()
    path, values = find_config(tmp_path)
    apply_config(parser, values, path)
    return parser.parse_args(list(argv))


def test_no_config_found(tmp_path):
    assert find_config(tmp_path) == (None, {})


def test_values_become_defaults(tmp_path):
    args = parse(
        tmp_path,
        'message = "Videos"\nlimit-mib = 50\nuse_lfs = true\n'
        'include = ["*.mp4"]\nbatch-type = "soft"\n',
    )
    assert args.message == "Videos"
    assert args.limit_mib == 50
    assert args.use_lfs is True
    assert args.include == ["*.mp4"]
    assert args.batch_type == "soft"


def test_command_line_wins_and_lists_combine(tmp_path):
    args = parse(
        tmp_path,
        'message = "Videos"\nlimit-mib = 50\ninclude = ["*.mp4"]\n',
        ["--limit-mib", "20", "--include", "*.zip"],
    )
    assert args.limit_mib == 20
    assert args.include == ["*.mp4", "*.zip"]


def test_pyproject_table_is_used(tmp_path):
    toml = '[project]\nname = "x"\n\n[tool.commitrocket]\nretries = 7\n'
    args = parse(tmp_path, toml, name="pyproject.toml")
    assert args.retries == 7


def test_commitrocket_toml_beats_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.commitrocket]\nretries = 7\n")
    args = parse(tmp_path, "retries = 2\n")
    assert args.retries == 2


def test_pyproject_without_table_is_ignored(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    assert find_config(tmp_path) == (None, {})


@pytest.mark.parametrize(
    "toml",
    [
        "unknown-option = 1\n",
        'limit-mib = "lots"\n',
        'force = "yes"\n',
        'batch-type = "random"\n',
        "include = 5\n",
        'repo = "elsewhere"\n',
        "this is not toml\n",
    ],
)
def test_bad_config_is_rejected(tmp_path, toml):
    with pytest.raises(ConfigError):
        parse(tmp_path, toml)


SENSITIVE = (
    'force = true\nremote = "evil"\nbranch = "evil"\nreport = "/tmp/x"\n'
    'log-file = "/tmp/y"\nnotify-webhook = "https://evil.example/h"\n'
    'include-from = ["/etc/passwd"]\nexclude-from = ["/etc/passwd"]\n'
    "retries = 9\n"
)


def load(tmp_path, toml, trusted):
    (tmp_path / "commitrocket.toml").write_text(toml)
    parser = build_parser()
    path, values = find_config(tmp_path)
    ignored = apply_config(parser, values, path, trusted=trusted)
    return parser.parse_args([]), ignored


def test_untrusted_config_cannot_set_sensitive_options(tmp_path):
    args, ignored = load(tmp_path, SENSITIVE, trusted=False)

    assert sorted(ignored) == sorted(
        [
            "force",
            "remote",
            "branch",
            "report",
            "log-file",
            "notify-webhook",
            "include-from",
            "exclude-from",
        ]
    )
    assert args.force is False
    assert args.remote is None and args.branch is None
    assert args.report is None and args.log_file is None
    assert args.notify_webhook is None
    assert args.include_from is None and args.exclude_from is None
    assert args.retries == 9  # ordinary settings still apply


def test_explicit_config_may_set_sensitive_options(tmp_path):
    args, ignored = load(tmp_path, SENSITIVE, trusted=True)

    assert ignored == []
    assert args.force is True
    assert args.remote == "evil"
    assert args.notify_webhook == "https://evil.example/h"


def test_explicit_config_must_exist(tmp_path):
    with pytest.raises(ConfigError):
        find_config(tmp_path, tmp_path / "missing.toml")
