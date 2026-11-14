import logging

logger = logging.getLogger(__name__)


def process_batches(
    console,
    repo,
    progress,
    task,
    push_task,
    options,
    target,
    number,
    limit_bytes,
    max_bytes,
    list_pending,
    lfs_files=frozenset(),
    lfs_limit_bytes=0,
    estimator=None,
    journal=None,
    check_lfs=None,
    verify=None,
    report=None,
):
    """Commit (and push) batches until only deferred files remain."""
    from commitrocket.core.batching import MIB, estimate_batch_count, select_batch
    from commitrocket.core.runner.helpers import push_target
    from commitrocket.core.template import add_attribution, render_message
    from commitrocket.git.git import (
        add_files,
        get_file_size,
        get_staged_files,
        run_git,
    )
    from commitrocket.support.errors import CommitRocketError

    batch_count = 0
    commit_number = number

    # Progress is measured in bytes so the ETA reflects the real amount of work.
    total_work = sum(
        size
        for size in (get_file_size(repo, path) for path in list_pending())
        if size <= max_bytes
    )
    done_bytes = 0
    progress.update(task, total=max(total_work, 1), completed=0)
    if estimator:
        estimator.start()

    selection = (
        limit_bytes,
        max_bytes,
        lfs_files,
        lfs_limit_bytes,
        options.batch_type,
    )

    while True:
        pending = list_pending()
        if not pending:
            break

        selected, _, total_bytes = select_batch(repo, pending, *selection)

        if not selected:
            # Only oversized files remain; report them at the end.
            break

        remaining_estimate = estimate_batch_count(repo, pending, *selection)
        estimated_total = max(batch_count + remaining_estimate, batch_count + 1)

        progress.update(
            task,
            description=(
                f"Batch {batch_count + 1}/{estimated_total}: commit #{commit_number}"
            ),
        )

        console.rule(f"[bold cyan]Batch {batch_count + 1}[/bold cyan]")
        console.print(f"Selected: {len(selected)} file(s), {total_bytes / MIB:.2f} MiB")
        logger.info(
            "Batch %d/%d: %d file(s), %.2f MiB, commit #%d",
            batch_count + 1,
            estimated_total,
            len(selected),
            total_bytes / MIB,
            commit_number,
        )
        logger.debug("Batch %d files: %s", batch_count + 1, selected)

        commit_message = add_attribution(
            render_message(
                options.message_template,
                options.message,
                commit_number,
                batch_count + 1,
                len(selected),
                total_bytes / MIB,
                selected[0],
            ),
            options.attribution,
        )

        # Lets an interrupted run recognise the files it left staged.
        if journal:
            journal.write(selected, commit_message, commit_number)

        add_files(repo, selected)

        if not get_staged_files(repo):
            raise CommitRocketError("No staged changes to commit.")

        run_git(repo, "commit", "-m", commit_message)
        if journal:
            journal.clear()

        entry = None
        if report:
            entry = report.add_batch(
                commit_number,
                commit_message,
                selected,
                total_bytes,
                lfs_files=len(lfs_files.intersection(selected)),
                commit=run_git(repo, "rev-parse", "HEAD").stdout.strip(),
            )

        # Catch files that did not become LFS pointers before uploading them.
        if check_lfs:
            check_lfs(selected)

        if not options.no_push:
            push_target(
                repo,
                progress,
                push_task,
                console,
                options,
                target,
                on_upload=lambda percent, base=done_bytes, size=total_bytes: (
                    progress.update(task, completed=base + size * percent / 100)
                ),
                batch_bytes=total_bytes,
            )

            if entry:
                entry["pushed"] = True

            if verify:
                verify()
                if entry:
                    entry["verified"] = True

        batch_count += 1
        commit_number += 1
        done_bytes += total_bytes
        progress.update(task, completed=done_bytes)

        outcome = "committed" if options.no_push else "committed and pushed"
        console.print(f"[green]Batch {batch_count} {outcome}.[/green]")
        logger.info("Batch %d %s", batch_count, outcome)

    return batch_count
