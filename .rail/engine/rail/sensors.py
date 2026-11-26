"""Sensors: ship steps backed by a tool (rail docs sensors).

A sensor is a `[[sensors]]` entry: a command and the exit codes that mean clean and violations. A violation is one
line of its output, `path:line: message`. Only a violation on a line the change adds fails the step, so old code
never fails, and a line git shows as moved is not new. The tool reads its config from the base branch's copy of
.rail/sensors/, so a ticket can't loosen the sensor of its own ship.
"""

import os
import re
import tempfile
from contextlib import contextmanager

from . import config as configmod, gitx, rules
from .project import PRODUCT_SPEC
from .util import could_not_run, match_any, run_shell, tail

FOLDER = ".rail/sensors"
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# path:line: message, as compilers and linters print it; a range (12-18) and a column (12:5) are read too.
LINE = re.compile(r"^(?P<path>[^\s:][^:]*):(?P<start>\d+)(?:-(?P<end>\d+))?(?::\d+)?:\s*(?P<message>\S.*)$")
MARK = re.compile(r"\bSENSOR\(\d+\):\s*\S")   # a violation the ticket's author answers for, on the line or the one above
MOVED = "\x1b[34m"
# git marks the added lines of a block it also finds removed elsewhere in the same change: blocks, not single
# lines, so a short line that happens to exist twice is still new.
COLOURS = [x for name in ("newMoved", "newMovedAlternative", "newMovedDimmed", "newMovedAlternativeDimmed")
           for x in ("-c", f"color.diff.{name}=blue")] + ["-c", "color.diff.new=green", "-c", "color.diff.old=red"]
HELP = ("Nothing was checked: the sensor's command ended with an exit code it declares neither as clean (ok_exit)"
        " nor as violations (violations_exit), so the tool crashed, or its command or config is wrong. If your change"
        " broke what the tool reads, fix that. Otherwise the sensor is the project's to repair: [[sensors]] in"
        " .rail/config.toml and the files under .rail/sensors/ are a person's to change, so open a ticket for it.")


def added_lines(project, ref, cwd):
    """{path: {line number: moved}} for every line the change adds, numbered as in the new file."""
    diff = gitx.git([*COLOURS, "diff", "-U0", "--color=always", "--color-moved=blocks", "--no-ext-diff",
                     *rules._diff_range(project, ref, cwd), *PRODUCT_SPEC], cwd).stdout
    found, path, at = {}, None, 0
    for raw in diff.splitlines():
        line = ANSI.sub("", raw)
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@ "):
            start = re.match(r"^@@ -\S+ \+(\d+)", line)
            at = int(start.group(1)) if start else 0
        elif line.startswith("+") and path is not None and at:
            found.setdefault(path, {})[at] = raw.startswith(MOVED)
            at += 1
    return found


def violations(output, cwd):
    """[(path, start, end, message)] from a sensor's output: every line of the form path:line: message."""
    found = []
    for raw in ANSI.sub("", output).splitlines():
        m = LINE.match(raw.strip())
        if not m:
            continue
        path = m.group("path")
        if os.path.isabs(path):
            path = os.path.relpath(path, os.path.realpath(cwd))
        path = os.path.normpath(path).replace(os.sep, "/")
        start = int(m.group("start"))
        found.append((path, start, int(m.group("end") or start), m.group("message").strip()))
    return found


def marked(cwd, path, start, end, cache):
    """Whether a `SENSOR(NN): why` comment stands on one of the lines, or on the line above the first."""
    if path not in cache:
        try:
            with open(os.path.join(cwd, path), encoding="utf-8", errors="replace") as f:
                cache[path] = f.read().splitlines()
        except OSError:
            cache[path] = []
    lines = cache[path]
    return any(MARK.search(lines[n - 1]) for n in range(max(1, start - 1), end + 1) if n <= len(lines))


def new(project, found, added, cwd):
    """The violations that fail the step: on a line the change adds that git doesn't show as moved, in a file the
    size count would count, with no SENSOR(NN) marker."""
    kept, cache = [], {}
    for path, start, end, message in found:
        lines = added.get(path) or {}
        if not any(n in lines and not lines[n] for n in range(start, end + 1)):
            continue
        if os.path.basename(path) in rules.LOCKFILES or match_any(project.config["size"]["exclude"], path):
            continue
        if marked(cwd, path, start, end, cache):
            continue
        kept.append((path, start, end, message))
    return kept


