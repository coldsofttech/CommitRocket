# Contributing to CommitRocket

Thanks for helping out! Bug reports, ideas, documentation fixes and code are all welcome.
By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Reporting bugs and suggesting features

- Search the existing issues first.
- Use the issue templates. For a bug, include the exact command, the output, your
  versions (`commitrocket --version`, `commitrocket doctor`), and the relevant lines from
  the log file (re-run with `--level DEBUG`). Remove secrets and private paths.
- **Security problems:** do not open an issue. Follow the [Security Policy](SECURITY.md).

## Setting up

You need Python 3.11+, [Git](https://git-scm.com/) and [uv](https://docs.astral.sh/uv/).

```
git clone https://github.com/coldsofttech/CommitRocket.git
cd CommitRocket
uv sync
uv run pre-commit install
```

`uv run commitrocket --help` runs the tool from your checkout.

## Making a change

1. Create a branch from `main`, for example `feat/short-name`, `fix/short-name` or
   `chore/short-name`.
2. Make the change, with tests. New behavior needs a test; a bug fix needs a test that
   fails without the fix.
3. Run the checks:

   ```
   uv run ruff check .
   uv run pytest -m "not integration"
   uv run pytest -m integration
   ```

   Pre-commit runs the first two on every commit. The integration tests drive the real
   CLI against a local bare repository and run in CI, so run them yourself when you touch
   the run flow, Git handling or LFS. Details are in [docs/development.md](docs/development.md).
4. Update the docs:
   - `README.md` is for users: describe options and behavior from a user's point of view.
   - Technical notes belong in `docs/`.
   - Add a short entry under `[Unreleased]` in `CHANGELOG.md`: one or two lines saying
     what changed for the reader, without file or function names.
5. Open a pull request against `main` and fill in the template. Keep it focused; separate
   unrelated changes into separate pull requests.

## Tests that touch Git

Tests create temporary repositories and never touch your real ones. Do not point a test at
a real remote. Keep any log or report files a test writes outside the repository the test
is operating on.

## Releases

Maintainers release by bumping the version in `pyproject.toml` and
`src/commitrocket/__init__.py`, moving the changelog entries under the new version, and
pushing a `v*.*.*` tag. See [docs/development.md](docs/development.md).
