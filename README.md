# CommitRocket

[![Tests](https://github.com/coldsofttech/CommitRocket/actions/workflows/tests.yml/badge.svg)](https://github.com/coldsofttech/CommitRocket/actions/workflows/tests.yml)
[![Lint](https://github.com/coldsofttech/CommitRocket/actions/workflows/lint.yml/badge.svg)](https://github.com/coldsofttech/CommitRocket/actions/workflows/lint.yml)
[![Release](https://img.shields.io/github/v/release/coldsofttech/CommitRocket?logo=github)](https://github.com/coldsofttech/CommitRocket/releases)
[![PyPI](https://img.shields.io/pypi/v/commitrocket?logo=pypi&logoColor=white)](https://pypi.org/project/commitrocket/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License](https://img.shields.io/github/license/coldsofttech/CommitRocket)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)

Got a huge pile of changes that a single push would choke on? CommitRocket splits them
into size-limited batches, commits each batch, and pushes as it goes, with live progress.

CommitRocket is a command-line tool: you install it and run `commitrocket`. It is not a
Python library and has no Python API to import.

## Why CommitRocket?

Pushing a lot of data in one go tends to go wrong. A single commit with gigabytes of videos,
datasets, archives or generated assets can time out halfway, be rejected for containing a
file over your host's limit (GitHub refuses anything over 100 MiB), or leave you with nothing
pushed after hours of waiting. CommitRocket turns that one fragile push into many small ones:
each batch is committed and uploaded on its own, so progress is saved as you go, a failure
costs you one batch instead of everything, and you can always see how far along you are.

It is a good fit for:

- **First uploads of big folders**: course material, media libraries, backups, game assets,
  data dumps, or a repository you are migrating.
- **Slow or unreliable connections**, where small pushes that can be retried beat one huge one.
- **Repositories with a few very large files**, which it can store with Git LFS for you
  without leaving LFS configuration behind.
- **Unattended runs**: scheduled jobs and CI, with a JSON report and notifications.

## What you get

- **Size-based batching**: choose how big each commit is, how files are picked (in order, or
  packed tightly), and the largest single file you will accept. Anything too large is skipped
  and listed at the end instead of failing the run.
- **Live progress** with elapsed time and an ETA based on how fast your upload really is.
- **Safe with large files**: files over the 100 MiB host limit are detected before anything
  is committed. With `--use-lfs` they go through Git LFS, installed and removed again for you.
- **Recovers from trouble**: failed pushes are retried, every push is checked against the
  remote, and if a run is interrupted (even with Ctrl+C) you just run the same command to
  carry on from where it stopped.
- **Under your control**: preview everything with `--dry-run`, pick files with
  `.gitignore`-style patterns, choose the remote and branch, commit without pushing, and
  shape the commit messages with a template.
- **Easy to automate**: save your options in a config file, read results from a JSON
  report, get a desktop or webhook notification when a long run ends, and check your setup
  with `commitrocket doctor`.
- **Leaves a trail**: every run writes a log file you can attach to a bug report.

It runs on Windows, macOS and Linux and talks to your remote through plain Git, so it works
with any host you can already push to. It never changes your global Git configuration:
temporary settings live in the repository and are restored afterwards.

## Install

```
pip install commitrocket
```

Requires Python 3.11 or later and [Git](https://git-scm.com/). Because it is a program
rather than a library, [pipx](https://pipx.pypa.io/) and [uv](https://docs.astral.sh/uv/)
are a good fit too, and keep it out of your project environments:

```
pipx install commitrocket
uv tool install commitrocket
```

Check the install with `commitrocket --version`. Git LFS is optional: only `--use-lfs`
needs it, and CommitRocket offers to install it when it is missing.

## Use

```
commitrocket --repo path/to/repo --message "Add assets"
```

Each batch is committed as `Add assets #1`, `Add assets #2`, and so on, and pushed
right away.

Before it starts, CommitRocket checks that you are on a branch with an upstream and have
nothing staged, then asks for confirmation.

The options you will use most:

| Option | What it does |
| --- | --- |
| `--message` | Commit message used for every batch (required, here or in a config file) |
| `--resume` | Continue the interrupted run in this repository with the parameters it started with (see [Interrupted or failed runs](#interrupted-or-failed-runs)) |
| `--limit-mib` | Target size of each batch in MiB (default 100) |
| `--dry-run` | Show the planned batches and commit messages without changing anything |
| `--include` / `--exclude` | Only handle / leave alone files matching a pattern (repeatable) |
| `--use-lfs` | Store files over 100 MiB with Git LFS for this run (see "Large files with Git LFS") |
| `--no-push` | Commit every batch but don't push them |
| `--force` | Skip the confirmation prompt |

There is also `commitrocket doctor`, which checks Git, git-lfs, your config and the remote without changing anything
(see [doctor](docs/guides/cli.md#doctor)).
Run `commitrocket --help` or see the [command line guide](docs/guides/cli.md) for every
option with its default and limits, and the exit codes.

### Config file

Save your usual options so you don't have to retype them, in `commitrocket.toml` in the
repository folder or in the `[tool.commitrocket]` table of `pyproject.toml`:

```toml
# commitrocket.toml
message = "Videos"
use-lfs = true
limit-mib = 50
exclude = ["raw/", "*.tmp"]
```

Options typed on the command line win over the file. A config file inside a repository is
not fully trusted, so it cannot turn on `force`, choose `remote` or `branch`, or set
`report`, `log-file`, `notify-webhook` or the pattern files; pass such a file yourself with
`--config` to use those. The [configuration guide](docs/guides/configuration.md) lists every
key and explains how files are found and trusted.

### More

Everything else is in the [command line guide](docs/guides/cli.md):

- [File patterns](docs/guides/cli.md#file-patterns) for `--include` and `--exclude`
- [Commit messages](docs/guides/cli.md#commit-messages), templates and the attribution line
- [Batch types](docs/guides/cli.md#batch-types)
- [Report and notifications](docs/guides/cli.md#report-and-notifications) for scripts and CI
- [Logs](docs/guides/cli.md#logs) and [`commitrocket doctor`](docs/guides/cli.md#doctor)
- [Examples](docs/guides/cli.md#examples), and settings in the
  [configuration guide](docs/guides/configuration.md)

### Large files with Git LFS

Hosts like GitHub reject files over 100 MiB. With `--use-lfs`, CommitRocket stores those
files with Git LFS instead: it installs git-lfs if it is missing (asking first, unless
`--force`), commits one rule per file type to `.gitattributes` so clones get the real
files, pushes your files as usual, and removes its local LFS setup when it finishes, even
if the run fails. Without `--use-lfs`, a file over 100 MiB stops the run before anything is
committed. See [Using Git LFS](docs/guides/cli.md#using-git-lfs) for the threshold, the
rules commit, thread settings and what happens after a failed run.

### Interrupted or failed runs

If a run stops, whether it failed or you pressed Ctrl+C, CommitRocket remembers it in a small
file inside `.git`, so it is never committed. Carry on with the same command, or let it reuse
the settings the run started with:

```
commitrocket --repo . --resume
```

Commits that were made but not pushed are pushed first, the files the run had staged are
committed with their original message, and numbering continues where it stopped. Repeating a
setting with `--resume` is fine as long as the value is the same; to change settings, run
without `--resume` and a new run starts. See
[Interrupted runs](docs/guides/cli.md#interrupted-runs) for the details and the cases where
`--resume` refuses to continue.

### Checks after each push

After every push CommitRocket confirms that the remote branch now points at your latest
commit, and stops with an error if it does not. With LFS, it also confirms right after each
commit that the large files really were turned into LFS pointers, before uploading them, so
a misconfiguration is caught before a doomed upload.

### Commits left over from a failed push

If an earlier run left local commits that contain files over 100 MiB, GitHub will keep
rejecting them. CommitRocket detects this at the start, changes nothing, and shows the
command to drop those commits while keeping your files:

```
git reset --mixed origin/main
```

Then run the same CommitRocket command again.

## Support, contributing and security

For help, see [SUPPORT.md](SUPPORT.md). Contributions are welcome. Start with
[CONTRIBUTING.md](CONTRIBUTING.md) and follow the [Code of Conduct](CODE_OF_CONDUCT.md). To
report a vulnerability, please read [SECURITY.md](SECURITY.md) first and do not open a
public issue. The guides and technical notes are listed in [docs/README.md](docs/README.md).

## License

See [LICENSE](LICENSE). CommitRocket depends on [Rich](https://github.com/Textualize/rich)
(MIT) and [pathspec](https://github.com/cpburnett/python-pathspec) (MPL-2.0). Git and
Git LFS are separate programs with their own licenses and are never bundled.
