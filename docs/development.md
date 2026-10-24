# Development

## Setup

```
uv sync                          # creates .venv with the dev tools
uv run pre-commit install        # lint + unit tests before every commit
```

## Tests

Tests are marked, so you can pick what to run:

| Command | What runs |
| --- | --- |
| `uv run pytest` | Everything |
| `uv run pytest -m "not integration"` | Unit tests only (fast; what pre-commit runs) |
| `uv run pytest -m integration` | End-to-end tests in `tests/integration/` |

Pre-commit and the `tests.yml` workflow run pytest in parallel with `pytest-xdist`
(`-n auto`, one worker per CPU core). Add `-n auto` locally for speed, or leave it off
when debugging a single test, since output and breakpoints are easier without workers.

Integration tests drive the real CLI against a local bare repository acting as the remote,
so they need only Git. They carry `pytestmark = pytest.mark.integration`; new end-to-end
tests belong in `tests/integration/` with the same marker. Markers are registered in
`pyproject.toml` and `--strict-markers` is on, so a typo in a marker name is an error.

## Lint

```
uv run ruff check .
```

## Pre-commit

`.pre-commit-config.yaml` runs `ruff check --fix` and the unit tests
(`pytest -m "not integration"`) on each commit. Integration tests are deliberately left to
CI. Run the hooks on everything with `uv run pre-commit run --all-files`, and bump hook
versions with `uv run pre-commit autoupdate`.

## GitHub workflows

| Workflow | When | What |
| --- | --- | --- |
| `lint.yml` | Pushes to `main`, pull requests | `ruff check` |
| `tests.yml` | Pushes to `main`, pull requests | Unit then integration tests on Ubuntu with Python 3.11, 3.12, 3.13, 3.14 and 3.15, and on Windows and macOS with 3.11. The 3.15 job may fail without failing the build while that version is a pre-release. |
| `release.yml` | Pushing a tag like `v0.2.0` | Checks the tag against the package version, re-runs lint and all tests, builds with `uv build`, publishes to PyPI and creates a GitHub release with the files attached |

## Releasing

1. Update `version` in `pyproject.toml` and `__version__` in
   `src/commitrocket/__init__.py` (they must match), and move the `[Unreleased]` entries in
   `CHANGELOG.md` under the new version.
2. Commit and push to `main`.
3. Tag and push the tag:

   ```
   git tag v0.2.0
   git push origin v0.2.0
   ```

One-time setup: create a PyPI API token and save it as the repository secret
`PYPI_API_TOKEN`. The publish job uses a GitHub environment named `pypi`, which you can
configure with required reviewers if you want a manual approval before each release. Scope
the token to this project once the first release has created it on PyPI.
