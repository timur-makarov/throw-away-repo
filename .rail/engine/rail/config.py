"""`.rail/config.toml`: the whole config surface, with defaults and type checks."""

import copy
import difflib
import os
import tomllib

from .util import RailError

REVIEW_COMMAND = (
    "claude -p --safe-mode --system-prompt-file .rail/engine/reviewer.md "
    "--tools Read,Grep,Glob,Bash,Edit,Write --allowedTools Bash,Edit,Write "
    "--disallowedTools 'Bash(git push *)' --output-format json "
    "--json-schema \"$(cat .rail/engine/review-v1.json)\""
)

DEFAULTS = {
    "base_branch": "main",
    "person_paths": [".rail/bin/**", ".rail/engine/**", ".rail/config.toml", ".claude/**", ".github/workflows/**"],
    "migration_paths": ["**/migrations/**"],
    "commands": {"setup": "", "verify": "", "provision": "", "timeout_secs": 900, "base_checks": True},
    "size": {"cap": 600, "exclude": []},
    "review": {"command": REVIEW_COMMAND, "model": "", "skip_paths": []},
    "retry": {"budget": 2, "cap": 5},
    "consult": {"command": "claude -p --safe-mode --tools Read,Grep,Glob", "model": ""},
    "claim": {"stale_minutes": 30, "save_minutes": 10},
    "worker": {"ladder": ["claude-sonnet-5-5:medium", "claude-sonnet-5-5:high", "claude-opus-5-5:medium"],
               "person_ladder": ["claude-opus-5-5:medium", "claude-opus-5-5:high"]},
    "sweep": {"after": 20, "every": 20},
    "map": {"depth": 1, "ignore": []},
    # A page named in the brief when its situation applies. The pages come with the seed config only: a project
    # whose config has no [guides] table gets no guide.
    "guides": {key: "" for key in ("start", "stuck", "findings", "conflict", "contract", "split", "setup")},
    "rules": [],
}

EFFORTS = ("low", "medium", "high", "xhigh", "max")
RULE_KEYS = {"id": str, "files": str, "forbid": list, "only_in": str, "allow": list, "fix": str, "why": str}


def _suggest(key, known):
    close = difflib.get_close_matches(key, list(known), n=1)
    return f" (did you mean '{close[0]}'?)" if close else ""


def _check(value, default, where):
    """Check a value against the default's type, recursing into tables. Returns the merged value."""
    if isinstance(default, dict):
        if not isinstance(value, dict):
            raise RailError(f"config: {where} must be a table")
        merged = copy.deepcopy(default)
        for key, item in value.items():
            if key not in default:
                raise RailError(f"config: unknown key '{where}.{key}'{_suggest(key, default)}")
            merged[key] = _check(item, default[key], f"{where}.{key}")
        return merged
    if isinstance(value, bool) != isinstance(default, bool) or not isinstance(value, type(default)):
        raise RailError(f"config: {where} must be {type(default).__name__}")
    if isinstance(default, list) and not all(isinstance(v, str) for v in value):
        raise RailError(f"config: {where} must be a list of strings")
    return value


def _check_rule(rule, n):
    if not isinstance(rule, dict):
        raise RailError(f"config: rules[{n}] must be a table")
    for key, value in rule.items():
        if key not in RULE_KEYS:
            raise RailError(f"config: unknown key 'rules[{n}].{key}'{_suggest(key, RULE_KEYS)}")
        if not isinstance(value, RULE_KEYS[key]):
            raise RailError(f"config: rules[{n}].{key} must be {RULE_KEYS[key].__name__}")
    if "id" not in rule:
        raise RailError(f"config: rules[{n}] needs an id")
    return rule


def _check_ladder(config):
    """Each rung of a worker ladder is model:effort."""
    for key in ("ladder", "person_ladder"):
        for n, rung in enumerate(config["worker"][key]):
            model, _, effort = rung.rpartition(":")
            if not model.strip() or effort not in EFFORTS:
                raise RailError(f"config: worker.{key}[{n}] must be model:effort, such as \"claude-sonnet-5-5:medium\","
                                f" with an effort of {', '.join(EFFORTS)}; got \"{rung}\"")


def load(root):
    path = os.path.join(root, ".rail", "config.toml")
    if not os.path.exists(path):
        raise RailError("no .rail/config.toml here: this is not a Rail project", code="NOT_A_PROJECT")
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise RailError(f"config: .rail/config.toml is not valid TOML: {e}")
    packs_dir = os.path.join(root, ".rail", "packs")
    config = copy.deepcopy(DEFAULTS)
    for key, value in raw.items():
        if key == "rules":
            if not isinstance(value, list):
                raise RailError("config: rules must be an array of tables ([[rules]])")
            config["rules"] = [_check_rule(r, n) for n, r in enumerate(value)]
        elif key in DEFAULTS:
            config[key] = _check(value, DEFAULTS[key], key)
        elif isinstance(value, dict) and os.path.isdir(os.path.join(packs_dir, key)):
            config[key] = value  # a pack's own section; the pack reads it
        else:
            raise RailError(f"config: unknown key '{key}'{_suggest(key, DEFAULTS)}")
    _check_ladder(config)
    return config
