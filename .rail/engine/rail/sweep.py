"""The sweep (plan, section 12): it reviews what shipped without a review, and its output is tickets, never edits.

A sweep is itself a LOW ticket. Its squash commit carries a `Sweep:` trailer, which marks where the next one starts.
"""

import json
import re
from collections import defaultdict

from . import doclint, gitx
from .project import events_path, parse_events
from .util import globmatch, match_any

SWEEP_LOOK_FOR = """This is a sweep: these changes merged without a review. Look for:
- duplication across tickets;
- logic in the wrong area;
- weak checks;
- security (the checklist below);
- stale docs.
Each finding becomes a ticket, so report only what is worth one. The earlier parked findings and the checks
reviewers proposed are below: report a parked one again when it is real, and group the proposed checks by kind."""


def unreviewed(project):
    """(start, commits): the commits on base since the last Sweep: commit that had no review: Tier: LOW, or no ticket."""
    base = project.base_ref
    log = gitx.out(["log", base, "--format=%H%x1f%B%x1e"], project.root)
    found, start = [], None
    for entry in log.split("\x1e"):
        if "\x1f" not in entry:
            continue
        sha, body = entry.strip().split("\x1f", 1)
        if re.search(r"^Sweep: ", body, re.M):
            start = sha
            break
        tier = re.search(r"^Tier: (\w+)", body, re.M)
        ticket = re.search(r"^Ticket: (\d+)", body, re.M)
        if not ticket or (tier and tier.group(1) == "LOW"):
            found.append((sha, ticket.group(1) if ticket else None))
    if start is None:
        # The first sweep starts where Rail was set up: work from before then was never on the rail.
        setup = gitx.out(["log", base, "--diff-filter=A", "--format=%H", "--", ".rail/config.toml"],
                         project.root).splitlines()
        start = setup[-1] if setup else ""
        shas = [sha for sha, _ in found]
        found = found[:shas.index(start)] if start in shas else found
    return start, list(reversed(found))


def due(project):
    start, commits = unreviewed(project)
    return len(commits) >= project.config["sweep"]["after"], start, commits


def ticket_text(start, count):
    return "\n".join([
        "+++", f'title = "Sweep the unreviewed work since {start[:12]}"', 'tier = "LOW"',
        'scope_paths = [".rail/journal/**"]', f'external_id = "sweep#{start[:12]}"', "+++", "",
        "## Why", f"{count} LOW tickets and ticketless commits merged without a review since the last sweep.", "",
        "## Done Contract", "- Check: `test -s .rail/journal/$RAIL_TICKET-summary.md`", ""])


def free_part(project):
    """What needs no model: doc-lint on base, and each structure rule counted over the whole tree."""
    problems = doclint.lint(project, project.base_ref)
    files = [f for f in gitx.git(["ls-tree", "-r", "-z", "--name-only", project.base_ref], project.root)
             .stdout.split("\0") if f]
    counts = {}
    for rule in project.config["rules"]:
        hits = 0
        paths = [f for f in files if globmatch(rule.get("files", "**"), f) and not match_any(rule.get("allow", []), f)]
        blobs = gitx.read_blobs([f"{project.base_ref}:{p}" for p in paths], project.root)
        for text in blobs.values():
            for line in (text or "").splitlines():
                if any(word in line for word in rule.get("forbid", [])):
                    hits += 1
        counts[rule["id"]] = hits
    return problems, counts


def history(project, commits):
    """The parked findings and the proposed checks of fixed findings, from the journals merged in range."""
    ids = sorted({nn for _, nn in commits if nn}, key=int)
    blobs = gitx.read_blobs([f"{project.base_ref}:{events_path(nn)}" for nn in ids], project.root)
    parked, checks = [], defaultdict(list)
    for nn in ids:
        events = parse_events(blobs.get(f"{project.base_ref}:{events_path(nn)}"))
        first = {e["id"]: e for e in events if e.get("event") == "finding" and "severity" in e}
        last = {}
        for e in events:
            if e.get("event") == "finding":
                last[e["id"]] = e
        for fid, e in last.items():
            claim = first.get(fid, {}).get("claim", "")
            if e.get("outcome") == "parked":
                parked.append((nn, fid, claim))
            elif e.get("outcome") == "fixed" and first.get(fid, {}).get("check"):
                checks[" ".join(first[fid]["check"].lower().split())].append(f"{nn}/{fid}")
    seen, unique = set(), []
    for nn, fid, claim in parked:
        key = " ".join(claim.lower().split())
        if key not in seen:
            seen.add(key)
            unique.append((nn, fid, claim))
    return unique, dict(checks)


def brief(project, commits, parked, checks):
    from .review import DO_NOT_REPORT, SECURITY, project_conventions

    diffs = []
    for sha, nn in commits:
        diffs.append(gitx.out(["show", "--no-color", "--format=commit %h %s", sha, "--", ".",
                               ":(exclude).rail/tickets", ":(exclude).rail/journal"], project.root))
    parts = [
        "# Sweep brief", "", "This run's job: sweep the changes below, which merged without a review.", "",
        "## The changes", "```diff", "\n\n".join(diffs), "```", "",
        "## The project's conventions (from AGENTS.md)", project_conventions(project, project.base_ref) or "(none)", "",
        "## What to look for", SWEEP_LOOK_FOR, "", SECURITY, "", DO_NOT_REPORT, "",
        "## Parked findings from these tickets",
        *([f"- ticket {nn} {fid}: {claim}" for nn, fid, claim in parked] or ["(none)"]), "",
        "## Checks reviewers proposed for findings that were fixed",
        *([f"- {check} ({', '.join(where)})" for check, where in checks.items()] or ["(none)"]),
    ]
    return "\n".join(parts) + "\n"


def summary(nn, start, commits, problems, counts, entry, parked, checks):
    lines = [f"# Sweep {nn}", "", f"Since {start[:12]}: {len(commits)} commits merged without a review.", "",
             "## Free part", *([f"- doc-lint: {p}" for p in problems] or ["- doc-lint: clean"]),
             *[f"- rule {rid}: {n} lines in the tree" for rid, n in counts.items()], "",
             "## Review", entry["summary"] if entry else "(the review run failed)", ""]
    for f in (entry or {}).get("findings", []):
        where = f"{f['file']}:{f['line']}" if f.get("line") else f["file"]
        lines.append(f"- {f['id']} ({f['severity']}) {where}: {f['claim']}" + (f" Check: {f['check']}" if f.get("check") else ""))
    lines += ["", "## Parked findings", *([f"- ticket {n} {fid}: {c}" for n, fid, c in parked] or ["(none)"]),
              "", "## Proposed checks, by kind", *([f"- {c} ({', '.join(w)})" for c, w in checks.items()] or ["(none)"])]
    return "\n".join(lines) + "\n"


def run(project, f, receipt):
    """The free part and one review pass with the sweep brief. Writes the run and NN-summary.md into `receipt`."""
    from .project import review_path
    from . import review

    start, commits = unreviewed(project)
    problems, counts = free_part(project)
    parked, checks = history(project, commits)
    entry = review.run(project, f, "sweep", receipt, prompt=brief(project, commits, parked, checks))
    receipt.files[f".rail/journal/{f.id}-summary.md"] = summary(f.id, start, commits, problems, counts, entry,
                                                               parked, checks)
    return entry
