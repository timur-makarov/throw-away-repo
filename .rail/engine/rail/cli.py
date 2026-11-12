"""The `rail` verbs. Every verb answers in one JSON shape (plan, section 6) with --json, or as text without it.

Exit codes: 0 when the command worked (read `owner`), 2 for a usage error, 3 when a step failed.
"""

import argparse
import json
import os
import re
import subprocess
import sys

from . import areas, gitx, hooks, steps
from .project import Project, event, events_path, ticket_path
from .state import OPEN, derive, floor
from .table import TRANSITIONS, first_match
from .ticket import Ticket, branch_name, highest, lint, rank, with_id, with_tier
from .util import RailError, age, match_any

VERBS = ("init", "add", "accept", "amend", "answer", "next", "advance", "status", "context", "drop", "doctor", "ci",
         "consult", "docs", "intake", "sweep")
STALE_DAYS = 3


def answer(ticket=None, state=None, owner="none", action=None, code="NO_WORK", steps_=None, cwd=None, **extra):
    result = {
        "schema_version": 1, "ok": True, "ticket": ticket, "state": state, "owner": owner, "cwd": cwd,
        "action": action or {"kind": "rest", "brief": ""}, "reason": {"code": code}, "steps": steps_ or [],
    }
    result.update(extra)
    return result


def from_facts(f, steps_=None, code=None, **extra):
    row_code, owner, action = first_match(f)
    cwd = "." if row_code == "MERGE" else f.cwd  # the merge removes the worktree, so it runs from the project's root
    return answer(f.id, f.state, owner, action, code or row_code, steps_, cwd, tier=f.tier, **extra)


# --- finding the ticket ----------------------------------------------------------


def ticket_from_cwd(project):
    cwd = os.path.realpath(os.getcwd())
    base = os.path.realpath(os.path.join(project.root, ".claude", "worktrees"))
    if cwd.startswith(base + os.sep):
        return os.path.relpath(cwd, base).split(os.sep)[0]
    head = gitx.git(["rev-parse", "--abbrev-ref", "HEAD"], cwd, check=False).stdout.strip()
    m = re.match(r"^(\d+)-", head)
    return m.group(1) if m else None


def requested(project, args):
    """--ticket, then RAIL_TICKET, then the worktree the command runs in (plan, section 6)."""
    return getattr(args, "ticket", None) or os.environ.get("RAIL_TICKET") or ticket_from_cwd(project)


def load(project, fresh_forge=True):
    """Tickets and their facts. The forge is read again each time, unless `fresh_forge` is False."""
    from .forge import Forge

    if fresh_forge or getattr(project, "forge", None) is None:
        project.forge = Forge(project)
    tickets = project.tickets()
    return tickets, derive(project, tickets)


# --- moves `next` makes itself -------------------------------------------------------


def ensure_local(project, t):
    """Make the local ticket branch, and fast-forward it to the remote one when that is ahead."""
    if t.remote_branch and project.remote:
        remote_tip = gitx.rev(f"refs/remotes/{project.remote}/{t.remote_branch}", project.root)
        if not t.branch:
            t.branch = t.remote_branch
            gitx.update_ref(project.root, f"refs/heads/{t.branch}", remote_tip, None)
        else:
            local_tip = gitx.rev(f"refs/heads/{t.branch}", project.root)
            if local_tip != remote_tip and gitx.ok(["merge-base", "--is-ancestor", local_tip, remote_tip], project.root):
                if t.worktree:
                    gitx.git(["merge", "--quiet", "--ff-only", remote_tip], t.worktree)
                else:
                    gitx.update_ref(project.root, f"refs/heads/{t.branch}", remote_tip, local_tip)
    t.ref = f"refs/heads/{t.branch}"


def claim(project, t, takeover=False):
    """A claim is a commit with the `claimed` event on the ticket branch, pushed (plan, section 5)."""
    for _ in range(3):
        ensure_local(project, t)
        before = gitx.rev(t.ref, project.root)
        claimed = event(t.id, "claimed", session=project.session, takeover=takeover)
        result = project.append_events(t, [claimed], "claim" if not takeover else "take over")
        if result != "rejected":
            return True
        # The branch moved on the remote: drop the local claim and look again.
        project.sync()
        remote_tip = gitx.rev(f"refs/remotes/{project.remote}/{t.remote_branch or t.branch}", project.root)
        gitx.update_ref(project.root, t.ref, remote_tip, gitx.rev(t.ref, project.root))
        fresh = project.tickets().get(t.id)
        if not fresh or fresh.last("claimed") or remote_tip == before:
            return False
        t.__dict__.update(fresh.__dict__)
    return False


def make_ready(project, t, run, fresh=False):
    """A worktree for the ticket, with setup run in it. A fresh claim starts from the current base branch: the
    branch holds only the ticket and its journal, so the rebase is clean, and an `after` ticket's merged work is
    there from the start."""
    if not t.worktree:
        steps.make_worktree(project, t)
        base_tip = gitx.rev(project.base_ref, project.root)
        if fresh and base_tip and not gitx.ok(["merge-base", "--is-ancestor", base_tip, "HEAD"], t.worktree):
            project.note_rewrite(t.branch)
            gitx.git(["rebase", "--quiet", base_tip], t.worktree)
            if project.remote:
                project.push_branch(t.branch)
        steps.setup(project, t, run)
        if run.events:
            project.append_events(t, run.events, "setup")


def ensure_pr(project, f, receipts):
    """Every wait after add has a PR to label (plan, section 7): a contract PR at add for tiers outside auto_tiers,
    and a PR at claim for the rest."""
    from .forge import ForgeError

    forge, t = project.forge, f.t
    if not forge or not forge.ok or f.pr_open or not t.name or not gitx.rev(
            f"refs/remotes/{project.remote}/{t.name}", project.root):
        return f.pr
    if f.state == "new":
        if f.lint_errors or f.auto:
            return None
        title = f"{t.id}: [contract] {f.ticket.title}"
        body = (f"The contract of ticket {t.id} ({f.tier}). Approve it with the label `rail:go`, or say \"accept {t.id}\"."
                f" To change it, comment here. To reject it, close this pull request.\n\n{f.ticket.text}")
    elif f.state in OPEN:
        title = f"{t.id}: {f.ticket.title}"
        body = (f"{f.ticket.sections.get('Why', '')} (ticket {t.id})\n\nNot shipped yet: the rail check stays red until"
                f" the ticket ships.")
    else:
        return None
    try:
        pr = forge.open_pr(t.name, title, body)
        receipts.append({"step": "pr", "status": "ran", "result": "pass", "detail": f"opened #{pr['number']}"})
        return pr
    except ForgeError as e:
        receipts.append({"step": "pr", "status": "unavailable", "detail": str(e)[:200]})
        return None


