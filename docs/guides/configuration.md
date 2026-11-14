# Configuration

CommitRocket reads defaults from `commitrocket.toml`, or from a `[tool.commitrocket]` table
in `pyproject.toml`, in the repository folder. Use `--config FILE` to read a different
file. Precedence: command line, config file, built-in defaults. `include` and `exclude`
lists from the file and the command line are combined. A flag set to `true` in the file
cannot be switched off from the command line (except `lfs-commit-rules`, which has
`--no-lfs-commit-rules`).

## Where the file is found

Without `--config`, CommitRocket looks only in the repository folder (`--repo`, default the
current folder), not in parent folders:

1. `commitrocket.toml`, if it exists.
2. Otherwise the `[tool.commitrocket]` table of `pyproject.toml`, if the table has any
   settings.

Run `commitrocket doctor` to see which file is in use. CommitRocket also prints
`Using config: <path>` at the start of a run.

## Trusting a config file

A file found in the repository might belong to someone else (a cloned repository, a
downloaded folder), because anyone who can change the repository can change it. So a file
found this way **cannot** set options that skip the confirmation, push somewhere else,
write files or contact other servers:

`force`, `remote`, `branch`, `report`, `log-file`, `notify-webhook`, `include-from` and
`exclude-from`.

These settings are ignored, and CommitRocket prints and logs which ones. If you wrote the
file and trust it, name it yourself, which counts as trusting it:

```
commitrocket --config commitrocket.toml
```

Everything else (limits, batch type, filters, retries, `use-lfs`, `dry-run` and so on)
works from a found file as usual. All of these settings work as normal command-line
options too.

## Keys

Keys use the option names, with dashes or underscores: `limit-mib` for `--limit-mib`.
Unknown keys or invalid values stop the run with exit code 2 and a message naming the file
and the key. The options `repo`, `config`, `help` and `version` cannot be set in a file.

```toml
# commitrocket.toml
message = "Add videos"
message-template = "{message} #{n} ({files} files, {size:.0f} MiB)"
limit-mib = 50
batch-type = "sequential"
exclude = ["raw/", "*.tmp"]
use-lfs = true
retries = 5
```

The same settings in `pyproject.toml`:

```toml
[tool.commitrocket]
message = "Add videos"
limit-mib = 50
```

| Key | Type | Meaning |
|---|---|---|
| `message` | string | Base commit message |
| `message-template` | string | Message of each batch; placeholders `message`, `n`, `batch`, `files`, `size`, `first`, `date` |
| `no-attribution` | true / false | Do not append the CommitRocket attribution line |
| `number` | integer | Number of the first commit |
| `include`, `exclude` | list of strings | `.gitignore`-style patterns |
| `include-from`, `exclude-from` | list of strings | Files of patterns (only from a trusted file) |
| `limit-mib` | integer | Normal batch size in MiB |
| `max-mib` | integer | Largest single file in MiB |
| `batch-type` | string | `deterministic`, `sequential` or `soft` |
| `remote`, `branch` | string | Push target (only from a trusted file) |
| `no-push` | true / false | Commit but do not push |
| `retries` | integer | Push retries |
| `post-buffer-mib` | integer | Raise `http.postBuffer` for the run |
| `compression-threads` | integer | `pack.threads` for the run |
| `use-lfs` | true / false | Send big files through Git LFS |
| `lfs-threshold-mib` | integer | Size above which files go through LFS (0 to 100) |
| `lfs-commit-rules` | true / false | Commit LFS rules to `.gitattributes` (default `true`) |
| `lfs-threads` | integer | Concurrent LFS uploads |
| `lfs-batch-mib` | integer | Total size of LFS files pushed together |
| `dry-run` | true / false | Only show the plan |
| `force` | true / false | Skip the confirmation (only from a trusted file) |
| `report` | string | Path of the JSON report (only from a trusted file) |
| `notify` | true / false | Desktop notification at the end |
| `notify-webhook` | string | http(s) URL for the end-of-run summary (only from a trusted file) |
| `level` | string | `DEBUG`, `INFO`, `WARNING` or `ERROR` |
| `log-file` | string | Log file path (only from a trusted file) |

Types are checked: a flag must be `true` or `false`, the list keys must be lists of
strings, and a list or table is rejected where a single value is expected. The command line
limits apply too, for example `limit-mib` must be positive and `max-mib` at least `limit-mib`.
`--no-push` still cannot be combined with `use-lfs`. See the
[command line guide](cli.md) for what each option does.

## Ignore file

`.commitrocketignore` in the repository root lists extra patterns to leave out, one per
line in `.gitignore` syntax. They are always excluded, whether or not a config file exists.

## Environment variables

CommitRocket does not read any environment variables for its settings.
