# Architecture

This document records the design as implemented.

## Layers

The command-line interface is a thin wrapper: it parses and validates options, builds
the `Console` and calls `core/runner`. The `Console` is created in `cli/execute.py` and
passed down, so the logic is usable without a global.

```
src/commitrocket/
  __init__.py       __version__
  __main__.py       python -m commitrocket
  cli/              command-line interface
    entry.py        main(): dispatches `commitrocket doctor` or a normal run
    parser.py       argparse definition of every option
    validate.py     option checks and the effective --max-mib
    execute.py      run_main(): config, logging, run, report, notifications
    doctor.py       doctor_main(): argparse and output for `commitrocket doctor`
  core/             the batching logic
    runner/         the run itself
      flow.py       run(): preflight, confirmation and the commit/push sequence
      batches.py    process_batches: the batch -> commit -> push loop
      resume.py     resume state, resumed commits, committed LFS rules
      setup.py      LFS planning, local git config, LFS session set-up and release
      dry_run.py    --dry-run planning
      helpers.py    own_output_files, push_target
    batching.py     select_batch / plan_batches / estimate_batch_count
    filters.py      include / exclude via pathspec (gitignore-style)
    options.py      RunOptions
    template.py     commit message templates and the attribution line
    verify.py       post-push and LFS pointer checks
    eta.py          EtaEstimator, format_duration
  git/              everything that talks to git
    git.py          run_git, pending/staged helpers, PushTarget, LocalConfig
    lfs.py          LFS candidates, git-lfs install, LfsSession
    push.py         streams `git push --progress`, retries
    journal.py      the resume journal
  io/               what the user sees and what a run writes
    ui.py           Rich progress, panels and tables
    logs.py         per-run log file and redaction
    report.py       RunReport (the --report JSON)
    notify.py       desktop and webhook notifications
    scripts/        toast.ps1, notification.applescript
  support/          shared helpers
    config.py       commitrocket.toml / [tool.commitrocket] -> option defaults
    doctor.py       the checks behind `commitrocket doctor`
    errors.py       CommitRocketError, GitError, PushError
    security.py     redaction and input validation
```

`git/` depends only on `support/`, and `core/` builds on `git/` and `support/`. `io/`
renders what `core/` and `cli/` produce. Only `cli/` calls the runner, and
`support/doctor.py` is the one support module that looks across the others, because
it checks them all.

## Imports and start-up

Imports are lazy: a module imports what it needs inside the function that uses it. A
name that a class body, a default argument or a module constant needs when the module
loads (a base class, a compiled regular expression, a dataclass field default, `MIB`)
stays at the top of its module. This keeps `import commitrocket` cheap and means a
command pays only for the code it runs: `commitrocket --version` loads neither `rich`
nor `pathspec`, and a `--no-push` run never loads the push code.

Settings that are data rather than logic live in files read on first use: the
notification scripts in `io/scripts/`.

## Tests

`tests/unit/` mirrors this tree (`cli/`, `core/`, `core/runner/`, `git/`, `io/`,
`support/`); `tests/integration/` runs the real CLI against a local bare repository.
See [development.md](development.md) for the markers and how to run them.

Exit codes: `0` success, `1` error or cancelled, `2` bad repo path or deferred files
remain, `130` interrupted.

## LFS flow (`--use-lfs`)

1. Pending files above `--lfs-threshold-mib` (default and maximum 100, `HOST_LIMIT_MIB`)
   and within `--max-mib` are the LFS candidates. Without `--use-lfs`, any file above the
   100 MiB host limit aborts the run (exit 2) before committing; with it and no
   candidates, LFS is skipped. A threshold of 0 selects every non-empty file.
2. `ensure_git_lfs` installs git-lfs via winget / brew / apt-get after confirmation.
3. `LfsSession.enable` runs `git lfs install --local` and appends one quoted, glob-escaped
   rule per file to `.git/info/attributes` (resolved with `rev-parse --git-path`). With a
   threshold of 0 it writes a single `*` rule plus unset rules for `.gitattributes`,
   `.gitignore` and `.lfsconfig` (`all_files_rules`) instead. Git
   applies it at `git add`; it is never committed, so no extra commits or pushes.
4. `LfsSession.close`, called from `finally` (so also on error or Ctrl+C), restores the
   original attributes file and runs `git lfs uninstall --local`.

## Dry run, retries, resume and verification

- **`--dry-run`**: `run` (`core/runner/flow.py`) does all read-only preflight (including resume detection
  and the over-100 MiB checks), then `core/runner/dry_run.py` simulates the real selection
  loop (`batching.plan_batches`) and `ui.print_dry_run` shows it. It returns 0 before any prompt, LFS install, config
  change, journal write or commit.
- **`--retries`**: `push.push_with_retries` wraps `push_with_progress`. A failed push
  raises `PushError` whose `retryable` flag is false when the output matches
  `NON_RETRYABLE_MARKERS` (host rejections, auth). Otherwise it waits 5 s, 15 s, 45 s...
  The same retry count applies to the post-push `ls-remote`.