def update_pr(project, f, receipts):
    """At ship, the PR's title loses [contract] and its description becomes the ticket's (plan, section 9)."""
    from .forge import ForgeError

    if not f.pr_open or not f.shipped:
        return
    ticket = Ticket(gitx.read_blobs([f"{f.t.ref}:{ticket_path(f.id)}"], project.root)[f"{f.t.ref}:{ticket_path(f.id)}"])
    subject, body = steps.describe(project, f.t, ticket, f.tier)
    if f.pr.get("title") == subject and f.pr.get("body") == body:
        return
    try:
        project.forge.update_pr(f.pr["number"], title=subject, body=body)
    except ForgeError as e:
        receipts.append({"step": "pr", "status": "unavailable", "detail": str(e)[:200]})


def person_comments(project, f):
    """PR comments since the ticket's last journal event: what a person said during the wait."""
    if not f.pr:
        return ""
    since = f.t.events[-1]["at"] if f.t.events else ""
    said = [c["body"].strip() for c in project.forge.comments(f.pr["number"])
            if c.get("created_at", "") >= since and c.get("body")]
    return "\n".join(said)


def transition(project, f, code):
    """Make one of the moves the table leaves to `next`. False when another clone got there first."""
    t = f.t
    run = steps.Run(project, t)
    if code == "ACCEPT_AUTO":
        ensure_local(project, t)
        project.append_events(t, [accepted_event(t.id, f.ticket, f.tier, "engine", "lint")], "accept")
    elif code == "CONSULT":
        from . import consult
        last = [e for e in t.events if e.get("event") == "step" and e.get("step") == f.consult_due]
        question = (f"The step '{f.consult_due}' failed {f.attempts.get(f.consult_due)} times. What is wrong, and"
                    " should the agent proceed, change its approach, or stop and ask a person?")
        consult.ask(project, f, "retry_cap", f.consult_due, question, last[-1].get("detail", "") if last else "", run)
        commit(project, f, run, "consult")
    elif code == "CLAIM":
        if not claim(project, t):
            return False, run
        make_ready(project, t, run, fresh=True)
        tickets, facts = load(project)
        ensure_pr(project, facts[t.id], run.steps)
    elif code == "GO":
        # A person's rail:go: it approves a contract or an amend, or continues any other wait (plan, section 10).
        note = person_comments(project, f) or None
        ensure_local(project, t)
        if f.state == "new" or f.amend_pending:
            record = accepted_event(t.id, f.ticket, f.tier, "person", "label", note)
        else:
            record = event(t.id, "continued", via="label", **({"note": note} if note else {}))
        project.append_events(t, [record], "continue")
        for label in ("rail:go", "rail:needs-you"):
            project.forge.remove_label(f.pr["number"], label)
    elif code == "REBASE_BEHIND":
        # The base requires up-to-date branches: rebase the shipped PR with no agent work (plan, section 11).
        ensure_local(project, t)
        if not t.worktree:
            make_ready(project, t, run)
        project.note_rewrite(t.branch)
        before = project.patch_id(t.ref)
        if gitx.git(["rebase", "--quiet", gitx.rev(project.base_ref, project.root)], t.worktree, check=False).returncode:
            gitx.git(["rebase", "--abort"], t.worktree, check=False)
            run.record("rebase", False, before, "conflict while bringing the PR up to date",
                       output=f"Rebasing {t.branch} conflicts. Run rail advance {t.id}, resolve the conflict, and run it again.")
            commit(project, f, run, "rebase failed")
        else:
            run.record("rebase", True, project.patch_id(t.ref), f"onto {project.base}")
            commit(project, f, run, "rebase")
    elif code == "RESUME":
        ensure_local(project, t)
        if f.claimed_elsewhere and not claim(project, t, takeover=True):
            return False, run
        make_ready(project, t, run)
        tickets, facts = load(project)
        ensure_pr(project, facts[t.id], run.steps)
    return True, run


def settle(project, nn, explicit):
    """Read the table for one ticket, making the moves `next` makes itself, until a row names a move to report."""
    receipts, reran_setup = [], False
    for _ in range(6):
        tickets, facts = load(project)
        f = facts[nn]
        f.explicit = explicit
        code, owner, action = first_match(f)
        if code == "SETUP_FAILED" and explicit and not reran_setup:
            # `next --ticket NN` runs a failed setup again, once (the SETUP_FAILED brief says so).
            run = steps.Run(project, f.t)
            steps.setup(project, f.t, run)
            project.append_events(f.t, run.events, "setup")
            receipts += run.steps
            reran_setup = True
            continue
        if code not in TRANSITIONS:
            return f, receipts
        done, run = transition(project, f, code)
        receipts += run.steps
        if not done:
            return None, receipts
    raise AssertionError(f"ticket {nn} did not settle")


def cleanup(project, tickets, facts):
    leftovers = []
    for nn, f in facts.items():
        if f.state == "dropped" and f.pr and not f.dropped_event:
            release_issue(project, f)  # a PR closed by hand gets the same cleanup as rail drop
        if f.state in ("merged", "dropped"):
            leftovers += steps.remove_ticket(project, f.t)
    return leftovers


# --- verbs ---------------------------------------------------------------------------


def create_ticket(project, text):
    """Take the next ID and make the ticket's branch with the ticket file, without touching any checkout (plan,
    section 5). A ticket that passes lint on an auto tier is accepted at once. Returns (id, branch, push result)."""
    base_tip = gitx.rev(project.base_ref, project.root)
    if not base_tip:
        raise RailError(f"the base branch '{project.base}' has no commits yet")
    tickets = project.tickets()

    def build(nn):
        body = with_id(text, nn)
        ticket = Ticket(body)
        files = {ticket_path(nn): body}
        if not lint(ticket):
            tier = highest(ticket.tier, floor(project, ticket.scope)[0])
            if tier != ticket.tier:  # a risk or migration path raised it: the ticket says so, and that tier freezes
                body = with_tier(body, tier)
                ticket = Ticket(body)
                files[ticket_path(nn)] = body
            if tier in project.config["auto_tiers"]:
                accepted = accepted_event(nn, ticket, tier, "engine", "lint")
                files[events_path(nn)] = json.dumps(accepted, separators=(",", ":")) + "\n"
        return gitx.commit_files(project.root, base_tip, files, f"{nn}: add ticket: {ticket.title}")

    nn, commit = project.take_id(project.max_id(tickets) + 1, build)
    branch = branch_name(Ticket(with_id(text, nn)))
    if not gitx.update_ref(project.root, f"refs/heads/{branch}", commit, None):
        raise RailError(f"branch {branch} already exists")
    pushed = project.push_branch(branch) if project.remote else None
    if pushed == "ok":
        project.sync()
    return nn, branch, pushed


