"""Where the time of merged tickets went, for `rail stats`.

Every line is read from events the journal already holds: nothing is timed for this. The lines overlap (a ship step
runs between the first ship and the merge, and so does a wait for a person), so their shares don't add up to 100%.
"""

import statistics

from .util import globs_overlap, parse_iso

PERSON_ACTS = ("accepted", "continued")
NOT_RECORDED = "(not recorded)"


def _at(e):
    try:
        return parse_iso(e["at"]).timestamp()
    except (KeyError, TypeError, ValueError):
        return None


def _first(t, name, after=None):
    """When the ticket's first event of that name was written, at or after `after`."""
    for e in t.events:
        at = _at(e) if e.get("event") == name else None
        if at is not None and (after is None or at >= after):
            return at
    return None


def _scope(t):
    accepted = next((e for e in t.events if e.get("event") == "accepted"), {})
    return accepted.get("scope_paths") or (sorted(t.ticket.scope) if t.ticket else [])


def _wait_code(t, i):
    """The code of the wait the person's act at events[i] answered. An act of an older engine doesn't say: an
    approval is then the contract's when it is the ticket's first, an amend's otherwise."""
    e = t.events[i]
    if e.get("wait"):
        return e["wait"]
    if e.get("event") == "accepted":
        return "APPROVE_AMEND" if any(x.get("event") == "accepted" for x in t.events[:i]) else "APPROVE_CONTRACT"
    return NOT_RECORDED


def collect(tickets, merged_at, counted):
    """The time lines for the merged tickets in `counted`, slowest first. `tickets` is every ticket, since a ticket
    waits behind others: a ticket held another back while it was claimed and neither merged nor dropped."""
    busy = {}  # ticket id -> (first claim, when it merged or was dropped or None, scope)
    for nn, t in tickets.items():
        claim = _first(t, "claimed")
        if claim is not None:
            busy[nn] = (claim, merged_at.get(nn) or _first(t, "dropped"), _scope(t))
    lines, total, spans, rebases = {}, 0.0, [], 0

    def add(key, label, seconds):
        line = lines.setdefault(key, {"key": key, "label": label, "values": []})
        line["values"].append(max(0.0, seconds))

    for nn in counted:
        t = tickets[nn]
        start = _first(t, "requested") or next((at for at in map(_at, t.events) if at is not None), None)
        if start is None:
            continue
        span = max(0.0, merged_at[nn] - start)
        spans.append(span)
        total += span
        accepted = _first(t, "accepted")
        claimed = _first(t, "claimed", accepted) if accepted is not None else None
        if claimed is not None:
            scope = _scope(t)
            behind = any(other != nn and began < claimed and (ended is None or ended > accepted)
                         and any(globs_overlap(a, b) for a in scope for b in theirs)
                         for other, (began, ended, theirs) in busy.items())
            if behind:
                add("claim_behind_overlap", "accepted to claimed, behind a ticket with an overlapping scope",
                    claimed - accepted)
            else:
                add("claim", "accepted to claimed, with no overlapping ticket open", claimed - accepted)
        shipped = _first(t, "shipped")
        if shipped is not None:
            add("shipped_to_merged", "first ship to merge", merged_at[nn] - shipped)
        for i, e in enumerate(t.events):
            kind, at = e.get("event"), _at(e)
            if kind == "step" and isinstance(e.get("duration_ms"), (int, float)):
                add(f"step:{e.get('step')}", f"step {e.get('step')}, each run", e["duration_ms"] / 1000)
                rebases += e.get("step") == "rebase" and shipped is not None and at is not None and at > shipped
            elif kind == "worked" and isinstance(e.get("minutes"), (int, float)):
                add("worker", "worker run (rail work), each run", e["minutes"] * 60)
            elif (kind == "continued" or (kind == "accepted" and e.get("by") == "person")) and i and at is not None:
                before = _at(t.events[i - 1])
                if before is not None:
                    code = _wait_code(t, i)
                    add(f"person:{code}", f"waiting for a person, {code}", at - before)
    rows = []
    for line in lines.values():
        values = line.pop("values")
        spent = sum(values)
        rows.append({**line, "count": len(values), "median_secs": round(statistics.median(values), 1),
                     "per_ticket_secs": round(spent / len(spans), 1) if spans else None,
                     "share": round(spent / total, 3) if total else None})
    rows.sort(key=lambda row: (-(row["share"] or 0), row["key"]))
    return {"tickets": len(spans), "request_to_merge_secs": round(statistics.median(spans), 1) if spans else None,
            "lines": rows, "rebases_after_ship": round(rebases / len(spans), 2) if spans else None}


def _span(seconds):
    if seconds is None:
        return "-"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(round(seconds / 60))
    if minutes < 60:
        return f"{minutes}m"
    if minutes < 1440:
        return f"{minutes // 60}h{minutes % 60:02d}m"
    return f"{minutes // 1440}d{minutes % 1440 // 60}h"


def render(data, table):
    if not data["lines"]:
        return []
    lines = ["", *table(["WHERE THE TIME GOES", "times", "median", "for each ticket", "share"], [
        [row["label"], row["count"], _span(row["median_secs"]), _span(row["per_ticket_secs"]),
         "-" if row["share"] is None else f"{row['share']:.0%}"] for row in data["lines"]])]
    lines.append(f"Share: of the time from request to merge, median {_span(data['request_to_merge_secs'])} over"
                 f" {data['tickets']} ticket{'' if data['tickets'] == 1 else 's'}. The lines overlap, so the shares"
                 " don't add up to 100%.")
    if data["rebases_after_ship"]:
        lines.append(f"Rebases after the first ship: {data['rebases_after_ship']:g} for each merged ticket.")
    return lines