- **Resume**: `journal.Journal` (`.git/commitrocket-journal.jsonl`, so never tracked) is an
  append-only event log: `run` (version, every run parameter, branch, target, starting
  HEAD), `staged` (before `git add`), `committed`, `pushed`, `resumed` and
  `interrupted`/`failed`. `Journal.state()` replays it and ignores a line cut short by a
  crash. `cli.run_params` collects the parameters (everything except `NOT_RUN_PARAMS`) into
  `RunOptions.params`. In `runner.run`, a journal whose params equal the current ones
  continues the run (plain re-run or `--resume`); different params replace it with a new
  run. `--resume` (`cli.apply_resume`) loads the stored params into the parsed arguments
  and errors on explicitly passed values that differ; `runner.check_resume` verifies
  branch, target and that the last recorded commit is still in HEAD's history. Staged files
  that are a subset of the in-flight batch are committed with its message and number;
  other staged files abort. Unpushed commits (after the >100 MiB stuck-commit check) are
  pushed before new batches, and numbering continues from the last committed number. The
  journal is deleted when a run finishes; `--dry-run` never writes it.
- **`--post-buffer-mib`**: sets `http.postBuffer` through `LocalConfig` for HTTP(S)
  remotes only (checked with `git remote get-url`), restored afterwards.
- **Verification**: `verify.verify_remote_head` compares `git ls-remote <remote> <ref>`
  with local HEAD after every push (remote and ref come from `branch.<name>.remote/merge`).
  `verify.find_non_pointers` checks committed LFS files by object size and content
  (`cat-file --batch-check` / `--batch`) before pushing. It replaces a
  `git lfs push --dry-run` check, which only lists local objects and cannot tell what the
  server already has.

## Options, config, filters, templates, targets, doctor

- **`RunOptions`** (`core/options.py`) carries every setting from `cli/execute.py` to `run`.
- **Config** (`support/config.py`): `cli/execute.py::run_main` locates the file with a small pre-parser
  (`--repo`, `--config`), `find_config` reads `commitrocket.toml` or
  `[tool.commitrocket]` (via `tomllib`), and `apply_config` validates each value against
  the argparse action (type, choices, flag, append list) and installs it with
  `parser.set_defaults`, so the command line wins. `--include`/`--exclude` are `append`
  actions, so command-line values are added to the config's lists.
- **Filters** (`core/filters.py`): `FileFilter` uses `pathspec` (`gitwildmatch`, i.e.
  `.gitignore` semantics). Include narrows, exclude wins; `.commitrocketignore` and
  `--*-from` files are read with `read_patterns`. `list_pending` in `core/runner/flow.py` applies the filter
  everywhere pending files are listed.
- **Templates** (`core/template.py`): `str.format` with fixed fields; `validate_template`
  renders sample values at startup so bad templates fail before any work.
- **Push target** (`git/git.py`: `PushTarget` / `resolve_target`): explicit `--remote/--branch`,
  else `branch.<name>.remote/merge`, else the local branch name. Pushes use
  `git push <remote> HEAD:refs/heads/<branch>`. "Unpushed" means
  `refs/remotes/<remote>/<branch>..HEAD`, or `HEAD --not --remotes=<remote>` when that
  branch was never pushed.
- **`--no-push`**: skips push and verification; rejected together with `--use-lfs`.
- **`--lfs-commit-rules`** (default on with `--use-lfs`; `--no-lfs-commit-rules` turns it off): `LfsSession.write_committed_rules` appends one rule per
  extension (`committed_rule_lines`; exact path for extension-less or odd names) to
  `.gitattributes` after checking it is clean. The runner (`core/runner/resume.py::commit_lfs_rules`) commits it as
  `<message> (LFS rules)` and pushes it before the first batch. Local-only rules in
  `.git/info/attributes` are not used in this mode; only the hooks are installed.
- **LFS hook safety**: `verify.unpushed_has_lfs_pointers` scans unpushed blobs for LFS
  pointers. If any exist, resume installs the hooks before pushing, and a failed run keeps
  them installed (`LfsSession.close(uninstall_hooks=False)`) so a later push still uploads
  the data.
- **Doctor** (`support/doctor.py`): `collect_checks` returns `(status, name, detail)` rows
  (pass/warn/fail/skip) and `run_doctor` prints them; exit 1 if any failed. Network checks
  are `git ls-remote` and `git push --dry-run`, skipped with `--offline`. `cli/entry.py::main`
  dispatches `commitrocket doctor ...` before normal argument parsing, so existing
  invocations are unchanged.

## Report and notifications

`io/report.py::RunReport` is created in `cli/execute.py::run_main` and filled by `run`: it sets
`status` (`success`, `completed_with_deferred_files`, `dry_run`, `cancelled`, `aborted`,
`interrupted`, `failed`) at every exit path, records each batch (commit SHA, message,
sizes, `pushed`, `verified`) as it happens, and holds the deferred files, resume counts and
LFS details. `RunReport.write` writes JSON via a temporary file and `os.replace`, so a
reader never sees a half-written report. The settings come from `asdict(RunOptions)`;
the webhook URL is deliberately not part of `RunOptions`, so it can't leak into a report.

