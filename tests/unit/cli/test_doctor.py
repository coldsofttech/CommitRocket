import pytest

from commitrocket.cli.doctor import doctor_main


@pytest.fixture
def doctor(monkeypatch):
    seen = {}

    def fake_run_doctor(console, repo, **kwargs):
        seen["repo"] = repo
        seen.update(kwargs)
        return 3

    monkeypatch.setattr("commitrocket.support.doctor.run_doctor", fake_run_doctor)
    monkeypatch.setattr("commitrocket.io.logs.setup_logging", lambda *a: None)
    return seen


def test_arguments_are_passed_to_the_checks(doctor):
    code = doctor_main(
        ["--repo", "r", "--remote", "origin", "--branch", "main", "--offline"]
    )
    assert code == 3
    assert doctor == {
        "repo": "r",
        "remote": "origin",
        "branch": "main",
        "offline": True,
        "config_path": None,
    }


def test_defaults(doctor):
    doctor_main([])
    assert doctor["repo"] == "."
    assert doctor["offline"] is False


def test_unknown_option_is_a_usage_error(doctor):
    with pytest.raises(SystemExit) as exit_info:
        doctor_main(["--nope"])
    assert exit_info.value.code == 2
