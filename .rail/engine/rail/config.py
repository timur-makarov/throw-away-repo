"""`.rail/config.toml`: the whole config surface (plan, section 4), with defaults and type checks."""

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
    "auto_tiers": ["LOW", "MEDIUM"],
    "migration_paths": ["**/migrations/**"],
    "commands": {"setup": "", "verify": "", "timeout_secs": 900},
    "risk_paths": {
        "HIGH": [".rail/bin/**", ".rail/engine/**", ".rail/config.toml", ".claude/**", ".github/workflows/**"],
        "MEDIUM": [],
    },
    "size": {"LOW": 300, "MEDIUM": 600, "exclude": []},
    "review": {"command": REVIEW_COMMAND},
    "retry": {"budget": 2},
    "consult": {"command": "claude -p --safe-mode --tools Read,Grep,Glob"},
    "sweep": {"after": 20},
    "map": {"depth": 1, "ignore": []},
    "rules": [],
}

RULE_KEYS = {"id": str, "files": str, "forbid": list, "only_in": str, "allow": list, "fix": str, "why": str}
TIERS = ("LOW", "MEDIUM", "HIGH")


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
    if isinstance(value, bool) or not isinstance(value, type(default)):
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
    for tier in config["auto_tiers"]:
        if tier not in TIERS:
            raise RailError(f"config: auto_tiers holds '{tier}', which is not one of {', '.join(TIERS)}")
    return config
