# Command line guide

```
commitrocket --message <text> [options]
commitrocket doctor [options]
```

| Command | What it does |
|---|---|
| `commitrocket` | Split the pending changes into size-limited batches, commit each one and push it |
| `commitrocket doctor` | Check that Git, git-lfs, the repository, the remote and your settings are ready. Changes nothing |

Add `--help` for the options of either command. Run the command inside the repository, or
point at it with `--repo`.

## How a run works

1. CommitRocket looks at the files you have changed or added and not yet committed.
2. It packs them into batches no bigger than `--limit-mib`, using the rule chosen with
   `--batch-type`.
3. For each batch it stages the files, makes a commit and pushes it, then checks that the
   remote now has that commit.
4. Files bigger than `--max-mib` are left out and listed at the end. With `--use-lfs`, big
   files go through Git LFS instead of being left out.

A run asks for confirmation first. Use `--dry-run` to see the plan without changing
anything, and `--force` to skip the question.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Everything was processed |
| 1 | An error stopped the run, or you cancelled at the prompt |
| 2 | The run did not start, or files were left out: bad repository path, files over the host limit without `--use-lfs`, unpushed commits that the host would reject, or files above `--max-mib` |
| 130 | Interrupted with Ctrl+C. Run the same command again to resume |

`commitrocket doctor` exits 1 if any check failed and 0 otherwise.

## Options

### Repository and message

| Option | Default | What it does |
|---|---|---|
| `--repo PATH` | `.` | The Git repository to work in |
| `--config FILE` | none | Read settings from this TOML file instead of `commitrocket.toml` or `[tool.commitrocket]` in `pyproject.toml` |
| `--message TEXT` | none | Base commit message. Required here or in the config file |
| `--message-template TEXT` | `{message} #{n}` | The message of each batch. Placeholders: `message`, `n`, `batch`, `files`, `size`, `first`, `date` |
| `--no-attribution`, `--ignore-attribution` | off | Do not append the "Prepared and Committed By: CommitRocket" line to commit messages |
| `--number N` | 1 | Number of the first commit (`{n}` in the template) |

### Choosing files

All patterns use `.gitignore` syntax. Exclusion always wins over inclusion, and patterns in
`.commitrocketignore` are always excluded.

| Option | What it does |
|---|---|
| `--include GLOB` | Only handle files matching this pattern. Repeat for more |
| `--exclude GLOB` | Leave files matching this pattern alone. Repeat for more |
| `--include-from FILE` | Read `--include` patterns from a file, one per line (`#` starts a comment) |
| `--exclude-from FILE` | Read `--exclude` patterns from a file, one per line |

### Batches

| Option | Default | What it does |
|---|---|---|
| `--limit-mib N` | 100 | Normal batch size in MiB. Must be positive |
| `--max-mib N` | 3 x `--limit-mib` | Largest single file to handle, in MiB. Must be at least `--limit-mib`. Bigger files are left out |
| `--batch-type TYPE` | `deterministic` | How files are picked: `deterministic` packs first-fit and skips files that do not fit, `sequential` takes files strictly in order, `soft` takes files in order and may pass `--limit-mib` up to `--max-mib` |

### Pushing

| Option | Default | What it does |
|---|---|---|
| `--remote NAME` | the branch's upstream remote | Remote to push to |
| `--branch NAME` | the upstream branch, else the current branch name | Remote branch to push to |
| `--no-push` | off | Commit every batch but do not push. A later run pushes them. Cannot be combined with `--use-lfs` |
| `--retries N` | 3 | Retry a failed push this many times, waiting 5 s, 15 s, 45 s and so on. Rejections such as file-size limits are never retried |
| `--post-buffer-mib N` | none | Raise Git's `http.postBuffer` for this run (HTTP and HTTPS remotes only). Helps with "RPC failed" and HTTP 408/500 errors on large pushes |
| `--compression-threads N` | Git's default | Threads Git uses to compress objects (`pack.threads`; 0 means automatic) |

`--remote` and `--branch` may not be empty, start with `-`, or contain spaces or control
characters.

### Git LFS

| Option | Default | What it does |
|---|---|---|
| `--use-lfs` | off | Send big files through Git LFS for this run, installing git-lfs if needed and undoing the local setup afterwards |
| `--lfs-threshold-mib N` | 100 | With `--use-lfs`, files larger than this go through LFS. Between 0 and 100; 0 means every file |
| `--lfs-commit-rules` / `--no-lfs-commit-rules` | on | With `--use-lfs`, commit one LFS rule per file extension to `.gitattributes` so clones get real files. With `--no-lfs-commit-rules` the rules stay local to the run and clones contain LFS pointer files |
| `--lfs-threads N` | git-lfs default | Concurrent LFS uploads (`lfs.concurrenttransfers`). Must be positive |
| `--lfs-batch-mib N` | same as `--limit-mib` | Total size of LFS files pushed together, so they can upload at the same time |

### Safety

