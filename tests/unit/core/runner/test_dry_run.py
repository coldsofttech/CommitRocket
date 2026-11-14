from rich.console import Console

from commitrocket.core.options import RunOptions
from commitrocket.core.runner.dry_run import run_dry
from commitrocket.io.report import DRY_RUN, RunReport

MIB = 1024 * 1024


def plan(repo, files, *, limit, maximum, start_number=5, **option_values):
    options = RunOptions(
        message="m", attribution=False, limit_mib=1, max_mib=3, **option_values
    )
    report = RunReport(options)
    console = Console(record=True, width=120)
    code = run_dry(
        console,
        options,
        report,
        repo,
        files,
        [],
        "",
        limit,
        maximum,
        limit,
        start_number,
    )
    return code, report, console.export_text()


def write(repo, name, size):
    (repo / name).write_bytes(b"x" * size)
    return name


def test_dry_run_records_the_planned_batches(git_repo):
    files = [write(git_repo, "a.txt", 600), write(git_repo, "b.txt", 600)]

    code, report, text = plan(git_repo, files, limit=1000, maximum=5000)

    assert code == 0
    assert report.status == DRY_RUN
    assert len(report.batches) == 2
    assert report.total_files == 2
    assert "m #5" in text
    assert "m #6" in text
    assert "Dry run only" in text


def test_dry_run_numbers_batches_from_the_start_number(git_repo):
    files = [write(git_repo, "a.txt", 10)]

    _, report, _ = plan(git_repo, files, limit=1000, maximum=5000, start_number=42)

    assert report.batches[0]["message"] == "m #42"


def test_dry_run_reports_files_over_the_maximum_as_deferred(git_repo):
    files = [write(git_repo, "small.txt", 10), write(git_repo, "huge.bin", 9000)]

    _, report, text = plan(git_repo, files, limit=1000, maximum=5000)

    assert [item["path"] for item in report.deferred] == ["huge.bin"]
    assert "Would be deferred" in text


def test_dry_run_does_not_touch_the_repository(git_repo):
    import subprocess

    files = [write(git_repo, "a.txt", 10)]

    plan(git_repo, files, limit=1000, maximum=5000)

    staged = subprocess.run(
        ["git", "-C", str(git_repo), "diff", "--cached", "--name-only"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert staged == ""


def test_dry_run_mentions_no_push(git_repo):
    files = [write(git_repo, "a.txt", 10)]

    _, _, text = plan(git_repo, files, limit=1000, maximum=5000, no_push=True)

    assert "--no-push" in text
