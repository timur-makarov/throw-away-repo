"""Claude Code hooks. They stay tool-neutral: stdin JSON in, text out, and they never fail a session."""

import json
import os
import re
import sys
import time

from .project import Project
from .util import RailError, cloud


def _input():
    try:
        data = json.loads(sys.stdin.read() or "{}")
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


# A hook written into the machine's own Claude Code settings by `rail provision` runs as `rail hook NAME --machine`.
# It is there for the sessions that load no repository's hooks: a cloud session that starts above several
# repositories, and a thread in a project.
MACHINE = False


def _projects(data):
    """(the directory the session stands in, whether that is inside a Rail project, the projects the hook is about).

    The project is the one the session stands in. A session that starts above several repositories stands in none:
    then it is every Rail project directly below. Where a repository's own hooks ran in this session, a machine
    hook leaves that project to them.
    """
    cwd = data.get("cwd") or os.getcwd()
    session = data.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID")
    found, inside = [], True
    try:
        found = [Project(cwd)]
    except RailError:
        inside = False
        try:
            names = sorted(os.listdir(cwd))
        except OSError:
            names = []
        for name in names:
            if os.path.exists(os.path.join(cwd, name, ".rail", "config.toml")):
                try:
                    found.append(Project(os.path.join(cwd, name)))
                except RailError:
                    pass
    for project in found:
        project.session = session or project.session
    if MACHINE:
        found = [p for p in found if not (p.session and p.cache_read("hooks", p.session))]
    return cwd, inside, found


def session_start():
    """After a start or a compaction: put .rail/bin on PATH, and print a snapshot of this session's ticket."""
    from .cli import load
    from .state import OPEN

    data = _input()
    cwd, inside, projects = _projects(data)
    if MACHINE and inside:
        return 0  # the repository's own hook says it, where that hook runs
    for project in projects:
        if inside:
            env_file = os.environ.get("CLAUDE_ENV_FILE")
            if env_file:
                with open(env_file, "a") as f:
                    f.write(f'export PATH="{os.path.join(project.root, ".rail", "bin")}:$PATH"\n')
            if project.session:
                project.cache_write("hooks", project.session, "1")  # doctor reads it: Rail's hooks run in this session
            lines = ["This repository runs on Rail. The loop: rail next --json, do action.brief, then rail advance --json."]
        else:
            where = os.path.relpath(project.root, cwd)
            lines = [f"The repository {where}/ runs on Rail. Run rail from inside it. The loop: rail next --json, do"
                     " action.brief, then rail advance --json."]
        tickets, facts = load(project)
        mine = [f for f in facts.values() if f.state in OPEN and f.claimed and not f.claimed_elsewhere]
        for f in mine:
            lines += [
                "", f"Your ticket {f.id}: {f.ticket.title} ({f.tier}, {f.state}), in {f.cwd or 'no worktree here yet'}.",
                "Done Contract:", f.ticket.sections.get("Done Contract", ""),
                f"scope_paths: {', '.join(f.ticket.scope)}",
            ]
        others = [f.id for f in facts.values() if f.held]
        if not mine:
            lines.append("No ticket is claimed by this session. Run rail next --json.")
        if others:
            lines.append(f"Other sessions are at work on: {', '.join(others)}. rail next resumes one by itself once it has"
                         " been quiet long enough; rail next --ticket NN takes it over now.")
        print("\n".join(lines))
    return 0


def _named(command, cwd, known, session):
    """The Rail projects a command names by a folder, besides the known ones: a session may stand more than one
    level above its repositories, and `cd work/repo && git push -f` is still about that repository."""
    found = []
    for word in sorted(set(re.findall(r"[^\s;&|()<>'\"`$=]+", command))):
        path = os.path.join(cwd, os.path.expanduser(word))
        if not os.path.isdir(path):
            continue
        try:
            project = Project(path)
        except RailError:
            continue
        project.session = session or project.session
        if any(project.root == other.root for other in known + found):
            continue
        if not (project.session and project.cache_read("hooks", project.session)):  # its own hooks aren't on the job
            found.append(project)
    return found


