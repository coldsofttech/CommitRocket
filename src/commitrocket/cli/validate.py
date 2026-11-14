def validate(parser, args):
    """Reject invalid combinations; returns the effective --max-mib."""
    from commitrocket.core.template import validate_template
    from commitrocket.git.lfs import LFS_THRESHOLD_MIB
    from commitrocket.io.notify import is_valid_webhook
    from commitrocket.support.errors import CommitRocketError
    from commitrocket.support.security import validate_ref_part

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

    for label, value in (("--remote", args.remote), ("--branch", args.branch)):
        if value is not None:
            try:
                validate_ref_part(value, label)
            except CommitRocketError as exc:
                parser.error(str(exc))
    if args.notify_webhook and not is_valid_webhook(args.notify_webhook):
        parser.error("--notify-webhook must be an http:// or https:// URL")

    template_error = validate_template(args.message_template)
    if template_error:
        parser.error(template_error)

    max_mib = args.max_mib if args.max_mib is not None else args.limit_mib * 3
    if max_mib < args.limit_mib:
        parser.error("--max-mib must be greater than or equal to --limit-mib")
    return max_mib
