"""The sweep: it reviews what shipped without a review, gathers what reviewers parked and proposed, and its output is
tickets, never edits.

A sweep is itself an AUTO ticket that changes no product file, so it merges with no reviewer of its own. Its squash
commit carries a `Sweep:` trailer, which marks where the next one starts.
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


NOTHING = "nothing to file"  # the detail of a harvest step that found nothing: the ticket merges with no task


def since_last(project):
    """(start, commits, merged): what landed on base since the last Sweep: commit. `commits` are those that had no
    review: a ticket whose trailer says `Review: none` (every file it changed is in [review] skip_paths), or a commit
    with no ticket, as (sha, ticket id or None). `merged` are the ids of every ticket that merged, reviewed or not."""
    base = project.base_ref
    # --first-parent: what landed on the base branch, one entry each. A merge commit counts once, as the change it
    # brought, and the commits inside it are not counted again.
    log = gitx.out(["log", "--first-parent", base, "--format=%H%x1f%B%x1e"], project.root)
    found, start = [], None
    for entry in log.split("\x1e"):
        if "\x1f" not in entry:
            continue
        sha, body = entry.strip().split("\x1f", 1)
        if re.search(r"^Sweep: ", body, re.M):
            start = sha
            break
        ticket = re.search(r"^Ticket: (\d+)", body, re.M)
        reviewed = bool(ticket) and bool(re.search(r"^Review: (?!none\b)\S", body, re.M))
        found.append((sha, ticket.group(1) if ticket else None, reviewed))
    if start is None:
        # The first sweep starts where Rail was set up: work from before then was never on the rail.
        setup = gitx.out(["log", "--first-parent", base, "--diff-filter=A", "--format=%H", "--", ".rail/config.toml"],
                         project.root).splitlines()
        start = setup[-1] if setup else ""
        shas = [sha for sha, _, _ in found]
        found = found[:shas.index(start)] if start in shas else found
    found.reverse()
    return (start, [(sha, nn) for sha, nn, reviewed in found if not reviewed],
            [nn for _, nn, _ in found if nn])


def due(project):
    """Due once [sweep] after changes merged with no review, or [sweep] every tickets merged (0 switches that off)."""
    start, commits, merged = since_last(project)
    config = project.config["sweep"]
    return (len(commits) >= config["after"] or 0 < config["every"] <= len(merged)), start, commits, merged


def ticket_text(start, unreviewed, merged):
    return "\n".join([
        "+++", f'title = "Sweep the work merged since {start[:12]}"', 'tier = "AUTO"',
        'scope_paths = [".rail/journal/**"]', f'external_id = "sweep#{start[:12]}"', "+++", "",
        "## Why", f"Since the last sweep {merged} tickets merged, and {unreviewed} changes merged without a review"
                  " (tickets whose every changed file is in [review] skip_paths, and commits with no ticket). The"
                  " sweep reviews those changes, when there are any, and gathers the findings reviewers parked and the"
                  " checks they proposed in every merged ticket, so each can become a ticket.", "",
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


def history(project, merged):
    """The parked findings and the proposed checks of fixed findings, from the journals of every ticket merged since
    the last sweep, reviewed or not: a reviewed ticket is where a reviewer parks a finding."""
    ids = sorted(set(merged), key=int)
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
        diffs.append(gitx.out(["show", "--no-color", "--diff-merges=first-parent", "--format=commit %h %s", sha, "--",
                               ".", ":(exclude).rail/tickets", ":(exclude).rail/journal"], project.root))
    parts = [
        "# Sweep brief", "", "This run's job: sweep the changes below, which merged without a review.", "",
        "## The changes", "```diff", "\n\n".join(diffs), "```", "",
        "## The project's conventions (from AGENTS.md)", project_conventions(project, project.base_ref) or "(none)", "",
        "## What to look for", SWEEP_LOOK_FOR, "", SECURITY, "", DO_NOT_REPORT, "",
        "## Parked findings from the tickets merged since the last sweep",
        *([f"- ticket {nn} {fid}: {claim}" for nn, fid, claim in parked] or ["(none)"]), "",
        "## Checks reviewers proposed for findings that were fixed",
        *([f"- {check} ({', '.join(where)})" for check, where in checks.items()] or ["(none)"]),
    ]
    return "\n".join(parts) + "\n"


def summary(nn, start, commits, merged, problems, counts, entry, parked, checks):
    review = (entry["summary"] if entry else "(the review run failed)") if commits else \
        "(no review run: nothing merged without a review)"
    lines = [f"# Sweep {nn}", "", f"Since {start[:12]}: {len(merged)} tickets merged; {len(commits)} commits merged"
                                  " without a review.", "",
             "## Free part", *([f"- doc-lint: {p}" for p in problems] or ["- doc-lint: clean"]),
             *[f"- rule {rid}: {n} lines in the tree" for rid, n in counts.items()], "",
             "## Review", review, ""]
    for f in (entry or {}).get("findings", []):
        where = f"{f['file']}:{f['line']}" if f.get("line") else f["file"]
        lines.append(f"- {f['id']} ({f['severity']}) {where}: {f['claim']}" + (f" Check: {f['check']}" if f.get("check") else ""))
    lines += ["", "## Parked findings", *([f"- ticket {n} {fid}: {c}" for n, fid, c in parked] or ["(none)"]),
              "", "## Proposed checks, by kind", *([f"- {c} ({', '.join(w)})" for c, w in checks.items()] or ["(none)"])]
    return "\n".join(lines) + "\n"


def run(project, f, receipt):
    """The free part, the parked findings and proposed checks, and one review pass with the sweep brief when
    something merged without a review. With nothing unreviewed there is no model run: a passed `harvest` step says
    so, and its detail says when nothing at all was found. Writes NN-summary.md into `receipt`."""
    from . import review

    start, commits, merged = since_last(project)
    problems, counts = free_part(project)
    parked, checks = history(project, merged)
    entry = None
    if commits:
        entry = review.run(project, f, "sweep", receipt, prompt=brief(project, commits, parked, checks))
    else:
        receipt.record("harvest", True, f.patch_id, NOTHING if not (problems or parked or checks) else
                       f"no review run: {len(parked)} parked findings, {len(checks)} proposed checks")
    receipt.files[f".rail/journal/{f.id}-summary.md"] = summary(f.id, start, commits, merged, problems, counts, entry,
                                                               parked, checks)
    return entry
