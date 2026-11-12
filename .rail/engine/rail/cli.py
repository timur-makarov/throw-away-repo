"""The `rail` verbs. Every verb answers in one JSON shape with --json, or as text without it.

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
from .util import RailError, age, cloud, disposable, match_any, session_url

VERBS = ("init", "add", "accept", "amend", "answer", "next", "advance", "status", "context", "drop", "doctor", "ci",
         "consult", "docs", "intake", "sweep", "provision", "save")
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
    """--ticket, then RAIL_TICKET, then the worktree the command runs in."""
    return getattr(args, "ticket", None) or os.environ.get("RAIL_TICKET") or ticket_from_cwd(project)


def load(project):
    """Tickets and their facts. GitHub is read again only when something can have changed there."""
    from .forge import Forge

    earlier = getattr(project, "forge", None)
    if earlier is None or earlier.stale:
        project.forge = Forge(project, earlier)
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
    """A claim is a commit with the `claimed` event on the ticket branch, pushed."""
    for _ in range(3):
        ensure_local(project, t)
        before = gitx.rev(t.ref, project.root)
        url = session_url()  # in a cloud session: the conversation a person can open from the ticket
        claimed = event(t.id, "claimed", session=project.session, takeover=takeover,
                        **({"session_url": url} if url else {}))
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


def contract_pr(f):
    """The title and description of a contract pull request: the ticket as it stands, for a person to approve."""
    title = f"{f.id}: [contract] {f.ticket.title}"
    body = (f"The contract of ticket {f.id} ({f.tier}). Approve it with the label `rail:go`, or say \"accept {f.id}\"."
            f" To change it, comment here. To reject it, close this pull request.\n\n"
            f"**Don't merge it.** It holds only the contract: the work comes after your approval, on this same pull"
            f" request, and the `rail` check stays red until it ships.\n\n{f.ticket.text}")
    return title, body


def restart_on_base(project, f, run):
    """A pull request merged before its ticket shipped has put the branch's commits on the base branch as one
    squash, and a branch can't be rebased over its own squash. So the branch starts again from the base: the commits
    made after the merge are replayed, and nothing else. Uncommitted work in the worktree is kept."""
    t = f.t
    merged_head = f.pr["head"]["sha"] if f.pr and f.pr.get("merged_at") and f.pr.get("head") else None
    base_tip, tip = gitx.rev(project.base_ref, project.root), gitx.rev(t.ref, project.root) if t.ref else None
    if not merged_head or not tip or not base_tip or gitx.ok(["merge-base", "--is-ancestor", base_tip, tip], project.root):
        return True  # no merged pull request to start again from, or the branch is on the base already
    if not gitx.ok(["merge-base", "--is-ancestor", merged_head, tip], project.root):
        return True  # the branch isn't built on what was merged: an ordinary rebase is right for it
    project.note_rewrite(t.branch)
    if tip == merged_head:
        if t.worktree:
            moved = gitx.git(["reset", "--quiet", "--keep", base_tip], t.worktree, check=False).returncode == 0
        else:
            moved = gitx.update_ref(project.root, t.ref, base_tip, tip)
    elif t.worktree:
        moved = gitx.git(["rebase", "--quiet", "--autostash", "--onto", base_tip, merged_head], t.worktree,
                         check=False).returncode == 0
        if not moved:
            gitx.git(["rebase", "--abort"], t.worktree, check=False)
    else:
        return True  # commits made after the merge are replayed once the ticket has its worktree
    return run.record("rebase", moved, project.patch_id(t.ref) if moved else None,
                      f"onto {project.base}: its pull request was merged before the work shipped",
                      output=f"The branch {t.branch} couldn't be moved onto {project.base} after its pull request was"
                             f" merged early. Rebase it yourself in {project.rel(t.worktree) if t.worktree else 'a worktree'}"
                             f" (git rebase --onto {project.base} {merged_head[:12]}), then run: rail next")


def ensure_pr(project, f, receipts):
    """Every wait after add has a PR to label: a contract PR at add for tiers outside auto_tiers,
    and a PR at claim for the rest."""
    from .forge import ForgeError

    forge, t = project.forge, f.t
    if not forge or not forge.ok or f.pr_open or not t.name or not gitx.rev(
            f"refs/remotes/{project.remote}/{t.name}", project.root):
        return f.pr
    if f.state == "new":
        if f.lint_errors or f.auto:
            return None
        title, body = contract_pr(f)
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
    """At ship, the PR's title loses [contract] and its description becomes the ticket's."""
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
    moves = [e["at"] for e in f.t.events if e.get("event") != "saved" and e.get("at")]  # a save isn't a move
    since = moves[-1] if moves else ""
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
        ensure_local(project, t)
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
    elif code == "CONTRACT_MERGED":
        # A person merged the contract's pull request. That is their approval: the ticket goes on, on its branch,
        # made again from the base when GitHub deleted it, and gets a new pull request at its claim.
        if not t.name:
            name = branch_name(f.ticket)
            gitx.update_ref(project.root, f"refs/heads/{name}", gitx.rev(project.base_ref, project.root), None)
            t.branch, t.ref = name, f"refs/heads/{name}"
        ensure_local(project, t)
        restart_on_base(project, f, run)
        run.events.append(accepted_event(t.id, f.ticket, f.tier, "person", "merge"))
        project.append_events(t, run.events, "accept: the contract was merged")
        run.events = []
        run.steps.append({"step": "contract", "status": "ran", "result": "pass",
                          "detail": "its pull request was merged before the work: taken as the approval"})
    elif code == "GO":
        # A person's rail:go: it approves a contract or an amend, or continues any other wait.
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
        # The base requires up-to-date branches: rebase the shipped PR with no agent work.
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
            if f.state in OPEN and f.forge and not f.pr_open and f.t.branch and not f.claimed_elsewhere:
                # Its pull request was merged or lost before the work shipped: the ticket goes on, with a new one.
                run = steps.Run(project, f.t)
                if f.contract_merged:
                    restart_on_base(project, f, run)
                    if run.events:
                        commit(project, f, run, "start again from the base")
                    receipts += run.steps
                if run.ok and ensure_pr(project, f, receipts):
                    continue
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
    """Take the next ID and make the ticket's branch with the ticket file, without touching any checkout. A ticket
    that passes lint on an auto tier is accepted at once. Returns (id, branch, push result)."""
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

    nn, commit = project.take_id(project.max_id(tickets) + 1, build, label=Ticket(text).title or "")
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
    """An intake ticket: the request verbatim, with the contract and tier for the agent to write."""
    return "\n".join(["+++", f"title = {json.dumps(title)}", 'tier = ""', "scope_paths = []",
                      f"external_id = {json.dumps(external_id)}", f"caused_by = {json.dumps(caused_by)}", "+++", "",
                      "## Request", request.strip(), "", "## Why", "", "## Done Contract", ""])


def caused_by(project, request):
    """An issue from a failed dev deploy starts with `Commit: <sha>`; the commit's Ticket: trailer caused it."""
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
    anything else. Both are idempotent by external_id."""
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
    """A person's one act that continues any wait: approve a contract or an amend, or continue."""
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
    """Record how a review finding ended: fixed, declined with a reason, or parked."""
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
    """Change a frozen contract: the Done Contract, the scope or the tier, which only rises."""
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
    project.sync()
    tickets, facts = load(project)
    nf, receipts = facts[t.id], []
    if nf.state == "new" and not nf.lint_errors and not nf.auto:
        # A contract a person has yet to approve: its pull request shows the contract as it now stands. A ticket
        # from intake gets its contract pull request here, once the agent has written the contract.
        from .forge import ForgeError
        if nf.pr_open:
            title, body = contract_pr(nf)
            try:
                project.forge.update_pr(nf.pr["number"], title=title, body=body)
            except ForgeError as e:
                receipts.append({"step": "pr", "status": "unavailable", "detail": str(e)[:200]})
        elif ensure_pr(project, nf, receipts):
            tickets, facts = load(project)
            nf = facts[t.id]
    return from_facts(nf, receipts)


