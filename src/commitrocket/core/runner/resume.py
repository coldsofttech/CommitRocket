import logging

logger = logging.getLogger(__name__)


def check_resume(repo, prior, options, branch, target_label):
    """Make sure --resume can safely continue the journal's run."""
    from commitrocket.git.git import run_git
    from commitrocket.support.errors import CommitRocketError

    if prior is None:
        raise CommitRocketError(
            "--resume: no interrupted run found in this repository. "
            "Run without --resume to start a new run."
        )
    if prior["params"] != options.params:
        raise CommitRocketError(
            "--resume: the parameters differ from the interrupted run. "
            "Run without --resume to start a new run."
        )
    if prior["branch"] != branch or prior["target"] != target_label:
        raise CommitRocketError(
            f"--resume: the interrupted run was on {prior['branch']} -> "
            f"{prior['target']}, but this is {branch} -> {target_label}. "
            "Run without --resume to start a new run."
        )
    anchor = prior["commits"][-1][1] if prior["commits"] else prior["head"]
    if anchor:
        reachable = run_git(
            repo, "merge-base", "--is-ancestor", anchor, "HEAD", check=False
        )
        if reachable.returncode != 0:
            raise CommitRocketError(
                "--resume: the repository changed since the interrupted run "
                f"(commit {anchor[:10]} is no longer in the history of {branch}). "
                "Run without --resume to start a new run."
            )


def read_resume_state(console, repo, options, branch, target_label):
    """Return (journal, prior state, same_run, journal entry, resumed staged files).

    The journal of an interrupted run holds its parameters. The same parameters
    continue that run; different ones start a new run.
    """
    from commitrocket.git.git import get_staged_files
    from commitrocket.git.journal import Journal, JournalError
    from commitrocket.support.errors import CommitRocketError

    journal = Journal(repo)
    try:
        prior = journal.state()
    except JournalError:
        if options.resume:
            raise
        logger.warning("Ignoring an incompatible journal: %s", journal.path)
        prior = None
    if options.resume:
        check_resume(repo, prior, options, branch, target_label)
    same_run = prior is not None and prior["params"] == options.params
    if prior is not None and not same_run:
        console.print(
            "[yellow]The parameters differ from the interrupted run; "
            "starting a new run.[/yellow]"
        )
        logger.info("Journal parameters differ; starting a new run")
    entry = journal.read() if same_run else None

    # Files left staged by an interrupted run are ours; anything else is not.
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
    return journal, prior, same_run, entry, resume_staged


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
        journal.committed(
            entry["number"], run_git(repo, "rev-parse", "HEAD").stdout.strip()
        )
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
        journal.pushed(run_git(repo, "rev-parse", "HEAD").stdout.strip())
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
