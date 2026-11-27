"""Read these: the lines of a change that need a person's eye, built from facts (rail docs review).

The pull request opens with the list, before the author's own `## Look at`: an author's framing leads a reader,
and this list has no author. Each item is a place, the reason, and where the reason comes from: the ticket's
tier, the review, an amend, a marker, or what the change can now do.
"""

import os
import re

from . import gitx, rules
from .forge import ENGINE_MARK, ForgeError
from .project import PRODUCT_SPEC
from .util import globmatch, match_any

MARKER = re.compile(r"\b(?:SHORTCUT|SENSOR|TODO|FIXME)\(\d+\)")
# Files that say what a project depends on or runs: a change to one changes what the code can reach.
MANIFESTS = {"package.json", "pyproject.toml", "requirements.txt", "setup.py", "setup.cfg", "Pipfile", "Cargo.toml",
             "go.mod", "Gemfile", "pom.xml", "build.gradle", "build.gradle.kts", "composer.json", "mix.exs",
             "pubspec.yaml", "Package.swift", "Dockerfile"}
SHOWN = 160  # characters of a claim or a line an item quotes


def numbered(project, ref, cwd=None):
    """{path: [(line number, text)]} for every line the change adds, numbered as in the new file."""
    cwd = cwd or project.root
    diff = gitx.out(["diff", "-U0", "--no-color", "--no-ext-diff", *rules._diff_range(project, ref, cwd),
                     *PRODUCT_SPEC], cwd)
    found, path, at = {}, None, 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@ "):
            start = re.match(r"^@@ -\S+ \+(\d+)", line)
            at = int(start.group(1)) if start else 0
        elif line.startswith("+") and path is not None and at:
            found.setdefault(path, []).append((at, line[1:]))
            at += 1
    return found


def ranges(numbers):
    """Line numbers as text: [3, 4, 5, 9] is "3-5, 9"."""
    out, numbers = [], sorted(set(numbers))
    for n in numbers:
        if out and n == out[-1][1] + 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in out)


def _cut(text):
    text = " ".join(str(text or "").split())
    return text if len(text) <= SHOWN else text[:SHOWN - 1].rstrip() + "…"


def items(project, t, ticket, tier, ledger, changed):
    """The list, as [{path, lines, why, source}]: `path` is None for an item about the ticket itself, and `lines` is
    empty for one about a whole file."""
    from .state import raised_tier

    added = numbered(project, t.ref)
    found = []

    def item(path, lines, why, source):
        for x in found:
            if (x["path"], x["why"], x["source"]) == (path, why, source):
                x["lines"] = sorted(set(x["lines"]) | set(lines))
                return
        found.append({"path": path, "lines": sorted(set(lines)), "why": why, "source": source})

    # Why a person is there at all: what the reviewer found that a revert doesn't undo, then the paths of a kind.
    for run in ledger.doc["runs"]:
        for k in run.get("kinds") or []:
            if isinstance(k, dict):
                item(k.get("file"), [k["line"]] if k.get("line") else [],
                     f"{k.get('kind')}: {_cut(k.get('why'))}", "the reviewer")
        if run.get("needs_person"):
            item(None, [], _cut(run["needs_person"]), "the reviewer")
    by_path = False
    for kind, hits, key in raised_tier(project, changed)[1]:
        by_path = True
        for path in hits:
            item(path, [n for n, _ in added.get(path, [])],
                 f"{kind}: this file is on {'[kinds] ' + kind if key == 'kinds' else key}, and a revert doesn't undo"
                 " a change of that kind", "the tier")
    if tier == "PERSON" and not by_path and (ticket.get("person_reason") or "").strip():
        item(None, [], f"the ticket is PERSON as it was written: {_cut(ticket.get('person_reason'))}", "the tier")

    # Findings the machines decided against: a person may see it differently.
    for fid, f in ledger.findings.items():
        last = ledger.last(fid)
        if last.get("outcome") != "declined":
            continue
        if f.get("severity") == "advisory":
            said = "an advisory finding the author declined"
        elif last.get("by") == "refuter":
            said = "a blocking finding the refuter dismissed"
        else:
            continue
        item(f.get("file"), [f["line"]] if f.get("line") else [], f"{fid}, {said}: {_cut(f.get('claim'))}", "the review")

    # The bar moved with no person: an amend of the Done Contract that the engine accepted.
    accepted = False
    for e in t.events:
        if e.get("event") == "accepted":
            accepted = True
        elif accepted and e.get("event") == "amended" and "done_contract" in (e.get("changed") or []) \
                and not e.get("needs_approval"):
            item(None, [], f"the Done Contract changed after it was accepted, with no person: {_cut(e.get('reason'))}",
                 "an amend")

    # Corners cut on purpose, and what the change can now do.
    flags = [r for r in project.config["rules"] if r.get("flag")]
    for path, lines in added.items():
        for n, text in lines:
            if MARKER.search(text):
                item(path, [n], _cut(text.strip()), "a marker")
            for rule in flags:
                if globmatch(rule.get("files", "**"), path) and not match_any(rule.get("allow", []), path) \
                        and any(word in text for word in rule.get("forbid", [])):
                    item(path, [n], f"{rule['id']}: {_cut(rule.get('why') or 'a flag rule matches this line')}",
                         "a flag rule")
    for path in changed:
        name = os.path.basename(path)
        if name in rules.LOCKFILES:
            item(path, [], "a lockfile changed: the versions the project installs", "the change")
        elif name in MANIFESTS:
            item(path, [], "a manifest changed: what the project depends on or runs", "the change")
        elif name == ".gitattributes":
            item(path, [], "it can mark files as generated, which hides them from the diff and from the size count",
                 "the change")
    return found


def section(project, ticket, found, added_count, reviewed):
    """The `## Read these` section of a pull request's description."""
    lines = []
    for x in found:
        where = (x["path"] + (f":{ranges(x['lines'])}" if x["lines"] else "")) if x["path"] else "The ticket"
        lines.append(f"- {where}: {x['why']} ({x['source']})")
    if not found:
        lines.append("Nothing needs a person's eye.")
    listed = len({(x["path"], n) for x in found if x["path"] for n in x["lines"]})
    by = (["verify"] if project.config["commands"]["verify"].strip() else []) \
        + [f"{len(ticket.checks())} check{'' if len(ticket.checks()) == 1 else 's'}"] \
        + (["the reviewer"] if reviewed else [])
    checked = by[0] if len(by) == 1 else f"{', '.join(by[:-1])} and {by[-1]}"
    rest = max(0, added_count - listed)
    lines.append(f"{rest} other changed line{'' if rest == 1 else 's'}: checked by {checked}.")
    return lines


def post(project, t, pr, found):
    """One review that comments on each item's first line, where that is a line the change adds, with the engine's
    mark. An item already there at the same path and line is left alone. Returns how many comments it posted."""
    forge = project.forge
    added = {(path, n) for path, lines in numbered(project, t.ref).items() for n, _ in lines}
    found = [x for x in found if x["path"] and x["lines"] and (x["path"], x["lines"][0]) in added]
    if not found:
        return 0
    have = {(c.get("path"), c.get("line") or c.get("original_line")) for c in forge.line_comments(pr["number"])
            if ENGINE_MARK in (c.get("body") or "")}
    comments = [{"path": x["path"], "line": x["lines"][0], "side": "RIGHT",
                 "body": f"{x['why']} ({x['source']})\n\n{ENGINE_MARK}"}
                for x in found if (x["path"], x["lines"][0]) not in have]
    if comments:
        forge.post_review(pr["number"], pr["head"]["sha"], comments)
    return len(comments)
