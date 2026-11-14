# Development

## Setup

```
uv sync                          # creates .venv with the dev tools
uv run pre-commit install        # lint + unit tests before every commit
```

The layout of the code is described in [architecture.md](architecture.md). Tests live in
`tests/`, with `tests/unit/` mirroring `src/commitrocket/`; see [Tests](#tests) below.

## Common tasks

```
uv run pytest -m "not integration" -n auto   # unit tests
uv run pytest -m integration                 # end to end, against a local bare repository
uv run ruff check .                          # lint
uv run mypy                                  # type check
```

`sweepito.toml` configures Sweepito for this repository, if you use it to clean caches and
build output (`.venv/` is kept).

## Imports

Imports are lazy: a module imports what it needs inside the function that uses it. A name
needed when the module loads (a base class, a compiled regular expression, a dataclass field
default, a module constant) stays at the top of its module. Tests that patch a standard
library module should patch the module itself (for example `sys` or `shutil`), not an
attribute of the module under test, because the import happens inside the function.

## Data files

Notification scripts are kept out of the code and read when a notification is sent:
`src/commitrocket/io/scripts/toast.ps1` (Windows) and `notification.applescript` (macOS).
They receive the title and body through the `CR_TITLE` and `CR_BODY` environment variables,
never in the script text. Both are packaged with the wheel.

## Tests

Tests are marked, so you can pick what to run:

| Command | What runs |
| --- | --- |
| `uv run pytest` | Everything |
| `uv run pytest -m "not integration"` | Unit tests only (fast; what pre-commit runs) |
| `uv run pytest -m integration` | End-to-end tests in `tests/integration/` |

Unit tests live in `tests/unit/` and mirror `src/commitrocket/`: a test for
`core/batching.py` goes in `tests/unit/core/test_batching.py`. Shared fixtures are in
`tests/conftest.py`. The test folders have no `__init__.py` and pytest runs with
`--import-mode=importlib`, so two modules in different folders can both have a
`test_doctor.py` or `test_resume.py`.

Pre-commit and the `tests.yml` workflow run pytest in parallel with `pytest-xdist`
(`-n auto`, one worker per CPU core). Add `-n auto` locally for speed, or leave it off
when debugging a single test, since output and breakpoints are easier without workers.

Integration tests drive the real CLI against a local bare repository acting as the remote,
so they need only Git. They carry `pytestmark = pytest.mark.integration`; new end-to-end
tests belong in `tests/integration/` with the same marker. Markers are registered in
`pyproject.toml` and `--strict-markers` is on, so a typo in a marker name is an error.

## Lint and type check

```
uv run ruff check .
uv run mypy
```

## Pre-commit

`.pre-commit-config.yaml` runs `ruff check --fix` and the unit tests
(`pytest -m "not integration"`) on each commit. Integration tests are deliberately left to
CI. Run the hooks on everything with `uv run pre-commit run --all-files`, and bump hook
versions with `uv run pre-commit autoupdate`.

## GitHub workflows

| Workflow | When | What |
| --- | --- | --- |
| `lint.yml` | Pushes to `main`, pull requests | `ruff check` and `mypy` |
| `tests.yml` | Pushes to `main`, pull requests | Unit then integration tests on Ubuntu with Python 3.11, 3.12, 3.13, 3.14 and 3.15, and on Windows and macOS with 3.11. The 3.15 job may fail without failing the build while that version is a pre-release. |
| `release.yml` | Pushing a tag like `v0.2.0` | Checks the tag against the package version, re-runs lint and all tests, builds with `uv build`, attests the build provenance, publishes to PyPI and creates a GitHub release with the files attached |

## Releasing

1. Choose the version with [Semantic Versioning](https://semver.org/): a patch (`0.1.3`)
   for fixes only, a minor (`0.2.0`) for new features, a major for breaking changes to the
   command line. Before 1.0, a minor may also carry breaking changes; say so under
   `### Changed`. Update `version` in `pyproject.toml` and `__version__` in
   `src/commitrocket/__init__.py` (they must match).
2. Move the `[Unreleased]` entries in `CHANGELOG.md` under the new version, keeping the
   headings that are used.
3. Commit and push to `main`.
4. Tag and push the tag:

   ```
   git tag v0.2.0
   git push origin v0.2.0
   ```

The release workflow checks the tag against both versions, runs lint and all tests,
publishes to PyPI with trusted publishing (no API token is stored), and creates a GitHub
release. Trusted publishing needs the repository, the workflow `release.yml` and the
`pypi` environment registered as a trusted publisher in the PyPI project settings. The
`pypi` GitHub environment can require reviewers if you want a manual approval before each
release.
