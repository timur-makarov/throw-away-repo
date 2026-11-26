"""Flaky checks: a `verify` or `Check:` command that both failed and passed on the same code.

At ship a failed command is run once more at once; when that passes, a `flake` event says so, and the step still
fails. A command that failed on a patch where another ship passed it is a flake too, read from the step events.
"""

import re

TOLD = ("This command failed, then passed when it was run again on the same code. Find why it is not deterministic;"
        " don't add a retry, a sleep or a skip.")
STEPS = ("verify", "checks")
_FAILED = re.compile(r": (?:exit \d+|timeout|command not found|found but could not be run)$")


def _key(e):
    """What names the command of a step event: a check's own line (its detail, less how it ended), or `verify`."""
    if e.get("step") != "checks":
        return e.get("step")
    return _FAILED.sub("", e.get("detail") or "")


def of(events):
    """The ticket's flakes, in order, each {step, command, patch_id}: every `flake` event, and every command whose
    step events on one patch hold both a pass and a counted failure with no `flake` event of its own (a ship that
    failed it and a later ship of the same code that passed it, or the other way round). A step that could not start
    and a verify that failed on a red base are neither."""
    found, told, results = [], set(), {}
    for e in events:
        if e.get("event") == "flake":
            key = e.get("command") if e.get("step") == "checks" else e.get("step")
            found.append({"step": e.get("step"), "command": e.get("command") or key, "patch_id": e.get("patch_id")})
            told.add((e.get("patch_id"), e.get("step"), key))
        elif e.get("event") == "step" and e.get("step") in STEPS and e.get("patch_id") and e.get("status") == "ran" \
                and e.get("counted", True):
            results.setdefault((e["patch_id"], e["step"], _key(e)), set()).add(e.get("result"))
    for (patch_id, step, key), seen in results.items():
        if {"pass", "fail"} <= seen and (patch_id, step, key) not in told:
            found.append({"step": step, "command": key, "patch_id": patch_id})
    return found


def runs(events):
    """{command: how many times ship ran it}, as `of` names commands."""
    counts = {}
    for e in events:
        if e.get("event") == "step" and e.get("step") in STEPS and e.get("patch_id") and e.get("status") == "ran":
            counts[_key(e)] = counts.get(_key(e), 0) + 1
    return counts


def name(flake):
    """The command as a later reader matches it: a check's line, or `verify`."""
    return flake["command"] if flake["step"] == "checks" else "verify"
