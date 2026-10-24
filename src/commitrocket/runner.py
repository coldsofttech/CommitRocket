import logging
import time
from pathlib import Path

from rich.markup import escape
from rich.panel import Panel
from rich.text import Text

from commitrocket.batching import (
    MIB,
    estimate_batch_count,
    plan_batches,
    select_batch,
)
from commitrocket.errors import CommitRocketError
from commitrocket.eta import EtaEstimator
from commitrocket.filters import FileFilter
from commitrocket.git import (
    LocalConfig,
    add_files,
    find_large_unpushed_blobs,
    get_file_size,
    get_pending_files,
    get_remote_url,
    get_staged_files,
    get_unpushed_commits,
    resolve_target,
    run_git,
)
from commitrocket.journal import Journal
from commitrocket.lfs import (
    HOST_LIMIT_MIB,
    LfsSession,
    committed_rule_lines,
    ensure_git_lfs,
    find_lfs_candidates,
    is_lfs_available,
)
from commitrocket.push import push_with_retries
from commitrocket.report import (
    ABORTED,
    CANCELLED,
    DEFERRED,
    DRY_RUN,
    FAILED,
    INTERRUPTED,
    SUCCESS,
    RunReport,
)
from commitrocket.security import redact
from commitrocket.template import render_message
from commitrocket.ui import (
    make_progress,
    print_dry_run,
    print_final_summary,
    print_lfs_required,
    print_resume,
    print_run_info,
    print_stuck_commits,
)
from commitrocket.verify import (
    expected_lfs_paths,
    find_non_pointers,
    unpushed_has_lfs_pointers,
    verify_remote_head,
)

logger = logging.getLogger(__name__)


def own_output_files(repo, options):
    """Paths (relative to the repo) of the log and report files this run writes."""
    found = set()
    for raw in (options.log_file, options.report):
        if not raw:
            continue
        path = Path(raw).expanduser().resolve()
        try:
            found.add(path.relative_to(repo).as_posix())
        except ValueError:
            pass  # outside the repository
    return found