def cmd_add(project, args):
    if args.file == "-":
        text = sys.stdin.read()
    else:
        with open(args.file) as f:
            text = f.read()
    errors = lint(Ticket(text))
    if errors:
        return answer(owner="agent", code="TICKET_LINT",
                      action={"kind": "agent_task", "brief": "Fix the ticket, then run rail add again:\n- " + "\n- ".join(errors)},
                      steps_=[{"step": "ticket-lint", "status": "ran", "result": "fail", "detail": "; ".join(errors)}])
    project.sync()
    nn, branch, pushed = create_ticket(project, text)
    tickets, facts = load(project)
    f = facts[nn]
    receipts = [{"step": "ticket-lint", "status": "ran", "result": "pass"}]
    if pushed:
        receipts.append({"step": "push", "status": "ran" if pushed == "ok" else "unavailable",
                         **({"result": "pass"} if pushed == "ok" else {})})
    if ensure_pr(project, f, receipts):
        tickets, facts = load(project)
        f = facts[nn]
    return from_facts(f, receipts, branch=branch)


def stub(title, request, external_id, caused_by=""):
    """An intake ticket: the request verbatim, with the contract and tier for the agent to write (plan, section 6)."""
    return "\n".join(["+++", f"title = {json.dumps(title)}", 'tier = ""', "scope_paths = []",
                      f"external_id = {json.dumps(external_id)}", f"caused_by = {json.dumps(caused_by)}", "+++", "",
                      "## Request", request.strip(), "", "## Why", "", "## Done Contract", ""])


def caused_by(project, request):
    """An issue from a failed dev deploy starts with `Commit: <sha>`; the commit's Ticket: trailer caused it
    (plan, section 16)."""
    m = re.match(r"\s*Commit:\s*([0-9a-f]{7,40})", request)
    if not m:
        return ""
    body = gitx.git(["log", "-1", "--format=%B", m.group(1)], project.root, check=False).stdout
    ticket = re.search(r"^Ticket: (\d+)", body, re.M)
    return ticket.group(1) if ticket else ""


def intake_one(project, facts, title, request, external_id):
    """Make a stub ticket unless a ticket for this external id is open or merged. Returns its id, or None."""
    for f in facts.values():
        if f.ticket and f.ticket.get("external_id") == external_id and f.state != "dropped":
            return None
    nn, _, _ = create_ticket(project, stub(title, request, external_id, caused_by(project, request)))
    return nn


def cmd_intake(project, args):
    """`rail intake github` pulls issues labelled rail; `rail intake --external-id KEY --title T --brief FILE` takes
    anything else. Both are idempotent by external_id (plan, section 6)."""
    project.sync()
    tickets, facts = load(project)
    created, skipped = [], []
    if args.source == "github":
        if not (project.forge and project.forge.ok):
            raise RailError("the forge can't be reached: rail intake github needs a GitHub remote and gh", code="UNAVAILABLE")
        for issue in project.forge.issues("rail"):
            key = f"github#{issue['number']}"
            nn = intake_one(project, facts, issue["title"], issue.get("body") or "", key)
            (created if nn else skipped).append(nn or key)
            tickets, facts = load(project)
    elif args.source:
        raise RailError(f"unknown intake source '{args.source}'; use github, or --external-id with --title and --brief")
    else:
        if not (args.external_id and args.title and args.brief):
            raise RailError("rail intake needs github, or --external-id, --title and --brief")
        with open(args.brief) as f:
            request = f.read()
        nn = intake_one(project, facts, args.title, request, args.external_id)
        (created if nn else skipped).append(nn or args.external_id)
    brief = (f"New tickets from intake: {', '.join(created)}. rail next asks for each one's contract."
             if created else "Nothing new to take in.")
    return answer(code="INTAKE", owner="agent" if created else "none",
                  action={"kind": "script" if created else "rest", "brief": brief,
                          **({"command": "rail next"} if created else {})}, created=created, skipped=skipped)


def accepted_event(nn, ticket, tier, by, via, note=None):
    """An accepted event. It also keeps the scope and the Done Contract's own hash, so amend can say what changed."""
    fields = {"by": by, "via": via, "tier": tier, "contract": ticket.contract_hash(), "done": ticket.done_hash(),
              "scope_paths": sorted(ticket.scope)}
    if note:
        fields["note"] = note
    return event(nn, "accepted", **fields)


def cmd_accept(project, args):
    """A person's one act that continues any wait (plan, section 10): approve a contract or an amend, or continue."""
    project.sync()
    tickets, facts = load(project)
    nn = project.find(args.ticket or requested(project, args), tickets).id
    f = facts[nn]
    note = args.note or None
    if f.state == "new":
        if f.lint_errors:
            raise RailError(f"ticket {nn} fails ticket lint: {'; '.join(f.lint_errors)}", code="TICKET_LINT")
        events = [accepted_event(nn, f.ticket, f.tier, "person", "accept", note)]
    elif f.amend_pending:
        events = [accepted_event(nn, f.ticket, f.tier, "person", "accept", note)]
    elif f.state in OPEN and first_match(f)[1] == "human":
        events = [event(nn, "continued", via="accept", **({"note": note} if note else {}))]
    else:
        raise RailError(f"ticket {nn} is {f.state}, and nothing waits for a person", code="NOTHING_TO_ACCEPT")
    ensure_local(project, f.t)
    project.append_events(f.t, events, "accept")
    if f.pr_open:
        for label in ("rail:go", "rail:needs-you"):
            if label in f.labels:
                project.forge.remove_label(f.pr["number"], label)
    tickets, facts = load(project)
    return from_facts(facts[nn])


def cmd_answer(project, args):
    """Record how a review finding ended: fixed, declined with a reason, or parked (plan, section 8)."""
    project.sync()
    tickets, facts = load(project)
    f = facts[project.find(args.ticket, tickets).id]
    fid = args.finding.upper()
    if fid not in f.ledger.findings:
        raise RailError(f"ticket {f.id} has no finding {fid}", code="NO_FINDING")
    if args.outcome == "declined" and not args.reason:
        raise RailError("a decline needs a reason")
    by = "owner" if args.owner else "author"
    if args.outcome == "declined" and by == "author" and f.ledger.findings[fid].get("severity") == "blocking":
        # The author can't decline a blocking finding: declining disputes it, and a fresh refuter decides.
        record = event(f.id, "finding", id=fid, outcome="open", by="author", disputed=True, reason=args.reason)
    else:
        record = event(f.id, "finding", id=fid, outcome=args.outcome, by=by, reason=args.reason or "")
    ensure_local(project, f.t)
    project.append_events(f.t, [record], f"answer {fid}")
    tickets, facts = load(project)
    return from_facts(facts[f.id])


