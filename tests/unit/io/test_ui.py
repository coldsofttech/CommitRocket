from rich.console import Console

from commitrocket.io import ui


def recording_console():
    return Console(record=True, width=120)


def output(console):
    return console.export_text()


class FakeEstimator:
    def __init__(self, remaining):
        self.remaining = remaining

    def estimate(self, completed, total):
        return self.remaining


def eta_text(estimator):
    progress = ui.make_progress(recording_console())
    task_id = progress.add_task("work", total=10, estimator=estimator)
    return progress.columns[-1].render(progress.tasks[task_id]).plain


def test_eta_column_is_empty_without_an_estimator():
    progress = ui.make_progress(recording_console())
    task_id = progress.add_task("work", total=10)
    assert progress.columns[-1].render(progress.tasks[task_id]).plain == ""


def test_eta_column_shows_when_the_estimate_is_not_ready():
    assert "estimating" in eta_text(FakeEstimator(None))


def test_eta_column_shows_the_remaining_time():
    assert eta_text(FakeEstimator(90)).startswith("ETA ")


def test_print_run_info():
    console = recording_console()
    ui.print_run_info(console, "/repo", "main", "origin/main", 100, 300, 7)
    text = output(console)
    for expected in ("/repo", "main", "origin/main", "100 MiB", "300 MiB", "7"):
        assert expected in text


def test_print_lfs_required_lists_the_files(tmp_path):
    (tmp_path / "big.bin").write_bytes(b"x" * 1024)
    console = recording_console()
    ui.print_lfs_required(console, tmp_path, ["big.bin"], 100)
    text = output(console)
    assert "big.bin" in text
    assert "--use-lfs" in text
    assert "Nothing was committed" in text


def test_print_resume_describes_staged_files_and_unpushed_commits():
    console = recording_console()
    ui.print_resume(console, ["a", "b"], {"message": "Batch #3"}, ["c1", "c2"])
    text = output(console)
    assert "2 file(s) were staged" in text
    assert "Batch #3" in text
    assert "2 unpushed commit(s)" in text


def test_print_resume_truncates_a_long_commit_list():
    console = recording_console()
    ui.print_resume(console, [], None, [f"c{n}" for n in range(15)])
    text = output(console)
    assert "and 5 more" in text
    assert "c9" in text
    assert "c10" not in text


def test_print_dry_run():
    console = recording_console()
    mib = 1024 * 1024
    ui.print_dry_run(
        console,
        batches=[(["a", "b"], 2 * mib), (["c"], mib)],
        deferred=[("huge.bin", 500 * mib)],
        messages=["m #1", "m #2"],
        lfs_files={"c"},
        lfs_scope="Via LFS: 1 file",
        no_push=True,
    )
    text = output(console)
    assert "m #1" in text
    assert "m #2" in text
    assert "2 batch(es), 3 file(s), 3.00 MiB in total." in text
    assert "Via LFS: 1 file" in text
    assert "huge.bin" in text
    assert "--no-push" in text
    assert "Dry run only" in text


def test_print_dry_run_without_extras_omits_their_sections():
    console = recording_console()
    ui.print_dry_run(console, [(["a"], 1)], [], ["m #1"], set(), None)
    text = output(console)
    assert "Would be deferred" not in text
    assert "--no-push" not in text


def test_print_stuck_commits_shows_how_to_drop_them():
    console = recording_console()
    ui.print_stuck_commits(
        console,
        ["abc first", "def second"],
        [("big.bin", 150 * 1024 * 1024)],
        "origin/main",
        100,
    )
    text = output(console)
    assert "big.bin" in text
    assert "2 unpushed local commit(s)" in text
    assert "git reset --mixed origin/main" in text


def test_final_summary_with_nothing_deferred(tmp_path):
    (tmp_path / "small.txt").write_text("x")
    console = recording_console()
    code = ui.print_final_summary(
        console, tmp_path, 3, 0, 1, pending_files=lambda: ["small.txt"]
    )
    text = output(console)
    assert code == 0
    assert "Batches pushed" in text
    assert "All eligible files processed." in text


def test_final_summary_reports_deferred_files(tmp_path):
    (tmp_path / "huge.bin").write_bytes(b"x" * (2 * 1024 * 1024))
    console = recording_console()
    code = ui.print_final_summary(
        console, tmp_path, 1, 0, 1, pending_files=lambda: ["huge.bin"], pushed=False
    )
    text = output(console)
    assert code == 2
    assert "Batches committed" in text
    assert "huge.bin" in text
    assert "Exceeds --max-mib (1 MiB)" in text