def cmd_sweep(project, args):
    """A sweep ticket over what merged without a review: the free part and one review pass."""
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
    """The consult pack on request: a different model's advice on one question."""
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
    """When verify fails on the base branch, one fix ticket for the base."""
    red = project.cache_read("red-base", "base")
    if not red or red != gitx.rev(project.base_ref, project.root):
        return None
    output = project.cache_read("red-base", "output") or ""
    request = f"verify fails on {project.base} at {red[:12]}:\n\n```\n{output}\n```"
    return intake_one(project, facts, f"Make verify pass on {project.base} again", request, f"red-base#{red[:12]}")


def auto_intake(project, facts):
    """Issues labelled rail come in with every `next` when GitHub can be reached, so labelling an issue is the
    whole act of handing work over. Returns the receipts of the tickets it made."""
    from .forge import ForgeError

    if not (project.forge and project.forge.ok):
        return []
    try:
        issues = project.forge.issues("rail")
    except ForgeError:
        return []
    receipts = []
    for issue in issues:
        key = f"github#{issue['number']}"
        nn = intake_one(project, facts, issue["title"], issue.get("body") or "", key)
        if nn:
            receipts.append({"step": "intake", "status": "ran", "result": "pass", "detail": f"ticket {nn} from {key}"})
            _, facts = load(project)
    return receipts


