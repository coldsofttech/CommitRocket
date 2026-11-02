from datetime import date

DEFAULT_TEMPLATE = "{message} #{n}"

ATTRIBUTION = (
    "Prepared and Committed By: 🚀 CommitRocket "
    "(https://github.com/coldsofttech/CommitRocket)"
)

PLACEHOLDERS = ("message", "n", "batch", "files", "size", "first", "date")


def render_message(template, message, n, batch, files, size_mib, first):
    """Fill in a commit message template for one batch.

    {message} the --message text, {n} the commit number, {batch} the position
    in this run, {files} the file count, {size} the size in MiB, {first} the
    first file's path and {date} today's date (YYYY-MM-DD).
    """
    return template.format(
        message=message.rstrip(),
        n=n,
        batch=batch,
        files=files,
        size=size_mib,
        first=first,
        date=date.today().isoformat(),
    ).strip()


def add_attribution(message, enabled=True):
    """Append the CommitRocket attribution trailer to a commit message.

    The trailer goes after a blank line at the end. It is never added twice and
    the message is returned untouched when attribution is switched off.
    """
    if not enabled or ATTRIBUTION in message.splitlines():
        return message
    return f"{message.rstrip()}\n\n{ATTRIBUTION}"


def validate_template(template):
    """Return an error string if the template can't be rendered, else None."""
    try:
        text = render_message(template, "msg", 1, 1, 1, 1.0, "a.txt")
    except (KeyError, IndexError, ValueError, AttributeError) as exc:
        return (
            f"invalid --message-template ({exc!r}); "
            f"available placeholders: {', '.join(PLACEHOLDERS)}"
        )
    if not text:
        return "--message-template renders an empty commit message"
    return None
