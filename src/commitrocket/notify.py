import json
import logging
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse

from commitrocket.eta import format_duration
from commitrocket.report import (
    ABORTED,
    CANCELLED,
    DEFERRED,
    FAILED,
    INTERRUPTED,
    SUCCESS,
)

logger = logging.getLogger(__name__)

# Windows PowerShell's own AppUserModelID, which Windows already trusts to show toasts.
WINDOWS_APP_ID = (
    "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"
)
WINDOWS_SCRIPT = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$text = $xml.GetElementsByTagName('text')
$text.Item(0).AppendChild($xml.CreateTextNode($env:CR_TITLE)) | Out-Null
$text.Item(1).AppendChild($xml.CreateTextNode($env:CR_BODY)) | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{WINDOWS_APP_ID}').Show($toast)
"""  # noqa: E501
MACOS_SCRIPT = (
    'display notification (system attribute "CR_BODY") '
    'with title (system attribute "CR_TITLE")'
)

DESKTOP_TIMEOUT = 15
WEBHOOK_TIMEOUT = 10

HEADLINES = {
    SUCCESS: "finished",
    DEFERRED: "finished, some files were skipped",
    CANCELLED: "cancelled",
    ABORTED: "stopped before starting",
    INTERRUPTED: "interrupted",
    FAILED: "failed",
}


def build_message(report):
    """(title, body) describing how the run ended."""
    title = f"CommitRocket {HEADLINES.get(report.status, report.status)}"

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

    return title, "; ".join(parts) or "No changes were made."


def _run_quietly(command, env):
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
    env = {"CR_TITLE": title, "CR_BODY": body}
    try:
        if sys.platform == "win32" and shutil.which("powershell"):
            command = ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
            if _run_quietly(command + [WINDOWS_SCRIPT], env):
                return "windows-toast"
        elif sys.platform == "darwin" and shutil.which("osascript"):
            if _run_quietly(["osascript", "-e", MACOS_SCRIPT], env):
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
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def notify_webhook(url, title, body, report):
    """POST a JSON summary. 'text' and 'content' suit Slack/Teams and Discord."""
    payload = {
        "text": f"{title}: {body}",
        "content": f"{title}: {body}",
        "title": title,
        "message": body,
        "status": report.status,
        "exit_code": report.exit_code,
        "repo": report.repo,
        "target": report.target,
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
