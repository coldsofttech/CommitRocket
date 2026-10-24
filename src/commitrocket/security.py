"""Small helpers that keep untrusted text from doing harm."""

import os
import re

from commitrocket.errors import CommitRocketError

# user:password@ inside a URL, e.g. https://name:token@host/path
_CREDENTIALS = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/\s@]+@")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def redact(text):
    """Hide credentials embedded in URLs before text is logged or shown."""
    return _CREDENTIALS.sub(r"\1***@", text)


def redact_value(value):
    """redact() applied to every string inside nested dicts and lists."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: redact_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(item) for item in value]
    return value


def has_control_chars(text):
    return bool(_CONTROL.search(text))


def validate_ref_part(value, label):
    """Reject remote and branch names that Git could read as options."""
    if not value or value.startswith("-") or has_control_chars(value) or any(
        char.isspace() for char in value
    ):
        raise CommitRocketError(
            f"Invalid {label} {value!r}: it must not be empty, start with '-', "
            "or contain spaces or control characters."
        )
    return value


def restrict_permissions(path):
    """Make a file readable and writable by its owner only (best effort)."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
