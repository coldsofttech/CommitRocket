import argparse
import logging
import sys

from rich.console import Console

from commitrocket import __version__
from commitrocket.batching import BATCH_TYPES, DETERMINISTIC
from commitrocket.config import ConfigError, apply_config, find_config
from commitrocket.doctor import run_doctor
from commitrocket.lfs import LFS_THRESHOLD_MIB
from commitrocket.logs import (
    DEFAULT_LEVEL,
    LOG_LEVELS,
    close_logging,
    default_log_dir,
    setup_logging,
)
from commitrocket.notify import is_valid_webhook, send_notifications
from commitrocket.options import RunOptions
from commitrocket.report import RunReport
from commitrocket.runner import run
from commitrocket.template import DEFAULT_TEMPLATE, PLACEHOLDERS, validate_template

DEFAULT_LIMIT_MIB = 100
DEFAULT_RETRIES = 3


def build_parser():
    parser = argparse.ArgumentParser(
        prog="commitrocket",
        description="Batch Git changes, commit each batch, and push "
        "with progress reporting. Run 'commitrocket doctor' to check your setup.",
        allow_abbrev=False,
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--repo", default=".", help="Path to the Git repository (default: .)"
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Read settings from this TOML file instead of commitrocket.toml / "
        "[tool.commitrocket] in pyproject.toml. Command-line options win",
    )
    parser.add_argument(
        "--message",
        default=None,
        help="Base commit message (required, here or in the config file)",
    )
    parser.add_argument(
        "--message-template",
        default=DEFAULT_TEMPLATE,
        help=f"Commit message for each batch (default: '{DEFAULT_TEMPLATE}'). "
        f"Placeholders: {', '.join(PLACEHOLDERS)}",
    )
    parser.add_argument(
        "--number",
        type=int,
        default=1,
        help="Starting commit suffix number (default: 1)",
    )
    parser.add_argument("--force", action="store_true", help="Skip confirmation")
    parser.add_argument(
        "--remote",
        default=None,
        help="Remote to push to (default: the branch's upstream remote)",
    )
    parser.add_argument(
        "--branch",
        default=None,
        help="Remote branch to push to (default: the branch's upstream branch, "
        "or the current branch name)",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Commit every batch but don't push; a later run pushes them",
    )
    parser.add_argument(
        "--include",
        action="append",
        default=None,
        metavar="GLOB",
        help="Only handle files matching this .gitignore-style pattern "
        "(repeatable), e.g. '*.mp4' or 'videos/**'",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=None,
        metavar="GLOB",
        help="Leave files matching this pattern alone (repeatable); wins over "
        "--include. Patterns in .commitrocketignore are always excluded",
    )
    parser.add_argument(
        "--include-from",
        action="append",
        default=None,
        metavar="FILE",
        help="Read --include patterns from a file, one per line (# comments)",
    )
    parser.add_argument(
        "--exclude-from",
        action="append",
        default=None,
        metavar="FILE",
        help="Read --exclude patterns from a file, one per line (# comments)",
    )
    parser.add_argument(
        "--limit-mib",
        type=int,
        default=DEFAULT_LIMIT_MIB,
        help=f"Normal batch limit in MiB (default: {DEFAULT_LIMIT_MIB})",
    )
    parser.add_argument(
        "--max-mib",
        type=int,
        default=None,
        help="Maximum individual file size in MiB (default: 3x --limit-mib)",
    )
    parser.add_argument(
        "--use-lfs",
        action="store_true",
        help="Track files above 100 MiB with Git LFS for this run, "
        "installing git-lfs if needed and reverting the setup afterwards",
    )
    parser.add_argument(
        "--lfs-commit-rules",
        action="store_true",
        help="With --use-lfs, also commit LFS rules to .gitattributes (one per "
        "file extension) so clones get real files and future files of the same "
        "type use LFS",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the batches and commit messages that would be created, "
        "without staging, committing or pushing anything",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help="Retry a failed push this many times, waiting 5 s, 15 s, 45 s... "
        f"(default: {DEFAULT_RETRIES}). Rejections such as file-size limits are "
        "never retried",
    )
    parser.add_argument(
        "--post-buffer-mib",
        type=int,
        default=None,
        help="Raise Git's http.postBuffer to this many MiB for this run "
        "(repository config only; HTTP/HTTPS remotes). Helps with 'RPC failed' "
        "and HTTP 408/500 errors on large pushes",
    )
    parser.add_argument(
        "--report",
        default=None,
        metavar="FILE",
        help="Write a machine-readable JSON summary of the run to this file "
        "(also written when the run fails, is interrupted or is a dry run)",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="Show a desktop notification when the run ends (Windows toast, "
        "macOS notification, Linux notify-send; terminal bell if none works)",
    )
    parser.add_argument(
        "--notify-webhook",
        default=None,
        metavar="URL",
        help="POST a JSON summary to this http(s) URL when the run ends "
        "(Slack, Discord, Teams, ntfy or your own endpoint)",
    )
    parser.add_argument(
        "--level",
        type=str.upper,
        choices=LOG_LEVELS,
        default=DEFAULT_LEVEL,
        help=f"Log level written to the log file (default: {DEFAULT_LEVEL}); "
        "DEBUG also records every git command and the push output",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Write the log here instead of the default per-user log folder "
        f"({str(default_log_dir()).replace('%', '%%')})",
    )
    parser.add_argument(
        "--batch-type",
        choices=BATCH_TYPES,
        default=DETERMINISTIC,
        help="How files are picked for a batch: 'deterministic' packs first-fit "
        "and skips files that don't fit; 'sequential' takes files strictly in "
        "order; 'soft' takes files in order and may pass --limit-mib, up to "
        "--max-mib (default: deterministic)",
    )
    parser.add_argument(
        "--compression-threads",
        type=int,
        default=None,
        help="Threads Git uses to compress objects when pushing (pack.threads; "
        "0 = auto). Set in the repository's local config for this run only",
    )
    parser.add_argument(
        "--lfs-threads",
        type=int,
        default=None,
        help="Concurrent Git LFS uploads (lfs.concurrenttransfers). Set in the "
        "repository's local config for this run only",
    )
    parser.add_argument(
        "--lfs-threshold-mib",
        type=int,
        default=LFS_THRESHOLD_MIB,
        help="With --use-lfs, files larger than this go through Git LFS "
        f"(default: {LFS_THRESHOLD_MIB}, the most hosts accept; 0 = every file)",
    )
    parser.add_argument(
        "--lfs-batch-mib",
        type=int,
        default=None,
        help="Max total size of LFS files pushed together so they can upload "
        "concurrently (default: same as --limit-mib)",
    )
    return parser