def cmd_next(project, args):
    project.sync()
    task = init_task(project)
    if task:
        return task
    task = provision_task(project)
    if task:
        return task
    tickets, facts = load(project)
    took_in = auto_intake(project, facts)
    if took_in or red_base_ticket(project, facts):
        tickets, facts = load(project)
    leftovers = cleanup(project, tickets, facts)
    explicit = requested(project, args)
    if explicit:
        nn = project.find(explicit, tickets).id
        f, receipts = settle(project, nn, explicit=True)
        if f is None:
            return answer(nn, None, "none", {"kind": "rest", "brief": f"Another session claimed ticket {nn} first."},
                          "CLAIMED_ELSEWHERE", receipts)
        return from_facts(f, took_in + receipts, leftovers=leftovers)

    tickets, facts = load(project)
    # A person's inbox is the label: every wait gets it now, not only when the agent runs dry.
    for f in facts.values():
        code, owner, _ = first_match(f)
        if owner == "human":
            label_wait(project, f, code)

    # Any ticket the agent can act on comes first: this session's own, then tickets no session holds (shipped ones,
    # which the engine moves from anywhere, and work an ended session left), then new work in ID order.
    mine = [f for f in facts.values() if f.state in OPEN and not f.claimed_elsewhere]
    free = [f for f in facts.values() if f.state in OPEN and f.claimed_elsewhere and not f.held]
    fresh = [f for f in facts.values() if f.state in ("new", "accepted")]
    for candidate in mine + free + fresh:
        if first_match(candidate)[1] != "agent":
            continue
        f, receipts = settle(project, candidate.id, explicit=False)
        if f is not None and first_match(f)[1] == "agent":
            return from_facts(f, took_in + receipts, leftovers=leftovers)

    tickets, facts = load(project)
    waits, held, ci = [], [], []
    for f in facts.values():
        code, owner, action = first_match(f)
        if owner == "human":
            waits.append({"ticket": f.id, "needs": code, "brief": action["brief"],
                          **({"pr": f.pr["html_url"]} if f.pr else {})})
        elif code == "CLAIMED_ELSEWHERE":
            held.append({"ticket": f.id, "quiet_minutes": f.quiet_minutes,
                         **({"session": f.claimed["session_url"]} if f.claimed.get("session_url") else {})})
        elif code == "CI_WAIT" and f.pushed:
            ci.append(f)
    extra = {"waits": waits, "held": held, "leftovers": leftovers}
    if ci:
        run_id = ci_run(project, ci[0])
        if run_id:
            command = f"gh run watch {run_id} --exit-status; rail next"
            return answer(ci[0].id, ci[0].state, "agent", {"kind": "script", "brief": command, "command": command},
                          "CI_WAIT", took_in, **extra)
    if waits:
        brief = "Tickets wait for a person:\n" + "\n".join(f"- {w['ticket']}: {w['brief']}" for w in waits)
        return answer(owner="human", code="WAITING_HUMAN", action={"kind": "human_wait", "brief": brief},
                      steps_=took_in, **extra)
    from . import sweep
    is_due, _, commits = sweep.due(project)
    if is_due and not held:
        return answer(owner="agent", code="SWEEP", action={"kind": "script", "brief": "rail sweep", "command": "rail sweep"},
                      steps_=took_in, **extra, unreviewed=len(commits))
    if ci:
        # CI is running and there is no run to watch (another CI system, or the run hasn't started yet).
        return answer(ci[0].id, ci[0].state, "none", first_match(ci[0])[2], "CI_WAIT", took_in, **extra)
    brief = "No ticket to work on. New work starts with: rail add <ticket file>"
    if held:
        limit = project.config["claim"]["stale_minutes"]
        brief += ("\nOther sessions are at work on: " + ", ".join(
            f"{h['ticket']} (quiet {h['quiet_minutes']} min)" for h in held)
            + f". A ticket quiet for {limit} min is resumed by the next rail next; rail next --ticket NN takes one now.")
    return answer(code="NO_WORK", action={"kind": "rest", "brief": brief}, steps_=took_in, **extra)


