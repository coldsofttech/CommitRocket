import pytest

from commitrocket.cli import main


def base_argv(tmp_path, *extra):
    return [
        "--repo",
        str(tmp_path),
        "--message",
        "m",
        "--log-file",
        str(tmp_path / "l"),
        *extra,
    ]


def captured_options(monkeypatch, argv, code=0):
    seen = {}

    def fake_run(console, options, report):
        seen["options"] = options
        return code

    monkeypatch.setattr("commitrocket.core.runner.run", fake_run)
    seen["code"] = main(argv)
    return seen


def test_attribution_is_on_by_default(monkeypatch, tmp_path):
    seen = captured_options(monkeypatch, base_argv(tmp_path))
    assert seen["options"].attribution is True


@pytest.mark.parametrize("flag", ["--no-attribution", "--ignore-attribution"])
def test_attribution_flag_turns_it_off(flag, monkeypatch, tmp_path):
    seen = captured_options(monkeypatch, base_argv(tmp_path, flag))
    assert seen["options"].attribution is False


def test_attribution_can_be_turned_off_in_the_config_file(monkeypatch, tmp_path):
    (tmp_path / "commitrocket.toml").write_text("no-attribution = true\n")
    seen = captured_options(monkeypatch, base_argv(tmp_path))
    assert seen["options"].attribution is False


def test_the_exit_code_of_the_run_is_returned(monkeypatch, tmp_path):
    seen = captured_options(monkeypatch, base_argv(tmp_path), code=2)
    assert seen["code"] == 2


def test_run_parameters_are_handed_to_the_run(monkeypatch, tmp_path):
    seen = captured_options(monkeypatch, base_argv(tmp_path, "--limit-mib", "5"))
    options = seen["options"]
    assert options.resume is False
    assert options.max_mib == 15
    assert options.params["message"] == "m"
    assert options.params["limit_mib"] == 5
    assert "repo" not in options.params


def test_command_line_overrides_the_config_file(monkeypatch, tmp_path):
    (tmp_path / "commitrocket.toml").write_text("limit-mib = 9\n")
    seen = captured_options(monkeypatch, base_argv(tmp_path, "--limit-mib", "4"))
    assert seen["options"].limit_mib == 4


def test_report_is_written_when_requested(monkeypatch, tmp_path):
    report = tmp_path / "report.json"
    captured_options(monkeypatch, base_argv(tmp_path, "--report", str(report)))
    assert report.is_file()


def test_resume_without_an_interrupted_run_is_a_usage_error(git_repo, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--repo", str(git_repo), "--resume"])
    assert exit_info.value.code == 2
    assert "no interrupted run" in capsys.readouterr().err


def test_missing_message_is_a_usage_error(tmp_path, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--repo", str(tmp_path)])
    assert exit_info.value.code == 2
    assert "error" in capsys.readouterr().err
