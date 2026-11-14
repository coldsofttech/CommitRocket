DEFAULT_LIMIT_MIB = 100
DEFAULT_RETRIES = 3


def build_parser():
    import argparse

    from commitrocket import __version__
    from commitrocket.core.batching import BATCH_TYPES, DETERMINISTIC
    from commitrocket.core.template import DEFAULT_TEMPLATE, PLACEHOLDERS
    from commitrocket.git.lfs import LFS_THRESHOLD_MIB
    from commitrocket.io.logs import DEFAULT_LEVEL, LOG_LEVELS, default_log_dir

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
        "--no-attribution",
        "--ignore-attribution",
        dest="no_attribution",
        action="store_true",
        help="Don't append the 'Prepared and Committed By: CommitRocket' line "
        "to commit messages",
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
        dest="lfs_commit_rules",
        action="store_true",
        default=True,
        help="With --use-lfs, commit LFS rules to .gitattributes (one per file "
        "extension) so clones and checkouts get real files (default)",
    )
    parser.add_argument(
        "--no-lfs-commit-rules",
        dest="lfs_commit_rules",
        action="store_false",
        help="With --use-lfs, keep the LFS rules local to this run. Checkouts "
        "and clones will then contain LFS pointer files instead of the real files",
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
