from commitrocket.journal import Journal


def test_journal_round_trip(git_repo):
    journal = Journal(git_repo)
    assert journal.read() is None

    journal.write(["a.txt", "b c.txt"], "Videos #22", 22)
    assert journal.read() == {
        "files": ["a.txt", "b c.txt"],
        "message": "Videos #22",
        "number": 22,
    }

    journal.clear()
    assert journal.read() is None
    journal.clear()  # clearing twice is fine
