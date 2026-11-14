import subprocess

import pytest
from rich.console import Console

from commitrocket.core.options import RunOptions
from commitrocket.core.runner import resume
from commitrocket.git.git import PushTarget
from commitrocket.git.journal import Journal
from commitrocket.io.report import RunReport
from commitrocket.support.errors import CommitRocketError


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(git_repo):
    (git_repo / "first.txt").write_text("first")
    git(git_repo, "add", "first.txt")
    git(git_repo, "commit", "-q", "-m", "first")
    return git_repo


def prior_run(repo, **changes):
    head = git(repo, "rev-parse", "HEAD")
    prior = {
        "params": {},
        "branch": "main",
        "target": "origin/main",
        "head": head,
        "commits": [],
    }
    return {**prior, **changes}


# -- check_resume -----------------------------------------------------------


def test_check_resume_needs_an_interrupted_run(repo):
    with pytest.raises(CommitRocketError, match="no interrupted run"):
        resume.check_resume(repo, None, RunOptions(), "main", "origin/main")


def test_check_resume_rejects_different_parameters(repo):
    options = RunOptions(params={"message": "other"})
    with pytest.raises(CommitRocketError, match="parameters differ"):
        resume.check_resume(repo, prior_run(repo), options, "main", "origin/main")


def test_check_resume_rejects_another_branch_or_target(repo):
    with pytest.raises(CommitRocketError, match="interrupted run was on"):
        resume.check_resume(repo, prior_run(repo), RunOptions(), "dev", "origin/main")
    with pytest.raises(CommitRocketError, match="interrupted run was on"):
        resume.check_resume(repo, prior_run(repo), RunOptions(), "main", "origin/dev")


def test_check_resume_rejects_a_changed_history(repo):
    prior = prior_run(repo, head="0" * 40)
    with pytest.raises(CommitRocketError, match="repository changed"):
        resume.check_resume(repo, prior, RunOptions(), "main", "origin/main")


def test_check_resume_follows_the_last_recorded_commit(repo):
    head = git(repo, "rev-parse", "HEAD")
    prior = prior_run(repo, head="0" * 40, commits=[(1, head)])
    resume.check_resume(repo, prior, RunOptions(), "main", "origin/main")


def test_check_resume_accepts_a_matching_run(repo):
    resume.check_resume(repo, prior_run(repo), RunOptions(), "main", "origin/main")


# -- read_resume_state ------------------------------------------------------


def read_state(repo, options=None):
    console = Console(record=True, width=120)
    state = resume.read_resume_state(
        console, repo, options or RunOptions(), "main", "origin/main"
    )
    return state, console.export_text()


def test_no_journal_means_a_fresh_run(repo):
    (_, prior, same_run, entry, staged), _ = read_state(repo)
    assert prior is None
    assert same_run is False
    assert entry is None
    assert staged == []


def test_a_journal_with_the_same_parameters_continues_the_run(repo):
    Journal(repo).start({"message": "m"}, "main", "origin/main", "abc")

    (_, prior, same_run, _, _), text = read_state(
        repo, RunOptions(params={"message": "m"})
    )

    assert prior is not None
    assert same_run is True
    assert "starting a new run" not in text


def test_a_journal_with_other_parameters_starts_a_new_run(repo):
    Journal(repo).start({"message": "old"}, "main", "origin/main", "abc")

    (_, prior, same_run, entry, _), text = read_state(
        repo, RunOptions(params={"message": "new"})
    )

    assert prior is not None
    assert same_run is False
    assert entry is None
    assert "starting a new run" in text


def test_an_incompatible_journal_is_ignored_without_resume(repo):
    Journal(repo).path.write_text('{"event": "run", "version": 999}\n')

    (_, prior, same_run, _, _), _ = read_state(repo)

    assert prior is None
    assert same_run is False


def test_an_incompatible_journal_stops_a_resume(repo):
    Journal(repo).path.write_text('{"event": "run", "version": 999}\n')

    with pytest.raises(CommitRocketError, match="incompatible"):
        read_state(repo, RunOptions(resume=True))


def test_files_staged_by_the_interrupted_run_are_picked_up(repo):
    journal = Journal(repo)
    journal.start({}, "main", "origin/main", "abc")
    (repo / "a.txt").write_text("a")
    journal.write(["a.txt"], "m #2", 2)
    git(repo, "add", "a.txt")

    (_, _, _, entry, staged), _ = read_state(repo)

    assert staged == ["a.txt"]
    assert entry["message"] == "m #2"


def test_files_staged_by_someone_else_stop_the_run(repo):
    (repo / "mine.txt").write_text("x")
    git(repo, "add", "mine.txt")

    with pytest.raises(CommitRocketError, match="already staged"):
        read_state(repo)