@contextmanager
def base_files(project):
    """RAIL_SENSORS and RAIL_MAP for a sensor's command: the base branch's .rail/sensors/ and ARCHITECTURE.md, written
    to a folder of their own."""
    with tempfile.TemporaryDirectory(prefix="rail-sensors-") as tmp:
        folder = os.path.join(tmp, "sensors")
        os.makedirs(folder)
        names = gitx.git(["ls-tree", "-r", "--name-only", project.base_ref, "--", FOLDER], project.root,
                         check=False).stdout.splitlines()
        blobs = gitx.read_blobs([f"{project.base_ref}:{n}" for n in names] + [f"{project.base_ref}:ARCHITECTURE.md"],
                                project.root)
        for name in names:
            path = os.path.join(folder, os.path.relpath(name, FOLDER))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(blobs.get(f"{project.base_ref}:{name}") or "")
        atlas = os.path.join(tmp, "ARCHITECTURE.md")
        with open(atlas, "w", encoding="utf-8") as f:
            f.write(blobs.get(f"{project.base_ref}:ARCHITECTURE.md") or "")
        yield {"RAIL_SENSORS": folder, "RAIL_MAP": atlas}


def due(project, changed):
    """The sensors whose paths the change touches."""
    return [s for s in project.config["sensors"] if any(match_any(s.get("paths") or ["**"], p) for p in changed)]


def step(project, nn, ref, cwd, run, patch_id, changed):
    """The `sensors` step, last at ship and in CI. Returns whether it passed."""
    sensors = due(project, changed)
    if not sensors:
        run.not_run("sensors")  # no receipt at all in a project with no sensor
        return True
    added, kept, ms_all = None, [], 0
    with base_files(project) as env:
        for sensor in sensors:
            code, output, ms = run_shell(sensor["command"], cwd, dict(env, RAIL_TICKET=nn, RAIL_BASE=project.base_ref),
                                         configmod.timeout(project.config, "sensors"))
            ms_all += ms
            if code in (sensor.get("ok_exit") or [0]):
                continue
            shown = f"$ {sensor['command']}\n{tail(ANSI.sub('', output))}"
            if code is None:
                return run.record("sensors", False, patch_id, f"{sensor['id']}: timeout", ms_all, output=shown)
            if code not in (sensor.get("violations_exit") or [1]):
                missing = could_not_run(code)
                detail = f"{sensor['id']}: {missing or f'exit {code}, which the sensor does not declare'}"
                return run.record("sensors", False, patch_id, detail, ms_all, status="could_not_run",
                                  output=shown if missing else f"{shown}\n\n{HELP}")
            if added is None:
                added = added_lines(project, ref, cwd)
            kept += [(sensor, v) for v in new(project, violations(output, cwd), added, cwd)]
    if not kept:
        return run.record("sensors", True, patch_id, None, ms_all)
    ids = list(dict.fromkeys(sensor["id"] for sensor, _ in kept))
    lines = [f"{path}:{start}{'' if end == start else f'-{end}'}: {message}. Sensor {sensor['id']}"
             + (f": {sensor['fix']}" if sensor.get("fix") else "") for sensor, (path, start, end, message) in kept]
    lines.append(f"Each is on a line this change adds. Where a sensor is wrong about a line, say why in a comment on"
                 f" that line or the one above it: SENSOR({nn}): the reason. The reviewer judges the reason.")
    return run.record("sensors", False, patch_id, f"{len(kept)} violations: {', '.join(ids)}", ms_all,
                      output="\n".join(lines))


def markers(project, ref, cwd=None):
    """The SENSOR(NN) markers a change adds, as 'path: line text', for the reviewer."""
    return [f"{path}: {line.strip()}" for path, lines in rules.added(project, ref, cwd)[0].items()
            for line in lines if MARK.search(line)]


def tools(project):
    """{sensor id: the program its command starts with} for rail doctor."""
    found = {}
    for sensor in project.config["sensors"]:
        words = [w for w in re.split(r"\s+", sensor["command"].strip()) if w and "=" not in w.split("/")[0]]
        if words:
            found[sensor["id"]] = words[0].strip("\"'")
    return found
