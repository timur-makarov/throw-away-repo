"""`rail stats`: what the journals of merged tickets say about the work and about the reviewer.

Everything is read from the events and the review runs, which merge with the code. Nothing is stored, so the
numbers can be checked against the journal they come from.
"""

import datetime
import re
import statistics
import time
from collections import Counter

from . import flakes, gitx, timing
from .project import events_path, parse_events, review_path
from .review import Ledger, load_doc
from .state import SHIP_STEPS
from .ticket import TIERS, highest
from .util import RailError, globs_overlap, parse_iso

REVIEW_STEPS = ("review", "security", "refuter", "sweep")
STEP_ORDER = ("setup", "rebase", "ticket-lint", "assumptions", "scope", "change", "rules", "migration", "size", "doc-lint",
              "verify", "checks", "sensors", *REVIEW_STEPS, "merge")
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
    where N is the pull request the ticket merged with; a revert ticket's squash carries a "Reverts: <sha>" trailer."""
    shas = {t.merged: nn for nn, t in tickets.items() if t.merged}
    if not shas:
        return set()
    prs = {}
    for line in gitx.out(["show", "--no-patch", "--format=%H %s", *shas], project.root).splitlines():
        sha, _, subject = line.partition(" ")
        if sha in shas and (m := re.search(r"\(#(\d+)\)$", subject.strip())):
            prs[m.group(1)] = shas[sha]
    log = gitx.out(["log", project.base_ref, "--grep=This reverts commit ", "--grep=^Reverts", "--format=%B%x1e"],
                   project.root)
    found = set()
    for body in log.split("\x1e"):
        for sha in re.findall(r"This reverts commit ([0-9a-f]{7,40})", body) + \
                re.findall(r"^Reverts: ([0-9a-f]{7,40})\s*$", body, re.M):
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


def _acts(t):
    """A person's acts the journal records: each approval and each continue, and each finding a person decided."""
    return sum(1 for e in t.events if e.get("event") == "continued"
               or (e.get("event") == "accepted" and e.get("by") == "person")
               or (e.get("event") == "finding" and e.get("by") == "owner"))


def _cost(t):
    """(what the review commands reported, what the worker runs reported), in dollars."""
    return (sum(e.get("cost_usd") or 0 for e in t.events if e.get("event") == "step" and e.get("step") in REVIEW_STEPS),
            sum(e.get("cost_usd") or 0 for e in t.events if e.get("event") == "worked"))


def _outcome_row():
    return {"merged": 0, "reverted": 0, "caused_fix": 0, "old_enough": 0, "held": 0, "first_try": 0,
            "review_usd": 0.0, "worker_usd": 0.0, "acts": []}


def _outcome_done(row):
    acts, merged = row.pop("acts"), row["merged"]
    row["review_usd"], row["worker_usd"] = round(row["review_usd"], 4), round(row["worker_usd"], 4)
    row["cost_per_ticket"] = round((row["review_usd"] + row["worker_usd"]) / merged, 4) if merged else None
    row["acts"] = {"total": sum(acts), "median": statistics.median(acts) if acts else None, "none": acts.count(0)}
    return row


SPLIT_LEAST = 5  # a group smaller than this says little by itself: it is summed with the other small ones


def _split(groups):
    """The groups of SPLIT_LEAST tickets or more by name, and the smaller ones summed as `other`. {} when no group
    is that large: a split of small groups shows nothing."""
    large = {name: row for name, row in sorted(groups.items()) if row["merged"] >= SPLIT_LEAST}
    if not large:
        return {}
    small = [row for row in groups.values() if row["merged"] < SPLIT_LEAST]
    if small:
        other = _outcome_row()
        for row in small:
            for key, value in row.items():
                other[key] += value
        large["other"] = other
    return {name: _outcome_done(row) for name, row in large.items()}


def _worker_of(t):
    """The model and effort of the ticket's last worker run, as `rail work` recorded it."""
    last = t.last("worked")
    if not last:
        return "(no worker run)"
    return ":".join(part for part in (last.get("model"), last.get("effort")) if part) or NO_MODEL