def guard():
    """PreToolUse on Bash: deny what a permission rule can't express."""
    from . import gitx, guard as rules
    from .forge import github_repo

    data = _input()
    command = (data.get("tool_input") or {}).get("command")
    if data.get("tool_name", "Bash") != "Bash" or not command:
        return 0
    cwd, inside, projects = _projects(data)
    if MACHINE and not inside:
        projects += _named(command, cwd, projects, data.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID"))
    if not projects:
        return 0  # no Rail project here, or its own hooks are on the job
    branch = gitx.git(["rev-parse", "--abbrev-ref", "HEAD"], cwd, check=False).stdout.strip() if inside else ""
    top = (gitx.git(["rev-parse", "--show-toplevel"], cwd, check=False).stdout.strip() if inside else "") or cwd
    probe = ["rev-parse", "--path-format=absolute", "--git-common-dir", "--abbrev-ref", "HEAD"]
    in_cloud = cloud()
    reason, decision = None, "deny"
    for project in projects:
        ours = gitx.git(probe[:3], project.root, check=False).stdout.strip()

        def locate(directory, ours=ours):
            """(this project's repository?, the branch checked out there), or None for a directory that doesn't
            exist: the shell stays where it was when a cd fails."""
            if not os.path.isdir(directory):
                return None
            found = gitx.git(probe, directory, check=False)
            if found.returncode != 0:
                # Another repository with no commit yet still answers the first line; no repository answers nothing.
                return (found.stdout.strip().splitlines()[:1] == [ours], "")
            common, _, there = found.stdout.strip().partition("\n")
            return (common == ours, there.strip())

        repo = github_repo(project) if project.remote else None
        # Where the guard can't follow the command, it is judged on a branch of this project's. From a folder above
        # the repositories that is the branch the project's own checkout is on.
        at = branch if inside else gitx.git(["rev-parse", "--abbrev-ref", "HEAD"], project.root, check=False).stdout.strip()
        reason = rules.deny(command, project.base, at, cwd=cwd, locate=locate, repo=repo, cloud=in_cloud)
        if reason:
            break
    if not reason:
        reason, decision = rules.ask(command, cwd, top, cloud=in_cloud), "ask"
    if reason:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                                 "permissionDecisionReason": f"Rail guard: {reason}."}}))
    return 0


def _save(via, data=None):
    """Save this session's work in flight, in every project the hook is about. Returns the notes for the agent,
    such as a takeover."""
    from .cli import save_all

    cwd, inside, projects = _projects(data if data is not None else _input())
    notes = []
    for project in projects:
        try:
            project.sync()
            notes += save_all(project, via)[1]
        except Exception as e:  # the hook goes on, and the agent hears of it: this work is not saved
            notes.append(f"Rail could not save the work in flight in {project.root}: {e}\nRun rail save there to see"
                         " why. Until it passes, a machine that goes away takes the unsaved work with it.")
    return notes


def stop():
    """Stop: the agent's turn ended. Save what it has, so a machine that goes away loses nothing of this turn. It
    never blocks the stop and says nothing."""
    _save("stop")
    return 0


def pulse():
    """PostToolUse, at most every few minutes (the hook's own command checks the stamp first): save the work in
    flight while the agent works, which also shows other sessions the ticket is alive. The stamp is the session's,
    in the home folder: the hook's command finds it there from any project folder, a ticket's worktree included."""
    data = _input()
    folder = os.path.join(os.path.expanduser("~"), ".cache", "rail", "pulse")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, os.environ.get("CLAUDE_CODE_SESSION_ID") or "any"), "w") as f:
        f.write("1")
    for name in os.listdir(folder):  # sessions that ended long ago
        path = os.path.join(folder, name)
        if time.time() - os.path.getmtime(path) > 86400:
            os.remove(path)
    notes = _save("pulse", data)
    if notes:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "\n".join(notes)}}))
    return 0


NEEDS = {
    "APPROVE_CONTRACT": "approve the contract", "APPROVE_AMEND": "approve the amended contract",
    "MERGE_BY_PERSON": "merge", "RETRY_CAP": "stuck at the retry budget", "STUCK_REVIEW": "the review timed out",
    "FINDING_UPHELD": "decide a finding", "HOLD": "held", "MERGE_FAILED": "the merge failed",
}


def terminal_sequence(message, term_program=None, term=None):
    """A desktop notification for the terminal in use, or a bell."""
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


HOOKS = {"session-start": session_start, "guard": guard, "notify": notify, "stop": stop, "pulse": pulse}


def run(name, machine=False):
    global MACHINE
    MACHINE = machine
    try:
        return HOOKS[name]()
    except Exception as e:  # a hook must never stop the session
        print(f"rail hook {name}: {e}", file=sys.stderr)
        return 0