| Option | What it does |
|---|---|
| `--dry-run` | Show the batches and commit messages that would be made, without staging, committing or pushing anything |
| `--force` | Skip the confirmation prompt, and install git-lfs without asking |
| `--resume` | Continue the interrupted run in this repository with the settings it started with (see [Interrupted runs](#interrupted-runs)) |

### Output

| Option | Default | What it does |
|---|---|---|
| `--report FILE` | none | Write a JSON summary of the run. Also written when the run fails, is interrupted or is a dry run |
| `--notify` | off | Show a desktop notification when the run ends |
| `--notify-webhook URL` | none | Send a JSON summary to this http(s) URL when the run ends (Slack, Discord, Teams, ntfy or your own endpoint) |
| `--level LEVEL` | `INFO` | Log level written to the log file: `DEBUG`, `INFO`, `WARNING` or `ERROR`. `DEBUG` also records every git command and the push output |
| `--log-file FILE` | per-user log folder | Write the log here instead |

Notifications are not sent for a dry run.

## Config file

Every option above except `--repo`, `--config`, `--help` and `--version` can be set in
`commitrocket.toml` or in a `[tool.commitrocket]` table of `pyproject.toml`. Use the option
name, with dashes or underscores. Flags take `true` or `false`, and `include`, `exclude`,
`include-from` and `exclude-from` take lists. Options given on the command line win.

```toml
# commitrocket.toml
message = "Add photos"
limit-mib = 50
exclude = ["*.tmp", "cache/"]
use-lfs = true
```

A config file found inside the repository is untrusted, because anyone who can change the
repository can change it. It cannot set `force`, `remote`, `branch`, `report`, `log-file`,
`notify-webhook`, `include-from` or `exclude-from`: those are ignored, and CommitRocket
prints which ones. They work in a file you name yourself with `--config`.

## doctor

```
commitrocket doctor [--repo PATH] [--remote NAME] [--branch NAME] [--config FILE] [--offline]
```

It reports the Python, Git and git-lfs versions, the config file in use, whether the log
folder is writable, the repository, branch and push target, whether the remote is reachable
and a push would be accepted, staged files, unpushed commits and pending files. Each row is
`PASS`, `WARN`, `FAIL` or `SKIP`. `--offline` skips the two checks that contact the remote.

## File patterns

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

## Commit messages

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

### Attribution

Every commit [CommitRocket](https://pypi.org/project/commitrocket/) creates ends with an
attribution line, separated from the message by a blank line:

```
Prepared and Committed By: 🚀 CommitRocket (https://github.com/coldsofttech/CommitRocket)
```

It is added to batch commits, the LFS rules commit and resumed commits, and it is shown in
`--dry-run` output and the JSON report. It is never added twice to the same message. To
leave your messages exactly as written, pass `--no-attribution` (or `--ignore-attribution`),
or set `no-attribution = true` in the config file.

## Batch types

Files are always taken in alphabetical order. For files A=60, B=50, C=30, D=20 MiB with a
100 MiB limit:

| Type | How it picks | Batches |
| --- | --- | --- |
| `deterministic` (default) | Fills each batch, skipping a file that doesn't fit and trying later ones | A + C, then B + D |
| `sequential` | Strict order; a batch ends at the first file that doesn't fit | A, then B + C + D |
| `soft` | Strict order; keeps adding until the batch reaches or passes the limit, never above `--max-mib` in total | A + B, then C + D |

Files larger than the batch limit (but under the maximum) get a batch of their own.
Files over the maximum are skipped and listed at the end so you can decide what to do.

## Using Git LFS

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

So that checkouts and clones receive the real files, CommitRocket commits the LFS rules by default. It commits
one rule per file type (for example `*.mp4`) to `.gitattributes` as `<message> (LFS rules)`,
pushes it first, and your files follow as LFS pointers. Because rules are per type, every
file of that type is stored in LFS from then on, including small ones and future ones.
Files without an extension get an exact-path rule. `.gitattributes` must have no
uncommitted changes beforehand. Pass `--no-lfs-commit-rules` to skip this; videos then turn into
text pointer files after a pull, reset or clone.

If a run fails after committing LFS files but before pushing them, the LFS hooks are left
installed so the files can still be uploaded. Run CommitRocket again to finish; avoid a
plain `git push` unless the hooks are still installed.

Each LFS file normally gets its own push. To upload several at once, raise
`--lfs-batch-mib` (for example `--lfs-batch-mib 500 --lfs-threads 4`).

The thread settings only change the repository's own Git configuration for the duration
of the run and are put back afterwards. Your global Git configuration is never touched.

If you run CommitRocket without `--use-lfs` and a file is over 100 MiB, it stops before
committing anything and tells you to use the flag.

## Report and notifications

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

## Logs

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


## Interrupted runs

If a run stops, whether from an error, a failed push or Ctrl+C, CommitRocket remembers it in
a small file inside `.git` (`commitrocket-journal.jsonl`), so it is never committed. It is
deleted when a run finishes.

To carry on, either run the same command again or use `--resume`:

```
commitrocket --repo . --resume
```

- `--resume` reuses the settings the interrupted run started with, so you don't type them
  again. Options that only affect how a run is shown or written (`--force`, `--dry-run`,
  `--report`, `--log-file`, `--level`, `--notify`, `--notify-webhook`) are not remembered and
  work as usual.
- You may repeat a setting with `--resume`, but only with the same value. A different value
  is an error. To change settings, run without `--resume`: a new run starts.
- Running the same command again without `--resume` also continues the run when the
  settings are identical. With different settings it starts a new run and replaces the old
  record.
- `--resume` stops with a clear message if there is no interrupted run, if the record is
  damaged or from another version, if you are on a different branch or push target, or if
  the repository changed (a commit the run made is no longer in the branch's history).

When continuing, CommitRocket recognises the files it left staged, commits them with their
original message, pushes any commits that are still waiting, and carries on numbering from
there. Files you staged yourself still stop the run.

## Examples

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
commitrocket --repo . --message "Videos" --use-lfs
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

**Check the setup without contacting the remote**
```
commitrocket doctor --repo path/to/repo --offline
```