def validate(parser, args):
    """Reject invalid combinations; returns the effective --max-mib."""
    if not args.message or not args.message.strip():
        parser.error("--message is required (or set 'message' in the config file)")
    if args.limit_mib <= 0:
        parser.error("--limit-mib must be positive")
    if args.number < 0:
        parser.error("--number cannot be negative")
    if args.compression_threads is not None and args.compression_threads < 0:
        parser.error("--compression-threads cannot be negative")
    if args.lfs_threads is not None and args.lfs_threads <= 0:
        parser.error("--lfs-threads must be positive")
    if not 0 <= args.lfs_threshold_mib <= LFS_THRESHOLD_MIB:
        parser.error(
            f"--lfs-threshold-mib must be between 0 and {LFS_THRESHOLD_MIB}; "
            "larger files would be rejected by the host"
        )
    if args.retries < 0:
        parser.error("--retries cannot be negative")
    if args.post_buffer_mib is not None and args.post_buffer_mib <= 0:
        parser.error("--post-buffer-mib must be positive")
    if args.lfs_batch_mib is not None and args.lfs_batch_mib <= 0:
        parser.error("--lfs-batch-mib must be positive")
    if args.no_push and args.use_lfs:
        parser.error(
            "--no-push cannot be combined with --use-lfs: the large files would "
            "stay local and a later plain 'git push' would publish LFS pointers "
            "without their data"
        )
    if args.lfs_commit_rules and not args.use_lfs:
        parser.error("--lfs-commit-rules requires --use-lfs")

    if args.notify_webhook and not is_valid_webhook(args.notify_webhook):
        parser.error("--notify-webhook must be an http:// or https:// URL")

    template_error = validate_template(args.message_template)
    if template_error:
        parser.error(template_error)

    max_mib = args.max_mib if args.max_mib is not None else args.limit_mib * 3
    if max_mib < args.limit_mib:
        parser.error("--max-mib must be greater than or equal to --limit-mib")
    return max_mib


def run_main(argv):
    parser = build_parser()

    # Find the config file first: its values become the parser's defaults, so
    # anything given on the command line still wins.
    pre = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    pre.add_argument("--repo", default=".")
    pre.add_argument("--config")
    known, _ = pre.parse_known_args(argv)

    config_path = None
    try:
        config_path, values = find_config(known.repo, known.config)
        if values:
            apply_config(parser, values, config_path)
    except ConfigError as exc:
        parser.error(str(exc))

    args = parser.parse_args(argv)
    max_mib = validate(parser, args)

    options = RunOptions(
        repo=args.repo,
        message=args.message,
        message_template=args.message_template,
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
    )

    console = Console()
    log_path = setup_logging(args.level, args.log_file)
    options.log_file = str(log_path) if log_path else None
    if log_path is None:
        console.print(
            "[yellow]Could not open a log file; continuing without one.[/yellow]"
        )
    if config_path:
        console.print(f"[dim]Using config: {config_path}[/dim]")

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


def doctor_main(argv):
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


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "doctor":
        return doctor_main(argv[1:])
    return run_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
