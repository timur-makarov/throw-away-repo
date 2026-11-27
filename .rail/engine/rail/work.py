"""`rail work NN`: one attempt at a ticket's agent work. The engine starts [worker] command as it starts the reviewer,
keeps the ticket's claim alive while it works, and records the run: a `worked` event in the journal, and a run log in
the local cache. It ships nothing: the runner runs `rail advance NN` after it."""

import json
import os
import re
import shlex
import signal
import subprocess
import threading
import time

from .project import event, parse_events
from .util import shell

# The answers whose brief a worker does: a ticket's agent work, after which the runner runs rail advance NN.
CODES = ("TICKET_LINT", "VERIFY_ASSUMPTIONS", "IMPLEMENT", "REVERT", "STEP_FAILED", "RED_CHECK", "ANSWER_FINDINGS", "CONFLICT",
         "REBASING", "SPLIT", "SWEEP_TICKETS", "AFTER_DROPPED")
# The line added to the brief. Inside the run, the verbs in REFUSED refuse (RAIL_WORKER is set).
LAST_LINE = ("When you are done, or can't go on, reply in one line. Don't run `rail advance`: the runner runs it after"
             " you exit.")
REFUSED = ("advance", "next", "work", "save")
# How the run ended, from the result line's subtype. A run with no result line ended `done` when it exited 0.
ENDS = {"success": "done", "error_max_turns": "turns", "error_max_budget_usd": "budget"}
LOG_CHARS, LOG_LINES = 200, 500  # the run log, per line and per run
KEYS = 20                        # the keys kept per count in the event
RUNNERS = (("uv", "run"), ("npx",), ("pnpm", "exec"), ("poetry", "run"), ("bundle", "exec"))


def refusal(verb):
    return (f"This is a worker run that rail work started (RAIL_WORKER is set), and rail {verb} is the runner's to run"
            " after you exit: finish the brief, then reply in one line.")


# --- running the command -------------------------------------------------------------------


def _start(command, cwd, env, brief):
    """Start the command in its own process group, with the brief on stdin. Returns (process, stdout lines, stderr
    lines, the threads that read them)."""
    proc = subprocess.Popen(shell(command), cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True)
    out, err = [], []

    def feed():
        try:
            proc.stdin.write(brief)
            proc.stdin.close()
        except OSError:
            pass  # the command exited without reading its input

    def drain(stream, into):
        for line in stream:
            into.append(line)

    threads = [threading.Thread(target=feed, daemon=True), threading.Thread(target=drain, args=(proc.stdout, out), daemon=True),
               threading.Thread(target=drain, args=(proc.stderr, err), daemon=True)]
    for thread in threads:
        thread.start()
    return proc, out, err, threads


def _run(project, command, cwd, env, brief, save):
    """One run of the command. Every [claim] save_minutes, `save()` keeps the claim alive. Past [worker]
    timeout_minutes the process group is ended. Returns (exit code or None past the timeout, stdout lines, stderr
    lines, seconds)."""
    period = max(60 * project.config["claim"]["save_minutes"], 1)
    began = time.monotonic()
    deadline = began + 60 * project.config["worker"]["timeout_minutes"]
    proc, out, err, threads = _start(command, cwd, env, brief)
    next_save = began + period
    while True:
        try:
            code = proc.wait(timeout=max(0, min(deadline, next_save) - time.monotonic()))
            break
        except subprocess.TimeoutExpired:
            if time.monotonic() >= deadline:
                # The wall clock is the bound a run always has, whatever the CLI does with its own limit flags: the
                # whole process group is killed, and a process that left the group can't hold rail work open.
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass  # it ended a moment ago
                proc.wait()
                code = None
                break
            save()
            next_save = time.monotonic() + period
    for thread in threads[1:]:
        thread.join(timeout=5)  # a process the command left behind may hold its output open: don't wait for it
    return code, out, err, time.monotonic() - began


# --- reading what it printed ---------------------------------------------------------------------


