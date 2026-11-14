## What changed

<!-- What does this do, and why? Link the issue it closes, e.g. "Closes #123". -->

## Checklist

- [ ] Tests added or updated
- [ ] `uv run ruff check .` and `uv run pytest -m "not integration"` pass
- [ ] `uv run pytest -m integration` passes (if the change touches the run flow, Git handling or LFS)
- [ ] `CHANGELOG.md` has a short `[Unreleased]` entry
- [ ] README or `docs/` updated if behaviour changed
- [ ] No secrets, tokens or private paths in the code, tests or logs
