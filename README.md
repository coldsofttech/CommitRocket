# CommitRocket

Got a huge pile of changes that a single push would choke on? CommitRocket splits them
into size-limited batches, commits each batch, and pushes as it goes, with live progress.

## Install

```
pip install commitrocket
```

Requires Python 3.11+ and [Git](https://git-scm.com/).

## Use

```
commitrocket --repo path/to/repo --message "Add assets"
```

Each batch is committed as `Add assets #1`, `Add assets #2`, and so on, and pushed
right away.

Before it starts, CommitRocket checks that you are on a branch with an upstream and have
nothing staged, then asks for confirmation.

| Option | What it does |
| --- | --- |
| `--repo` | The Git repository to work on (default: the current folder) |
| `--message` | Commit message used for every batch (required, here or in a config file) |
| `--message-template` | Shape of each commit message (default `{message} #{n}`, see below) |
| `--number` | Number to start the `#` suffix from (default 1) |
| `--config` | Read settings from this TOML file (see "Config file") |
| `--remote` / `--branch` | Push to this remote / remote branch instead of the upstream |
| `--no-push` | Commit every batch but don't push them |
| `--include` / `--exclude` | Only handle / leave alone files matching a pattern (repeatable) |
| `--include-from` / `--exclude-from` | Read those patterns from a file |
| `--limit-mib` | Target size of each batch in MiB (default 100) |
| `--batch-type` | How files are picked: `deterministic` (default), `sequential` or `soft` (see below) |
| `--dry-run` | Show the planned batches and commit messages without changing anything |
| `--retries` | Retry a failed push this many times with growing waits (default 3, `0` = never) |
| `--post-buffer-mib` | Raise Git's `http.postBuffer` for this run, for large pushes over HTTPS |
| `--max-mib` | Largest single file allowed, in MiB (default 3x the limit) |
| `--force` | Skip the confirmation prompt |
| `--compression-threads` | Threads Git uses to compress data while pushing (0 = automatic) |
| `--lfs-threads` | How many Git LFS files upload at the same time |
| `--lfs-batch-mib` | Total size of LFS files pushed together (default: same as `--limit-mib`) |
| `--level` | Detail written to the log file: `DEBUG`, `INFO` (default), `WARNING` or `ERROR` |
| `--log-file` | Write the log to this file instead of the default folder |
| `--lfs-threshold-mib` | With `--use-lfs`, files larger than this use LFS (default 100, `0` = every file) |
| `--use-lfs` | Store files over 100 MiB with Git LFS for this run (see below) |
| `--lfs-commit-rules` | With `--use-lfs`, also commit LFS rules so clones get the real files |
| `--report` | Write a JSON summary of the run to this file |
| `--notify` | Show a desktop notification when the run ends |
| `--notify-webhook` | Send a JSON summary to this web address when the run ends |

There is also `commitrocket doctor`, which checks your setup (see "Check your setup").

### Choosing which files to handle

`--include` and `--exclude` take `.gitignore`-style patterns and can be repeated:

| Pattern | Matches |
| --- | --- |
| `*.mp4` | Every `.mp4` file, in any folder (this is how you select by extension) |
| `raw/` | The `raw` folder and everything in it |
| `/notes.txt` | Only `notes.txt` in the repository root |
| `videos/**/*.mov` | `.mov` files anywhere under `videos` |
| `!keep.mp4` | Re-includes a file matched by an earlier pattern in the same list |

With `--include`, only matching files are handled. Anything matching `--exclude` is left
alone, and exclusion always wins. Files that are filtered out are not staged, committed or
counted as skipped; they simply stay pending.

For longer lists, put one pattern per line in a file (blank lines and `#` comments are
ignored) and pass it with `--include-from` or `--exclude-from`. A file named
`.commitrocketignore` in the repository root is read automatically as a permanent list of
excludes.

```
commitrocket --repo . --message "Videos" --include "*.mp4" --include "*.mov" --exclude "raw/"
commitrocket --repo . --message "Videos" --include-from patterns.txt
```

### Config file

Save your usual options so you don't have to retype them. CommitRocket reads
`commitrocket.toml` in the repository folder, or else the `[tool.commitrocket]` table of
`pyproject.toml`; `--config FILE` points at a different file. Option names are the same as
on the command line, with `-` or `_`. Options typed on the command line win over the file,
and `--include`/`--exclude` lists are combined.

```toml
# commitrocket.toml
message = "Videos"
use-lfs = true
limit-mib = 50
batch-type = "sequential"
exclude = ["raw/", "*.tmp"]
message-template = "{message} #{n} ({files} files, {size:.0f} MiB)"
```

```toml
# or in pyproject.toml
[tool.commitrocket]
message = "Videos"
retries = 5
```

### Commit message templates

`--message-template` decides the message of each batch. The default is `{message} #{n}`.

| Placeholder | Value |
| --- | --- |
| `{message}` | The `--message` text |
| `{n}` | The commit number (starts at `--number`) |
| `{batch}` | The batch's position in this run, starting at 1 |
| `{files}` | Number of files in the batch |
| `{size}` | Size of the batch in MiB (e.g. `{size:.1f}`) |
| `{first}` | Path of the first file in the batch |
| `{date}` | Today's date, `YYYY-MM-DD` |

```
commitrocket --repo . --message "Course" --message-template "{message} part {n}: {files} files ({size:.0f} MiB)"
```

### Pushing somewhere else, or not at all

By default each batch is pushed to the branch's upstream. `--remote` and `--branch` choose
another destination, for example a backup remote or a different branch; HEAD is pushed to
that remote branch. With `--no-push` the batches are committed locally and a later run
pushes them (the "interrupted runs" resume does this). `--no-push` can't be combined with
`--use-lfs`, because the large files would stay on your machine while a later plain
`git push` published pointers without them.

### Report and notifications

`--report out.json` writes a machine-readable summary every time, including when the run
fails, is interrupted or is a dry run, so scripts and CI can read the result:

```json
{
  "schema_version": 1,
  "status": "success",
  "exit_code": 0,
  "target": "origin/main",
  "duration_seconds": 412.7,
  "totals": { "batches": 3, "files": 42, "size_bytes": 1234567890, "deferred_files": 0 },
  "batches": [
    { "number": 1, "message": "Videos #1", "commit": "e57cffb...", "file_count": 14,
      "size_bytes": 412345678, "lfs_file_count": 2, "pushed": true, "verified": true,
      "files": ["..."] }
  ],
  "deferred": [],
  "error": null,
  "log_file": "..."
}
```

`status` is one of `success`, `completed_with_deferred_files`, `dry_run`, `cancelled`,
`aborted` (stopped before doing anything, for example files needing `--use-lfs`),
`interrupted` and `failed`. The report also lists your settings, what was resumed, the LFS
files and the commit that holds the LFS rules. It never contains the webhook address.

Long runs can tell you when they are done:

| Option | What happens |
| --- | --- |
| `--notify` | A desktop notification: a toast on Windows, a notification on macOS, `notify-send` on Linux. If none of these works (for example over SSH), the terminal bell sounds instead. |
| `--notify-webhook URL` | A JSON message is POSTed to the address. It has `text` and `content` fields, so Slack, Teams and Discord incoming webhooks work, plus `status`, `batches`, `files` and `duration_seconds` for your own endpoint. [ntfy](https://ntfy.sh) also works. |

Notifications are sent when the run ends, whether it succeeded or not, and never for
`--dry-run`. A notification that can't be delivered never changes the run's result.

### Check your setup

```
commitrocket doctor
commitrocket doctor --repo path/to/repo --remote backup --offline
```

Checks Git and git-lfs, your config file, the log folder, the repository, branch and push
target, whether the remote is reachable and accepts a push (a dry run), staged and
unpushed files, and pending files over 100 MiB. It changes nothing. Use `--offline` to skip
the checks that contact the remote. The exit code is 1 if any check fails.

### Examples

Run these from inside the repository (`--repo .`), or point `--repo` at any path.

**Push everything in 100 MiB batches (the default)**
```
commitrocket --repo . --message "Add assets"
```

**Leave it running and get told when it's done**
```
commitrocket --repo . --message "Videos" --use-lfs --notify
commitrocket --repo . --message "Videos" --notify-webhook https://ntfy.sh/my-topic
```

**Results for scripts and CI**
```
commitrocket --repo . --message "Nightly" --force --report result.json
```

**Check everything is ready**
```
commitrocket doctor
```

**Only some files, or everything except some**
```
commitrocket --repo . --message "Videos" --include "*.mp4" --exclude "raw/"
```

**Push to a different remote or branch**
```
commitrocket --repo . --message "Backup" --remote backup --branch main
```

**Commit now, push later**
```
commitrocket --repo . --message "Add assets" --no-push
commitrocket --repo . --message "Add assets"     # later: pushes the saved commits
```

**Videos in LFS that clones can download too**
```
commitrocket --repo . --message "Videos" --use-lfs --lfs-commit-rules
```

**See what would happen first**

Prints every batch, its commit message and size, and any files that would be skipped.
Nothing is staged, committed, pushed or installed.
```
commitrocket --repo . --message "Add assets" --use-lfs --dry-run
```

**Flaky connection or "RPC failed" errors**

Failed pushes are retried automatically (3 times by default, after 5, 15 and 45
seconds). A bigger HTTP buffer helps with timeouts on large uploads over HTTPS.
```
commitrocket --repo . --message "Videos" --retries 5 --post-buffer-mib 500
```

**Smaller batches for a slow or unreliable connection**

Each push is shorter, so a failure costs less to repeat.
```
commitrocket --repo . --message "Add assets" --limit-mib 50
```

**Continue numbering after an earlier run**

If the last commit was `Videos #21`, the next batch becomes `Videos #22`.
```
commitrocket --repo . --message "Videos" --number 22
```

**Run without prompts (scripts, scheduled jobs)**
```
commitrocket --repo . --message "Nightly sync" --force
```

**Keep files in order, such as numbered lectures**

`sequential` never skips ahead, so `01`, `02`, `03` land in commits in that order.
```
commitrocket --repo . --message "Course videos" --batch-type sequential
```

**Fewer, larger pushes**

`soft` lets a batch run slightly past the limit instead of leaving gaps.
```
commitrocket --repo . --message "Add assets" --batch-type soft --limit-mib 100 --max-mib 300
```

**Files over 100 MiB (videos, archives, datasets)**

GitHub rejects these, so use LFS. Without `--use-lfs`, CommitRocket stops before
committing anything and lists the files.
```
commitrocket --repo . --message "Videos" --use-lfs
```

**Many large files, faster uploads**

Group several LFS files per push and upload four at a time.
```
commitrocket --repo . --message "Videos" --use-lfs --lfs-batch-mib 500 --lfs-threads 4
```

**Also move mid-size files (over 50 MiB) to LFS**

GitHub warns about files above 50 MiB, even though it accepts them.
```
commitrocket --repo . --message "Assets" --use-lfs --lfs-threshold-mib 50
```

**Send every file through LFS**

Use with care: clones will show pointer files for all content.
```
commitrocket --repo . --message "Archive" --use-lfs --lfs-threshold-mib 0
```

**Allow bigger individual files**

Files above `--max-mib` (default 3x the limit) are skipped and reported at the end.
```
commitrocket --repo . --message "Videos" --use-lfs --max-mib 500
```

**Find out why a push failed**

The log records every Git command and the push output. Its path is printed at the end.
```
commitrocket --repo . --message "Add assets" --level DEBUG
commitrocket --repo . --message "Add assets" --level DEBUG --log-file push-debug.log
```

### Logs

Every run writes its own log file, and the path is shown at the end of the run. Logs are
kept here by default:

| System | Folder |
| --- | --- |
| Windows | `%LOCALAPPDATA%\CommitRocket\Logs\` |
| macOS | `~/Library/Logs/CommitRocket/` |
| Linux | `~/.local/state/commitrocket/` (or `$XDG_STATE_HOME/commitrocket/`) |

Files are named `commitrocket-YYYYMMDD-HHMMSS.log`. Use `--level DEBUG` to also record
every Git command and the push output, which helps when a push fails. Old logs are not
deleted automatically.

### Batch types

Files are always taken in alphabetical order. For files A=60, B=50, C=30, D=20 MiB with a
100 MiB limit:

| Type | How it picks | Batches |
| --- | --- | --- |
| `deterministic` (default) | Fills each batch, skipping a file that doesn't fit and trying later ones | A + C, then B + D |
| `sequential` | Strict order; a batch ends at the first file that doesn't fit | A, then B + C + D |
| `soft` | Strict order; keeps adding until the batch reaches or passes the limit, never above `--max-mib` in total | A + B, then C + D |

Files larger than the batch limit (but under the maximum) get a batch of their own.
Files over the maximum are skipped and listed at the end so you can decide what to do.

### Large files with Git LFS

Hosts like GitHub reject files over 100 MiB. With `--use-lfs`, CommitRocket stores those
files with Git LFS instead:

1. Installs git-lfs if it is missing (asks first, unless `--force`).
2. Routes each file over 100 MiB through LFS using a rule that only exists on your
   machine. Nothing extra is committed to your repository.
3. Pushes your files in batches as usual.
4. Removes the local LFS setup when it finishes, even if the run fails.

The large files are stored in LFS on the remote. Because no tracking rules are committed,
a fresh clone will show small pointer files for them until LFS tracking is set up there.

By default only files over 100 MiB use LFS. Lower the cut-off with `--lfs-threshold-mib`
(for example `50`), or use `0` to send every file through LFS. Take care with `0`: because
no tracking rules are committed, anyone cloning the repository will see small pointer
files in place of all your content, and LFS storage and bandwidth quotas on the host are
used up quickly. Git's own settings files (`.gitattributes`, `.gitignore`, `.lfsconfig`)
always stay as normal files. The threshold cannot be above 100, since larger files are
rejected by hosts.

To let clones receive the real files, add `--lfs-commit-rules`. CommitRocket then commits
one rule per file type (for example `*.mp4`) to `.gitattributes` as `<message> (LFS rules)`,
pushes it first, and your files follow as LFS pointers. Because rules are per type, every
file of that type is stored in LFS from then on, including small ones and future ones.
Files without an extension get an exact-path rule. `.gitattributes` must have no
uncommitted changes beforehand.

If a run fails after committing LFS files but before pushing them, the LFS hooks are left
installed so the files can still be uploaded. Run CommitRocket again to finish; avoid a
plain `git push` unless the hooks are still installed.

Each LFS file normally gets its own push. To upload several at once, raise
`--lfs-batch-mib` (for example `--lfs-batch-mib 500 --lfs-threads 4`).

The thread settings only change the repository's own Git configuration for the duration
of the run and are put back afterwards. Your global Git configuration is never touched.

If you run CommitRocket without `--use-lfs` and a file is over 100 MiB, it stops before
committing anything and tells you to use the flag.

### Interrupted or failed runs

If a run stops, whether it failed or you pressed Ctrl+C, just run the same command again.
CommitRocket picks up where it stopped:

- Commits that were made but not pushed are pushed first (they are listed in the plan, and
  the usual confirmation applies).
- Files left staged by the interrupted batch are recognised as its own and committed with
  their original message. Files you staged yourself still stop the run.
- Numbering continues after the interrupted batch.

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
