"""`rail stats`: what the journals of merged tickets say about the work and about the reviewer.

Everything is read from the events and the review runs, which merge with the code. Nothing is stored, so the
numbers can be checked against the journal they come from.
"""

import datetime
import re
import statistics
from collections import Counter

from . import gitx
from .project import events_path, parse_events, review_path
from .review import Ledger, load_doc
from .state import SHIP_STEPS
from .ticket import TIERS, highest
from .util import RailError, parse_iso

REVIEW_STEPS = ("review", "security", "refuter", "sweep")
STEP_ORDER = ("setup", "rebase", "ticket-lint", "assumptions", "scope", "change", "rules", "migration", "size", "doc-lint",
              "verify", "checks", *REVIEW_STEPS, "merge")
NO_MODEL = "(not reported)"
NO_RUNS = {"runs": 0, "cost_usd": 0.0, "blocking": 0, "fixed": 0}


def _since(text):
    try:
        return datetime.datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc).timestamp()
    except ValueError:
        raise RailError(f"--since takes a date like 2026-01-31, not '{text}'")


def _merge_times(project, tickets):
    """{ticket id: when its squash commit landed on the base branch, in seconds since the epoch}."""
    shas = {t.merged: nn for nn, t in tickets.items() if t.merged}
    if not shas:
        return {}
    lines = gitx.out(["show", "--no-patch", "--format=%H %ct", *shas], project.root).splitlines()
    return {shas[sha]: int(at) for sha, at in (line.split() for line in lines if line.strip()) if sha in shas}


def _reverted(project, tickets):
    """The merged tickets whose squash commit a later commit on the base branch reverts. git revert writes "This
    reverts commit <sha>."; GitHub's Revert button opens a pull request whose squash says "Reverts owner/repo#N",
    where N is the pull request the ticket merged with."""
    shas = {t.merged: nn for nn, t in tickets.items() if t.merged}
    if not shas:
        return set()
    prs = {}
    for line in gitx.out(["show", "--no-patch", "--format=%H %s", *shas], project.root).splitlines():
        sha, _, subject = line.partition(" ")
        if sha in shas and (m := re.search(r"\(#(\d+)\)$", subject.strip())):
            prs[m.group(1)] = shas[sha]
    log = gitx.out(["log", project.base_ref, "--grep=This reverts commit ", "--grep=^Reverts ", "--format=%B%x1e"],
                   project.root)
    found = set()
    for body in log.split("\x1e"):
        for sha in re.findall(r"This reverts commit ([0-9a-f]{7,40})", body):
            found |= {nn for full, nn in shas.items() if full.startswith(sha)}
        for number in re.findall(r"^Reverts \S+#(\d+)", body, re.M):
            found |= {prs[number]} if number in prs else set()
    return found


def _journals_of_reverted(project, tickets):
    """A revert of a squash commit takes the ticket's journal off the base branch with its code. The ticket still
    counts: its journal is read from its squash commit."""
    gone = [t for t in tickets.values() if t.merged and not t.events]
    blobs = gitx.read_blobs([f"{t.merged}:{path(t.id)}" for t in gone for path in (events_path, review_path)],
                            project.root) if gone else {}
    for t in gone:
        t.events = parse_events(blobs.get(f"{t.merged}:{events_path(t.id)}"))
        t.review_text = blobs.get(f"{t.merged}:{review_path(t.id)}")


def _ended(severity, last):
    """How a finding ended. Only a refuter or a person can decline a blocking one: the author's decline disputes it."""
    if severity == "blocking" and last.get("outcome") == "declined":
        return "dismissed" if last.get("by") == "refuter" else "declined_by_person"
    return last.get("outcome")


def _first_try(t, ships):
    """No counted ship step failed before the ticket first shipped."""
    before = t.events[:t.events.index(ships[0])] if ships else t.events
    return not any(e.get("event") == "step" and e.get("result") == "fail" and e.get("counted", True)
                   and e.get("step") in SHIP_STEPS for e in before)


