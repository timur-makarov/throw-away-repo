"""Sources: a named prompt that reads one signal and files tickets, never edits.

A source is `.rail/sources/NAME.md`: TOML front matter between `+++` lines (`fetch`, a shell command whose output is
the signal, and `max_open`) and a body that is the prompt. A ticket belongs to a source when its external_id starts
with `NAME#` and the source's file exists. The engine schedules nothing: `rail source NAME` hands the agent a brief.
"""

import os
import re
import tomllib

from .util import RailError

DIR = os.path.join(".rail", "sources")
NAME = re.compile(r"^[a-z0-9-]+$")
RESERVED = ("sweep", "red-base", "github")  # external_id prefixes the engine writes itself
KEYS = {"fetch": str, "max_open": int}
SIGNAL_LIMIT = 20000  # characters of the fetch's output in a brief: the tail, where a log's news usually is
ENDED = ("merged", "dropped")


class Source:
    def __init__(self, name, fetch, max_open, prompt):
        self.name, self.fetch, self.max_open, self.prompt = name, fetch, max_open, prompt


def names(project):
    folder = os.path.join(project.root, DIR)
    return sorted(f[:-3] for f in os.listdir(folder) if f.endswith(".md")) if os.path.isdir(folder) else []


def load(project, name):
    """The source NAME. A bad name, a missing file or a malformed one is an error that names the file."""
    where = f"{DIR}/{name}.md"
    if not NAME.match(name):
        raise RailError(f"{where}: a source's name takes lowercase letters, digits and hyphens", code="BAD_SOURCE")
    if name in RESERVED:
        raise RailError(f"{where}: '{name}' can't name a source: the engine writes {name}# external ids itself",
                        code="BAD_SOURCE")
    path = os.path.join(project.root, where)
    if not os.path.exists(path):
        known = ", ".join(names(project)) or "none"
        raise RailError(f"no source '{name}': {where} doesn't exist (sources: {known})", code="NO_SOURCE")
    with open(path) as f:
        lines = f.read().split("\n")

    def bad(problem):
        return RailError(f"{where}: {problem}", code="BAD_SOURCE")

    if lines[0].strip() != "+++":
        raise bad("it must start with TOML front matter between '+++' lines")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "+++"), None)
    if end is None:
        raise bad("the front matter has no closing '+++' line")
    try:
        meta = tomllib.loads("\n".join(lines[1:end]))
    except tomllib.TOMLDecodeError as e:
        raise bad(f"the front matter is not valid TOML: {e}")
    for key, value in meta.items():
        if key not in KEYS:
            raise bad(f"unknown key '{key}'; a source takes {' and '.join(KEYS)}")
        if not isinstance(value, KEYS[key]) or isinstance(value, bool):
            raise bad(f"{key} must be {KEYS[key].__name__}")
    if not meta.get("fetch", "").strip():
        raise bad("fetch is missing: the command whose output is the signal")
    if "max_open" not in meta:
        raise bad("max_open is missing: how many of this source's tickets may be open at once")
    if meta["max_open"] < 1:
        raise bad("max_open must be 1 or more")
    prompt = "\n".join(lines[end + 1:]).strip()
    if not prompt:
        raise bad("the prompt is empty: write below the front matter what to look for in the signal")
    return Source(name, meta["fetch"], meta["max_open"], prompt)


def problems(project):
    """For doctor: each source file that doesn't load, with why."""
    found = []
    for name in names(project):
        try:
            load(project, name)
        except RailError as e:
            found.append(str(e))
    return found


def owner(project, external_id):
    """The source a ticket belongs to: its external_id starts with NAME# and the source's file exists."""
    name, hash_, _ = (external_id or "").partition("#")
    if hash_ and NAME.match(name) and name not in RESERVED and os.path.exists(os.path.join(project.root, DIR,
                                                                                            f"{name}.md")):
        return name
    return None


def tickets_of(facts, name):
    """[(external_id, ticket id, state)] of the source's tickets that git still has."""
    return [(f.ticket.get("external_id"), nn, f.state) for nn, f in facts.items()
            if f.ticket and (f.ticket.get("external_id") or "").startswith(f"{name}#")]


def check_add(project, facts, external_id):
    """rail add on a source's ticket: no second open ticket for one key, and no more than max_open open at once."""
    name = owner(project, external_id)
    if not name:
        return
    source = load(project, name)
    mine = [(key, nn) for key, nn, state in tickets_of(facts, name) if state not in ENDED]
    same = [nn for key, nn in mine if key == external_id]
    if same:
        raise RailError(f"ticket {same[0]} with external_id {external_id} is open already: the same problem gets"
                        " one ticket at a time", code="SOURCE_DUPLICATE")
    if len(mine) >= source.max_open:
        raise RailError(f"source {name} has {len(mine)} open tickets ({', '.join(nn for _, nn in mine)}), its"
                        f" max_open: no more until one merges or is dropped", code="SOURCE_FULL")


def brief(source, output, room, mine):
    cut = len(output) > SIGNAL_LIMIT
    signal = output[-SIGNAL_LIMIT:] if cut else output
    existing = [f"  - {key} (ticket {nn}, {state})" for key, nn, state in mine]
    parts = [
        f"# Source {source.name}", "",
        "This run's job: read the signal below and file a ticket for each problem worth one. File tickets only:"
        " change no file in the repository, and commit nothing.", "",
        "## What to look for", source.prompt, "",
        "## The signal",
        f"The output of `{source.fetch}`, run in the project's root"
        + (f". It was cut: these are its last {SIGNAL_LIMIT:,} characters." if cut else ":"),
        "```text", signal.rstrip("\n") or "(no output)", "```", "",
        "## How to file",
        f"- You may file at most {room} tickets now: max_open is {source.max_open}, and"
        f" {source.max_open - room} of this source's tickets are open.",
        "- Write each ticket to a file outside the repository, such as a temporary file, in the format of"
        " .rail/tickets/TEMPLATE.md (rail docs tickets), and file it with: rail add FILE",
        f"- Set each ticket's external_id to \"{source.name}#KEY\". KEY names the underlying problem, not this run,"
        " so the same problem found on a later run gets the same key. rail add refuses a key whose ticket is"
        " still open.",
        "- These tickets of this source exist already. Don't draft them again; file a merged or dropped one's key"
        " again only when its problem is still there:",
        *(existing or ["  (none)"]),
        "- When nothing is worth a ticket, file none and say so.",
    ]
    return "\n".join(parts) + "\n"
