from pathlib import Path


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
    from commitrocket.git.push import push_with_retries

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