def cmd_amend(project, args):
    """Change a frozen contract (plan, section 5): the Done Contract, the scope or the tier, which only rises."""
    project.sync()
    tickets, facts = load(project)
    f = facts[project.find(args.ticket or requested(project, args), tickets).id]
    t = f.t
    if f.state in ("merged", "dropped"):
        raise RailError(f"ticket {f.id} is {f.state}; follow-up work is a new ticket with caused_by")
    path = os.path.join(t.worktree, ticket_path(t.id)) if t.worktree else None
    if args.file:
        with open(args.file) as fh:
            text = fh.read()
    elif path:
        with open(path) as fh:
            text = fh.read()
    else:
        raise RailError("edit the ticket in its worktree, or pass the new ticket with --file")
    if Ticket(text).id != t.id and not Ticket(text).errors:
        text = with_id(text, t.id)  # the engine owns the id, as at add
    new = Ticket(text)
    errors = lint(new, expect_id=t.id)
    if errors:
        return answer(t.id, f.state, "agent", {"kind": "agent_task", "brief": "Fix the ticket, then amend again:\n- "
                                                + "\n- ".join(errors)}, "TICKET_LINT", [
            {"step": "ticket-lint", "status": "ran", "result": "fail", "detail": "; ".join(errors)}], f.cwd)
    events, last = [], f.accepted
    if last:
        if rank(new.tier) < rank(last.get("tier")):
            raise RailError(f"the tier can't go below the accepted {last.get('tier')}")
        changed = [name for name, differs in (
            ("done_contract", new.done_hash() != last.get("done")),
            ("scope", sorted(new.scope) != last.get("scope_paths")),
            ("tier", rank(new.tier) > rank(last.get("tier")))) if differs]
        if not changed:
            raise RailError(f"the contract of ticket {t.id} matches the accepted one; there is nothing to amend",
                            code="NOTHING_TO_AMEND")
        tier = highest(new.tier, last.get("tier"), floor(project, new.scope)[0])
        if tier != new.tier:
            text = with_tier(text, tier)
            new = Ticket(text)
        needs = "done_contract" in changed and tier not in project.config["auto_tiers"]
        added_paths = [p for p in new.scope if p not in (last.get("scope_paths") or [])]
        events.append(event(t.id, "amended", contract=new.contract_hash(), changed=changed, added_paths=added_paths,
                            needs_approval=needs))
        if not needs:
            events.append(accepted_event(t.id, new, tier, "engine", "amend"))
    ensure_local(project, t)
    if path:
        with open(path, "w") as fh:
            fh.write(text)
        if gitx.dirty(t.worktree, exclude=[]) and gitx.git(["status", "--porcelain", "--", ticket_path(t.id)],
                                                         t.worktree).stdout.strip():
            gitx.git(["add", "--", ticket_path(t.id)], t.worktree)
            gitx.git(["commit", "--quiet", "-m", f"{t.id}: amend the contract", "--", ticket_path(t.id)], t.worktree)
    else:
        old = gitx.rev(t.ref, project.root)
        new_commit = gitx.commit_files(project.root, old, {ticket_path(t.id): text}, f"{t.id}: amend the contract")
        gitx.update_ref(project.root, t.ref, new_commit, old)
    if events:
        project.append_events(t, events, "amend")
    elif project.remote:
        project.push_branch(t.branch)
    tickets, facts = load(project)
    return from_facts(facts[t.id])


def cmd_sweep(project, args):
    """A sweep ticket over what merged without a review: the free part and one review pass (plan, section 12)."""
    from . import sweep

    project.sync()
    tickets, facts = load(project)
    start, commits = sweep.unreviewed(project)
    key = f"sweep#{start[:12]}"
    existing = next((f for f in facts.values() if f.ticket and f.ticket.get("external_id") == key
                     and f.state not in ("merged", "dropped")), None)
    if not existing:
        if not commits:
            return answer(code="NO_WORK", action={"kind": "rest", "brief": "Nothing merged without a review since the"
                                                                           " last sweep."})
        nn, _, _ = create_ticket(project, sweep.ticket_text(start, len(commits)))
    else:
        nn = existing.id
    f, receipts = settle(project, nn, explicit=True)
    if f is None or f.state != "implementing" or not f.worktree:
        return from_facts(f, receipts) if f else answer(nn, code="CLAIMED_ELSEWHERE")
    if not f.sweep_done:
        run = steps.Run(project, f.t)
        sweep.run(project, f, run)
        commit(project, f, run, "sweep")
        receipts += run.steps
    tickets, facts = load(project)
    return from_facts(facts[nn], receipts)


def cmd_consult(project, args):
    """The consult pack on request: a different model's advice on one question (plan, section 18)."""
    from . import consult

    if not os.path.exists(consult.pack(project)):
        raise RailError("the consult pack isn't installed (.rail/packs/consult)", code="NO_PACK")
    project.sync()
    tickets, facts = load(project)
    f = facts[project.find(args.ticket, tickets).id]
    if f.consults >= consult.LIMIT:
        raise RailError(f"ticket {f.id} has had its {consult.LIMIT} consults", code="CONSULT_LIMIT")
    run = steps.Run(project, f.t)
    ensure_local(project, f.t)
    advice = consult.ask(project, f, "request", None, args.question, "", run)
    commit(project, f, run, "consult")
    tickets, facts = load(project)
    return from_facts(facts[f.id], run.steps, advice=advice)


def red_base_ticket(project, facts):
    """When verify fails on the base branch, one fix ticket for the base (plan, section 7)."""
    red = project.cache_read("red-base", "base")
    if not red or red != gitx.rev(project.base_ref, project.root):
        return None
    output = project.cache_read("red-base", "output") or ""
    request = f"verify fails on {project.base} at {red[:12]}:\n\n```\n{output}\n```"
    return intake_one(project, facts, f"Make verify pass on {project.base} again", request, f"red-base#{red[:12]}")