def program(command):
    """The program a Bash command runs: its first word, after leading NAME=value words, a leading `cd DIR &&` and the
    runners uv run, npx, pnpm exec, poetry run and bundle exec. `uv run pytest -x` is pytest."""
    try:
        words = shlex.split(command)
    except ValueError:
        words = command.split()
    while True:
        before = len(words)
        while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            words = words[1:]
        if len(words) >= 3 and words[0] == "cd" and words[2] == "&&":
            words = words[3:]
        for runner in RUNNERS:
            if tuple(words[:len(runner)]) == runner:
                words = words[len(runner):]
        if len(words) == before:
            return os.path.basename(words[0]) if words else ""


def _text(content):
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
    return content if isinstance(content, str) else ""


def _what(tool_input):
    """The command or path a tool call names."""
    for key in ("command", "file_path", "notebook_path", "path", "pattern", "url", "query"):
        value = tool_input.get(key) if isinstance(tool_input, dict) else None
        if isinstance(value, str) and value:
            return value
    return ""


def read(lines):
    """What the command printed, when it is JSON lines: the last `result` line, the session id, and the tool calls in
    order, each {tool, what, outcome (ok, failed, denied), text, reason}."""
    result, session, calls, denied = None, None, {}, {}
    for line in lines:
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        kind = data.get("type")
        session = session or data.get("session_id")
        if kind == "result":
            result = data
            for d in data.get("permission_denials") or []:
                if isinstance(d, dict):
                    denied.setdefault(d.get("tool_use_id"), "")
        elif kind == "system" and data.get("subtype") == "permission_denied":
            denied[data.get("tool_use_id")] = data.get("decision_reason") or ""
        elif kind in ("assistant", "user"):
            content = (data.get("message") or {}).get("content")
            for part in content if isinstance(content, list) else []:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "tool_use":
                    calls[part.get("id")] = {"tool": part.get("name") or "?", "what": _what(part.get("input")),
                                             "outcome": "ok", "text": ""}
                elif part.get("type") == "tool_result" and part.get("tool_use_id") in calls:
                    call = calls[part["tool_use_id"]]
                    call["text"] = _text(part.get("content"))
                    call["outcome"] = "failed" if part.get("is_error") else "ok"
    for tool_id, reason in denied.items():
        if tool_id in calls:
            text = calls[tool_id]["text"]
            hook = re.search(r"hook error: (.*)", text)  # a hook's denial, such as the guard's
            calls[tool_id].update(outcome="denied", reason=(reason or (hook.group(1) if hook else text)).strip()[:80])
    if result:
        session = result.get("session_id") or session
    return result, session, list(calls.values())


def counts(calls):
    """What the run's tool calls say about the project, with a short key per item: Bash commands that failed before
    the first one of the same program passed (`failed`), commands the shell couldn't find (`not_found`, exit 127),
    tool calls a rule or the guard denied (`denied`), and files read more than twice (`reread`)."""
    passed, found, reads = set(), {"failed": [], "not_found": [], "denied": [], "reread": []}, {}
    for call in calls:
        bash = call["tool"] == "Bash"
        name = program(call["what"]) if bash else call["tool"]
        if call["outcome"] == "denied":
            found["denied"].append(f"{name}: {call.get('reason', '')}")
        elif bash and call["outcome"] == "ok":
            passed.add(name)
        elif bash and re.match(r"Exit code 127\b", call["text"]):
            found["not_found"].append(name)
        elif bash and name not in passed:
            found["failed"].append(name)
        if call["tool"] == "Read" and call["what"]:
            reads[call["what"]] = reads.get(call["what"], 0) + 1
    found["reread"] = [path for path, n in reads.items() if n > 2]
    return ({kind: len(items) for kind, items in found.items()},
            {kind: sorted(set(items))[:KEYS] for kind, items in found.items() if items})


def log_lines(calls):
    """The run log: one line per tool call, its tool, outcome and command or path, cut to the caps."""
    lines = []
    for call in calls[:LOG_LINES]:
        what = " ".join(call["what"].split())
        lines.append(f"{call['tool']} {call['outcome']}: {what}"[:LOG_CHARS])
    return lines


# --- the run -----------------------------------------------------------------------------------


