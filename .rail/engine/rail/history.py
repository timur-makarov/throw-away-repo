"""What earlier work on the same paths left for the next agent (rail docs tickets, "What a ticket carries on").

The last merged tickets whose change touched the ticket's scope_paths, each with the first line of its `## Why`,
its decided rows, and its "not tested:" and "Noticed:" lines; and the SHORTCUT(NN), TODO(NN) and FIXME(NN)
markers that stand in those paths on the base branch. `rail context NN` gives it, and so does the implement brief.
"""

import re

from . import gitx
from .project import PRODUCT_SPEC, ticket_path
from .ticket import Ticket
from .util import match_any

TICKETS, MARKERS, SEARCHED = 5, 10, 300  # tickets and markers shown; merges on the base branch looked through
MARKER = r"(SHORTCUT|TODO|FIXME)\([0-9]+\)"


def earlier(project, scope, skip=None):
    """The last merged tickets that changed a path inside `scope`, newest first."""
    log = gitx.git(["log", f"-{SEARCHED}", project.base_ref, "--grep=^Ticket: ", "--name-only", "--no-color",
                    "--format=%x1e%B%x1f"], project.root, check=False).stdout
    found = []
    for entry in log.split("\x1e"):
        if "\x1f" not in entry:
            continue
        body, names = entry.split("\x1f", 1)
        nn = next(iter(re.findall(r"^Ticket: (\d+)\s*$", body, re.M)), None)
        if not nn or nn == skip or nn in found:
            continue
        if any(match_any(scope, path) for path in names.split("\n") if path and not path.startswith(".rail/")):
            found.append(nn)
            if len(found) == TICKETS:
                break
    specs = [f"{project.base_ref}:{ticket_path(nn)}" for nn in found]
    blobs = gitx.read_blobs(specs, project.root)
    tickets = []
    for nn, spec in zip(found, specs):
        t = Ticket(blobs.get(spec) or "")
        if t.errors:
            continue
        tickets.append({"ticket": nn, "title": t.title, "why": t.why_line(), "decided": t.decided(),
                        "not_tested": t.not_tested(), "noticed": t.noticed()})
    return tickets


def markers(project, scope):
    """(the markers standing in `scope` on the base branch as 'path:line: text', how many more there are)."""
    out = gitx.git(["grep", "-n", "-I", "--no-color", "-E", MARKER, project.base_ref, *PRODUCT_SPEC], project.root,
                   check=False).stdout
    found = []
    for line in out.splitlines():
        parts = line.split(":", 3)  # ref:path:line:text; refs/remotes/origin/main holds no colon
        if len(parts) == 4 and match_any(scope, parts[1]):
            found.append(f"{parts[1]}:{parts[2]}: {parts[3].strip()[:160]}")
    return found[:MARKERS], max(0, len(found) - MARKERS)


def of(project, scope, skip=None):
    """The history for `rail context` and the implement brief."""
    shown, more = markers(project, scope)
    return {"tickets": earlier(project, scope, skip), "markers": shown, "more_markers": more}


def text(found):
    """The history as the lines of a brief; empty when there is none."""
    lines = []
    if found["tickets"]:
        lines.append("Earlier tickets that changed these paths, newest first. Their decisions stand unless this ticket"
                     " says otherwise:")
        for t in found["tickets"]:
            lines.append(f"- {t['ticket']} {t['title']}: {t['why']}")
            lines += [f"    {name}: {row}" for name, key in (("decided", "decided"), ("not tested", "not_tested"),
                                                             ("noticed", "noticed")) for row in t[key]]
    if found["markers"]:
        lines.append("Markers standing in these paths (the number is the ticket that left it, or the one that will do"
                     " it):")
        lines += [f"- {m}" for m in found["markers"]]
        if found["more_markers"]:
            lines.append(f"- and {found['more_markers']} more")
    return lines