def label_wait(project, f, code):
    """The inbox is one saved search, is:open label:rail:needs-you: label each wait's PR."""
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
    """At the retry budget, consult advises once before the agent's last attempt."""
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
    """Squash-merge with no remote. When the base moved since ship, rebase and ship again first."""
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
    """auto_tiers, once CI is green: the async merge endpoint, the head pinned with sha. The request
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
        elif code == "MERGE" and first and f.worktree and not project.remote:
            # A shipped ticket is anyone's to merge: with no remote, every session shares this clone and its worktrees.
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
            if first and f.state == "in-ci" and not f.forge:
                receipts.append({"step": "ci", "status": "unavailable", "detail": "GitHub can't be reached, so CI and"
                                                                                  " the merge wait"})
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
        elif f.held:
            note = f"another session's work, quiet {f.quiet_minutes} min"
        elif f.in_flight and f.claimed_elsewhere:
            note = "left by an ended session: rail next resumes it"
        elif f.in_flight and f.claimed and not t.worktree:
            note = f"no worktree here: rail next --ticket {nn} makes one"
        elif f.state in OPEN and last and age(last).endswith("d") and int(age(last)[:-1]) >= STALE_DAYS:
            note = f"STALE: no event for {age(last)[:-1]} days"
        elif f.state in ("new", "accepted") and code in ("WAITING_AFTER", "SCOPE_OVERLAP"):
            note = action["brief"]
        if f.pr and not note:
            note = f"PR #{f.pr['number']}"
        rows.append({"ticket": nn, "title": t.ticket.title if t.ticket else t.label, "state": f.state, "owner": owner,
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
        if f.t.name:
            ensure_local(project, f.t)
            project.append_events(f.t, [event(f.id, "dropped", by=args.by, reason=args.reason or "")], "drop")
        project.mark_dropped(f.id)
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
    ticket again. Labelling the issue again is how to retry."""
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
    brief = ("Rail is installed. Next: rail next, which returns the init task: the project's commands, ## Areas,"
             " risk_paths and rules. " + ("In this cloud session you set them up and the person confirms by merging one"
                                          " pull request." if cloud() else "You propose each and the person confirms."))
    return answer(code="INITIALISED", owner="agent", action={"kind": "script", "brief": brief, "command": "rail next"},
                  steps_=receipts, root=root)


def init_task(project):
    """The first `rail next` returns the init task until the project's config is on the base branch."""
    if gitx.read_blobs([f"{project.base_ref}:.rail/config.toml"], project.root).get(f"{project.base_ref}:.rail/config.toml"):
        return None
    from .init import INIT_TASK, INIT_TASK_CLOUD
    brief = (INIT_TASK_CLOUD if cloud() else INIT_TASK).format(base=project.base, depth=project.config["map"]["depth"])
    return answer(owner="agent", code="INIT_TASK", action={"kind": "agent_task", "brief": brief}, cwd=".")


