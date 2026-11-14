import pytest

from commitrocket.cli import main
from commitrocket.options import RunOptions
from commitrocket.runner import own_output_files


def test_own_output_files_are_found_only_inside_the_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    options = RunOptions(
        log_file=str(repo / "logs" / "run.log"),
        report=str(tmp_path / "elsewhere" / "report.json"),
    )
    assert own_output_files(repo.resolve(), options) == {"logs/run.log"}

    options = RunOptions(report=str(repo / "report.json"))
    assert own_output_files(repo.resolve(), options) == {"report.json"}
    assert own_output_files(repo.resolve(), RunOptions()) == set()


@pytest.mark.parametrize(
    "argv",
    [
        ["--message", "m", "--no-push", "--use-lfs"],
        ["--message", "m", "--message-template", "{nope}"],
        ["--message", "m", "--lfs-threshold-mib", "150"],
        ["--message", "m", "--retries", "-1"],
        ["--message", "m", "--remote", "--receive-pack=x"],
        ["--message", "m", "--remote", "origin", "--branch", "-d"],
        [],
    ],
)
def test_invalid_combinations_exit_with_usage_error(argv, tmp_path, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--repo", str(tmp_path), *argv])
    assert exit_info.value.code == 2
    assert "error" in capsys.readouterr().err


def captured_options(monkeypatch, argv):
    seen = {}

    def fake_run(console, options, report):
        seen["options"] = options
        return 0

    monkeypatch.setattr("commitrocket.cli.run", fake_run)
    assert main(argv) == 0
    return seen["options"]


def test_attribution_is_on_by_default(monkeypatch, tmp_path):
    argv = [
        "--repo",
        str(tmp_path),
        "--message",
        "m",
        "--log-file",
        str(tmp_path / "l"),
    ]
    assert captured_options(monkeypatch, argv).attribution is True


@pytest.mark.parametrize("flag", ["--no-attribution", "--ignore-attribution"])
def test_attribution_flag_turns_it_off(flag, monkeypatch, tmp_path):
    argv = [
        "--repo",
        str(tmp_path),
        "--message",
        "m",
        "--log-file",
        str(tmp_path / "l"),
        flag,
    ]
    assert captured_options(monkeypatch, argv).attribution is False


def test_attribution_can_be_turned_off_in_the_config_file(monkeypatch, tmp_path):
    (tmp_path / "commitrocket.toml").write_text("no-attribution = true\n")
    argv = [
        "--repo",
        str(tmp_path),
        "--message",
        "m",
        "--log-file",
        str(tmp_path / "l"),
    ]
    assert captured_options(monkeypatch, argv).attribution is False


def test_attribution_flag_is_listed_in_help(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "--no-attribution" in capsys.readouterr().out
