import time

from rich.markup import escape
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    ProgressColumn,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text

from commitrocket.batching import MIB
from commitrocket.eta import format_duration
from commitrocket.git import get_file_size, get_pending_files


class EtaColumn(ProgressColumn):
    """Shows the run's own ETA for tasks created with an `estimator` field."""

    def render(self, task):
        estimator = task.fields.get("estimator")
        if estimator is None:
            return Text("")

        remaining = estimator.estimate(task.completed, task.total or 0)
        if remaining is None:
            return Text("ETA estimating…", style="dim")
        return Text(f"ETA {format_duration(remaining)}", style="progress.remaining")


def make_progress(console):
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        EtaColumn(),
        console=console,
    )


def print_run_info(console, repo, branch, upstream, limit_mib, max_mib, number):
    info = Table.grid(padding=(0, 2))
    info.add_column(style="bold cyan")
    info.add_column()
    info.add_row("Repository", Text(str(repo)))
    info.add_row("Branch", Text(branch))
    info.add_row("Push target", Text(upstream))
    info.add_row("Normal batch limit", f"{limit_mib} MiB")
    info.add_row("Maximum file size", f"{max_mib} MiB")
    info.add_row("Starting commit #", str(number))

    console.print(Panel(info, title="Git Batch Push", border_style="cyan"))


def print_lfs_required(console, repo, paths, threshold_mib):
    table = Table(title=f"Files over {threshold_mib} MiB", show_lines=True)
    table.add_column("File", overflow="fold")
    table.add_column("Size (MiB)", justify="right")

    for path in sorted(paths):
        table.add_row(Text(path), f"{get_file_size(repo, path) / MIB:.2f}")

    console.print(table)
    console.print(
        f"\n[bold red]These files exceed the {threshold_mib} MiB limit of most "
        "Git hosts and the push would be rejected.[/bold red]\n"
        "[yellow]Nothing was committed. Run again with [bold]--use-lfs[/bold] "
        "to store them with Git LFS.[/yellow]"
    )


def print_resume(console, staged, entry, unpushed):
    lines = []
    if staged:
        lines.append(
            f"{len(staged)} file(s) were staged by an interrupted run and will be "
            f"committed as: {entry['message']}"
        )
    if unpushed:
        lines.append(f"{len(unpushed)} unpushed commit(s) will be pushed first:")
        lines.extend(f"  {commit}" for commit in unpushed[:10])
        if len(unpushed) > 10:
            lines.append(f"  ... and {len(unpushed) - 10} more")

    panel = Panel(Text("\n".join(lines)), title="Resuming", border_style="yellow")
    console.print(panel)


def print_dry_run(
    console, batches, deferred, messages, lfs_files, lfs_scope, no_push=False
):
    table = Table(title="Dry run: planned batches", show_lines=True)
    table.add_column("Batch", justify="right")
    table.add_column("Commit message")
    table.add_column("Files", justify="right")
    table.add_column("Size (MiB)", justify="right")
    table.add_column("Via LFS", justify="right")

    total_files = 0
    total_bytes = 0
    for index, (paths, size) in enumerate(batches):
        lfs_count = len(set(paths) & set(lfs_files))
        table.add_row(
            str(index + 1),
            Text(messages[index]),
            str(len(paths)),
            f"{size / MIB:.2f}",
            str(lfs_count) if lfs_count else "-",
        )
        total_files += len(paths)
        total_bytes += size

    console.print(table)
    console.print(
        f"{len(batches)} batch(es), {total_files} file(s), "
        f"{total_bytes / MIB:.2f} MiB in total."
    )
    if lfs_scope:
        console.print(f"[cyan]{lfs_scope}[/cyan]")

    if deferred:
        details = Table(title="Would be deferred (over --max-mib)", show_lines=True)
        details.add_column("File", overflow="fold")
        details.add_column("Size (MiB)", justify="right")
        for path, size in sorted(deferred):
            details.add_row(Text(path), f"{size / MIB:.2f}")
        console.print(details)

    if no_push:
        console.print("[dim]--no-push: batches would be committed, not pushed.[/dim]")

    console.print(
        "\n[bold green]Dry run only: nothing was staged, committed, pushed or "
        "changed.[/bold green]"
    )


def print_stuck_commits(console, commits, blobs, upstream, threshold_mib):
    table = Table(title=f"Unpushed files over {threshold_mib} MiB", show_lines=True)
    table.add_column("File", overflow="fold")
    table.add_column("Size (MiB)", justify="right")

    for path, size in blobs:
        table.add_row(Text(path), f"{size / MIB:.2f}")

    console.print(table)
    console.print(f"\n[bold]{len(commits)} unpushed local commit(s):[/bold]")
    for commit in commits:
        console.print(Text(f"  {commit}"))

    console.print(
        f"\n[bold red]These commits already contain files over {threshold_mib} "
        "MiB, so pushing them would be rejected.[/bold red]\n"
        "[yellow]Nothing was changed. To drop those commits and keep your files "
        "as untracked changes, run:[/yellow]\n\n"
        f"  git reset --mixed {escape(upstream)}\n\n"
        "[yellow]then run CommitRocket again (the commits stay recoverable via "
        "'git reflog').[/yellow]"
    )


def print_final_summary(
    console, repo, batch_count, started_at, max_mib, pending_files=None, pushed=True
):
    """Report files still deferred after all eligible batches finish."""
    elapsed = time.monotonic() - started_at
    pending = pending_files() if pending_files else get_pending_files(repo)

    deferred = []
    for path in pending:
        size = get_file_size(repo, path)
        if size > max_mib * MIB:
            deferred.append((path, size))

    table = Table(title="Execution Summary", show_lines=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    label = "Batches pushed" if pushed else "Batches committed"
    table.add_row(label, str(batch_count))
    table.add_row("Elapsed time", f"{elapsed:.1f} seconds")
    table.add_row("Deferred files", str(len(deferred)))

    console.print()
    console.print(Panel(table, border_style="green" if not deferred else "yellow"))

    if not deferred:
        console.print("[bold green]All eligible files processed.[/bold green]")
        return 0

    details = Table(title="Deferred Files — Final Report", show_lines=True)
    details.add_column("File", overflow="fold")
    details.add_column("Size (MiB)", justify="right")
    details.add_column("Reason", overflow="fold")

    for path, size in sorted(deferred):
        details.add_row(
            Text(path),
            f"{size / MIB:.2f}",
            f"Exceeds --max-mib ({max_mib} MiB)",
        )

    console.print(details)
    console.print(
        "\n[yellow]Increase --max-mib to include these files. "
        "Deferred files were not committed by this run.[/yellow]"
    )

    return 2
