import logging

logger = logging.getLogger(__name__)


def run_dry(
    console,
    options,
    report,
    repo,
    pending_files,
    lfs_paths,
    lfs_scope,
    limit_bytes,
    max_bytes,
    lfs_limit_bytes,
    start_number,
):
    """Plan the batches without touching the repository and record them in report."""
    from commitrocket.core.batching import MIB, plan_batches
    from commitrocket.core.template import add_attribution, render_message
    from commitrocket.io.report import DRY_RUN
    from commitrocket.io.ui import print_dry_run

    o = options
    batches, deferred = plan_batches(
        repo,
        pending_files,
        limit_bytes,
        max_bytes,
        frozenset(lfs_paths),
        lfs_limit_bytes,
        o.batch_type,
    )
    messages = [
        add_attribution(
            render_message(
                o.message_template,
                o.message,
                start_number + index,
                index + 1,
                len(paths),
                size / MIB,
                paths[0],
            ),
            o.attribution,
        )
        for index, (paths, size) in enumerate(batches)
    ]
    logger.info("Dry run: %d batch(es) planned", len(batches))
    for index, (paths, size) in enumerate(batches):
        report.add_batch(
            start_number + index,
            messages[index],
            paths,
            size,
            lfs_files=len(set(paths).intersection(lfs_paths)),
        )
    report.set_deferred(deferred)
    report.status = DRY_RUN
    print_dry_run(console, batches, deferred, messages, lfs_paths, lfs_scope, o.no_push)
    return 0