# --- saving work in flight ---------------------------------------------------------------


def save_work(project, f, via):
    """Commit a ticket's in-scope changes as they are and push them, with a `saved` event. Nothing is checked: the
    point is that a machine that goes away takes at most a few minutes of work with it, and that other sessions see
    the ticket is alive. Returns (paths saved, paths left because they are outside scope, the push's result), or
    None when there was nothing to save and the ticket moved a moment ago."""
    t = f.t
    changes = gitx.dirty(t.worktree, exclude=[".rail/journal"])
    inside = [c for c in changes if c.startswith(".rail/tickets/") or match_any(f.ticket.scope, c)]
    outside = [c for c in changes if c not in inside]
    quiet = f.quiet_minutes
    if not inside and quiet is not None and quiet < project.config["claim"]["save_minutes"]:
        return None
    if inside:
        # [skip ci]: GitHub starts no workflow for it. The check that counts runs on the commit a ship pushes.
        gitx.git(["add", "-A", "--", *inside], t.worktree)
        gitx.git(["commit", "--quiet", "-m", f"{t.id}: save work in progress [skip ci]", "--", *inside], t.worktree)
    pushed = project.append_events(t, [event(t.id, "saved", via=via, files=len(inside))], "save [skip ci]")
    return inside, outside, pushed


def save_all(project, via, only=None):
    """Save every ticket this session has in flight. Returns (receipts, briefs for the agent)."""
    tickets, facts = load(project)
    receipts, notes = [], []
    for f in facts.values():
        if only and f.id != only:
            continue
        if not (f.in_flight and f.claimed and f.worktree and f.ticket):
            if only:
                notes.append(f"Ticket {f.id} is {f.state}: there is no work in flight to save here.")
            continue
        if f.claimed_elsewhere:
            if f.taken_from_me or only:
                notes.append(first_match(f)[2]["brief"])
            continue
        saved = save_work(project, f, via)
        if saved is None:
            continue
        inside, outside, pushed = saved
        detail = f"ticket {f.id}: {len(inside)} files" + ("" if pushed == "ok" or not project.remote else f", push {pushed}")
        receipts.append({"step": "save", "status": "ran", "result": "pass", "detail": detail})
        if outside:
            notes.append(f"Ticket {f.id}: not saved, because they are outside scope_paths: {', '.join(outside)}")
        if pushed == "rejected":
            notes.append(f"Ticket {f.id}: the push was refused, so its branch moved on the remote. Run rail next.")
    return receipts, notes


def cmd_save(project, args):
    """Commit and push the work in flight as it is, with no checks: `rail save`, or `rail save NN` for one ticket.
    The hooks run it at the end of each turn and every few minutes; an agent runs it where no hook does."""
    project.sync()
    only = None
    key = getattr(args, "ticket", None)
    if key:
        only = project.find(key, project.tickets()).id
    receipts, notes = save_all(project, "save", only)
    brief = "\n".join(notes) or ("Saved." if receipts else "Nothing to save.")
    return answer(code="SAVED", action={"kind": "rest", "brief": brief}, steps_=receipts)


# --- provisioning: the machine carries the tools --------------------------------------


MACHINE_SETUP = "machine-1"  # raise it when what provision writes onto a cloud machine changes


def bin_dir():
    """Where provision links rail on a cloud machine. RAIL_BIN_DIR moves it, for tests."""
    return os.environ.get("RAIL_BIN_DIR") or "/usr/local/bin"


def _provision_marker(project):
    """One file per project on this machine: what provision last did here. It lives in the home folder, so an
    environment's snapshot keeps it and a fresh VM starts without it."""
    import hashlib
    name = hashlib.sha256(project.root.encode()).hexdigest()[:16]
    return os.path.join(os.path.expanduser("~"), ".cache", "rail", "provisioned", name)


