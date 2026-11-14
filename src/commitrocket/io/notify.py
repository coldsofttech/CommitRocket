import logging

logger = logging.getLogger(__name__)

DESKTOP_TIMEOUT = 15
WEBHOOK_TIMEOUT = 10


def build_message(report):
    """(title, body) describing how the run ended."""
    from commitrocket.core.eta import format_duration
    from commitrocket.io.report import (
        ABORTED,
        CANCELLED,
        DEFERRED,
        FAILED,
        INTERRUPTED,
        SUCCESS,
    )
    from commitrocket.support.security import redact

    headlines = {
        SUCCESS: "finished",
        DEFERRED: "finished, some files were skipped",
        CANCELLED: "cancelled",
        ABORTED: "stopped before starting",
        INTERRUPTED: "interrupted",
        FAILED: "failed",
    }
    title = f"CommitRocket {headlines.get(report.status, report.status)}"

    parts = []
    if report.batches:
        mib = report.total_bytes / (1024 * 1024)
        verb = "committed" if report.settings.get("no_push") else "pushed"
        parts.append(
            f"{len(report.batches)} batch(es) {verb}, {report.total_files} file(s), "
            f"{mib:.1f} MiB"
        )
    if report.deferred:
        parts.append(f"{len(report.deferred)} file(s) skipped for size")
    if report.error:
        parts.append(report.error.strip().splitlines()[0])
    if report.target:
        parts.append(f"to {report.target}")
    if report.duration_seconds is not None:
        parts.append(f"in {format_duration(report.duration_seconds)}")

    return title, redact("; ".join(parts) or "No changes were made.")


def _read_script(name):
    """Text of a notification script shipped in the io/scripts folder."""
    from importlib.resources import files

    return (files("commitrocket.io") / "scripts" / name).read_text(encoding="utf-8")


def _run_quietly(command, env):
    import os
    import subprocess

    result = subprocess.run(
        command,
        env={**os.environ, **env},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=DESKTOP_TIMEOUT,
    )
    return result.returncode == 0


def notify_desktop(title, body):
    """Show a native notification. Returns the method used; 'bell' if none worked."""
    import shutil
    import subprocess
    import sys

    env = {"CR_TITLE": title, "CR_BODY": body}
    try:
        if sys.platform == "win32" and shutil.which("powershell"):
            command = ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
            if _run_quietly(command + [_read_script("toast.ps1")], env):
                return "windows-toast"
        elif sys.platform == "darwin" and shutil.which("osascript"):
            if _run_quietly(
                ["osascript", "-e", _read_script("notification.applescript")], env
            ):
                return "macos-notification"
        elif shutil.which("notify-send"):
            command = ["notify-send", "--app-name=CommitRocket", title, body]
            if _run_quietly(command, env):
                return "notify-send"
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Desktop notification failed: %s", exc)

    sys.stdout.write("\a")
    sys.stdout.flush()
    return "bell"


def is_valid_webhook(url):
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def notify_webhook(url, title, body, report):
    """POST a JSON summary. 'text' and 'content' suit Slack/Teams and Discord."""
    import json
    import urllib.request

    from commitrocket.support.security import redact

    payload = {
        "text": f"{title}: {body}",
        "content": f"{title}: {body}",
        "title": title,
        "message": body,
        "status": report.status,
        "exit_code": report.exit_code,
        "repo": report.repo,
        "target": redact(report.target) if report.target else None,
        "batches": len(report.batches),
        "files": report.total_files,
        "size_bytes": report.total_bytes,
        "duration_seconds": report.duration_seconds,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Title": title.encode("ascii", "replace").decode("ascii"),
            "User-Agent": "commitrocket",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=WEBHOOK_TIMEOUT) as response:
        return response.status


def send_notifications(console, report, desktop=False, webhook=None):
    """Notify about the finished run. Failures are reported but never raised."""
    import urllib.error

    title, body = build_message(report)

    if desktop:
        method = notify_desktop(title, body)
        logger.info("Desktop notification sent via %s", method)

    if webhook:
        try:
            status = notify_webhook(webhook, title, body, report)
            logger.info("Webhook notified (HTTP %s)", status)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            logger.warning("Webhook notification failed: %s", exc)
            console.print(f"[yellow]Could not notify the webhook: {exc}[/yellow]")