def _profiles_of(project, t):
    """The language profiles ([[profiles]] in the config) whose paths the ticket's scope reaches."""
    accepted = next((e for e in t.events if e.get("event") == "accepted"), {})
    scope = accepted.get("scope_paths") or (sorted(t.ticket.scope) if t.ticket else [])
    return [p["name"] for p in project.config["profiles"]
            if any(globs_overlap(p.get("paths") or "**", path) for path in scope)]


def _person_reasons(t):
    """Why a PERSON ticket was PERSON: the kinds it held (rail docs kinds). Those its first acceptance names when
    that was already PERSON, and those of each `tier_raised` event. A journal that names no kind, as an older
    engine's doesn't, gives `at add` and the event's reason instead."""
    first = next((e for e in t.events if e.get("event") == "accepted"), {})
    reasons = list(first.get("kinds") or ["at add"]) if first.get("tier") == "PERSON" else []
    for e in t.events:
        if e.get("event") == "tier_raised":
            reasons += e.get("kinds") or [e.get("kind") or e.get("reason") or "?"]
    return list(dict.fromkeys(reasons))


def drops(tickets, start):
    """The dropped tickets requested on or after `start`: who dropped them, and for the engine's drops at the retry
    cap the step each stopped at. Read from the drop marks, which outlive the tickets' branches, and from the
    journal of a drop whose mark isn't written yet."""
    by, steps_, cost = Counter(), Counter(), 0.0
    for t in tickets.values():
        record = t.dropped_record or (t.last("dropped") if not t.merged else None)
        if not record:
            continue
        req = next((e for e in t.events if e.get("event") == "requested"), None) or t.dropped_request
        if start is not None and (not req or parse_iso(req["at"]).timestamp() < start):
            continue
        by[record.get("by") or "?"] += 1
        if record.get("by") == "engine":
            steps_[record.get("step") or "?"] += 1
        # The mark keeps what the ticket's runs reported; a drop whose mark isn't written yet still has its journal.
        cost += record.get("cost_usd") or sum(_cost(t))
    return {"total": sum(by.values()), "by": dict(sorted(by.items())), "stuck_steps": dict(sorted(steps_.items())),
            "cost_usd": round(cost, 4)}


def _held_a_kind(tickets):
    """{id of a ticket: the kinds a later PERSON ticket that names it in caused_by holds}. Such a ticket did
    something a revert doesn't undo: when it merged AUTO, nobody was asked."""
    found = {}
    for t in tickets.values():
        cause = str(t.ticket.get("caused_by") or "") if t.ticket else ""
        if cause and t.ticket.tier == "PERSON" and t.ticket.kinds:
            found.setdefault(cause, []).extend(t.ticket.kinds)
    return found


def _person_changed_nothing(t):
    """The person's involvement changed nothing: no note with an approval or a continue, no finding the person
    decided, no amend after the person's first act, and no new commit after the person's first act once the work had
    shipped (an approval of the contract before the work comes before every commit, so it is not that act)."""
    acts = [i for i, e in enumerate(t.events) if e.get("event") == "continued"
            or (e.get("event") == "accepted" and e.get("by") == "person")]
    if any(e.get("note") for e in (t.events[i] for i in acts)):
        return False
    if any(e.get("event") == "finding" and e.get("by") == "owner" for e in t.events):
        return False
    if acts and any(e.get("event") == "amended" for e in t.events[acts[0]:]):
        return False
    ships = [i for i, e in enumerate(t.events) if e.get("event") == "shipped"]
    after = next((i for i in acts if ships and i > ships[0]), None)
    if after is not None:
        patch = [t.events[i] for i in ships if i < after][-1].get("patch_id")
        if any(t.events[i].get("patch_id") != patch for i in ships if i > after):
            return False
    return True


TAKEN = ("accepted", "edited", "rejected", "answered")


def _grill_row():
    return {"tickets": 0, "questions": 0, **{taken: 0 for taken in TAKEN}, "merged": 0, "dropped": 0, "open": 0,
            "amended": 0, "first_try": 0, "caused_fix": 0, "hidden": 0, "minutes": []}


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
            row["hidden"] += bool(req.get("hidden_removed"))
            if state == "merged":
                row["first_try"] += _first_try(t, ships)
                row["minutes"].append(max(0.0, (merged_at[nn] - parse_iso(req["at"]).timestamp()) / 60))
    for row in [*groups.values(), *channels.values(), *agents.values()]:
        minutes = row.pop("minutes")
        row["median_minutes"] = round(statistics.median(minutes), 1) if minutes else None
        offered = row["accepted"] + row["edited"] + row["rejected"]
        row["acceptance"] = round(row["accepted"] / offered, 3) if offered else None
    return {"groups": groups, "channels": dict(sorted(channels.items())), "agents": dict(sorted(agents.items()))}


