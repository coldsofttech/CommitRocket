# Settings of a run that are not part of its identity: they never need to match
# the interrupted run when resuming.
NOT_RUN_PARAMS = {
    "help",
    "version",
    "config",
    "repo",
    "resume",
    "force",
    "dry_run",
    "report",
    "log_file",
    "level",
    "notify",
    "notify_webhook",
}


def run_params(parser, args):
    """The parameters that identify a run, as stored in the journal."""
    return {
        action.dest: getattr(args, action.dest)
        for action in parser._actions
        if action.dest not in NOT_RUN_PARAMS and hasattr(args, action.dest)
    }


def explicit_arguments(argv):
    """The destinations (and values) given on the command line, defaults excluded."""
    import argparse

    from commitrocket.cli.parser import build_parser

    parser = build_parser()
    for action in parser._actions:
        if action.dest != "help":
            action.default = argparse.SUPPRESS
    return vars(parser.parse_args(argv))


def apply_resume(parser, argv, args, repo):
    """Replace the run parameters in args with those stored by the interrupted run."""
    from commitrocket.git.git import run_git
    from commitrocket.git.journal import Journal
    from commitrocket.support.errors import CommitRocketError

    try:
        root = run_git(repo, "rev-parse", "--show-toplevel").stdout.strip()
        state = Journal(root).state()
    except CommitRocketError as exc:
        parser.error(f"--resume: {exc}")
    if state is None:
        parser.error(
            "--resume: no interrupted run found in this repository. "
            "Run without --resume to start a new run."
        )

    stored = state["params"]
    given = explicit_arguments(argv)
    differing = [
        action.option_strings[0]
        for action in parser._actions
        if action.dest in stored
        and action.dest in given
        and given[action.dest] != stored[action.dest]
    ]
    if differing:
        parser.error(
            "--resume reuses the parameters of the interrupted run, but these "
            f"differ from it: {', '.join(differing)}. Remove them, or run without "
            "--resume to start a new run."
        )
    for dest, value in stored.items():
        if hasattr(args, dest):
            setattr(args, dest, value)
