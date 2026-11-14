def run_main(argv):
    import argparse
    import logging

    from rich.console import Console
    from rich.markup import escape

    from commitrocket.cli.parser import build_parser
    from commitrocket.cli.resume import apply_resume, run_params
    from commitrocket.cli.validate import validate
    from commitrocket.core.options import RunOptions
    from commitrocket.core.runner import run
    from commitrocket.io.logs import close_logging, setup_logging
    from commitrocket.io.notify import send_notifications
    from commitrocket.io.report import RunReport
    from commitrocket.support.config import ConfigError, apply_config, find_config

    parser = build_parser()

    # Find the config file first: its values become the parser's defaults, so
    # anything given on the command line still wins.
    pre = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    pre.add_argument("--repo", default=".")
    pre.add_argument("--config")
    known, _ = pre.parse_known_args(argv)

    config_path = None
    ignored_settings = []
    try:
        config_path, values = find_config(known.repo, known.config)
        if values:
            # Only a file named with --config is trusted with sensitive settings.
            ignored_settings = apply_config(
                parser, values, config_path, trusted=bool(known.config)
            )
    except ConfigError as exc:
        parser.error(str(exc))

    args = parser.parse_args(argv)
    if args.resume:
        apply_resume(parser, argv, args, known.repo)
    max_mib = validate(parser, args)
    params = run_params(parser, args)

    options = RunOptions(
        repo=args.repo,
        message=args.message,
        message_template=args.message_template,
        attribution=not args.no_attribution,
        number=args.number,
        force=args.force,
        remote=args.remote,
        branch=args.branch,
        no_push=args.no_push,
        include=args.include or [],
        exclude=args.exclude or [],
        include_from=args.include_from or [],
        exclude_from=args.exclude_from or [],
        limit_mib=args.limit_mib,
        max_mib=max_mib,
        batch_type=args.batch_type,
        use_lfs=args.use_lfs,
        lfs_commit_rules=args.lfs_commit_rules,
        lfs_threshold_mib=args.lfs_threshold_mib,
        lfs_threads=args.lfs_threads,
        lfs_batch_mib=args.lfs_batch_mib,
        compression_threads=args.compression_threads,
        dry_run=args.dry_run,
        retries=args.retries,
        post_buffer_mib=args.post_buffer_mib,
        report=args.report,
        resume=args.resume,
        params=params,
    )

    console = Console()
    log_path = setup_logging(args.level, args.log_file)
    options.log_file = str(log_path) if log_path else None
    if log_path is None:
        console.print(
            "[yellow]Could not open a log file; continuing without one.[/yellow]"
        )
    if config_path:
        console.print(f"[dim]Using config: {escape(str(config_path))}[/dim]")
    if ignored_settings:
        names = ", ".join(ignored_settings)
        console.print(
            f"[yellow]Ignored from {escape(str(config_path))}: {escape(names)}. "
            "Settings that skip the prompt, change where files are pushed or "
            "written, or contact other servers are only used from a file you "
            "pass with --config.[/yellow]"
        )
        logging.getLogger(__name__).warning(
            "Ignored sensitive settings from untrusted config %s: %s",
            config_path,
            names,
        )

    report = RunReport(options)
    try:
        code = run(console, options, report)
        report.finish(code, log_path)

        if args.report:
            try:
                report_path = report.write(args.report)
                console.print(f"\n[dim]Report: {report_path}[/dim]")
            except OSError as exc:
                console.print(f"[yellow]Could not write the report: {exc}[/yellow]")
                logging.getLogger(__name__).warning("Report not written: %s", exc)

        if (args.notify or args.notify_webhook) and not args.dry_run:
            send_notifications(
                console, report, desktop=args.notify, webhook=args.notify_webhook
            )
    finally:
        close_logging()

    if log_path:
        console.print(f"\n[dim]Log file: {log_path}[/dim]")
    return code