def cmd_next(project, args):
    project.sync()
    task = init_task(project)
    if task:
        return task
    tickets, facts = load(project)
    if red_base_ticket(project, facts):
        tickets, facts = load(project)
    leftovers = cleanup(project, tickets, facts)
    explicit = requested(project, args)
    if explicit:
        nn = project.find(explicit, tickets).id
        f, receipts = settle(project, nn, explicit=True)
        if f is None:
            return answer(nn, None, "none", {"kind": "rest", "brief": f"Another session claimed ticket {nn} first."},
                          "CLAIMED_ELSEWHERE", receipts)
        return from_facts(f, receipts, leftovers=leftovers)

    # Any ticket the agent can act on comes first: this session's own, then new work in ID order.
    tickets, facts = load(project)
    mine = [f for f in facts.values() if f.state in OPEN and not f.claimed_elsewhere]
    fresh = [f for f in facts.values() if f.state in ("new", "accepted")]
    for candidate in mine + fresh:
        if first_match(candidate)[1] != "agent":
            continue
        f, receipts = settle(project, candidate.id, explicit=False)
        if f is not None and first_match(f)[1] == "agent":
            return from_facts(f, receipts, leftovers=leftovers)

    tickets, facts = load(project)
    waits, resumable, ci = [], [], []
    for f in facts.values():
        code, owner, action = first_match(f)
        if owner == "human":
            waits.append({"ticket": f.id, "needs": code, "brief": action["brief"],
                          **({"pr": f.pr["html_url"]} if f.pr else {})})
            label_wait(project, f, code)
        elif code == "CLAIMED_ELSEWHERE":
            resumable.append(f.id)
        elif code == "CI_WAIT" and f.pushed:
            ci.append(f)
    extra = {"waits": waits, "resumable": resumable, "leftovers": leftovers}
    if ci:
        run_id = ci_run(project, ci[0])
        if run_id:
            command = f"gh run watch {run_id} --exit-status; rail next"
            return answer(ci[0].id, ci[0].state, "agent", {"kind": "script", "brief": command, "command": command},
                          "CI_WAIT", **extra)
    if waits:
        brief = "Tickets wait for a person:\n" + "\n".join(f"- {w['ticket']}: {w['brief']}" for w in waits)
        return answer(owner="human", code="WAITING_HUMAN", action={"kind": "human_wait", "brief": brief}, **extra)
    from . import sweep
    is_due, _, commits = sweep.due(project)
    if is_due:
        return answer(owner="agent", code="SWEEP", action={"kind": "script", "brief": "rail sweep", "command": "rail sweep"},
                      **extra, unreviewed=len(commits))
    brief = "No ticket to work on. New work starts with: rail add <ticket file>"
    if resumable:
        brief += f"\nClaimed by other sessions, resumable with rail next --ticket NN: {', '.join(resumable)}"
    return answer(code="NO_WORK", action={"kind": "rest", "brief": brief}, **extra)


def label_wait(project, f, code):
    """The inbox is one saved search, is:open label:rail:needs-you (plan, section 10): label each wait's PR."""
    from .forge import ForgeError

    if f.pr_open and code != "HOLD" and "rail:needs-you" not in f.labels:
        try:
            project.forge.add_labels(f.pr["number"], ["rail:needs-you"])
        except ForgeError:
            pass


def ci_run(project, f):
    """The Actions run on the ticket's PR head, for `gh run watch`."""
    from .forge import ForgeError

    try:
        runs = project.forge.call("GET", f"actions/runs?head_sha={f.pr['head']['sha']}&per_page=5") or {}
    except ForgeError:
        return None
    found = runs.get("workflow_runs") or []
    return found[0]["id"] if found else None


def commit_work(project, f, run):
    """`advance` commits the agent's in-scope changes with the NN: prefix. Changes outside scope fail."""
    t = f.t
    changes = gitx.dirty(t.worktree, exclude=[".rail/journal"])
    if not changes:
        return True
    product = [c for c in changes if not c.startswith(".rail/tickets/")]
    outside = [c for c in product if not match_any(f.ticket.scope, c)]
    if outside:
        run.record("scope", False, f.patch_id, f"outside scope: {', '.join(outside)}",
                   output=f"These changes are outside scope_paths ({', '.join(f.ticket.scope)}):\n" + "\n".join(outside)
                          + "\nUndo them, or move them to another ticket. Nothing was committed.")
        return False
    gitx.git(["add", "-A", "--", ".", ":(exclude).rail/journal"], t.worktree)
    gitx.git(["commit", "--quiet", "-m", f"{t.id}: {f.ticket.title}"], t.worktree)
    return True


def commit(project, f, run, message):
    """Commit a run's events and journal files to the ticket branch, and push."""
    t = f.t
    if run.events or run.files:
        project.append_events(t, run.events, message, files=run.files)
        run.events, run.files, run.rebased = [], {}, False
    elif project.remote:
        project.push_branch(t.branch)


def after_failure(project, nn, run):
    """At the retry budget, consult advises once before the agent's last attempt (plan, section 7)."""
    from . import consult

    tickets, facts = load(project)
    f = facts[nn]
    if not f.consult_due:
        return None
    step, output = run.failure if run.failure else (f.consult_due, "")
    question = (f"The step '{f.consult_due}' failed {f.attempts.get(f.consult_due)} times. What is wrong, and should the"
                " agent proceed, change its approach, or stop and ask a person?")
    advice = consult.ask(project, f, "retry_cap", f.consult_due, question, output, run)
    commit(project, f, run, "consult")
    return advice


def review_stage(project, f, run):
    """One review action: the refuter for a disputed finding, or the run of the role the patch still needs."""
    from . import review

    disputed = f.ledger.disputed()
    if disputed:
        return review.run(project, f, "refuter", run, disputed=disputed[0])
    role = f.ledger.needed_run(f.patch_id, f.tier)
    return review.run(project, f, role, run) if role else None


def merge_stage(project, f, run):
    """Squash-merge with no remote. When the base moved since ship, rebase and ship again first (plan, section 10)."""
    base_tip = gitx.rev(project.base_ref, project.root)
    if not gitx.ok(["merge-base", "--is-ancestor", base_tip, f.t.ref], project.root):
        steps.ship(project, f, run)
        commit(project, f, run, "ship" if run.ok else "ship failed")
        if not run.ok:
            return None
        tickets, facts = load(project)
        f = facts[f.id]
        if first_match(f)[0] != "MERGE":
            return None
    return steps.merge_local(project, f, run)


def forge_merge(project, f, receipts):
    """auto_tiers, once CI is green: the async merge endpoint, the head pinned with sha (plan, section 7). The request
    is noted in the local cache, not the journal, because a journal commit would move the head CI just passed."""
    import time

    pr = f.pr
    ticket = Ticket(gitx.read_blobs([f"{f.t.ref}:{ticket_path(f.id)}"], project.root)[f"{f.t.ref}:{ticket_path(f.id)}"])
    subject, body = steps.describe(project, f.t, ticket, f.tier)
    requested, why = project.forge.merge(pr["number"], pr["head"]["sha"], f"{subject} (#{pr['number']})", body)
    if requested:
        project.cache_write("merge", f.id, f"{pr['head']['sha']} {int(time.time())}")
        receipts.append({"step": "merge", "status": "ran", "result": "pass", "detail": f"requested for #{pr['number']}"})
        project.sync()
        tickets, facts = load(project)
        nf = facts[f.id]
        leftovers = steps.remove_ticket(project, nf.t) if nf.state == "merged" else []
        tickets, facts = load(project)
        return from_facts(facts[f.id], receipts, leftovers=leftovers)
    receipts.append({"step": "merge", "status": "ran", "result": "fail", "detail": why[:300]})
    tickets, facts = load(project)
    nf = facts[f.id]
    if nf.state != "merge-ready":
        return from_facts(nf, receipts)  # a conflict or a red check: back to implementing
    return answer(f.id, nf.state, "human", {"kind": "human_wait", "brief": f"GitHub refused the merge of PR #{pr['number']}:"
                  f" {why}. A person looks, then continues: rail accept {f.id}"}, "MERGE_FAILED", receipts, nf.cwd,
                  tier=nf.tier)


