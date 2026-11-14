def doctor_main(argv):
    import argparse

    from rich.console import Console

    from commitrocket.io.logs import DEFAULT_LEVEL, close_logging, setup_logging
    from commitrocket.support.doctor import run_doctor

    parser = argparse.ArgumentParser(
        prog="commitrocket doctor",
        description="Check that Git, git-lfs, the repository, the remote and "
        "your settings are ready for a run. Changes nothing.",
        allow_abbrev=False,
    )
    parser.add_argument("--repo", default=".", help="Repository to check (default: .)")
    parser.add_argument("--remote", default=None, help="Remote to check")
    parser.add_argument("--branch", default=None, help="Remote branch to check")
    parser.add_argument("--config", default=None, help="Config file to check")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip the checks that contact the remote",
    )
    args = parser.parse_args(argv)

    console = Console()
    log_path = setup_logging(DEFAULT_LEVEL, None)
    try:
        code = run_doctor(
            console,
            args.repo,
            remote=args.remote,
            branch=args.branch,
            offline=args.offline,
            config_path=args.config,
        )
    finally:
        close_logging()

    if log_path:
        console.print(f"\n[dim]Log file: {log_path}[/dim]")
    return code
