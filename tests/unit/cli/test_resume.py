import pytest

from commitrocket.cli.parser import build_parser
from commitrocket.cli.resume import (
    NOT_RUN_PARAMS,
    apply_resume,
    explicit_arguments,
    run_params,
)
from commitrocket.git.journal import Journal


def stored_run(repo, *argv):
    """Write a journal for a run started with argv."""
    parser = build_parser()
    params = run_params(parser, parser.parse_args(list(argv)))
    Journal(repo).start(params, "main", "origin/main", "abc123")
    return params


def resume_args(repo, *extra):
    parser = build_parser()
    argv = ["--repo", str(repo), "--resume", *extra]
    return parser, argv, parser.parse_args(argv)


def test_run_params_leave_out_settings_that_are_not_part_of_the_run():
    parser = build_parser()
    params = run_params(parser, parser.parse_args(["--message", "m"]))
    assert params["message"] == "m"
    assert params["limit_mib"] == 100
    assert not NOT_RUN_PARAMS & params.keys()


def test_explicit_arguments_only_hold_what_was_given():
    given = explicit_arguments(["--message", "m", "--no-push"])
    assert given == {"message": "m", "no_push": True}


def test_apply_resume_without_a_journal_is_a_usage_error(git_repo, capsys):
    parser, argv, args = resume_args(git_repo)
    with pytest.raises(SystemExit) as exit_info:
        apply_resume(parser, argv, args, str(git_repo))
    assert exit_info.value.code == 2
    assert "no interrupted run" in capsys.readouterr().err


def test_apply_resume_restores_the_stored_parameters(git_repo):
    stored_run(git_repo, "--message", "stored", "--limit-mib", "7", "--no-push")
    parser, argv, args = resume_args(git_repo)

    apply_resume(parser, argv, args, str(git_repo))

    assert args.message == "stored"
    assert args.limit_mib == 7
    assert args.no_push is True


def test_apply_resume_accepts_identical_parameters(git_repo):
    stored_run(git_repo, "--message", "stored")
    parser, argv, args = resume_args(git_repo, "--message", "stored")

    apply_resume(parser, argv, args, str(git_repo))

    assert args.message == "stored"


def test_apply_resume_rejects_different_parameters(git_repo, capsys):
    stored_run(git_repo, "--message", "stored", "--limit-mib", "7")
    parser, argv, args = resume_args(git_repo, "--message", "other")
    with pytest.raises(SystemExit) as exit_info:
        apply_resume(parser, argv, args, str(git_repo))
    assert exit_info.value.code == 2
    message = capsys.readouterr().err.splitlines()[-2:]
    assert "differ from it: --message." in " ".join(message)


def test_apply_resume_reports_an_incompatible_journal(git_repo, capsys):
    Journal(git_repo).path.write_text(
        '{"event": "run", "version": 999}\n', encoding="utf-8"
    )
    parser, argv, args = resume_args(git_repo)
    with pytest.raises(SystemExit) as exit_info:
        apply_resume(parser, argv, args, str(git_repo))
    assert exit_info.value.code == 2
    assert "incompatible" in capsys.readouterr().err