def _provision_wanted(project):
    """The hash of what provision does on this kind of machine: the project's command, and in a cloud session
    Rail's own part (the link and the machine's hooks)."""
    import hashlib
    command = project.config["commands"]["provision"]
    if not command and not cloud():
        return None  # nothing to do here
    return hashlib.sha256(f"{command}\n{MACHINE_SETUP if cloud() else ''}".encode()).hexdigest()


def provisioned(project):
    wanted = _provision_wanted(project)
    if wanted is None:
        return True
    path = _provision_marker(project)
    if not os.path.exists(path):
        return False
    with open(path) as f:
        return f.read().strip() == wanted


def install_machine(project, run):
    """On a cloud machine: link rail onto PATH, and write Rail's hooks into the machine's own Claude Code settings.
    Claude Code loads a repository's hooks only in a session that starts with that one repository; the machine's
    settings load in every session, so the guard and the saves also work above several repositories and in a
    project's threads. Where the repository's hooks do run, these step aside."""
    launcher = os.path.join(project.root, ".rail", "bin", "rail")
    link = os.path.join(bin_dir(), "rail")
    try:
        if os.path.realpath(link) != os.path.realpath(launcher):
            if os.path.lexists(link):
                os.remove(link)
            os.symlink(launcher, link)
        linked = True
    except OSError:
        linked = False
    command = link if linked else launcher
    pulse = ('[ -n "$(find "$HOME/.cache/rail/pulse/${CLAUDE_CODE_SESSION_ID:-any}" -mmin -10 2>/dev/null)" ]'
             f" || {command} hook pulse --machine")
    wanted = [("SessionStart", None, f"{command} hook session-start --machine"),
              ("PreToolUse", "Bash", f"{command} hook guard --machine"),
              ("PostToolUse", None, pulse),
              ("Stop", None, f"{command} hook stop --machine")]
    path = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
    try:
        with open(path) as f:
            settings = json.load(f)
    except OSError:
        settings = {}
    except ValueError:
        return run.record("machine", False, None, "the machine's ~/.claude/settings.json isn't valid JSON",
                          output=f"{path} isn't valid JSON, so Rail's hooks weren't written into it.")
    added = []
    for name, matcher, hook_command in wanted:
        mark = hook_command[hook_command.index("hook "):]  # such as "hook guard --machine"
        entries = settings.setdefault("hooks", {}).setdefault(name, [])
        if any(mark in json.dumps(entry) for entry in entries):
            continue
        entries.append({**({"matcher": matcher} if matcher else {}), "hooks": [{"type": "command", "command": hook_command}]})
        added.append(name)
    if added:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(settings, f, indent=2)
            f.write("\n")
    detail = ("rail linked into " + bin_dir() if linked else "rail not linked (no write access to " + bin_dir() + ")")
    return run.record("machine", True, None, detail + ("; hooks written to ~/.claude/settings.json" if added
                                                       else "; the machine's hooks are there already"))


def run_provision(project, run):
    """What a machine made for the work gets: on a cloud machine Rail's own part, then [commands] provision as
    root. Notes that it ran. Returns whether it passed."""
    import shlex

    passed = install_machine(project, run) if cloud() else True
    command = project.config["commands"]["provision"]
    if passed and command:
        as_root = command
        if os.geteuid() != 0 and subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode == 0:
            as_root = f"sudo -n -E sh -c {shlex.quote(command)}"  # a CI runner isn't root, and its sudo asks no password
        code, output, ms = steps.run_shell(as_root, project.root, {"RAIL_BASE": project.base_ref},
                                           project.config["commands"]["timeout_secs"])
        passed = run.record("provision", code == 0, None, "timeout" if code is None else f"exit {code}", ms,
                            output=f"$ {command}\n{steps.tail(output)}")
    if passed:
        path = _provision_marker(project)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(_provision_wanted(project) + "\n")
    return passed


def provision_task(project):
    """In a cloud session, the first `next` on a machine that hasn't been provisioned says so."""
    if not cloud() or provisioned(project):
        return None
    return answer(owner="agent", code="PROVISION", cwd=".",
                  action={"kind": "script", "brief": "rail provision", "command": "rail provision"})