def _amended_after_acceptance(t):
    """The Done Contract or the scope changed after the ticket was first accepted: what it meant wasn't settled."""
    accepted = False
    for e in t.events:
        if e.get("event") == "accepted":
            accepted = True
        elif accepted and e.get("event") == "amended" and {"done_contract", "scope"} & set(e.get("changed") or []):
            return True
    return False


def _guide_row():
    return {"tickets": 0, "failed_steps": 0, "review_runs": 0, "waited": 0}


def _per_ticket(row):
    n = row["tickets"]
    return {**row, "failed_steps_per_ticket": round(row["failed_steps"] / n, 2) if n else None,
            "review_runs_per_ticket": round(row["review_runs"] / n, 2) if n else None}


def _waited_on_retries(events):
    """A person continued the ticket right after a counted failed ship, review or security step: the wait the retry
    budget or cap makes."""
    last = None
    for e in events:
        if e.get("event") == "step":
            last = e
        elif e.get("event") == "continued" and last and last.get("result") == "fail" and last.get("counted", True) \
                and last.get("step") in (*SHIP_STEPS, "review", "security"):
            return True
    return False


TAKEN = ("accepted", "edited", "rejected", "answered")


def _grill_row():
    return {"tickets": 0, "questions": 0, **{taken: 0 for taken in TAKEN}, "merged": 0, "dropped": 0, "open": 0,
            "amended": 0, "first_try": 0, "caused_fix": 0, "minutes": []}


def grilling(tickets, states, merged_at, start):
    """Where tickets came from, how the grilling went, and what happened to them afterwards. A ticket counts when it
    was requested on or after `start`."""
    caused = {str(t.ticket.get("caused_by")) for t in tickets.values() if t.ticket and t.ticket.get("caused_by")}
    groups = {"grilled": _grill_row(), "not grilled": _grill_row()}
    channels, agents = {}, {}
    for nn, t in tickets.items():
        req = next((e for e in t.events if e.get("event") == "requested"), None) or t.dropped_request
        if not req or (start is not None and parse_iso(req["at"]).timestamp() < start):
            continue
        state = states.get(nn) or ("merged" if nn in merged_at else "dropped" if t.last("dropped") else "open")
        state = state if state in ("merged", "dropped") else "open"
        rows = [groups["grilled" if req.get("grilled") else "not grilled"],
                channels.setdefault(req.get("channel") or "?", _grill_row())]
        if req.get("grilled"):
            rows.append(agents.setdefault(req.get("agent") or NO_MODEL, _grill_row()))
        ships = [e for e in t.events if e.get("event") == "shipped"]
        for row in rows:
            row["tickets"] += 1
            row["questions"] += len(req.get("questions") or [])
            for q in req.get("questions") or []:
                if q.get("taken") in TAKEN:
                    row[q["taken"]] += 1
            row[state] += 1
            row["amended"] += _amended_after_acceptance(t)
            row["caused_fix"] += nn in caused
            if state == "merged":
                row["first_try"] += _first_try(t, ships)
                row["minutes"].append(max(0.0, (merged_at[nn] - parse_iso(req["at"]).timestamp()) / 60))
    for row in [*groups.values(), *channels.values(), *agents.values()]:
        minutes = row.pop("minutes")
        row["median_minutes"] = round(statistics.median(minutes), 1) if minutes else None
        offered = row["accepted"] + row["edited"] + row["rejected"]
        row["acceptance"] = round(row["accepted"] / offered, 3) if offered else None
    return {"groups": groups, "channels": dict(sorted(channels.items())), "agents": dict(sorted(agents.items()))}


def by_source(project, tickets, states, merged_at, reverted, start):
    """What became of each source's tickets: those requested on or after `start`, as the grilling counts them."""
    from . import sources

    rows = {}
    for nn, t in tickets.items():
        req = next((e for e in t.events if e.get("event") == "requested"), None) or t.dropped_request
        external = (t.ticket.get("external_id") if t.ticket else None) or (req or {}).get("external_id")
        name = sources.owner(project, external)
        if not name or (start is not None and (not req or parse_iso(req["at"]).timestamp() < start)):
            continue
        state = states.get(nn) or ("merged" if nn in merged_at else "dropped" if t.last("dropped") else "open")
        row = rows.setdefault(name, {"filed": 0, "merged": 0, "reverted": 0, "dropped": 0, "open": 0})
        row["filed"] += 1
        row[state if state in ("merged", "dropped") else "open"] += 1
        row["reverted"] += nn in reverted
    return dict(sorted(rows.items()))