def dev_broken(tickets, merged_at, start):
    """How long dev stayed broken after a failed deploy: from the smoke check's issue to the merge of the revert the
    intake filed for it. The requested event keeps the issue's own time as `opened`."""
    minutes = []
    for nn, t in tickets.items():
        req = t.last("requested") or {}
        if (str(req.get("external_id") or "").startswith("smoke#") and req.get("opened") and nn in merged_at
                and (start is None or merged_at[nn] >= start)):
            minutes.append(max(0.0, (merged_at[nn] - parse_iso(req["opened"]).timestamp()) / 60))
    return {"reverts": len(minutes), "median_minutes": round(statistics.median(minutes), 1) if minutes else None}


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


def collect(project, tickets, since=None, states=None, now=None):
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
    # Merged AUTO tickets over [size] cap and under it, by the size they last shipped with, and how many of each were
    # reverted afterwards or named in a later ticket's caused_by: size raises no tier, so this shows what it costs.
    cap = project.config["size"]["cap"]
    sizes = {side: {"merged": 0, "reverted_or_fixed": 0} for side in ("over", "under")}
    caused = {str(t.ticket.get("caused_by")) for t in tickets.values() if t.ticket and t.ticket.get("caused_by")}
    blocking, advisory, parked, disputes = Counter(), Counter(), 0, Counter()
    rounds, evidence, by_reason = [], Counter(), {}  # review runs per reviewed ticket; blocking evidence re-run; PERSON
    situations = Counter()
    # What became of the merged tickets, by tier, and by what did the work. A ticket is old enough to count as held
    # once it has been merged for [stats] held_days: before that it has had no time to fail.
    held_days = project.config["stats"]["held_days"]
    old = (now if now is not None else time.time()) - held_days * 86400
    outcomes = {tier: _outcome_row() for tier in TIERS}
    by_worker, by_profile, names_cause, counted = {}, {}, 0, []
    fixed_by_person, under = _held_a_kind(tickets), {"tickets": 0, "kinds": Counter()}
    workers, acted = {}, {"tickets": 0, "cost_usd": 0.0}  # worker runs by model and effort; tickets a person acted on
    flaky = {}  # command -> the merged tickets it was flaky on, its flakes and its runs at ship
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
        if ledger.runs("review"):
            rounds.append(len(ledger.runs("review")))
        if tier == "PERSON":
            nothing = _person_changed_nothing(t)
            for reason in _person_reasons(t) or ["?"]:
                counts = by_reason.setdefault(reason, {"tickets": 0, "changed_nothing": 0})
                counts["tickets"] += 1
                counts["changed_nothing"] += nothing
        person = any(e.get("event") == "continued" or (e.get("event") == "accepted" and e.get("by") == "person")
                     or (e.get("event") == "finding" and e.get("by") == "owner") for e in t.events)
        row["no_person"] += tier == "AUTO" and not person
        if tier == "AUTO" and nn in fixed_by_person:
            under["tickets"] += 1
            under["kinds"].update(set(fixed_by_person[nn]))
        row["first_try"] += _first_try(t, ships)
        row["reverted"] += nn in reverted
        if tier == "AUTO" and ships and isinstance(ships[-1].get("size"), int):
            side = sizes["over" if ships[-1]["size"] > cap else "under"]
            side["merged"] += 1
            side["reverted_or_fixed"] += nn in reverted or nn in caused
        counted.append(nn)
        review_usd, worker_usd = _cost(t)
        found_flakes = flakes.of(t.events)
        for name, n in flakes.runs(t.events).items():
            if found_flakes or name in flaky:
                flaky.setdefault(name, {"tickets": 0, "flakes": 0, "runs": 0})["runs"] += n
        for name in dict.fromkeys(flakes.name(x) for x in found_flakes):
            flaked = flaky.setdefault(name, {"tickets": 0, "flakes": 0, "runs": 0})
            flaked["tickets"] += 1
            flaked["flakes"] += sum(flakes.name(x) == name for x in found_flakes)
        if _acts(t):
            acted["tickets"] += 1
            acted["cost_usd"] += review_usd + worker_usd
        for e in t.events:
            if e.get("event") == "worked":
                rung = ":".join(part for part in (e.get("model"), e.get("effort")) if part) or NO_MODEL
                w = workers.setdefault(rung, {"runs": 0, "cost_usd": 0.0, "minutes": 0.0, "turns": 0, "budget": 0,
                                              "timeout": 0, "error": 0, "resumed": 0, "resume_failed": 0})
                w["runs"] += 1
                w["cost_usd"] += e.get("cost_usd") or 0
                w["minutes"] += e.get("minutes") or 0
                if e.get("end") in ("turns", "budget", "timeout", "error"):
                    w[e["end"]] += 1
                w["resumed"] += bool(e.get("resumed"))
                w["resume_failed"] += bool(e.get("resume_failed"))
        names_cause += bool(t.ticket and t.ticket.get("caused_by"))
        for out in (outcomes[tier], by_worker.setdefault(_worker_of(t), _outcome_row()),
                    *[by_profile.setdefault(name, _outcome_row()) for name in _profiles_of(project, t)]):
            out["merged"] += 1
            out["reverted"] += nn in reverted
            out["caused_fix"] += nn in caused
            out["old_enough"] += merged_at[nn] <= old
            out["held"] += merged_at[nn] <= old and nn not in reverted and nn not in caused
            out["first_try"] += _first_try(t, ships)
            out["review_usd"] += review_usd
            out["worker_usd"] += worker_usd
            out["acts"].append(_acts(t))
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
                if "reproduced" in (finding.get("evidence") or {}):  # the engine ran the evidence again
                    evidence["rerun"] += 1
                    evidence["reproduced"] += finding["evidence"]["reproduced"] is True
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
    overturned, disputed = disputes["dismissed"] + disputes["parked"], sum(disputes.values())
    return {
        "since": since, "merged": merged, "left_out": len(tickets) - merged,
        "outcomes": {"held_days": held_days, "tiers": {tier: _outcome_done(row) for tier, row in outcomes.items()},
                     "names_cause": names_cause, "by_worker": _split(by_worker), "by_profile": _split(by_profile)},
        "time": timing.collect(tickets, merged_at, counted),
        "dev_broken": dev_broken(tickets, merged_at, start),
        # Commands that both failed and passed on the same code, in the merged tickets: flakes of the runs counted.
        "flakes": {name: dict(row, share=round(row["flakes"] / row["runs"], 3) if row["runs"] else None)
                   for name, row in sorted(flaky.items()) if row["flakes"]},
        # What rail work's runs on the merged tickets reported, by model and effort, and what the tickets a person
        # acted on cost. A session a person drives records no cost.
        "worker": {"runs": {name: _rounded(workers[name]) for name in sorted(workers)},
                   "person_acted": {"tickets": acted["tickets"], "cost_usd": round(acted["cost_usd"], 4)}},
        "tiers": tiers, "raised": dict(raised), "drops": drops(tickets, start),
        # AUTO tickets a later PERSON ticket names as its cause, by that ticket's kinds: nobody was asked.
        "auto_held_a_kind": {"tickets": under["tickets"], "kinds": dict(sorted(under["kinds"].items()))},
        "base_checks": base, "adopted": adopted, "split": split, "size": {"cap": cap, **sizes},
        "guides": {"situations": dict(sorted(situations.items()))},
        "grilling": grilling(tickets, states or {}, merged_at, start),
        "sources": by_source(project, tickets, states or {}, merged_at, reverted, start),
        "consults": consults, "steps": {name: steps[name] for name in sorted(steps, key=_step_rank)},
        # Per reason a ticket was PERSON: its merged tickets, and those where the person changed nothing.
        "person_changed_nothing": dict(sorted(by_reason.items())),
        "review": {
            "roles": {name: _rounded(roles[name]) for name in REVIEW_STEPS if name in roles},
            "models": {name: _rounded(models[name]) for name in sorted(models)},
            "cost_usd": round(sum(role["cost_usd"] for role in roles.values()), 4),
            "blocking": {"total": sum(blocking.values()), **dict(blocking)},
            "advisory": {"total": sum(advisory.values()), **dict(advisory)},
            "parked": parked, "disputes": dict(disputes),
            # Disputes the refuter dismissed or parked, of all its verdicts.
            "refuter_overturns": round(overturned / disputed, 3) if disputed else None,
            # Review runs per merged ticket the reviewer read: the median, and the share merged after one run.
            "rounds": {"tickets": len(rounds), "median": statistics.median(rounds) if rounds else None,
                       "one_run": round(rounds.count(1) / len(rounds), 3) if rounds else None},
            # Blocking findings whose evidence the engine ran again, and those whose re-run showed the quoted output.
            "evidence": {"rerun": evidence["rerun"], "reproduced": evidence["reproduced"],
                         "share": round(evidence["reproduced"] / evidence["rerun"], 3) if evidence["rerun"] else None},
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
    hidden = {name: r["hidden"] for name, r in data["grilling"]["channels"].items() if r["hidden"]}
    if hidden:
        lines += ["", "Tickets whose request had hidden text removed at intake (HTML comments a reader of the page"
                      " doesn't see): " + ", ".join(f"{name} {count}" for name, count in hidden.items()) + "."]
    return lines


DROPPED_BY = (("engine", "by the engine at the retry cap"), ("agent", "by an agent"), ("person", "by a person"),
              ("?", "with no record of who"))


def render_drops(data):
    found = data["drops"]
    if not found["total"]:
        return []
    line = f"Dropped: {found['total']}. " + _listed(found["by"], DROPPED_BY)
    if found["cost_usd"]:
        line += f" Their runs reported ${found['cost_usd']:.2f}."
    if found["stuck_steps"]:
        line += " The engine's drops, by the step that kept failing: " + ", ".join(
            f"{step} {n}" for step, n in found["stuck_steps"].items()) + "."
    return [line]


def render_flakes(data):
    rows = data["flakes"]
    if not rows:
        return []
    return ["", *_table(["FLAKES", "tickets", "flakes", "runs", "share"], [
        [name if len(name) <= 60 else name[:57] + "...", r["tickets"], r["flakes"], r["runs"], _pct(r["share"])]
        for name, r in rows.items()])]


def render_worker(data):
    """What the worker runs of the merged tickets cost and how they ended, once rail work ran one."""
    runs = data["worker"]["runs"]
    if not runs:
        return []
    ends = ["turns", "budget", "timeout", "error"]
    lines = ["", *_table(["WORKER", "runs", "cost", "time", "hit turns", "hit budget", "timed out", "errors", "resumed"], [
        [name, w["runs"], f"${w['cost_usd']:.2f}", _span(w["minutes"]), *[w[end] for end in ends], w["resumed"]]
        for name, w in runs.items()])]
    failed = sum(w["resume_failed"] for w in runs.values())
    if failed:
        lines.append(f"Runs that could not resume their session and started fresh: {failed}.")
    acted = data["worker"]["person_acted"]
    if acted["tickets"]:
        lines.append(f"Merged tickets a person acted on: {acted['tickets']}, whose runs reported"
                     f" ${acted['cost_usd']:.2f}.")
    return lines


def render_sources(data):
    rows = data["sources"]
    head = ["filed", "merged", "reverted", "dropped", "open"]
    return ["", *_table(["SOURCES", *head], [[name, *[r[k] for k in head]] for name, r in rows.items()])] if rows else []


def render_guides(data):
    """How many merged tickets each guide was named for, once any was."""
    situations = data["guides"]["situations"]
    if not situations:
        return []
    return ["", "Guides named: " + ", ".join(f"{name} {n}" for name, n in situations.items()) + "."]


def _money(value):
    return "-" if value is None else f"${value:.2f}"


def render_outcomes(data):
    """What became of the merged tickets: the first thing to read."""
    out = data["outcomes"]
    rows = list(out["tiers"].values())
    days = out["held_days"]
    lines = _table(["OUTCOMES", *out["tiers"]], [
        ["merged", *[r["merged"] for r in rows]],
        ["reverted afterwards", *[r["reverted"] for r in rows]],
        ["caused a fix ticket", *[r["caused_fix"] for r in rows]],
        [f"held, of those merged {days} days ago or more", *[f"{r['held']} of {r['old_enough']}" for r in rows]],
        ["cost for each merged ticket", *[_money(r["cost_per_ticket"]) for r in rows]],
        ["a person's acts, median for a ticket", *["-" if r["acts"]["median"] is None else f"{r['acts']['median']:g}"
                                                   for r in rows]],
        ["tickets with no act of a person", *[r["acts"]["none"] for r in rows]]])
    lines.append(f"Merged tickets that name the ticket that caused them (caused_by): {out['names_cause']} of"
                 f" {data['merged']}.")
    broken = data.get("dev_broken") or {}
    if broken.get("reverts"):
        lines.append(f"Failed dev deploys reverted: {broken['reverts']}, a median of {broken['median_minutes']:g} minutes"
                     f" from the smoke check's issue to the revert's merge.")
    head = ["merged", "reverted", "caused a fix", "first try", "cost each"]
    for title, split in (("BY WORKER", out["by_worker"]), ("BY LANGUAGE", out["by_profile"])):
        if split:
            lines += ["", *_table([title, *head], [
                [name, r["merged"], r["reverted"], r["caused_fix"], r["first_try"], _money(r["cost_per_ticket"])]
                for name, r in split.items()])]
    return lines + [""]


def render(data):
    when = f" since {data['since']}" if data["since"] else ""
    if not data["merged"]:
        grill = render_drops(data) + render_sources(data) + render_grilling(data)
        if grill:
            return "\n".join([f"Rail stats: no ticket has merged{when} yet.", *grill])
        return f"No ticket has merged{when}, so there is nothing to count yet."
    tiers, review = data["tiers"], data["review"]
    head = f"Rail stats: {data['merged']} merged ticket{'' if data['merged'] == 1 else 's'}{when}."
    if data["left_out"]:
        head += f" Not counted: {data['left_out']} {'merged earlier or not merged' if data['since'] else 'not merged'}."
    lines = [head, "", *render_outcomes(data)]
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
        lines.append(f"Offered a split over [size] cap: {split['offered']}. Shipped AUTO afterwards: {split['auto']}."
                     + (f" Became PERSON for size, under an older engine: {split['person']}." if split["person"] else ""))
    held = data["auto_held_a_kind"]
    if held["tickets"]:
        lines.append(f"AUTO tickets that held a kind (a later PERSON ticket names one as its cause): {held['tickets']}"
                     f" ({', '.join(f'{kind} {n}' for kind, n in held['kinds'].items())}).")
    over, under = data["size"]["over"], data["size"]["under"]
    if over["merged"]:
        lines.append(f"AUTO tickets over [size] cap of {data['size']['cap']}: {over['merged']} merged,"
                     f" {over['reverted_or_fixed']} reverted or named in a later ticket's caused_by. Under it:"
                     f" {under['merged']} merged, {under['reverted_or_fixed']}.")
    lines += render_drops(data)
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
    lines += timing.render(data["time"], _table)
    lines += render_flakes(data)
    lines += render_worker(data)
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
            ("dismissed", "the refuter dismissed"), ("parked", "parked"), ("upheld", "upheld")))
            + f" Refuter overturns: {_pct(review['refuter_overturns'])}.")
    rounds, evidence = review["rounds"], review["evidence"]
    if rounds["tickets"]:
        lines.append(f"Rounds to pass: median {rounds['median']:g} review runs for each ticket the reviewer read;"
                     f" {_pct(rounds['one_run'])} merged after one run.")
    if evidence["rerun"]:
        lines.append(f"Evidence reproduced: {evidence['reproduced']} of {evidence['rerun']} blocking findings whose"
                     f" evidence the engine ran again ({_pct(evidence['share'])}).")
    if data["person_changed_nothing"]:
        lines.append("PERSON tickets where the person changed nothing, by why they were PERSON: " + ", ".join(
            f"{reason} {r['changed_nothing']} of {r['tickets']}" for reason, r in data["person_changed_nothing"].items())
            + ".")
    lines += render_sources(data) + render_grilling(data)
    return "\n".join(line.rstrip() for line in lines)