def cmd_advance(project, args):
    """Run the step the ticket's state calls for: ship, then the review runs it needs, or the merge."""
    project.sync()
    tickets, facts = load(project)
    key = requested(project, args)
    if not key:
        mine = [f for f in facts.values() if f.state in OPEN and f.claimed and not f.claimed_elsewhere]
        if len(mine) != 1:
            raise RailError("which ticket? Run it in the ticket's worktree, or pass --ticket NN")
        key = mine[0].id
    nn = project.find(key, tickets).id
    receipts, first = [], True
    for _ in range(12):
        tickets, facts = load(project)
        f = facts[nn]
        f.explicit = True
        code, owner, _ = first_match(f)
        mine = bool(f.worktree) and not f.claimed_elsewhere
        run = steps.Run(project, f.t)
        if f.state == "implementing" and mine and owner == "agent":
            stage = "ship"
            if commit_work(project, f, run):
                tickets, facts = load(project)
                f = facts[nn]
                steps.ship(project, f, run)
        elif code == "REVIEW" and mine:
            stage = "review"
            review_stage(project, f, run)
        elif code == "MERGE" and first and project.remote and f.pr_open:
            return forge_merge(project, f, receipts)
        elif code == "MERGE" and first and mine and not project.remote:
            merged = merge_stage(project, f, run)
            receipts += run.steps
            if not merged:
                if run.failure and run.failure[0] == "merge":
                    return answer(nn, f.state, "human", {"kind": "human_wait", "brief": run.failure[1]}, "MERGE_FAILED",
                                  receipts, f.cwd, tier=f.tier)
                break
            tickets, facts = load(project)
            leftovers = steps.remove_ticket(project, facts[nn].t)
            tickets, facts = load(project)
            return from_facts(facts[nn], receipts, leftovers=leftovers, merge_commit=merged)
        else:
            if first and f.state == "in-ci":
                receipts.append({"step": "ci", "status": "unavailable", "detail": "the forge comes in Phase 5"})
            break
        first = False
        commit(project, f, run, stage if run.ok else f"{stage} failed")
        receipts += run.steps
        if run.failure and run.failure[1] and run.steps[-1].get("detail") == "timeout":
            continue  # a review run that timed out is started once more; two in a row wait for a person
        if run.failure:
            advice = after_failure(project, nn, run)
            receipts += [s for s in run.steps if s["step"] == "consult"]
            tickets, facts = load(project)
            nf = facts[nn]
            if stage == "ship":
                brief = steps.ship_failed_brief(nf.t, run)
                if advice:
                    brief += f"\n\n{advice}"
                code_, owner_, action_ = first_match(nf)
                if owner_ == "human":
                    return from_facts(nf, receipts)
                return answer(nn, nf.state, "agent", {"kind": "agent_task", "brief": brief}, "STEP_FAILED", receipts,
                              nf.cwd, tier=nf.tier)
            update_pr(project, nf, receipts)
            result = from_facts(nf, receipts)
            if advice:
                result["action"]["brief"] += f"\n\n{advice}"
            return result
        tickets, facts = load(project)
        if first_match(facts[nn])[0] not in ("REVIEW",):
            break
    tickets, facts = load(project)
    update_pr(project, facts[nn], receipts)
    return from_facts(facts[nn], receipts)


def cmd_status(project, args):
    project.sync()
    tickets, facts = load(project)
    rows, leftovers = [], []
    for nn, f in facts.items():
        t = f.t
        code, owner, action = first_match(f)
        last = t.events[-1]["at"] if t.events else ""
        note = ""
        if owner == "human":
            note = f"waiting: {code.lower().replace('_', ' ')}"
        elif f.state == "implementing" and not t.worktree:
            note = "STALE: no worktree found"
        elif f.state in OPEN and last and age(last).endswith("d") and int(age(last)[:-1]) >= STALE_DAYS:
            note = f"STALE: no event for {age(last)[:-1]} days"
        elif f.state in ("new", "accepted") and code in ("WAITING_AFTER", "SCOPE_OVERLAP"):
            note = action["brief"]
        if f.pr and not note:
            note = f"PR #{f.pr['number']}"
        rows.append({"ticket": nn, "title": t.ticket.title if t.ticket else "", "state": f.state, "owner": owner,
                     "tier": f.tier, "last_event": age(last), "branch": t.name, "note": note,
                     **({"pr": f.pr["html_url"]} if f.pr else {})})
        if f.state in ("merged", "dropped"):
            if t.worktree:
                leftovers.append({"kind": "worktree", "ref": project.rel(t.worktree), "reason": f"ticket {nn} {f.state}"})
            if t.branch:
                leftovers.append({"kind": "branch", "ref": t.branch, "reason": f"ticket {nn} {f.state}"})
            if t.remote_branch:
                leftovers.append({"kind": "remote branch", "ref": t.remote_branch, "reason": f"ticket {nn} {f.state}"})
    for branch in project.orphans:
        leftovers.append({"kind": "branch", "ref": branch, "reason": "no ticket; left for you"})
    return answer(code="STATUS", tickets=rows, leftovers=leftovers)


def cmd_context(project, args):
    key = args.ticket or requested(project, args)
    if key:
        tickets = project.tickets()
        t = project.find(key, tickets)
        found = areas.context(project, t.ref or project.base_ref, t.ticket.scope if t.ticket else [])
        return answer(t.id, code="CONTEXT", **found)
    return answer(code="CONTEXT", **areas.context(project, project.base_ref))