def collect(project, tickets, since=None, states=None):
    """The numbers, for tickets merged on or after `since` (YYYY-MM-DD), or for every merged ticket. The grilling
    numbers count the tickets requested on or after `since`, whatever became of them; `states` says which were
    dropped."""
    start = _since(since) if since else None
    merged_at = _merge_times(project, tickets)
    reverted = _reverted(project, tickets)
    _journals_of_reverted(project, tickets)
    tiers = {tier: {"merged": 0, "reviewed": 0, "no_person": 0, "first_try": 0, "reverted": 0, "minutes": []}
             for tier in TIERS}
    base = {"tickets": 0, "all_green": 0}  # tickets whose Check: lines ran on the base before the work
    raised, consults, adopted, steps, roles, models = Counter(), 0, 0, {}, {}, {}
    split = {"offered": 0, "auto": 0, "person": 0}  # AUTO changes over [size] cap offered a split, and what came of it
    blocking, advisory, parked, disputes = Counter(), Counter(), 0, Counter()
    guided = {"guided": _guide_row(), "not guided": _guide_row()}  # by whether the start guide was named
    situations = Counter()
    for nn, t in tickets.items():
        ships = [e for e in t.events if e.get("event") == "shipped"]
        tier = (ships[-1] if ships else t.last("accepted") or {}).get("tier")
        if tier in TIERS:  # a reviewer may raise it after the last ship
            tier = highest(tier, *[e.get("to") for e in t.events if e.get("event") == "tier_raised"])
        if nn not in merged_at or tier not in tiers or (start is not None and merged_at[nn] < start):
            continue
        doc = load_doc(t.review_text, nn)
        ledger = Ledger(t.events, doc)
        row = tiers[tier]
        row["merged"] += 1
        row["reviewed"] += bool(ledger.runs("review"))
        person = any(e.get("event") == "continued" or (e.get("event") == "accepted" and e.get("by") == "person")
                     or (e.get("event") == "finding" and e.get("by") == "owner") for e in t.events)
        row["no_person"] += tier == "AUTO" and not person
        row["first_try"] += _first_try(t, ships)
        row["reverted"] += nn in reverted
        adopted += t.last("adopted") is not None  # work that came in on a branch with no ticket: rail adopt
        found = t.last("base_checks")
        if found and found.get("checks"):
            base["tickets"] += 1
            base["all_green"] += all(c.get("result") == "green" for c in found["checks"])
        claims = [e["at"] for e in t.events if e.get("event") == "claimed" and e.get("at")]
        if claims:
            row["minutes"].append(max(0.0, (merged_at[nn] - parse_iso(claims[0]).timestamp()) / 60))
        named = {e.get("situation") for e in t.events if e.get("event") == "guided"}
        situations.update(named)
        group = guided["guided" if "start" in named else "not guided"]
        group["tickets"] += 1
        group["failed_steps"] += sum(e.get("event") == "step" and e.get("result") == "fail" and e.get("counted", True)
                                     and e.get("step") in SHIP_STEPS for e in t.events)
        group["review_runs"] += sum(e.get("event") == "step" and e.get("status") == "ran"
                                    and e.get("step") in ("review", "security", "refuter") for e in t.events)
        group["waited"] += _waited_on_retries(t.events)
        offered = next((i for i, e in enumerate(t.events) if e.get("event") == "split_offered"), None)
        if offered is not None:
            later = t.events[offered + 1:]
            split["offered"] += 1
            if any(e.get("event") == "tier_raised" and e.get("reason") == "size" for e in later):
                split["person"] += 1
            elif any(e.get("event") == "shipped" and e.get("tier") == "AUTO" for e in later):
                split["auto"] += 1
        for e in t.events:
            if e.get("event") == "tier_raised":
                raised[e.get("reason") or "?"] += 1
            elif e.get("event") == "consulted":
                consults += 1
            elif e.get("event") == "step" and e.get("status") in ("ran", "could_not_run"):
                step = steps.setdefault(e.get("step"), {"runs": 0, "failed": 0, "could_not_run": 0})
                step["runs"] += 1
                step["could_not_run" if e["status"] == "could_not_run" else "failed"] += e.get("result") == "fail"
                if e.get("step") in REVIEW_STEPS:
                    role = roles.setdefault(e["step"], {"runs": 0, "cost_usd": 0.0, "minutes": 0.0})
                    role["runs"] += 1
                    role["cost_usd"] += e.get("cost_usd") or 0
                    role["minutes"] += (e.get("duration_ms") or 0) / 60000
        first_run = {}  # finding id -> the run that first reported it
        for run in doc["runs"]:
            model = models.setdefault(run.get("model") or NO_MODEL, dict(NO_RUNS))
            model["runs"] += 1
            model["cost_usd"] += run.get("cost_usd") or 0
            found = run.get("findings") or []
            if run.get("role") == "refuter":
                disputes["dismissed" if not found else "parked" if found[0].get("severity") == "parked" else "upheld"] += 1
            for finding in found:
                first_run.setdefault(finding.get("id"), run)
        for fid, finding in ledger.findings.items():
            severity = finding.get("severity")
            if finding.get("role") not in ("review", "security"):
                continue  # a sweep's findings become tickets, not ledger entries
            if severity == "parked":
                parked += 1
            elif severity == "blocking":
                ended = _ended(severity, ledger.last(fid))
                blocking[ended] += 1
                model = models.setdefault(first_run.get(fid, {}).get("model") or NO_MODEL, dict(NO_RUNS))
                model["blocking"] += 1
                model["fixed"] += ended == "fixed"
            elif severity == "advisory":
                advisory[ledger.last(fid).get("outcome")] += 1
    for row in tiers.values():
        minutes = row.pop("minutes")
        row["median_minutes"] = round(statistics.median(minutes), 1) if minutes else None
    decided = sum(blocking.values()) - blocking["open"]
    merged = sum(row["merged"] for row in tiers.values())
    return {
        "since": since, "merged": merged, "left_out": len(tickets) - merged, "tiers": tiers, "raised": dict(raised),
        "base_checks": base, "adopted": adopted, "split": split,
        "guides": {**{name: _per_ticket(row) for name, row in guided.items()},
                   "situations": dict(sorted(situations.items()))},
        "grilling": grilling(tickets, states or {}, merged_at, start),
        "sources": by_source(project, tickets, states or {}, merged_at, reverted, start),
        "consults": consults, "steps": {name: steps[name] for name in sorted(steps, key=_step_rank)},
        "review": {
            "roles": {name: _rounded(roles[name]) for name in REVIEW_STEPS if name in roles},
            "models": {name: _rounded(models[name]) for name in sorted(models)},
            "cost_usd": round(sum(role["cost_usd"] for role in roles.values()), 4),
            "blocking": {"total": sum(blocking.values()), **dict(blocking)},
            "advisory": {"total": sum(advisory.values()), **dict(advisory)},
            "parked": parked, "disputes": dict(disputes),
            # Of the blocking findings that were decided, the share that ended in a fix.
            "hit_rate": round(blocking["fixed"] / decided, 3) if decided else None,
        },
    }


