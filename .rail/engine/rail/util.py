"""Small helpers shared by the engine: errors, time, globs and shell commands."""

import datetime
import os
import re
import shutil
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


# Globs: '**' matches across directories, '*' and '?' stay inside one path segment, '{a,b}' matches either
# alternative (one level, no nesting), and a trailing '/' means everything below that directory.
_GLOBS = {}


def _glob_regex(pattern):
    if pattern.endswith("/"):
        pattern += "**"
    return re.compile("^" + _glob_body(pattern) + "$")


def _glob_body(pattern):
    out, i = [], 0
    while i < len(pattern):
        close = pattern.find("}", i) if pattern[i] == "{" else -1
        if close > 0 and "," in pattern[i:close]:
            out.append("(?:" + "|".join(_glob_body(alt) for alt in pattern[i + 1:close].split(",")) + ")")
            i = close + 1
        elif pattern.startswith("**/", i):
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
    return "".join(out)


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


# The exit codes a shell gives a command it could not start: 127 when it isn't found, 126 when it is found but
# can't be run (not executable, a directory). A check that ends this way checked nothing.
COULD_NOT_RUN = {126: "found but could not be run", 127: "command not found"}


def tried_help(step, ticket):
    """What a brief says after a failed attempt at the work itself: verify, a Check: line or a sensor. A failed lint
    or scope check is a slip, not an attempt."""
    if step not in ("verify", "checks", "sensors"):
        return ""
    return (f"Before you try again, write one line under \"## Tried\" in {ticket}: what you tried and how it failed."
            " The next attempt reads it, and it may start with none of what you know now.")


# What to do about it, for the agent's brief.
MISSING_HELP = ("Nothing was checked: the shell couldn't start the command or a tool it calls, which isn't on this"
                " machine or isn't executable. If your change removed, renamed or broke it, put it back. Otherwise"
                " install it here to go on, and open a ticket so that [commands] provision (or setup) installs it on"
                " every machine.")


# After a ship step that could not run: the machine's lack is no attempt at the work.
NOT_COUNTED = ("Nothing was checked, so no attempt was counted. The same thing a second time in a row waits for a"
               " person.")


def could_not_run(code):
    """The words for a command the shell could not start, or None when it ran (or timed out)."""
    return f"could not run (exit {code}: {COULD_NOT_RUN[code]})" if code in COULD_NOT_RUN else None


def shell(command):
    """The argv that runs a configured command. A failure anywhere in a pipe fails the command (pipefail), so
    `pytest | tail -20` fails when pytest fails, and `pytest | head` fails when head cuts pytest off before it ends.
    bash has pipefail on Linux and macOS alike; Linux's sh (dash) has none. Without bash, sh gets it where its
    shell knows the option, as busybox's does."""
    bash = shutil.which("bash")
    if bash:
        return [bash, "-o", "pipefail", "-c", command]
    return ["sh", "-c", "(set -o pipefail) 2>/dev/null && set -o pipefail; " + command]


def run_shell(command, cwd, env_extra=None, timeout=None, stdin=None):
    """Run a command through the shell (see `shell`), with `stdin` as its input. Returns (exit code or None on
    timeout, output, ms)."""
    env = dict(os.environ)
    env.update(env_extra or {})
    start = time.monotonic()
    proc = subprocess.Popen(
        shell(command), cwd=cwd, env=env, stdin=subprocess.DEVNULL if stdin is None else subprocess.PIPE,
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