def push_target(repo, progress, push_task, console, options, target, **kwargs):
    """Push HEAD to the run's remote branch, retrying transient failures."""
    push_with_retries(
        repo,
        progress,
        push_task,
        console,
        retries=options.retries,
        remote=target.remote,
        refspec=target.refspec,
        **kwargs,
    )


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
                f"Batch {batch_count + 1}/{estimated_total}: "
                f"commit #{commit_number}"
            ),
        )

        console.rule(f"[bold cyan]Batch {batch_count + 1}[/bold cyan]")
        console.print(
            f"Selected: {len(selected)} file(s), {total_bytes / MIB:.2f} MiB"
        )
        logger.info(
            "Batch %d/%d: %d file(s), %.2f MiB, commit #%d",
            batch_count + 1,
            estimated_total,
            len(selected),
            total_bytes / MIB,
            commit_number,
        )
        logger.debug("Batch %d files: %s", batch_count + 1, selected)

        commit_message = render_message(
            options.message_template,
            options.message,
            commit_number,
            batch_count + 1,
            len(selected),
            total_bytes / MIB,
            selected[0],
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


def run(console, options, report=None):
    """Batch, commit and push pending changes. Returns a process exit code.

    The outcome is recorded in report (a RunReport) for --report and notifications.
    """
    o = options
    report = report or RunReport(options)
    repo = Path(o.repo).expanduser().resolve()

    if not repo.is_dir():
        console.print(f"[red]Repository directory not found: {repo}[/red]")
        report.abort(f"Repository directory not found: {repo}")
        return 2

    started_at = time.monotonic()
    lfs = None
    config = None
    acting = False
    completed = False

    try:
        root = run_git(repo, "rev-parse", "--show-toplevel")
        repo = Path(root.stdout.strip()).resolve()

        branch = run_git(repo, "branch", "--show-current").stdout.strip()
        if not branch:
            raise CommitRocketError(
                "Detached HEAD. Check out a branch before continuing."
            )

        target = resolve_target(repo, branch, o.remote, o.branch)
        report.repo = str(repo)
        report.branch = branch
        report.target = target.label
        file_filter = FileFilter.from_options(
            repo, o.include, o.exclude, o.include_from, o.exclude_from
        )

        # The run's own log and report must never be committed, or writing them
        # would create a new batch forever.
        own_files = own_output_files(repo, o)

        def raw_pending():
            return [p for p in get_pending_files(repo) if p not in own_files]

        def list_pending():
            return file_filter.apply(raw_pending())

        logger.info(
            "Run started: repo=%s branch=%s target=%s limit=%d MiB max=%d MiB "
            "batch_type=%s use_lfs=%s dry_run=%s no_push=%s retries=%d",
            repo,
            branch,
            target.label,
            o.limit_mib,
            o.max_mib,
            o.batch_type,
            o.use_lfs,
            o.dry_run,
            o.no_push,
            o.retries,
        )

        # Files left staged by an interrupted run are ours; anything else is not.
        journal = Journal(repo)
        entry = journal.read()
        staged = get_staged_files(repo)
        resume_staged = []
        if staged:
            if entry and set(staged) <= set(entry["files"]):
                resume_staged = staged
            else:
                raise CommitRocketError(
                    f"{len(staged)} file(s) already staged. Commit or unstage "
                    "them before running this tool."
                )
        elif entry and not o.dry_run:
            journal.clear()

        # Earlier failed runs can leave commits that the host will reject.
        stuck = find_large_unpushed_blobs(repo, HOST_LIMIT_MIB * MIB, target.revs)
        if stuck:
            logger.warning("Unpushed commits contain large files: %s", stuck)
            print_stuck_commits(
                console,
                get_unpushed_commits(repo, target.revs),
                stuck,
                target.label,
                HOST_LIMIT_MIB,
            )
            report.abort(
                f"Unpushed commits contain files over {HOST_LIMIT_MIB} MiB: "
                + ", ".join(path for path, _ in stuck[:5])
            )
            return 2

        unpushed = get_unpushed_commits(repo, target.revs)
        start_number = (
            max(o.number, entry["number"] + 1) if resume_staged else o.number
        )

        print_run_info(
            console,
            repo,
            branch,
            target.label,
            o.limit_mib,
            o.max_mib,
            start_number,
        )

        status = run_git(repo, "status", "--short").stdout.strip()
        console.print(
            Panel(Text(status or "(no pending changes)"), title="Pending Changes")
        )

        if resume_staged or unpushed:
            logger.info(
                "Resuming: %d staged file(s), %d unpushed commit(s)",
                len(resume_staged),
                len(unpushed),
            )
            print_resume(console, resume_staged, entry, unpushed)
            report.resumed = {
                "staged_files": len(resume_staged),
                "unpushed_commits": len(unpushed),
            }

        limit_bytes = o.limit_mib * MIB
        max_bytes = o.max_mib * MIB
        lfs_limit_bytes = (o.lfs_batch_mib or o.limit_mib) * MIB

        all_pending = raw_pending()
        pending_files = list_pending()
        if file_filter.active:
            left_out = len(all_pending) - len(pending_files)
            console.print(
                f"[dim]Filters: {len(pending_files)} file(s) selected, "
                f"{left_out} left out.[/dim]"
            )
            logger.info("Filters kept %d, left out %d", len(pending_files), left_out)

        if not o.use_lfs:
            over_host_limit = find_lfs_candidates(
                repo, pending_files, HOST_LIMIT_MIB * MIB, max_bytes
            )
            if over_host_limit:
                # The host would reject the push, so stop before committing anything.
                logger.warning(
                    "Files over the limit need --use-lfs: %s", over_host_limit
                )
                print_lfs_required(console, repo, over_host_limit, HOST_LIMIT_MIB)
                report.abort(
                    f"{len(over_host_limit)} file(s) over {HOST_LIMIT_MIB} MiB "
                    "need --use-lfs"
                )
                return 2

        lfs_paths = []
        lfs_scope = ""
        if o.use_lfs:
            lfs_paths = find_lfs_candidates(
                repo, pending_files, o.lfs_threshold_mib * MIB, max_bytes
            )
            report.lfs["files"] = len(lfs_paths)
            if not lfs_paths:
                lfs_scope = (
                    f"--use-lfs: no files above {o.lfs_threshold_mib} MiB; "
                    "LFS not needed."
                )
            else:
                which = (
                    f"All {len(lfs_paths)} file(s)"
                    if o.lfs_threshold_mib == 0
                    else f"{len(lfs_paths)} file(s) above {o.lfs_threshold_mib} MiB"
                )
                if o.lfs_commit_rules:
                    rule_count = len(committed_rule_lines(lfs_paths))
                    lfs_scope = (
                        f"{which} will be stored with Git LFS. {rule_count} rule(s) "
                        "will be committed to .gitattributes first, so they also "
                        "cover files of the same type added later."
                    )
                else:
                    lfs_scope = (
                        f"{which} will be stored with Git LFS for this run only; "
                        "no LFS config is committed."
                    )
                if o.dry_run and not is_lfs_available():
                    lfs_scope += " git-lfs is not installed and would be installed."

        if o.dry_run:
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
                render_message(
                    o.message_template,
                    o.message,
                    start_number + index,
                    index + 1,
                    len(paths),
                    size / MIB,
                    paths[0],
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
            print_dry_run(
                console, batches, deferred, messages, lfs_paths, lfs_scope, o.no_push
            )
            return 0

        if lfs_scope:
            console.print(f"[cyan]{lfs_scope}[/cyan]")

        if not o.force:
            answer = (
                console.input(
                    "[yellow]Proceed with staging, committing, and "
                    f"{'finishing' if o.no_push else 'pushing'}? [y/N][/yellow] "
                )
                .strip()
                .lower()
            )
            if answer not in {"y", "yes"}:
                console.print("[yellow]Cancelled.[/yellow]")
                logger.info("Cancelled by user at the confirmation prompt")
                report.status = CANCELLED
                return 1

        # Unpushed LFS pointers need the LFS hooks, or a push would publish
        # pointers whose files were never uploaded.
        resume_needs_lfs = (
            not o.no_push
            and bool(unpushed)
            and unpushed_has_lfs_pointers(repo, target.revs)
        )
        if lfs_paths or resume_needs_lfs:
            ensure_git_lfs(console, o.force)

        def verify():
            verify_remote_head(repo, target.remote, target.ref, o.retries)

        def check_lfs(selected):
            bad = find_non_pointers(repo, expected_lfs_paths(selected, lfs_paths))
            if bad:
                raise CommitRocketError(
                    f"{len(bad)} file(s) were committed as ordinary files instead of "
                    f"LFS pointers (first: {bad[0]}). Nothing was pushed. Drop the "
                    f"commit with 'git reset --mixed {target.label}' and report this."
                )

        acting = True
        try:
            # Repository-local settings only; the previous values are restored below.
            config = LocalConfig(repo)
            if o.compression_threads is not None:
                config.set("pack.threads", o.compression_threads)
                logger.info("Set local pack.threads=%d", o.compression_threads)
            if o.lfs_threads is not None:
                config.set("lfs.concurrenttransfers", o.lfs_threads)
                logger.info("Set local lfs.concurrenttransfers=%d", o.lfs_threads)
            if o.post_buffer_mib is not None:
                url = get_remote_url(repo, target.remote).lower()
                if url.startswith(("http://", "https://")):
                    config.set("http.postBuffer", o.post_buffer_mib * MIB)
                    logger.info("Set local http.postBuffer=%d MiB", o.post_buffer_mib)
                else:
                    console.print(
                        "[dim]--post-buffer-mib ignored: remote is not HTTP(S).[/dim]"
                    )
                    logger.info("--post-buffer-mib ignored for non-HTTP remote")

            if lfs_paths or resume_needs_lfs:
                lfs = LfsSession(repo)
                if lfs_paths and not o.lfs_commit_rules:
                    lfs.enable(lfs_paths, all_files=o.lfs_threshold_mib == 0)
                    logger.info(
                        "LFS enabled locally for %d file(s) (threshold %d MiB)",
                        len(lfs_paths),
                        o.lfs_threshold_mib,
                    )
                    logger.debug("LFS files: %s", lfs_paths)
                else:
                    lfs.install_hooks()

            with make_progress(console) as progress:
                estimator = EtaEstimator()
                task = progress.add_task(
                    "Preparing batches", total=1, estimator=estimator
                )
                push_task = progress.add_task("Git push", total=100, visible=False)

                if resume_staged:
                    run_git(repo, "commit", "-m", entry["message"])
                    journal.clear()
                    logger.info("Committed resumed batch: %s", entry["message"])
                    if find_large_unpushed_blobs(
                        repo, HOST_LIMIT_MIB * MIB, target.revs
                    ):
                        raise CommitRocketError(
                            "The resumed commit contains files over "
                            f"{HOST_LIMIT_MIB} MiB. Drop it with "
                            f"'git reset --mixed {target.label}' and run again."
                        )

                if (resume_staged or unpushed) and not o.no_push:
                    push_target(repo, progress, push_task, console, o, target)
                    verify()
                    console.print("[green]Resumed commits pushed.[/green]")

                if o.lfs_commit_rules and lfs_paths:
                    if lfs.write_committed_rules(lfs_paths):
                        run_git(repo, "add", "--", ".gitattributes")
                        rules_message = f"{o.message.rstrip()} (LFS rules)"
                        run_git(repo, "commit", "-m", rules_message)
                        logger.info("Committed LFS rules: %s", rules_message)
                        report.lfs["rules_commit"] = run_git(
                            repo, "rev-parse", "HEAD"
                        ).stdout.strip()
                        console.print("[cyan]Committed LFS rules.[/cyan]")
                        push_target(repo, progress, push_task, console, o, target)
                        verify()

                batch_count = process_batches(
                    console,
                    repo,
                    progress,
                    task,
                    push_task,
                    o,
                    target,
                    start_number,
                    limit_bytes,
                    max_bytes,
                    list_pending,
                    frozenset(lfs_paths),
                    lfs_limit_bytes,
                    estimator,
                    journal,
                    check_lfs if lfs_paths else None,
                    verify,
                    report,
                )
            completed = True
        finally:
            if lfs:
                keep_hooks = False
                if not completed:
                    try:
                        keep_hooks = unpushed_has_lfs_pointers(repo, target.revs)
                    except (RuntimeError, OSError):
                        keep_hooks = True
                lfs.close(uninstall_hooks=not keep_hooks)
                if keep_hooks:
                    console.print(
                        "[yellow]Git LFS hooks were left installed because unpushed "
                        "commits contain LFS files. Run CommitRocket again to push "
                        "them; a plain 'git push' only works while the hooks "
                        "stay.[/yellow]"
                    )
                    logger.warning("LFS hooks kept: unpushed LFS commits remain")
                else:
                    logger.info("Local LFS setup removed")
            if config:
                config.restore()
                logger.info("Local git config restored")

        code = print_final_summary(
            console,
            repo,
            batch_count,
            started_at,
            o.max_mib,
            pending_files=list_pending,
            pushed=not o.no_push,
        )
        report.set_deferred(
            (path, size)
            for path, size in ((p, get_file_size(repo, p)) for p in list_pending())
            if size > max_bytes
        )
        report.status = SUCCESS if code == 0 else DEFERRED
        logger.info(
            "Finished: %d batch(es) in %.1f s, exit code %d",
            batch_count,
            time.monotonic() - started_at,
            code,
        )
        return code

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user.[/yellow]")
        report.status = INTERRUPTED
        report.error = "Interrupted by user"
        if acting:
            console.print(
                "[dim]Run the same command again to resume from where it "
                "stopped.[/dim]"
            )
        logger.warning("Interrupted by user")
        return 130
    except (RuntimeError, OSError) as exc:
        message = redact(str(exc))
        console.print(f"\n[bold red]Error:[/bold red] {escape(message)}")
        report.status = ABORTED if not acting else FAILED
        report.error = message
        if acting:
            console.print(
                "[dim]Run the same command again to resume from where it "
                "stopped.[/dim]"
            )
        logger.error("Run failed: %s", exc, exc_info=True)
        return 1