def _step_rank(name):
    return STEP_ORDER.index(name) if name in STEP_ORDER else len(STEP_ORDER)


def _rounded(row):
    return {key: round(value, 4) if isinstance(value, float) else value for key, value in row.items()}


def _span(minutes):
    if minutes is None:
        return "-"
    minutes = int(round(minutes))
    if minutes < 60:
        return f"{minutes}m"
    if minutes < 1440:
        return f"{minutes // 60}h{minutes % 60:02d}m"
    return f"{minutes // 1440}d{minutes % 1440 // 60}h"


def _table(head, rows):
    """Lines of a table: the first column left-aligned, the rest right-aligned under their headings."""
    widths = [max(len(str(row[i])) for row in [head, *rows]) for i in range(len(head))]
    return ["  ".join(str(cell).ljust(widths[i]) if i == 0 else str(cell).rjust(widths[i]) for i, cell in enumerate(row))
            .rstrip() for row in [head, *rows]]


def _listed(counts, names):
    """'Fixed 6, dismissed by the refuter 2': the outcomes that happened, in a fixed order."""
    parts = [f"{label} {counts[key]}" for key, label in names if counts.get(key)]
    return (", ".join(parts)[:1].upper() + ", ".join(parts)[1:] + ".") if parts else ""


def _pct(value):
    return "-" if value is None else f"{value:.0%}"


