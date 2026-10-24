## What does this change?

<!-- A short summary, and why it is needed. Link the issue it closes, e.g. "Closes #123". -->

## How was it tested?

<!-- Commands you ran and anything you checked by hand. -->

## Checklist

- [ ] `uv run ruff check .` passes
- [ ] `uv run pytest -m "not integration"` passes
- [ ] `uv run pytest -m integration` passes (if the change touches the run flow, Git handling or LFS)
- [ ] Tests added or updated for the change
- [ ] `CHANGELOG.md` has a short entry under `[Unreleased]` (what changed for the reader, in one or two lines)
- [ ] `README.md` updated if user-facing behavior or options changed; technical details go in `docs/`
- [ ] No secrets, tokens or private paths in the code, tests or logs
