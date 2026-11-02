import pytest

from commitrocket.journal import JOURNAL_VERSION, Journal, JournalError


def start(journal, **params):
    journal.start(params or {"message": "m"}, "main", "origin/main", "abc123")


def test_no_journal_means_no_state(git_repo):
    journal = Journal(git_repo)
    assert journal.state() is None
    assert journal.read() is None


def test_journal_lives_in_git_as_jsonl(git_repo):
    journal = Journal(git_repo)
    start(journal)
    assert journal.path.name == "commitrocket-journal.jsonl"
    assert ".git" in journal.path.parts
    assert journal.path.read_text(encoding="utf-8").count("\n") == 1


def test_in_flight_batch_round_trip(git_repo):
    journal = Journal(git_repo)
    start(journal)
    journal.write(["a.txt", "b c.txt"], "Videos #22", 22)
    assert journal.read() == {
        "files": ["a.txt", "b c.txt"],
        "message": "Videos #22",
        "number": 22,
    }

    journal.committed(22, "deadbeef")
    assert journal.read() is None


def test_state_replays_progress(git_repo):
    journal = Journal(git_repo)
    start(journal, message="Videos", number=1)
    journal.write(["a"], "Videos #1", 1)
    journal.committed(1, "sha1")
    journal.pushed("sha1")
    journal.write(["b"], "Videos #2", 2)
    journal.committed(2, "sha2")
    journal.note("interrupted")

    state = journal.state()
    assert state["params"] == {"message": "Videos", "number": 1}
    assert state["branch"] == "main"
    assert state["target"] == "origin/main"
    assert state["head"] == "abc123"
    assert state["commits"] == [(1, "sha1"), (2, "sha2")]
    assert state["pushed"] == "sha1"
    assert state["next_number"] == 3
    assert state["status"] == "interrupted"
    assert state["inflight"] is None


def test_a_line_cut_short_by_a_crash_is_ignored(git_repo):
    journal = Journal(git_repo)
    start(journal)
    journal.committed(1, "sha1")
    with open(journal.path, "a", encoding="utf-8") as handle:
        handle.write('{"event": "committed", "num')

    state = journal.state()
    assert state["commits"] == [(1, "sha1")]


def test_incompatible_version_is_reported(git_repo):
    journal = Journal(git_repo)
    start(journal)
    text = journal.path.read_text(encoding="utf-8")
    journal.path.write_text(
        text.replace(f'"version": {JOURNAL_VERSION}', '"version": 999'),
        encoding="utf-8",
    )
    with pytest.raises(JournalError):
        journal.state()
    assert journal.read() is None


def test_start_replaces_an_earlier_journal_and_the_legacy_file(git_repo):
    journal = Journal(git_repo)
    start(journal, message="old")
    journal.committed(1, "sha1")
    journal._legacy.write_text("{}", encoding="utf-8")

    start(journal, message="new")

    assert journal.state()["params"] == {"message": "new"}
    assert journal.state()["commits"] == []
    assert not journal._legacy.exists()


def test_delete_removes_the_journal(git_repo):
    journal = Journal(git_repo)
    start(journal)
    journal.delete()
    assert journal.state() is None
    journal.delete()  # deleting twice is fine