def render_grilling(data):
    groups = data["grilling"]["groups"]
    if not any(row["tickets"] for row in groups.values()):
        return []
    cols = list(groups.values())
    lines = ["", *_table(["GRILLING", *groups], [
        ["tickets requested", *[r["tickets"] for r in cols]],
        ["questions asked", *[r["questions"] for r in cols]],
        ["recommendation accepted", *[r["accepted"] for r in cols]],
        ["recommendation edited", *[r["edited"] for r in cols]],
        ["recommendation rejected", *[r["rejected"] for r in cols]],
        ["acceptance rate", *[_pct(r["acceptance"]) for r in cols]],
        ["merged", *[r["merged"] for r in cols]],
        ["dropped", *[r["dropped"] for r in cols]],
        ["still open", *[r["open"] for r in cols]],
        ["contract amended after acceptance", *[r["amended"] for r in cols]],
        ["shipped on the first try", *[r["first_try"] for r in cols]],
        ["caused a fix ticket", *[r["caused_fix"] for r in cols]],
        ["median request to merge", *[_span(r["median_minutes"]) for r in cols]]])]
    lines.append("Acceptance rate: recommendations taken as they were, of those accepted, edited or rejected. Read it"
                 " with the amends: many acceptances and many amends mean the person said yes without deciding.")
    head = ["tickets", "questions", "accepted", "edited", "rejected", "amended", "dropped"]
    for title, rows in (("BY CHANNEL", data["grilling"]["channels"]), ("GRILLED BY", data["grilling"]["agents"])):
        if rows:
            lines += ["", *_table([title, *head], [[name, *[r[k] for k in head]] for name, r in rows.items()])]
    return lines


def render_sources(data):
    rows = data["sources"]
    head = ["filed", "merged", "reverted", "dropped", "open"]
    return ["", *_table(["SOURCES", *head], [[name, *[r[k] for k in head]] for name, r in rows.items()])] if rows else []


def render_guides(data):
    """Tickets the start guide was named for beside the rest, once any guide was named."""
    guides = data["guides"]
    if not guides["situations"]:
        return []
    cols = [guides["guided"], guides["not guided"]]
    return ["", *_table(["GUIDES", "guided", "not guided"], [
        ["merged tickets", *[r["tickets"] for r in cols]],
        ["failed steps per ticket", *["-" if r["failed_steps_per_ticket"] is None else r["failed_steps_per_ticket"]
                                     for r in cols]],
        ["review runs per ticket", *["-" if r["review_runs_per_ticket"] is None else r["review_runs_per_ticket"]
                                    for r in cols]],
        ["waited for a person on retries", *[r["waited"] for r in cols]]]),
        "Guides named: " + ", ".join(f"{name} {n}" for name, n in guides["situations"].items()) + "."]


