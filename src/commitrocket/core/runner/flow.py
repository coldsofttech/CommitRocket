import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def run(console, options, report=None):
    """Batch, commit and push pending changes. Returns a process exit code.

    The outcome is recorded in report (a RunReport) for --report and notifications.
    """
    from commitrocket.io.report import RunReport

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
    journal = None
    acting = False
    completed = False

    try:
        from commitrocket.core.batching import MIB
        from commitrocket.core.filters import FileFilter
        from commitrocket.core.runner.helpers import own_output_files
        from commitrocket.core.runner.resume import read_resume_state
        from commitrocket.core.runner.setup import plan_lfs
        from commitrocket.git.git import (
            find_large_unpushed_blobs,
            get_pending_files,
            get_unpushed_commits,
            resolve_target,
            run_git,
        )
        from commitrocket.git.lfs import HOST_LIMIT_MIB, find_lfs_candidates
        from commitrocket.io.report import CANCELLED, DEFERRED, SUCCESS
        from commitrocket.support.errors import CommitRocketError

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

        journal, prior, same_run, entry, resume_staged = read_resume_state(
            console, repo, o, branch, target.label
        )

        # Earlier failed runs can leave commits that the host will reject.
        stuck = find_large_unpushed_blobs(repo, HOST_LIMIT_MIB * MIB, target.revs)
        if stuck:
            from commitrocket.io.ui import print_stuck_commits

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
        start_number = o.number
        if same_run:
            start_number = max(start_number, prior["next_number"])
        if resume_staged:
            start_number = max(start_number, entry["number"] + 1)

        from rich.panel import Panel
        from rich.text import Text

        from commitrocket.io.ui import print_resume, print_run_info

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
                from commitrocket.io.ui import print_lfs_required

                logger.warning(
                    "Files over the limit need --use-lfs: %s", over_host_limit
                )
                print_lfs_required(console, repo, over_host_limit, HOST_LIMIT_MIB)
                report.abort(
                    f"{len(over_host_limit)} file(s) over {HOST_LIMIT_MIB} MiB "
                    "need --use-lfs"
                )
                return 2

        lfs_paths, lfs_scope = plan_lfs(o, report, repo, pending_files, max_bytes)

        if o.dry_run:
            from commitrocket.core.runner.dry_run import run_dry

            return run_dry(
                console,
                o,
                report,
                repo,
                pending_files,
                lfs_paths,
                lfs_scope,
                limit_bytes,
                max_bytes,
                lfs_limit_bytes,
                start_number,
            )

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
        from commitrocket.core.verify import unpushed_has_lfs_pointers

        resume_needs_lfs = (
            not o.no_push
            and bool(unpushed)
            and unpushed_has_lfs_pointers(repo, target.revs)
        )
        if lfs_paths or resume_needs_lfs:
            from commitrocket.git.lfs import ensure_git_lfs

            ensure_git_lfs(console, o.force)

        def verify():
            from commitrocket.core.verify import verify_remote_head

            verify_remote_head(repo, target.remote, target.ref, o.retries)

        def check_lfs(selected):
            from commitrocket.core.verify import expected_lfs_paths, find_non_pointers

            bad = find_non_pointers(repo, expected_lfs_paths(selected, lfs_paths))
            if bad:
                raise CommitRocketError(
                    f"{len(bad)} file(s) were committed as ordinary files instead of "
                    f"LFS pointers (first: {bad[0]}). Nothing was pushed. Drop the "
                    f"commit with 'git reset --mixed {target.label}' and report this."
                )

        acting = True
        try:
            if same_run:
                journal.note("resumed", staged_files=len(resume_staged))
            else:
                journal.start(
                    o.params,
                    branch,
                    target.label,
                    run_git(repo, "rev-parse", "HEAD").stdout.strip(),
                )
            # Repository-local settings only; the previous values are restored below.
            from commitrocket.core.runner.setup import apply_local_config, configure_lfs
            from commitrocket.git.git import LocalConfig

            config = LocalConfig(repo)
            apply_local_config(console, o, repo, target, config)

            if lfs_paths or resume_needs_lfs:
                from commitrocket.git.lfs import LfsSession

                lfs = LfsSession(repo)
                configure_lfs(lfs, o, lfs_paths)

            from commitrocket.core.eta import EtaEstimator
            from commitrocket.core.runner.batches import process_batches
            from commitrocket.core.runner.resume import resume_previous
            from commitrocket.io.ui import make_progress

            with make_progress(console) as progress:
                estimator = EtaEstimator()
                task = progress.add_task(
                    "Preparing batches", total=1, estimator=estimator
                )
                push_task = progress.add_task("Git push", total=100, visible=False)

                resume_previous(
                    console,
                    repo,
                    progress,
                    push_task,
                    o,
                    target,
                    journal,
                    entry,
                    resume_staged,
                    unpushed,
                    verify,
                )

                if o.lfs_commit_rules and lfs_paths:
                    from commitrocket.core.runner.resume import commit_lfs_rules

                    commit_lfs_rules(
                        console,
                        repo,
                        progress,
                        push_task,
                        o,
                        target,
                        lfs,
                        lfs_paths,
                        report,
                        verify,
                    )

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
                from commitrocket.core.runner.setup import release_lfs

                release_lfs(console, repo, target, lfs, completed)
            if config:
                config.restore()
                logger.info("Local git config restored")

        journal.delete()

        from commitrocket.io.ui import print_final_summary

        code = print_final_summary(
            console,
            repo,
            batch_count,
            started_at,
            o.max_mib,
            pending_files=list_pending,
            pushed=not o.no_push,
        )
        from commitrocket.git.git import get_file_size

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
        from commitrocket.io.report import INTERRUPTED

        console.print("\n[yellow]Interrupted by user.[/yellow]")
        report.status = INTERRUPTED
        report.error = "Interrupted by user"
        if acting and journal:
            journal.note("interrupted")
        if acting:
            console.print(
                "[dim]Run the same command again to resume from where it stopped.[/dim]"
            )
        logger.warning("Interrupted by user")
        return 130
    except (RuntimeError, OSError) as exc:
        from rich.markup import escape

        from commitrocket.io.report import ABORTED, FAILED
        from commitrocket.support.security import redact

        message = redact(str(exc))
        console.print(f"\n[bold red]Error:[/bold red] {escape(message)}")
        report.status = ABORTED if not acting else FAILED
        report.error = message
        if acting and journal:
            journal.note("failed", error=message)
        if acting:
            console.print(
                "[dim]Run the same command again to resume from where it stopped.[/dim]"
            )
        logger.error("Run failed: %s", exc, exc_info=True)
        return 1
