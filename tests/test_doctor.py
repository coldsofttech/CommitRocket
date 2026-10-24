from rich.console import Console

from commitrocket.doctor import FAIL, PASS, collect_checks, run_doctor


def statuses(results):
    return {name: status for status, name, _ in results}


def test_repository_without_upstream_fails_the_push_target_check(git_repo):
    (git_repo / "a.txt").write_text("x")
    results = collect_checks(git_repo, offline=True)

    found = statuses(results)
    assert found["Git"] == PASS
    assert found["Repository"] == PASS
    assert found["Push target"] == FAIL


def test_explicit_remote_is_enough_for_the_push_target(git_repo):
    results = collect_checks(git_repo, remote="origin", offline=True)
    assert statuses(results)["Push target"] == PASS
    assert statuses(results)["Remote access"] == "skip"


def test_not_a_repository(tmp_path):
    found = statuses(collect_checks(tmp_path, offline=True))
    assert found["Repository"] == FAIL


def test_run_doctor_exit_code(git_repo):
    console = Console(quiet=True)
    assert run_doctor(console, git_repo, offline=True) == 1
    assert run_doctor(console, git_repo, remote="origin", offline=True) == 0
