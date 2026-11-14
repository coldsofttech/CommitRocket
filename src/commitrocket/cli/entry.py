def main(argv=None):
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "doctor":
        from commitrocket.cli.doctor import doctor_main

        return doctor_main(argv[1:])

    from commitrocket.cli.execute import run_main

    return run_main(argv)