def render(data):
    when = f" since {data['since']}" if data["since"] else ""
    if not data["merged"]:
        grill = render_sources(data) + render_grilling(data)
        if grill:
            return "\n".join([f"Rail stats: no ticket has merged{when} yet.", *grill])
        return f"No ticket has merged{when}, so there is nothing to count yet."
    tiers, review = data["tiers"], data["review"]
    head = f"Rail stats: {data['merged']} merged ticket{'' if data['merged'] == 1 else 's'}{when}."
    if data["left_out"]:
        head += f" Not counted: {data['left_out']} {'merged earlier or not merged' if data['since'] else 'not merged'}."
    lines = [head, ""]
    lines += _table(["TICKETS", *tiers], [
        ["merged", *[row["merged"] for row in tiers.values()]],
        ["the reviewer read it", *[row["reviewed"] for row in tiers.values()]],
        ["merged with no review", *[row["merged"] - row["reviewed"] for row in tiers.values()]],
        ["no person acted", *[row["no_person"] for row in tiers.values()]],
        ["shipped on the first try", *[row["first_try"] for row in tiers.values()]],
        ["reverted afterwards", *[row["reverted"] for row in tiers.values()]],
        ["median claim to merge", *[_span(row["median_minutes"]) for row in tiers.values()]]])
    base = data["base_checks"]
    if base["tickets"]:
        lines.append(f"Every check already green on the base: {base['all_green']} of {base['tickets']} tickets whose"
                     " checks ran there before the work.")
    if data["adopted"]:
        lines.append(f"Adopted from a branch with no ticket (rail adopt): {data['adopted']} of {data['merged']} merged"
                     " tickets.")
    if data["raised"]:
        reasons = ", ".join(f"{reason} {n}" for reason, n in sorted(data["raised"].items()))
        lines.append(f"Became PERSON at ship or review: {sum(data['raised'].values())} ({reasons}).")
    if data["split"]["offered"]:
        split = data["split"]
        lines.append(f"Offered a split over [size] cap: {split['offered']}. Shipped AUTO afterwards: {split['auto']};"
                     f" became PERSON for size: {split['person']}.")
    failed = [[name, s["runs"], s["failed"], s["could_not_run"]] for name, s in data["steps"].items()
              if s["failed"] or s["could_not_run"]]
    lines.append("")
    if failed:
        lines += _table(["STEPS THAT FAILED", "runs", "failed", "could not run"], failed)
    else:
        lines.append("No step failed.")
    if data["consults"]:
        lines.append(f"Consult ran {data['consults']} times.")
    lines += render_guides(data)
    if not review["roles"]:
        return "\n".join(lines + ["", "No review ran.", *render_sources(data), *render_grilling(data)])
    roles = review["roles"]
    total = ["total", sum(r["runs"] for r in roles.values()), f"${review['cost_usd']:.2f}",
             _span(sum(r["minutes"] for r in roles.values()))]
    lines += ["", *_table(["REVIEW", "runs", "cost", "time"], [
        *[[name, r["runs"], f"${r['cost_usd']:.2f}", _span(r["minutes"])] for name, r in roles.items()], total])]
    reviewed = sum(row["reviewed"] for row in tiers.values())
    if reviewed:
        lines.append(f"${review['cost_usd'] / reviewed:.2f} for each ticket the reviewer read.")
    lines += ["", *_table(["BY MODEL", "runs", "cost", "blocking", "fixed"], [
        [name, m["runs"], f"${m['cost_usd']:.2f}", m["blocking"], m["fixed"]] for name, m in review["models"].items()])]
    blocking, advisory = review["blocking"], review["advisory"]
    lines += ["", f"Blocking findings: {blocking['total']}. " + _listed(blocking, (
        ("fixed", "fixed"), ("dismissed", "dismissed by the refuter"), ("declined_by_person", "declined by a person"),
        ("parked", "parked"), ("open", "still open")))]
    if review["hit_rate"] is not None:
        lines.append(f"Hit rate: {review['hit_rate']:.0%} of the decided ones ended in a fix. A finding the author fixed"
                     " without disputing it counts as a hit, so read this as an upper bound.")
    lines.append(f"Advisory findings: {advisory['total']}. " + _listed(advisory, (
        ("fixed", "fixed"), ("declined", "declined"), ("parked", "parked"), ("open", "still open"))))
    if review["parked"]:
        lines.append(f"Parked by the reviewer: {review['parked']}.")
    if review["disputes"]:
        lines.append(f"Disputes: {sum(review['disputes'].values())}. " + _listed(review["disputes"], (
            ("dismissed", "the refuter dismissed"), ("parked", "parked"), ("upheld", "upheld"))))
    lines += render_sources(data) + render_grilling(data)
    return "\n".join(line.rstrip() for line in lines)
