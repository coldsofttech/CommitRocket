from commitrocket.cli import main


def test_doctor_goes_to_the_doctor_command(monkeypatch):
    seen = {}

    def fake_doctor(argv):
        seen["argv"] = argv
        return 4

    monkeypatch.setattr("commitrocket.cli.doctor.doctor_main", fake_doctor)
    assert main(["doctor", "--offline"]) == 4
    assert seen["argv"] == ["--offline"]


def test_anything_else_is_a_run(monkeypatch):
    seen = {}

    def fake_run_main(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr("commitrocket.cli.execute.run_main", fake_run_main)
    assert main(["--message", "m"]) == 0
    assert seen["argv"] == ["--message", "m"]


def test_arguments_default_to_the_command_line(monkeypatch):
    seen = {}

    def fake_run_main(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr("commitrocket.cli.execute.run_main", fake_run_main)
    monkeypatch.setattr("sys.argv", ["commitrocket", "--dry-run"])
    main()
    assert seen["argv"] == ["--dry-run"]
