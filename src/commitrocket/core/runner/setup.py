import logging

from commitrocket.core.batching import MIB

logger = logging.getLogger(__name__)


def plan_lfs(options, report, repo, pending_files, max_bytes):
    """Return (LFS candidate paths, scope message) for --use-lfs, or ([], "")."""
    from commitrocket.git.lfs import (
        committed_rule_lines,
        find_lfs_candidates,
        is_lfs_available,
    )

    o = options
    lfs_paths = []
    lfs_scope = ""
    if o.use_lfs:
        lfs_paths = find_lfs_candidates(
            repo, pending_files, o.lfs_threshold_mib * MIB, max_bytes
        )
        report.lfs["files"] = len(lfs_paths)
        if not lfs_paths:
            lfs_scope = (
                f"--use-lfs: no files above {o.lfs_threshold_mib} MiB; LFS not needed."
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
                    "no LFS config is committed, so checkouts and clones will "
                    "contain LFS pointer files instead of the real files."
                )
            if o.dry_run and not is_lfs_available():
                lfs_scope += " git-lfs is not installed and would be installed."
    return lfs_paths, lfs_scope


def apply_local_config(console, options, repo, target, config):
    """Set repository-local tuning options; the caller restores them afterwards."""
    o = options
    if o.compression_threads is not None:
        config.set("pack.threads", o.compression_threads)
        logger.info("Set local pack.threads=%d", o.compression_threads)
    if o.lfs_threads is not None:
        config.set("lfs.concurrenttransfers", o.lfs_threads)
        logger.info("Set local lfs.concurrenttransfers=%d", o.lfs_threads)
    if o.post_buffer_mib is not None:
        from commitrocket.git.git import get_remote_url

        url = get_remote_url(repo, target.remote).lower()
        if url.startswith(("http://", "https://")):
            config.set("http.postBuffer", o.post_buffer_mib * MIB)
            logger.info("Set local http.postBuffer=%d MiB", o.post_buffer_mib)
        else:
            console.print(
                "[dim]--post-buffer-mib ignored: remote is not HTTP(S).[/dim]"
            )
            logger.info("--post-buffer-mib ignored for non-HTTP remote")


def configure_lfs(lfs, options, lfs_paths):
    """Enable LFS for this run, or only install its hooks when rules are committed."""
    if lfs_paths and not options.lfs_commit_rules:
        lfs.enable(lfs_paths, all_files=options.lfs_threshold_mib == 0)
        logger.info(
            "LFS enabled locally for %d file(s) (threshold %d MiB)",
            len(lfs_paths),
            options.lfs_threshold_mib,
        )
        logger.debug("LFS files: %s", lfs_paths)
    else:
        lfs.install_hooks()


def release_lfs(console, repo, target, lfs, completed):
    """Close the LFS session, keeping hooks while unpushed LFS commits remain."""
    from commitrocket.core.verify import unpushed_has_lfs_pointers

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