def previous(project, f):
    """The ticket's last `worked` event, one a rebase holds back in the cache included."""
    held = parse_events(project.cache_read("worked", f.id))
    found = [e for e in list(f.t.events) + held if e.get("event") == "worked"]
    return found[-1] if found else None


def run(project, f, result, save):
    """Run [worker] command once on the brief of `result` (the answer `next` gives for the ticket). Returns (the
    `worked` event, the worker's reply)."""
    action, code = result["action"], result["reason"]["code"]
    model, effort = action.get("model", ""), action.get("effort", "")
    last = previous(project, f)
    # The same worker goes on while the rung stays the same and its last run ended done: it has read the code already.
    resume = (last.get("session") if last and last.get("end") == "done" and last.get("model", "") == model
              and last.get("effort", "") == effort else "") or ""
    cwd = f.t.worktree or project.root  # a contract for a ticket not yet claimed is written from the project's root
    brief = f"{action['brief']}\n\n{LAST_LINE}\n"
    env = dict(os.environ, RAIL_TICKET=f.id, RAIL_MODEL=model, RAIL_EFFORT=effort, RAIL_WORKER="1")
    if model:
        env["ANTHROPIC_MODEL"] = model
    command = project.config["worker"]["command"]
    resume_failed = False
    while True:
        env["RAIL_SESSION"] = resume
        exit_code, out, err, seconds = _run(project, command, cwd, env, brief, save)
        found, session, calls = read(out)
        if exit_code is None:
            end = "timeout"
        elif found and found.get("subtype"):
            end = ENDS.get(found["subtype"], "error")
        else:
            end = "done" if exit_code == 0 else "error"
        turns = found.get("num_turns") if found else None
        if resume and end == "error" and not turns:
            # A session lives on the machine that ran it: on another one the resume fails before any turn. Once more,
            # as a fresh session.
            resume, resume_failed = "", True
            continue
        break
    tally, keys = counts(calls)
    fields = {"code": code, "model": model, "effort": effort, "end": end, "minutes": round(seconds / 60, 1),
              "resumed": bool(resume)}
    if resume_failed:
        fields["resume_failed"] = True
    if found and exit_code is not None and isinstance(found.get("total_cost_usd"), (int, float)):
        fields["cost_usd"] = found["total_cost_usd"]
    if isinstance(turns, int):
        fields["turns"] = turns
    if session:
        fields["session"] = session
    fields["counts"] = tally
    if keys:
        fields["keys"] = keys
    worked = event(f.id, "worked", **fields)
    write_log(project, f.id, worked, calls)
    reply = found.get("result") if found and isinstance(found.get("result"), str) else "".join(out[-5:] + err[-5:])
    return worked, reply.strip()[-1000:]


def write_log(project, nn, worked, calls):
    """Append the run's lines to the ticket's run log in the local cache. It is never committed: a command line can
    carry a token, and a journal file, once pushed and merged, can't be taken out."""
    path = os.path.join(project.common, "rail", "cache", "work", nn)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    head = " ".join(str(x) for x in ("#", worked["at"], worked["code"], worked["model"], worked["effort"], worked["end"],
                                     "session", worked.get("session", "-")) if x)
    with open(path, "a") as f:
        f.write("\n".join([head] + log_lines(calls)) + "\n")


def record(project, nn, worked):
    """Write the `worked` event to the ticket's journal. While a rebase is open in its worktree nothing may be written
    to the ticket, so the event waits in the local cache, and the next `rail work` or `rail advance` writes it."""
    held = project.cache_read("worked", nn) or ""
    project.cache_write("worked", nn, held + "\n" + json.dumps(worked, separators=(",", ":")) + "\n")
    flush(project, nn)


def flush(project, nn):
    """Write the `worked` events a rebase held back, once it has ended. Returns whether it wrote any."""
    held = parse_events(project.cache_read("worked", nn))
    if not held:
        return False
    t = project.tickets().get(nn)
    if not t or t.rebasing or not t.name:
        return False
    from .cli import ensure_local
    ensure_local(project, t)
    project.append_events(t, held, "work")
    project.cache_write("worked", nn, None)
    return True