`run_main` calls `finish`, writes the report and then `notify.send_notifications`
(skipped for `--dry-run`), all before logging is closed. Desktop notifications use only
built-in tools and pass the text through environment variables (`CR_TITLE`, `CR_BODY`) to
avoid quoting problems: Windows PowerShell's `Windows.UI.Notifications` toast (using
PowerShell's own AppUserModelID, which Windows already trusts), `osascript` on macOS,
`notify-send` on Linux, then the terminal bell. The Windows and macOS scripts are files in
`io/scripts/` (`toast.ps1`, `notification.applescript`), read only when a notification is sent. The webhook is a stdlib `urllib` POST
restricted to http(s) URLs with a 10 s timeout. Delivery errors are logged and printed,
never raised.

## Security hardening

Findings from the security review and what addresses them (`support/security.py` holds the helpers):

- **Literal file names**: `run_git` sets `GIT_LITERAL_PATHSPECS=1`, so a name such as
  `[ab].txt` stages only that file instead of also matching `a.txt` and `b.txt`.
- **No option injection**: `--remote` / `--branch` (and values from config or the
  upstream) are rejected if empty, starting with `-`, or containing spaces or control
  characters (`validate_ref_part`, checked in `cli/validate.py` and `git/git.py::resolve_target`),
  and `--` precedes the remote in `push`, `ls-remote` and `remote get-url`.
- **Untrusted repository config**: `support/config.py::apply_config` ignores `SENSITIVE_KEYS`
  (`force`, `remote`, `branch`, `report`, `log_file`, `notify_webhook`, `include_from`,
  `exclude_from`) unless the file was passed with `--config`. The ignored names are
  printed and logged.
- **Credentials**: `redact()` hides `user:password@` in URLs. It is applied by the log
  formatter (so also to tracebacks), to git and push error messages, to the push output
  shown on the console, and to the report's `error` field.
- **Private files**: log and report files are restricted to the owner (`0600`, best effort
  on Windows).
- **Rule injection**: `git/lfs.py::attribute_line` refuses file names with control characters, so
  a newline cannot add attribute lines.
- **Report temp file**: `RunReport.write` uses `tempfile.mkstemp` (random name, created
  exclusively) in the target folder, then `os.replace`.
- **Rich markup**: file names, commit text, remote output and error messages are shown as
  `Text` or passed through `escape()`, so brackets such as `[/x]` neither crash the display
  nor disappear.

## Logging

`io/logs.py::setup_logging` (called from `cli/execute.py` and `cli/doctor.py`) attaches one `FileHandler` to the
`commitrocket` logger, with `propagate = False` so nothing reaches the console, which is
Rich's job. The file is `commitrocket-<timestamp>.log` in `default_log_dir()` (per OS) or
`--log-file`. If the file can't be opened the run continues without logging. Modules use
`logging.getLogger(__name__)`. INFO records the run, each batch and its outcome; DEBUG adds
file lists, every git command (`run_git`, output truncated to 2000 chars) and the
push output (progress lines are thinned to one per phase change plus the final one). The
log path is printed after the run on every exit path.

## ETA

`core/eta.py::EtaEstimator` (not Rich's `TimeRemainingColumn`) computes the ETA as remaining bytes
divided by the run's average speed: bytes completed, including the part of the current
batch already uploaded, over the time since the first batch started. It reports nothing
for the first 5 seconds. The estimator is attached to the overall task as a task field,
and the progress column built in `io/ui.py::make_progress` calls it on every Rich refresh, so the countdown ticks without needing
progress events. The push row has no estimator and shows no ETA.

## Batch types

`batching.select_batch(..., batch_type)`: `deterministic` is the original algorithm (a file
above the limit goes first and alone, otherwise first-fit that skips misfits).
`sequential` and `soft` share `_select_in_order`, which walks eligible files in order and
stops at the first that doesn't fit; `soft` instead stops once the total reaches the limit
or the next file would pass `--max-mib`. A first file above the limit always travels alone
(or with consecutive LFS files up to `--lfs-batch-mib`). Files above `--max-mib` are
deferred in every mode, and `estimate_batch_count` uses the same rules.

## Threads and LFS grouping

`--compression-threads` and `--lfs-threads` map to `pack.threads` and
`lfs.concurrenttransfers`. `git.LocalConfig` writes them with `git config --local`,
remembers any previous local value, and restores or unsets it in `finally`. The global
config is never read for writing. `select_batch` groups LFS files up to
`--lfs-batch-mib` (default `--limit-mib`, which means one file per push unless raised) so
git-lfs has several files to upload concurrently. A group always has at least one file.

## Stuck-commit check

At startup, `find_large_unpushed_blobs` inspects `@{upstream}..HEAD`
(`rev-list --objects` piped to `cat-file --batch-check`). If any blob is over 100 MiB the
run exits 2 without changing anything and prints `git reset --mixed <upstream>`.
LFS pointer blobs are tiny, so commits already converted to LFS pass.

## Development

See [development.md](development.md) for setup, test markers, pre-commit, the GitHub
workflows and the release process.
