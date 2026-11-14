from commitrocket.core.options import RunOptions
from commitrocket.core.runner import own_output_files


def test_own_output_files_are_found_only_inside_the_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    options = RunOptions(
        log_file=str(repo / "logs" / "run.log"),
        report=str(tmp_path / "elsewhere" / "report.json"),
    )
    assert own_output_files(repo.resolve(), options) == {"logs/run.log"}

    options = RunOptions(report=str(repo / "report.json"))
    assert own_output_files(repo.resolve(), options) == {"report.json"}
    assert own_output_files(repo.resolve(), RunOptions()) == set()
