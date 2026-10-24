import tomllib
from pathlib import Path

from commitrocket.errors import CommitRocketError

CONFIG_NAME = "commitrocket.toml"
PYPROJECT_NAME = "pyproject.toml"

# Options that make no sense in a config file.
NOT_CONFIGURABLE = {"config", "repo", "help", "version"}

# Options an untrusted (repository) config file must not set: they can skip the
# confirmation, push to another remote, write files, send data to a URL or read
# files. They work in a file passed explicitly with --config.
SENSITIVE_KEYS = {
    "force",
    "remote",
    "branch",
    "report",
    "log_file",
    "notify_webhook",
    "include_from",
    "exclude_from",
}


class ConfigError(CommitRocketError):
    """The config file could not be read or holds an invalid value."""


def find_config(repo, explicit=None):
    """Return (path, values) from the config file, or (None, {}) if there is none.

    Looked up in the repository folder: commitrocket.toml first, then the
    [tool.commitrocket] table of pyproject.toml. --config overrides the lookup.
    """
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise ConfigError(f"Config file not found: {path}")
        return path, _load(path)

    folder = Path(repo).expanduser()
    plain = folder / CONFIG_NAME
    if plain.is_file():
        return plain, _load(plain)

    pyproject = folder / PYPROJECT_NAME
    if pyproject.is_file():
        values = _load(pyproject)
        if values:
            return pyproject, values

    return None, {}


def _load(path):
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"Cannot read config file {path}: {exc}") from exc

    if path.name == PYPROJECT_NAME:
        data = data.get("tool", {}).get("commitrocket", {})
    return data


def apply_config(parser, values, source, trusted=False):
    """Use config values as the parser's defaults, so the command line wins.

    A config file found in the repository is untrusted: anyone who can change the
    repository can change it. Unless trusted (the user named it with --config),
    settings that can skip the confirmation, push elsewhere, write files or contact
    other servers are ignored. Returns the names of the ignored settings.
    """
    actions = {action.dest: action for action in parser._actions}
    defaults = {}
    ignored = []

    for key, value in values.items():
        dest = key.replace("-", "_")
        action = actions.get(dest)
        if action is None or dest in NOT_CONFIGURABLE:
            raise ConfigError(f"{source}: unknown option '{key}'")
        coerced = _coerce(action, key, value, source)
        if dest in SENSITIVE_KEYS and not trusted:
            ignored.append(key)
        else:
            defaults[dest] = coerced

    parser.set_defaults(**defaults)
    return ignored


def _coerce(action, key, value, source):
    where = f"{source}: '{key}'"

    if action.nargs == 0:  # a flag such as --force
        if not isinstance(value, bool):
            raise ConfigError(f"{where} must be true or false")
        return value

    if _is_append(action):
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ConfigError(f"{where} must be a list of strings")
        return value

    if isinstance(value, (bool, list, dict)):
        raise ConfigError(f"{where} has the wrong type")

    if action.type is not None:
        try:
            value = action.type(value)
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"{where} is invalid: {exc}") from exc

    if action.choices and value not in action.choices:
        choices = ", ".join(map(str, action.choices))
        raise ConfigError(f"{where} must be one of: {choices}")
    return value


def _is_append(action):
    return type(action).__name__ == "_AppendAction"
