"""Claude Code hooks (plan, section 15). They stay tool-neutral: stdin JSON in, text out, and they never fail a session."""

import json
import os
import sys

from .project import Project
from .util import RailError


def _input():
    try:
        data = json.loads(sys.stdin.read() or "{}")
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def session_start():
    """After a start or a compaction: put .rail/bin on PATH, and print a snapshot of this session's ticket."""
    from .cli import load
    from .state import OPEN

    data = _input()
    try:
        project = Project(data.get("cwd") or os.getcwd())
    except RailError:
        return 0  # not a Rail project
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if env_file:
        with open(env_file, "a") as f:
            f.write(f'export PATH="{os.path.join(project.root, ".rail", "bin")}:$PATH"\n')
    project.session = data.get("session_id") or project.session
    lines = ["This repository runs on Rail. The loop: rail next --json, do action.brief, then rail advance --json."]
    tickets, facts = load(project)
    mine = [f for f in facts.values() if f.state in OPEN and f.claimed and not f.claimed_elsewhere]
    for f in mine:
        lines += [
            "", f"Your ticket {f.id}: {f.ticket.title} ({f.tier}, {f.state}), in {f.cwd or 'no worktree here yet'}.",
            "Done Contract:", f.ticket.sections.get("Done Contract", ""),
            f"scope_paths: {', '.join(f.ticket.scope)}",
        ]
    others = [f.id for f in facts.values() if f.state in OPEN and f.claimed_elsewhere]
    if not mine:
        lines.append("No ticket is claimed by this session. Run rail next --json.")
    if others:
        lines.append(f"Claimed by other sessions: {', '.join(others)}. Take one over only when its session has ended:"
                     " rail next --ticket NN.")
    print("\n".join(lines))
    return 0


def guard():
    """PreToolUse on Bash: deny what a permission rule can't express (plan, section 15)."""
    from . import gitx, guard as rules

    data = _input()
    command = (data.get("tool_input") or {}).get("command")
    if data.get("tool_name", "Bash") != "Bash" or not command:
        return 0
    cwd = data.get("cwd") or os.getcwd()
    try:
        project = Project(cwd)
    except RailError:
        return 0  # not a Rail project
    branch = gitx.git(["rev-parse", "--abbrev-ref", "HEAD"], cwd, check=False).stdout.strip()
    top = gitx.git(["rev-parse", "--show-toplevel"], cwd, check=False).stdout.strip() or project.root
    reason, decision = rules.deny(command, project.base, branch), "deny"
    if not reason:
        reason, decision = rules.ask(command, cwd, top), "ask"
    if reason:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                                 "permissionDecisionReason": f"Rail guard: {reason}."}}))
    return 0


NEEDS = {
    "APPROVE_CONTRACT": "approve the contract", "APPROVE_AMEND": "approve the amended contract",
    "MERGE_BY_PERSON": "merge", "RETRY_CAP": "stuck at the retry budget", "STUCK_REVIEW": "the review timed out",
    "FINDING_UPHELD": "decide a finding", "HOLD": "held", "MERGE_FAILED": "the merge failed",
}


def terminal_sequence(message, term_program=None, term=None):
    """A desktop notification for the terminal in use (plan, section 15), or a bell."""
    term_program = term_program if term_program is not None else os.environ.get("TERM_PROGRAM", "")
    term = term if term is not None else os.environ.get("TERM", "")
    message = message.replace("\x07", "").replace("\x1b", "")
    if term_program in ("iTerm.app", "WezTerm"):
        return f"\x1b]9;{message}\x07"
    if term_program in ("ghostty", "WarpTerminal"):
        return f"\x1b]777;notify;Rail;{message}\x07"
    if "kitty" in term:
        return f"\x1b]99;;{message}\x1b\\"
    return "\x07"


def notify():
    """Notification (idle_prompt): announce each new wait for a person once, and stay silent otherwise."""
    from .cli import load
    from .table import first_match

    data = _input()
    try:
        project = Project(data.get("cwd") or os.getcwd())
    except RailError:
        return 0
    tickets, facts = load(project)
    waits = {}
    for f in facts.values():
        code, owner, _ = first_match(f)
        if owner == "human":
            waits[f.id] = (code, f.pr["html_url"] if f.pr else None)
    announced = json.loads(project.cache_read("notify", "announced") or "{}")
    new = [(nn, code, url) for nn, (code, url) in waits.items() if announced.get(nn) != code]
    project.cache_write("notify", "announced", json.dumps({nn: code for nn, (code, _) in waits.items()}))
    if not new:
        return 0
    message = " · ".join(f"{nn}: {NEEDS.get(code, code.lower().replace('_', ' '))}" for nn, code, _ in new)
    link = next((url for _, _, url in new if url), None)
    print(json.dumps({"terminalSequence": terminal_sequence(f"Rail: {message}" + (f" {link}" if link else ""))}))
    return 0


HOOKS = {"session-start": session_start, "guard": guard, "notify": notify}


def run(name):
    try:
        return HOOKS[name]()
    except Exception as e:  # a hook must never stop the session
        print(f"rail hook {name}: {e}", file=sys.stderr)
        return 0
