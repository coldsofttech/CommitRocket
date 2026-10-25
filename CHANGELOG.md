# Changelog

## [Unreleased]

## [0.1.2] - 2026-10-25

### Changed
- `--use-lfs` now commits LFS rules by default so checkouts and clones get the real files. Use `--no-lfs-commit-rules` for the old per-run behaviour.
- Releases are published to PyPI with trusted publishing instead of an API token.
- The PyPI page now shows keywords, classifiers and project links.

## [0.1.1] - 2026-10-24

### Added
- Issue and pull request templates, a security policy, a code of conduct and contributing guidelines.
- Dependabot keeps dependencies, GitHub Actions and pre-commit hooks up to date.

### Fixed
- Batches with thousands of files no longer fail on Windows with "The filename or extension is too long".

### Security
- A config file found inside a repository can no longer turn on `force`, set the remote or branch, write reports or logs, or read pattern files; use `--config` for those.
- File names with characters like `[` or `*` are treated literally, so they no longer pull other files into a batch.
- `--remote` and `--branch` values that look like Git options are rejected.
- Credentials inside remote URLs are hidden in logs, errors and reports, and log and report files are readable only by you.
- File names with line breaks are refused when creating LFS rules.
- Square brackets in file names and Git messages no longer break or hide output.

## [0.1.0] - 2026-10-24

### Added
- CommitRocket is now an installable package with a `commitrocket` command.
- Files over 100 MiB are detected up front, and the run stops with a hint to use `--use-lfs` instead of failing at push time.
- The overall progress bar shows an ETA based on the average speed of the whole run so far, updating live during each upload.
- `--use-lfs` stores files over 100 MiB with Git LFS during the run, without committing any LFS config, and removes the local setup afterwards.
- `--report FILE` writes a machine-readable JSON summary of every run.
- `--notify` and `--notify-webhook` tell you when a run ends, via a desktop notification or a web hook.
- `commitrocket doctor` checks Git, git-lfs, your settings, the remote and the repository before a run.
- Settings can be saved in `commitrocket.toml` or `[tool.commitrocket]` in `pyproject.toml`.
- `--include`, `--exclude`, `--include-from`, `--exclude-from` and `.commitrocketignore` choose which files are handled, using `.gitignore`-style patterns.
- `--remote` and `--branch` choose where to push, `--no-push` only commits, and `--message-template` customises commit messages.
- `--lfs-commit-rules` commits LFS rules per file type so clones get the real files.
- A failed `--use-lfs` run now keeps the LFS hooks until its commits are pushed, so LFS files are never published as bare pointers.
- `--repo` now defaults to the current folder.
- A `--log-file` or `--report` inside the repository is no longer committed, which previously made a run commit its own log forever.
- `--dry-run` shows the planned batches and commit messages without changing anything.
- Failed pushes are retried with growing waits (`--retries`, default 3); rejections are not retried.
- Interrupted or failed runs can be resumed by running the same command again.
- `--post-buffer-mib` raises Git's HTTP buffer for large pushes over HTTPS.
- Each push is checked against the remote, and LFS files are confirmed as pointers before upload.
- `--lfs-threshold-mib` sets the size above which `--use-lfs` applies (default 100); `0` sends every file through LFS.
- Each run writes a log file to the system's standard log folder; `--level` sets the detail and `--log-file` overrides the location.
- `--batch-type` chooses how files are grouped: `deterministic` (default, unchanged), `sequential` or `soft`.
- `--compression-threads`, `--lfs-threads` and `--lfs-batch-mib` speed up pushes; the thread settings apply to the repository only and are restored afterwards.
- Leftover local commits containing files over 100 MiB are detected at startup, with the command to clean them up.
