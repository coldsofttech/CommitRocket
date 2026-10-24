import logging
import os
import re
import subprocess
import time

from commitrocket.errors import PushError

logger = logging.getLogger(__name__)

PERCENT_RE = re.compile(r"(\d{1,3})%")

UPLOAD_PHASE = "Uploading objects"
LFS_PHASE = "Uploading LFS objects"

# git-lfs reports e.g. "Uploading LFS objects:  50% (1/2), 52 MB | 3.2 MB/s".
# The percentage counts files, so the transferred byte count is used instead.
LFS_BYTES_RE = re.compile(
    r"Uploading LFS objects:.*?\)\s*,\s*([\d.]+)\s*([KMGT]?B)\b", re.IGNORECASE
)
LFS_UNITS = {"B": 1, "KB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4}

# Output that means the host refused the push, so a retry would fail the same way.
NON_RETRYABLE_MARKERS = (
    "[rejected]",
    "[remote rejected]",
    "remote rejected",
    "pre-receive hook declined",
    "non-fast-forward",
    "fetch first",
    "gh001",
    "large files detected",
    "protected branch",
    "authentication failed",
    "permission denied",
    "access denied",
    "repository not found",
    "could not read username",
)

RETRY_BASE_SECONDS = 5

PHASES = (
    ("enumerating objects", "Enumerating objects"),
    ("counting objects", "Counting objects"),
    ("compressing objects", "Compressing objects"),
    ("writing objects", UPLOAD_PHASE),
    ("resolving deltas", "Resolving deltas"),
    ("receiving objects", "Receiving objects"),
)


def parse_progress_line(line):
    """Return (phase, percent) for a git progress line; percent may be None."""
    match = PERCENT_RE.search(line)
    percent = min(100, int(match.group(1))) if match else None

    lower = line.lower()
    phase = next((label for key, label in PHASES if key in lower), "Git push")
    return phase, percent


def is_retryable(output):
    """False for failures that trying again cannot fix (rejections, auth)."""
    lower = output.lower()
    return not any(marker in lower for marker in NON_RETRYABLE_MARKERS)


def parse_lfs_bytes(line):
    """Bytes transferred so far according to a git-lfs upload line, else None."""
    match = LFS_BYTES_RE.search(line)
    if not match:
        return None
    return int(float(match.group(1)) * LFS_UNITS[match.group(2).upper()])


def push_with_retries(
    repo, progress, push_task, console, retries=0, sleep=time.sleep, **kwargs
):
    """push_with_progress, retried with growing waits on transient errors."""
    attempt = 0
    while True:
        try:
            return push_with_progress(repo, progress, push_task, console, **kwargs)
        except PushError as exc:
            if not exc.retryable or attempt >= retries:
                raise

            delay = RETRY_BASE_SECONDS * 3**attempt
            attempt += 1
            logger.warning(
                "Push failed (attempt %d of %d), retrying in %d s: %s",
                attempt,
                retries,
                delay,
                exc,
            )
            console.print(
                f"[yellow]Push failed. Retrying in {delay} s "
                f"(retry {attempt} of {retries})...[/yellow]"
            )
            sleep(delay)


def push_with_progress(
    repo,
    progress,
    push_task,
    console,
    on_upload=None,
    batch_bytes=None,
    remote=None,
    refspec=None,
):
    """Stream Git push progress into a live Rich progress task.

    on_upload, if given, is called with a rising percent (0-100) of the upload,
    covering both the git-lfs upload and the pack transfer. batch_bytes is the
    size of the batch being pushed and lets LFS byte counts become a percent.
    """
    console.print("\n[bold cyan]Pushing commit...[/bold cyan]")
    logger.info("Pushing %s", repo)

    progress.update(
        push_task,
        description="Git push: Starting",
        total=100,
        completed=0,
        visible=True,
    )

    process = subprocess.Popen(
        ["git", "-C", str(repo), "push", "--progress"]
        + ([remote, refspec] if remote else []),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
        # Without a terminal git-lfs would otherwise print no progress at all.
        env={**os.environ, "GIT_LFS_FORCE_PROGRESS": "1"},
    )

    pending = b""
    messages = []
    best_percent = 0
    logged_phase = None

    try:
        while True:
            chunk = os.read(process.stdout.fileno(), 4096)

            if not chunk:
                break

            pending += chunk

            # Git progress commonly uses carriage returns instead
            # of newlines to refresh terminal output.
            parts = re.split(rb"[\r\n]+", pending)
            pending = parts.pop()

            for raw_line in parts:
                line = raw_line.decode("utf-8", errors="replace").strip()

                if not line:
                    continue

                messages.append(line)

                phase, percent = parse_progress_line(line)

                uploaded = parse_lfs_bytes(line)
                if uploaded is not None:
                    phase = LFS_PHASE
                    if batch_bytes:
                        percent = min(100, int(uploaded * 100 / batch_bytes))

                # Progress lines repeat constantly; keep one per phase change
                # plus the final one, and every other line.
                if percent is None or phase != logged_phase or percent == 100:
                    logger.debug("push: %s", line)
                    logged_phase = phase

                if (
                    on_upload
                    and percent is not None
                    and phase in (UPLOAD_PHASE, LFS_PHASE)
                    and percent > best_percent
                ):
                    best_percent = percent
                    on_upload(percent)

                if percent is not None:
                    progress.update(
                        push_task,
                        description=phase,
                        completed=percent,
                        total=100,
                        visible=True,
                    )
                else:
                    progress.update(push_task, description=phase, visible=True)

        # Process any final output without a trailing delimiter.
        if pending.strip():
            line = pending.decode("utf-8", errors="replace").strip()
            if line:
                messages.append(line)

        return_code = process.wait()

    except BaseException:
        process.kill()
        process.wait()
        raise

    finally:
        if process.stdout:
            process.stdout.close()

    logger.info("git push finished with exit code %d", return_code)

    if return_code != 0:
        progress.update(push_task, description="Git push failed", visible=True)
        raise PushError(
            "git push failed with exit code "
            f"{return_code}:\n" + "\n".join(messages[-15:]),
            retryable=is_retryable("\n".join(messages)),
        )

    progress.update(
        push_task,
        description="Git push complete",
        completed=100,
        total=100,
        visible=True,
    )

    # Display non-progress messages such as the remote branch update.
    for line in messages:
        if not PERCENT_RE.search(line):
            console.print(f"[dim]{line}[/dim]")

    progress.update(push_task, visible=False)