# -- resume_previous --------------------------------------------------------


@pytest.fixture
def pushes(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "commitrocket.core.runner.helpers.push_target",
        lambda *args, **kwargs: calls.append(args),
    )
    monkeypatch.setattr(
        "commitrocket.git.git.find_large_unpushed_blobs", lambda *args: []
    )
    return calls


def staged_by_interrupted_run(repo):
    journal = Journal(repo)
    journal.start({}, "main", "origin/main", "abc")
    (repo / "a.txt").write_text("a")
    journal.write(["a.txt"], "m #4", 4)
    git(repo, "add", "a.txt")
    return journal, journal.read()


def call_resume_previous(repo, journal, entry, staged, unpushed, verify, **options):
    resume.resume_previous(
        Console(quiet=True),
        repo,
        None,
        None,
        RunOptions(**options),
        PushTarget("origin", "main", []),
        journal,
        entry,
        staged,
        unpushed,
        verify,
    )


def test_resume_previous_commits_and_pushes_the_staged_batch(repo, pushes):
    journal, entry = staged_by_interrupted_run(repo)
    verified = []

    call_resume_previous(
        repo, journal, entry, ["a.txt"], [], lambda: verified.append(1)
    )

    assert git(repo, "log", "-1", "--format=%s") == "m #4"
    state = journal.state()
    assert state["commits"] == [(4, git(repo, "rev-parse", "HEAD"))]
    assert state["pushed"] == git(repo, "rev-parse", "HEAD")
    assert len(pushes) == 1
    assert verified == [1]


def test_resume_previous_does_not_push_with_no_push(repo, pushes):
    journal, entry = staged_by_interrupted_run(repo)

    call_resume_previous(
        repo, journal, entry, ["a.txt"], [], lambda: None, no_push=True
    )

    assert git(repo, "log", "-1", "--format=%s") == "m #4"
    assert pushes == []
    assert journal.state()["pushed"] is None


def test_resume_previous_pushes_unpushed_commits_only(repo, pushes):
    journal = Journal(repo)
    journal.start({}, "main", "origin/main", "abc")
    verified = []

    call_resume_previous(repo, journal, None, [], ["abc"], lambda: verified.append(1))

    assert len(pushes) == 1
    assert verified == [1]
    assert git(repo, "rev-list", "--count", "HEAD") == "1"


def test_resume_previous_does_nothing_when_there_is_nothing_to_resume(repo, pushes):
    journal = Journal(repo)
    journal.start({}, "main", "origin/main", "abc")

    call_resume_previous(repo, journal, None, [], [], lambda: None)

    assert pushes == []


def test_resume_previous_refuses_a_commit_with_oversized_files(
    repo, pushes, monkeypatch
):
    journal, entry = staged_by_interrupted_run(repo)
    monkeypatch.setattr(
        "commitrocket.git.git.find_large_unpushed_blobs",
        lambda *args: [("a.txt", 1)],
    )

    with pytest.raises(CommitRocketError, match="over 100 MiB"):
        call_resume_previous(repo, journal, entry, ["a.txt"], [], lambda: None)

    assert pushes == []


# -- commit_lfs_rules -------------------------------------------------------


class FakeLfs:
    def __init__(self, changed):
        self.changed = changed

    def write_committed_rules(self, paths):
        if self.changed:
            (self.repo / ".gitattributes").write_text("*.bin filter=lfs\n")
        return self.changed


def run_commit_lfs_rules(repo, changed, **options):
    lfs = FakeLfs(changed)
    lfs.repo = repo
    options = RunOptions(message="m", attribution=False, **options)
    report = RunReport(options)
    verified = []
    resume.commit_lfs_rules(
        Console(quiet=True),
        repo,
        None,
        None,
        options,
        PushTarget("origin", "main", []),
        lfs,
        ["a.bin"],
        report,
        lambda: verified.append(1),
    )
    return report, verified


def test_commit_lfs_rules_commits_and_pushes_the_rules(repo, pushes):
    report, verified = run_commit_lfs_rules(repo, True)

    assert git(repo, "log", "-1", "--format=%s") == "m (LFS rules)"
    assert report.lfs["rules_commit"] == git(repo, "rev-parse", "HEAD")
    assert len(pushes) == 1
    assert verified == [1]


def test_commit_lfs_rules_does_nothing_when_the_rules_are_unchanged(repo, pushes):
    report, verified = run_commit_lfs_rules(repo, False)

    assert git(repo, "rev-list", "--count", "HEAD") == "1"
    assert report.lfs["rules_commit"] is None
    assert pushes == []
    assert verified == []