def cmd_drop(project, args):
    project.sync()
    tickets, facts = load(project)
    f = facts[project.find(args.ticket or requested(project, args), tickets).id]
    if f.state == "merged":
        raise RailError(f"ticket {f.id} is merged; follow-up work is a new ticket with caused_by", code="MERGED")
    receipts = []
    if f.state != "dropped":
        ensure_local(project, f.t)
        project.append_events(f.t, [event(f.id, "dropped", by=args.by, reason=args.reason or "")], "drop")
    if f.pr_open:
        project.forge.update_pr(f.pr["number"], state="closed")
        receipts.append({"step": "close-pr", "status": "ran", "result": "pass", "detail": f"closed #{f.pr['number']}"})
    elif project.remote and not (project.forge and project.forge.ok):
        receipts.append({"step": "close-pr", "status": "unavailable", "detail": "the forge can't be reached"})
    release_issue(project, f)
    tickets, facts = load(project)
    leftovers = steps.remove_ticket(project, facts[f.id].t)
    tickets, facts = load(project)
    return from_facts(facts[f.id], receipts, leftovers=leftovers)


def release_issue(project, f):
    """A dropped ticket from an issue: take the rail label off the issue and say so, so intake doesn't make the
    ticket again. Labelling the issue again is how to retry (plan, section 7)."""
    from .forge import ForgeError

    external = (f.ticket.get("external_id", "") if f.ticket else "") or ""
    if not external.startswith("github#") or not (project.forge and project.forge.ok):
        return
    number = external.split("#", 1)[1]
    try:
        issue = project.forge.call("GET", f"issues/{number}")
        if "rail" in {l["name"] for l in issue.get("labels", [])}:
            project.forge.remove_label(number, "rail")
            link = f.pr["html_url"] if f.pr else f"branch {f.t.name}"
            project.forge.comment(number, f"Ticket {f.id} was dropped ({link}). Label this issue `rail` again to retry.")
    except ForgeError:
        pass


def cmd_init(args):
    from . import init

    root, receipts = init.init(os.getcwd())
    project = Project(root)
    repo = None
    if project.remote:
        from . import forge
        repo = forge.github_repo(project)
        if repo:
            try:
                created = forge.create_labels(repo)
                receipts.append({"step": "labels", "status": "ran", "result": "pass",
                                 "detail": f"created {', '.join(created)}" if created else "all three exist"})
            except forge.ForgeError as e:
                receipts.append({"step": "labels", "status": "unavailable", "detail": str(e)})
    brief = ("Rail is installed. Next: rail next, which returns the init task: setup and verify, ## Areas, risk_paths,"
             " rules and .worktreeinclude, for the person to confirm.")
    return answer(code="INITIALISED", owner="agent", action={"kind": "script", "brief": brief, "command": "rail next"},
                  steps_=receipts, root=root)


def init_task(project):
    """The first `rail next` returns the init task until the project's config is on the base branch (plan, section 14)."""
    if gitx.read_blobs([f"{project.base_ref}:.rail/config.toml"], project.root).get(f"{project.base_ref}:.rail/config.toml"):
        return None
    from .init import INIT_TASK
    brief = INIT_TASK.format(base=project.base, depth=project.config["map"]["depth"])
    return answer(owner="agent", code="INIT_TASK", action={"kind": "agent_task", "brief": brief}, cwd=".")


def cmd_docs(args):
    from . import docs

    if not args.topic:
        return answer(code="DOCS", action={"kind": "rest", "brief": ""}, topic=None, text=docs.index())
    text = docs.page(args.topic, parser())
    if text is None:
        raise RailError(f"no docs topic '{args.topic}'; topics: {', '.join(docs.topics())}", code="NO_TOPIC")
    return answer(code="DOCS", action={"kind": "rest", "brief": ""}, topic=args.topic, text=text)


def cmd_doctor(project, args):
    from . import doctor

    found = doctor.checks(project)
    missing = [f"- {name}: {detail}" for name, passed, detail in found if passed is False]
    brief = "Everything Rail needs is in place." if not missing else "Fix these:\n" + "\n".join(missing)
    return answer(code="DOCTOR", action={"kind": "rest" if not missing else "human_wait", "brief": brief},
                  owner="none" if not missing else "human", steps_=doctor.as_steps(found))


def cmd_ci(project, args):
    """The `rail` check: the ship checks again, on the PR head (plan, section 11). It writes nothing."""
    from .state import raised_tier

    head = "HEAD"
    branch = os.environ.get("RAIL_BRANCH") or gitx.git(["rev-parse", "--abbrev-ref", "HEAD"], project.root).stdout.strip()
    m = re.match(r"^(\d+)-", branch)
    nn = m.group(1) if m else None
    text = gitx.read_blobs([f"{head}:{ticket_path(nn)}"], project.root).get(f"{head}:{ticket_path(nn)}") if nn else None
    run = steps.Run(project, type("T", (), {"id": nn or ""})())
    changed = project.changed_files(head)
    if text is None:
        # A PR with no ticket: the rail init PR, Dependabot, a person's own PR.
        tier, _ = raised_tier(project, changed)
        verify = project.config["commands"]["verify"]
        if project.config["commands"]["setup"]:
            steps.run_command(project, project.root, "", "setup", project.config["commands"]["setup"], run)
        if run.ok and verify:
            steps.run_command(project, project.root, "", "verify", verify, run)
        elif not verify:
            run.not_run("verify")
        brief = f"No ticket on branch {branch}. Its paths would make it {tier}."
        return answer(code="CI_NO_TICKET", action={"kind": "rest", "brief": brief}, steps_=run.steps, tier=tier)

    from .project import parse_events
    events = parse_events(gitx.read_blobs([f"{head}:{events_path(nn)}"], project.root).get(f"{head}:{events_path(nn)}"))
    patch_id = project.patch_id(head)
    shipped = [e for e in events if e.get("event") == "shipped" and e.get("patch_id") == patch_id]
    if not run.record("shipped", bool(shipped), patch_id, None if shipped else "not shipped yet",
                      output="The ticket hasn't shipped this patch: run rail advance in its worktree."):
        return answer(nn, code="CI_FAIL", action={"kind": "rest", "brief": "not shipped yet"}, steps_=run.steps)
    if project.config["commands"]["setup"]:
        steps.run_command(project, project.root, nn, "setup", project.config["commands"]["setup"], run)
    tier = shipped[-1].get("tier", "LOW")
    accepted = [e for e in events if e.get("event") == "accepted"]
    if run.ok:
        needed = steps.check(project, nn, Ticket(text), head, project.root, tier, run, patch_id,
                             accepted=accepted[-1] if accepted else None)
        if needed is not None and rank(needed) > rank(tier):
            run.record("tier", False, patch_id, f"the change needs {needed}, and it shipped as {tier}")
    if run.ok and rank(tier) >= rank("MEDIUM"):
        from .review import Ledger, load_doc
        from .project import review_path
        doc = load_doc(gitx.read_blobs([f"{head}:{review_path(nn)}"], project.root).get(f"{head}:{review_path(nn)}"), nn)
        complete = Ledger(events, doc).complete(patch_id, tier)
        run.record("review", complete, patch_id, None if complete else "no complete review for this patch",
                   output="A review bound to this patch, with every finding answered, is missing.")
    code = "CI_PASS" if run.ok else "CI_FAIL"
    brief = "Every check passed." if run.ok else f"Failed at '{run.failure[0]}':\n{run.failure[1]}"
    return answer(nn, code=code, action={"kind": "rest", "brief": brief}, steps_=run.steps, tier=tier)


