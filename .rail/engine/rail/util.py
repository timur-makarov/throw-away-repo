"""Small helpers shared by the engine: errors, time, globs and shell commands."""

import datetime
import os
import re
import signal
import subprocess
import time


class RailError(Exception):
    """A usage error. The CLI answers with ok: false and exit code 2."""

    def __init__(self, message, code="USAGE"):
        super().__init__(message)
        self.code = code


def cloud():
    """Whether this is a Claude Code cloud session: a disposable VM nobody owns, where Rail may install what it
    needs and the rules that protect a person's own machine don't apply. RAIL_CLOUD=1 or 0 overrides."""
    forced = os.environ.get("RAIL_CLOUD")
    if forced is not None:
        return forced in ("1", "true")
    return os.environ.get("CLAUDE_CODE_REMOTE") == "true"


def disposable():
    """A cloud session or a CI runner: a machine made for this run, where the project's provision command may run."""
    return cloud() or os.environ.get("GITHUB_ACTIONS") == "true"


def session_url():
    """The cloud session's page, for a person who wants to open the conversation that worked a ticket."""
    remote = os.environ.get("CLAUDE_CODE_REMOTE_SESSION_ID", "")
    return f"https://claude.ai/code/session_{remote[4:]}" if remote.startswith("cse_") else None


def minutes_since(text):
    """Whole minutes since an ISO time; None when there is none."""
    if not text:
        return None
    return max(0, int((datetime.datetime.now(datetime.timezone.utc) - parse_iso(text)).total_seconds() // 60))


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text):
    return datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)


def age(text):
    """'4m', '3h', '2d' since an ISO time, or '' when there is none."""
    if not text:
        return ""
    seconds = (datetime.datetime.now(datetime.timezone.utc) - parse_iso(text)).total_seconds()
    if seconds < 3600:
        return f"{max(0, int(seconds // 60))}m"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h"
    return f"{int(seconds // 86400)}d"


# Globs: '**' matches across directories, '*' and '?' stay inside one path segment,
# and a trailing '/' means everything below that directory.
_GLOBS = {}


def _glob_regex(pattern):
    if pattern.endswith("/"):
        pattern += "**"
    out, i = ["^"], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    out.append("$")
    return re.compile("".join(out))


def globmatch(pattern, path):
    if pattern not in _GLOBS:
        _GLOBS[pattern] = _glob_regex(pattern)
    return bool(_GLOBS[pattern].match(path))


def match_any(patterns, path):
    return any(globmatch(p, path) for p in patterns)


def globs_overlap(a, b):
    """Whether two globs can name the same path, judged by matching each against the other's text."""
    return globmatch(a, b) or globmatch(b, a)


AFTER_SHELL = []  # called after every shell command: what the engine remembers about git and GitHub may be old


def run_shell(command, cwd, env_extra=None, timeout=None, stdin=None):
    """Run a command through sh, with `stdin` as its input. Returns (exit code or None on timeout, output, ms)."""
    env = dict(os.environ)
    env.update(env_extra or {})
    start = time.monotonic()
    proc = subprocess.Popen(
        ["sh", "-c", command], cwd=cwd, env=env, stdin=subprocess.DEVNULL if stdin is None else subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE if stdin is not None else subprocess.STDOUT, text=True,
        start_new_session=True,
    )
    try:
        output, errors = proc.communicate(input=stdin, timeout=timeout)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        output, errors = proc.communicate()
        code = None
    if code != 0 and errors:  # with stdin, stderr is kept apart so stdout stays clean JSON
        output = (output or "") + errors
    for forget in AFTER_SHELL:
        forget()  # the command may have changed the repository, and time has passed on GitHub
    return code, output or "", int((time.monotonic() - start) * 1000)


def tail(text, lines=60, chars=4000):
    kept = "\n".join(text.rstrip().splitlines()[-lines:])
    return kept[-chars:]