def cmd_provision(project, args):
    """Get a machine made for the work ready: on a cloud machine, link rail and write the machine's hooks; then
    [commands] provision, which installs what setup and verify need, once per machine. It runs in a cloud session
    and on a CI runner. A person's own machine is theirs."""
    command = project.config["commands"]["provision"]
    if not disposable():
        brief = ("This is your own machine, so Rail installs nothing here." + (
            f" In a cloud session and in CI it runs:\n  {command}\nInstall the same tools your own way."
            if command else " No provision command is set ([commands] provision in .rail/config.toml)."))
        return answer(owner="human" if command else "none", code="PROVISION_LOCAL",
                      action={"kind": "human_wait" if command else "rest", "brief": brief})
    if _provision_wanted(project) is None:
        return answer(code="NO_WORK", action={"kind": "rest", "brief": "No provision command is set ([commands]"
                                                                       " provision in .rail/config.toml)."})
    if provisioned(project) and not args.force:
        return answer(code="PROVISIONED", action={"kind": "rest", "brief": "This machine is provisioned already;"
                                                                           " rail provision --force runs it again."})
    run = steps.Run(project, type("T", (), {"id": ""})())
    passed = run_provision(project, run)
    brief = ("Provisioned. Next: rail next" if passed else
             f"Provisioning failed at '{run.failure[0]}':\n{run.failure[1]}\n\nFix [commands] provision in"
             " .rail/config.toml (a HIGH ticket), or the machine, then run: rail provision")
    return answer(owner="agent", code="PROVISIONED" if passed else "PROVISION_FAILED", steps_=run.steps, cwd=".",
                  action={"kind": "script" if passed else "agent_task", "brief": brief,
                          **({"command": "rail next"} if passed else {})})


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
    """The `rail` check: the ship checks again, on the PR head. It writes nothing."""
    from .state import raised_tier

    head = "HEAD"
    branch = os.environ.get("RAIL_BRANCH") or gitx.git(["rev-parse", "--abbrev-ref", "HEAD"], project.root).stdout.strip()
    m = re.match(r"^(\d+)-", branch)
    nn = m.group(1) if m else None
    text = gitx.read_blobs([f"{head}:{ticket_path(nn)}"], project.root).get(f"{head}:{ticket_path(nn)}") if nn else None
    run = steps.Run(project, type("T", (), {"id": nn or ""})())
    changed = project.changed_files(head)
    if disposable() and project.config["commands"]["provision"] and not provisioned(project):
        # The runner is made for this run, like a cloud VM: it gets the same tools before any check needs them.
        if not run_provision(project, run):
            return answer(nn, code="CI_FAIL", action={"kind": "rest", "brief": f"Failed at 'provision':\n{run.failure[1]}"},
                          steps_=run.steps)
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
    # allow_abbrev=False: `--own` must not pass for `--owner`, which the guard asks a person about.
    p = _Parser(prog="rail", description="Keeps coding agents on the rail: what is legal next, and what counts as done.",
                allow_abbrev=False)
    sub = p.add_subparsers(dest="verb", required=True, parser_class=_Parser)

    def verb(name, help_, ticket=True):
        v = sub.add_parser(name, help=help_, allow_abbrev=False)
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
    verb("save", "commit and push the work in flight as it is, with no checks")
    provision = verb("provision", "install what the checks need on this machine (cloud sessions and CI only)",
                     ticket=False)
    provision.add_argument("--force", action="store_true", help="run it again on a machine that has it")
    verb("init", "set this project up for Rail", ticket=False)
    verb("doctor", "check the setup and print what's missing", ticket=False)
    verb("ci", "the rail check: the ship checks again on a pull request's head", ticket=False)
    hook = sub.add_parser("hook")  # internal: Claude Code hooks call it; not a verb
    hook.add_argument("name", choices=sorted(hooks.HOOKS))
    hook.add_argument("--machine", action="store_true")  # from the machine's settings, not the repository's
    return p


def run_pack(argv):
    """`rail NAME ...` runs a pack's bin/NAME. None when NAME isn't an installed pack."""
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
            return hooks.run(args.name, args.machine)
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