# --- output ----------------------------------------------------------------------------


def render(result):
    if not result.get("ok"):
        return f"rail: {result['reason'].get('message')}"
    if "text" in result:
        return result["text"].rstrip("\n")
    if "tickets" in result:
        lines = [f"{'TICKET':<7} {'STATE':<13} {'OWNER':<6} {'TIER':<7} {'LAST':<5} NOTE"]
        for r in result["tickets"]:
            lines.append(f"{r['ticket']:<7} {r['state']:<13} {r['owner']:<6} {r['tier']:<7} {r['last_event']:<5} {r['note']}")
        for i, l in enumerate(result.get("leftovers", [])):
            lines.append(f"{'leftovers:' if i == 0 else '':<11}{l['kind']} {l['ref']} ({l['reason']})")
        return "\n".join(lines)
    if "digest" in result:
        lines = ["## Areas"] + [f"- {a['area']} ({', '.join(a['paths'])}): {a['holds']}" for a in result["areas"]]
        if not result["architecture"]:
            lines.append("(no ARCHITECTURE.md yet)")
        return "\n".join(lines + ["", "## Directories", result["digest"]])
    head = " · ".join(str(x) for x in (
        f"ticket {result['ticket']}" if result.get("ticket") else None, result.get("state"),
        f"owner {result['owner']}", result["reason"]["code"]) if x)
    lines = [head]
    if result.get("cwd"):
        lines.append(f"cwd: {result['cwd']}")
    for s in result.get("steps", []):
        lines.append(f"  {s['step']}: {s['status']}" + (f", {s['result']}" if s.get("result") else "")
                     + (f" ({s['detail']})" if s.get("detail") else ""))
    if result["action"].get("brief"):
        lines += ["", result["action"]["brief"]]
    for i, l in enumerate(result.get("leftovers") or []):
        lines.append(f"{'' if i else chr(10)}leftover: {l['kind']} {l['ref']} ({l['reason']})")
    return "\n".join(lines)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise RailError(message)


def parser():
    p = _Parser(prog="rail", description="Keeps coding agents on the rail: what is legal next, and what counts as done.")
    sub = p.add_subparsers(dest="verb", required=True, parser_class=_Parser)

    def verb(name, help_, ticket=True):
        v = sub.add_parser(name, help=help_)
        v.add_argument("--json", action="store_true", help="answer in JSON")
        if ticket:
            v.add_argument("ticket", nargs="?", help="ticket ID or external id")
            v.add_argument("--ticket", dest="ticket_opt", help="ticket ID or external id")
        return v

    add = verb("add", "create a ticket from a ticket file", ticket=False)
    add.add_argument("file", help="the ticket file, or - for stdin")
    accept = verb("accept", "approve a ticket's contract")
    accept.add_argument("note", nargs="?", help="a note for the agent's next brief")
    verb("next", "the next legal move")
    verb("advance", "run the step the ticket's state calls for: ship, or merge")
    verb("status", "every ticket and its state", ticket=False)
    verb("context", "the ## Areas rows that match a ticket, and a directory digest")
    drop = verb("drop", "end a ticket without merging it")
    drop.add_argument("--reason", default="")
    drop.add_argument("--by", choices=("agent", "person"), default="agent")
    answer_ = verb("answer", "record how a review finding ended", ticket=False)
    answer_.add_argument("ticket", help="ticket ID")
    answer_.add_argument("finding", help="the finding's id, such as F2")
    answer_.add_argument("outcome", choices=("fixed", "declined", "parked"))
    answer_.add_argument("reason", nargs="?", default="", help="what changed, or why")
    answer_.add_argument("--owner", action="store_true", help="the project's owner decides (a person)")
    amend = verb("amend", "change a ticket's frozen contract: Done Contract, scope or tier")
    amend.add_argument("--file", help="the new ticket file, when the ticket has no worktree here")
    consult_ = verb("consult", "ask the consult pack for advice on one question", ticket=False)
    consult_.add_argument("ticket", help="ticket ID")
    consult_.add_argument("question")
    docs_ = verb("docs", "the framework's docs; with no topic, the list of topics", ticket=False)
    docs_.add_argument("topic", nargs="?")
    intake = verb("intake", "take in work from GitHub issues labelled rail, or from any tracker", ticket=False)
    intake.add_argument("source", nargs="?", help="github")
    intake.add_argument("--external-id")
    intake.add_argument("--title")
    intake.add_argument("--brief", help="a file with the request, verbatim")
    verb("sweep", "review what merged without a review, and turn its findings into tickets", ticket=False)
    verb("init", "set this project up for Rail", ticket=False)
    verb("doctor", "check the setup and print what's missing", ticket=False)
    verb("ci", "the rail check: the ship checks again on a pull request's head", ticket=False)
    hook = sub.add_parser("hook")  # internal: Claude Code hooks call it; not a verb
    hook.add_argument("name", choices=sorted(hooks.HOOKS))
    return p


def run_pack(argv):
    """`rail NAME ...` runs a pack's bin/NAME (plan, section 18). None when NAME isn't an installed pack."""
    if not argv or argv[0] in VERBS or argv[0].startswith("-") or argv[0] == "hook":
        return None
    try:
        root = Project(os.getcwd()).root
    except RailError:
        return None
    command = os.path.join(root, ".rail", "packs", argv[0], "bin", argv[0])
    if not os.path.exists(command):
        return None
    return subprocess.run([command, *argv[1:]], env=dict(os.environ, RAIL_ROOT=root)).returncode


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    as_json = "--json" in argv
    code = run_pack(argv)
    if code is not None:
        return code
    try:
        args = parser().parse_args(argv)
        if getattr(args, "ticket_opt", None):
            args.ticket = args.ticket_opt
        if args.verb == "hook":
            return hooks.run(args.name)
        if args.verb == "init":
            result = cmd_init(args)
        elif args.verb == "docs":
            result = cmd_docs(args)
        else:
            result = globals()[f"cmd_{args.verb}"](Project(os.getcwd()), args)
        code = 3 if any(s.get("result") == "fail" for s in result.get("steps", [])) else 0
    except RailError as e:
        result = {"schema_version": 1, "ok": False, "reason": {"code": e.code, "message": str(e)}}
        code = 2
    print(json.dumps(result, indent=2) if as_json else render(result))
    return code
