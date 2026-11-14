import logging

logger = logging.getLogger(__name__)


def read_resume_state(repo, options):
    """Return (journal, journal entry, staged files left by an interrupted run)."""
    from commitrocket.git.git import get_staged_files
    from commitrocket.git.journal import Journal
    from commitrocket.support.errors import CommitRocketError

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
    elif entry and not options.dry_run:
        journal.clear()
    return journal, entry, resume_staged


def resume_previous(
    console,
    repo,
    progress,
    push_task,
    options,
    target,
    journal,
    entry,
    resume_staged,
    unpushed,
    verify,
):
    """Commit the batch an interrupted run left staged and push earlier commits."""
    from commitrocket.core.batching import MIB
    from commitrocket.core.runner.helpers import push_target
    from commitrocket.git.git import find_large_unpushed_blobs, run_git
    from commitrocket.git.lfs import HOST_LIMIT_MIB
    from commitrocket.support.errors import CommitRocketError

    if resume_staged:
        run_git(repo, "commit", "-m", entry["message"])
        journal.clear()
        logger.info("Committed resumed batch: %s", entry["message"])
        if find_large_unpushed_blobs(repo, HOST_LIMIT_MIB * MIB, target.revs):
            raise CommitRocketError(
                "The resumed commit contains files over "
                f"{HOST_LIMIT_MIB} MiB. Drop it with "
                f"'git reset --mixed {target.label}' and run again."
            )

    if (resume_staged or unpushed) and not options.no_push:
        push_target(repo, progress, push_task, console, options, target)
        verify()
        console.print("[green]Resumed commits pushed.[/green]")


def commit_lfs_rules(
    console, repo, progress, push_task, options, target, lfs, lfs_paths, report, verify
):
    """Commit the .gitattributes LFS rules before the first batch."""
    from commitrocket.core.runner.helpers import push_target
    from commitrocket.core.template import add_attribution
    from commitrocket.git.git import run_git

    if lfs.write_committed_rules(lfs_paths):
        run_git(repo, "add", "--", ".gitattributes")
        rules_message = add_attribution(
            f"{options.message.rstrip()} (LFS rules)", options.attribution
        )
        run_git(repo, "commit", "-m", rules_message)
        logger.info("Committed LFS rules: %s", rules_message)
        report.lfs["rules_commit"] = run_git(repo, "rev-parse", "HEAD").stdout.strip()
        console.print("[cyan]Committed LFS rules.[/cyan]")
        push_target(repo, progress, push_task, console, options, target)
        verify()
