"""The steps the engine runs: claim and setup, ship, the local merge and the PR description."""

import os
import shutil
from pathlib import Path

from . import doclint, gitx, rules
from .project import event, events_path, ticket_path
from .state import raised_tier
from .ticket import Ticket, lint, rank
from .util import match_any, minutes_since, run_shell, tail

class Run:
    """The receipt of one command: the steps it ran, their events, and the first failure."""

    def __init__(self, project, t):
        self.project, self.t = project, t
        self.steps, self.events = [], []
        self.files = {}      # journal files to commit with the events: the review runs, the advice
        self.failure = None  # (step, output)
        self.rebased = False
        self.size = None

    def record(self, step, passed, patch_id=None, detail=None, duration_ms=None, output="", status="ran",
               counted=True, cost_usd=None):
        receipt = {"step": step, "status": status}
        if status == "ran":
            receipt["result"] = "pass" if passed else "fail"
            fields = {"step": step, "status": status, "result": receipt["result"]}
            if patch_id is not None:
                fields["patch_id"] = patch_id
            if not counted:
                fields["counted"] = False
            if detail:
                fields["detail"] = detail
            if duration_ms is not None:
                fields["duration_ms"] = duration_ms
            if cost_usd is not None:
                fields["cost_usd"] = cost_usd
            self.events.append(event(self.t.id, "step", **fields))
        if detail:
            receipt["detail"] = detail
        self.steps.append(receipt)
        if status == "ran" and not passed and not self.failure:
            self.failure = (step, output or detail or "")
        return passed

    def not_run(self, *names):
        for name in names:
            self.steps.append({"step": name, "status": "not_run"})

    @property
    def ok(self):
        return self.failure is None


def keep_alive(project, t):
    """Before a long command inside advance: when the ticket's last pushed event is older than claim.save_minutes,
    push one. Another session reads a ticket with no event for claim.stale_minutes as abandoned."""
    if not getattr(t, "branch", None) or not getattr(t, "events", None):
        return
    quiet = minutes_since(t.events[-1].get("at"))
    if quiet is not None and quiet >= project.config["claim"]["save_minutes"]:
        project.append_events(t, [event(t.id, "saved", via="advance", files=0)], "still at work [skip ci]")


def run_command(project, cwd, nn, step, command, run, patch_id=None, label=None):
    """Run one configured command in `cwd` and record it."""
    keep_alive(project, run.t)
    code, output, ms = run_shell(command, cwd, {"RAIL_TICKET": nn, "RAIL_BASE": project.base_ref},
                                 project.config["commands"]["timeout_secs"])
    status = "timeout" if code is None else f"exit {code}"
    detail = (f"{label}: {status}" if code != 0 else label) if label else status
    return run.record(step, code == 0, patch_id, detail, ms, output=f"$ {command}\n{tail(output)}")


# --- claim -----------------------------------------------------------------------


def make_worktree(project, t):
    """Check the ticket branch out in .claude/worktrees/NN and copy the files .worktreeinclude lists."""
    path = project.worktree_path(t.id)
    gitx.git(["worktree", "prune"], project.root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    gitx.git(["worktree", "add", "--quiet", path, t.branch], project.root)
    t.worktree = path
    copy_includes(project, path)


def copy_includes(project, path):
    """Copy the local files .worktreeinclude lists (such as .env) into a worktree."""
    include = os.path.join(project.root, ".worktreeinclude")
    if os.path.exists(include):
        with open(include) as f:
            patterns = [l.strip() for l in f if l.strip() and not l.startswith("#")]
        for pattern in patterns:
            for src in Path(project.root).glob(pattern):
                if src.is_file():
                    dest = os.path.join(path, os.path.relpath(src, project.root))
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.copy2(src, dest)


def setup(project, t, run, cwd=None):
    command = project.config["commands"]["setup"]
    if not command:
        run.not_run("setup")
        return True
    return run_command(project, cwd or t.worktree, t.id, "setup", command, run)


# --- ship and CI -------------------------------------------------------------------

CHECKS = ["ticket-lint", "assumptions", "scope", "rules", "migration", "size", "doc-lint", "verify", "checks"]


def _stop(run, step):
    run.not_run(*CHECKS[CHECKS.index(step) + 1:])
    return None


def check(project, nn, ticket, ref, cwd, tier, run, patch_id, accepted=None):
    """The checks ship and CI share, in order, stopping at the first failure.

    Returns the tier the change needs (it may rise), or None when a check failed.
    """
    errors = lint(ticket, expect_id=nn)
    if accepted and not errors:
        # The contract and tier freeze at acceptance: only `rail amend` changes them.
        if ticket.contract_hash() != accepted.get("contract"):
            errors.append(f"the contract (Done Contract and scope_paths) differs from the accepted one; change it with"
                          f" rail amend {nn}")
        if rank(ticket.tier) < rank(accepted.get("tier")):
            errors.append(f"the tier is {ticket.tier}, below the accepted {accepted.get('tier')}; tiers only go up")
    if not run.record("ticket-lint", not errors, patch_id, "; ".join(errors) or None, output="\n".join(errors)):
        return _stop(run, "ticket-lint")

    open_rows = ticket.open_assumptions()
    if not run.record("assumptions", not open_rows, patch_id, f"{len(open_rows)} open" if open_rows else None,
                      output="Open ASSUMED rows:\n" + "\n".join(f"- {r}" for r in open_rows)):
        return _stop(run, "assumptions")

    changed = project.changed_files(ref)
    outside = [p for p in changed + project.other_tickets(ref, nn) if not match_any(ticket.scope, p)]
    if not run.record("scope", not outside, patch_id, f"outside scope: {', '.join(outside)}" if outside else None,
                      output=f"These files are outside scope_paths ({', '.join(ticket.scope)}):\n" + "\n".join(outside)):
        return _stop(run, "scope")

    broken = rules.violations(project, ref, cwd)
    if not project.config["rules"]:
        run.not_run("rules")
    elif not run.record("rules", not broken, patch_id,
                      f"{len(broken)} broken: {broken[0][0]['id']}" if broken else None,
                      output="\n".join(f"{path} {what}. Rule {rule['id']}: {rule.get('fix', '')}"
                                       for rule, path, what in broken)):
        return _stop(run, "rules")

    needed, reason = raised_tier(project, changed)
    if rank(needed) > rank(tier):
        globs = project.config["risk_paths"].get(needed, []) + (project.config["migration_paths"] if needed == "HIGH" else [])
        hits = [p for p in changed if match_any(globs, p)]
        run.events.append(event(nn, "tier_raised", **{"from": tier, "to": needed, "reason": reason,
                                                     "detail": ", ".join(hits[:5])}))
        tier = needed

    migrations = [p for p in changed if match_any(project.config["migration_paths"], p)]
    if migrations:
        missing = [k for k in ("reversibility", "rollback") if not ticket.get(k)]
        if not run.record("migration", not missing, patch_id, f"missing {', '.join(missing)}" if missing else None,
                          output=f"This ticket changes migrations ({', '.join(migrations)}). Set {' and '.join(missing)}"
                                 " in the front matter: expand then contract, write the down step, test the rollback."):
            return _stop(run, "migration")

    count, _ = rules.size(project, ref, cwd)
    cap = project.config["size"].get(tier)
    run.record("size", True, patch_id, f"size {count}/{cap}" if cap else f"size {count}")
    sized = rules.size_tier(project, tier, count)
    if rank(sized) > rank(tier):
        run.events.append(event(nn, "tier_raised", **{"from": tier, "to": sized, "reason": "size",
                                                     "detail": f"{count} changed lines, over the {tier} cap of {cap}"}))
        tier = sized
    run.size = count

    if gitx.read_blobs([f"{ref}:ARCHITECTURE.md"], project.root).get(f"{ref}:ARCHITECTURE.md") is None:
        run.not_run("doc-lint")
    else:
        problems = doclint.lint(project, ref)
        if not run.record("doc-lint", not problems, patch_id, f"{len(problems)} problems" if problems else None,
                          output="ARCHITECTURE.md:\n" + "\n".join(f"- {p}" for p in problems)):
            return _stop(run, "doc-lint")

    verify = project.config["commands"]["verify"]
    if verify:
        if not run_command(project, cwd, nn, "verify", verify, run, patch_id):
            return _stop(run, "verify")
    else:
        run.not_run("verify")

    for command in ticket.checks():
        if not run_command(project, cwd, nn, "checks", command, run, patch_id, label=command):
            return None
    return tier


def base_fails_verify(project):
    """Run verify once more on the base branch, in a scratch worktree. Returns its output when it fails there too."""
    import tempfile

    tip = gitx.rev(project.base_ref, project.root)
    path = tempfile.mkdtemp(prefix="rail-base-")
    gitx.git(["worktree", "add", "--quiet", "--detach", path, tip], project.root)
    try:
        copy_includes(project, path)
        timeout = project.config["commands"]["timeout_secs"]
        if project.config["commands"]["setup"]:
            run_shell(project.config["commands"]["setup"], path, {"RAIL_TICKET": ""}, timeout)
        code, output, _ = run_shell(project.config["commands"]["verify"], path, {"RAIL_TICKET": ""}, timeout)
        return None if code == 0 else tail(output)
    finally:
        gitx.git(["worktree", "remove", "--force", path], project.root, check=False)


def ship(project, f, run):
    """Rebase onto a moved base, run the checks, and add a shipped event when all pass."""
    t, ref = f.t, f.t.ref
    wt = t.worktree
    base_tip = gitx.rev(project.base_ref, project.root)
    if base_tip and not gitx.ok(["merge-base", "--is-ancestor", base_tip, "HEAD"], wt):
        before = project.patch_id(ref)
        project.note_rewrite(t.branch)
        result = gitx.git(["rebase", "--quiet", base_tip], wt, check=False)
        if result.returncode != 0:
            conflicts = gitx.out(["diff", "--name-only", "--diff-filter=U"], wt).splitlines()
            gitx.git(["rebase", "--abort"], wt, check=False)
            run.record("rebase", False, before, f"conflict in {', '.join(conflicts) or 'the branch'}",
                       output=f"Rebasing {t.branch} onto {project.base} conflicts in: {', '.join(conflicts)}.\n"
                              f"Rebase it yourself in {project.rel(wt)} (git rebase {project.base}), resolve the"
                              f" conflict, then run: rail advance {t.id}")
            run.not_run(*CHECKS)
            return run
        run.rebased = True
        run.record("rebase", True, project.patch_id(ref), f"onto {project.base}")

    patch_id = project.patch_id(ref)
    text = gitx.read_blobs([f"{ref}:{ticket_path(t.id)}"], project.root)[f"{ref}:{ticket_path(t.id)}"]
    tier = check(project, t.id, Ticket(text or ""), ref, wt, f.tier, run, patch_id, accepted=f.accepted)
    if tier is None and run.failure[0] == "verify":
        # A red base spends no budget: two tickets that each pass can break main together.
        red = base_fails_verify(project)
        if red:
            run.events[-1]["counted"] = False
            run.events[-1]["detail"] = "red base"
            run.steps[-1 if run.steps[-1]["step"] == "verify" else -2]["detail"] = "red base"
            project.cache_write("red-base", "base", gitx.rev(project.base_ref, project.root))
            project.cache_write("red-base", "output", red)
            run.failure = ("verify", "verify fails on the base branch too, so this attempt doesn't count. rail next"
                                     " opens one ticket that fixes the base; this ticket's ship waits until it merges.")
    if tier is None:
        return run
    head = gitx.rev(ref, project.root)
    run.events.append(event(t.id, "shipped", patch_id=patch_id, head=head[:12], tier=tier, size=run.size))
    return run


def ship_failed_brief(t, run):
    step, output = run.failure
    return f"Ship of ticket {t.id} failed at '{step}'.\n{output}\n\nFix it in the worktree, then run: rail advance {t.id}"


# --- merge -------------------------------------------------------------------------


def describe(project, t, ticket, tier):
    """The PR title and description. Locally they are the squash commit's subject and body."""
    title = ticket.title.strip()
    subject = f"{t.id}: {title[:1].lower()}{title[1:]}"
    run_events = []
    for e in reversed(t.events):
        if e.get("event") == "shipped" and not run_events:
            run_events.append(e)
        elif run_events and e.get("event") in ("step", "tier_raised"):
            run_events.append(e)
        elif run_events:
            break
    rows = []
    for e in reversed(run_events):
        if e.get("event") != "step":
            continue
        name = f"check: {e.get('detail')}" if e.get("step") == "checks" else e.get("step")
        rows.append(f"| {name} | {e.get('status')}, {e.get('result')} |")
    from .review import Ledger, load_doc
    ledger = Ledger(t.events, load_doc(t.review_text, t.id))
    for role in ("review", "security"):
        if ledger.runs(role):
            own = [fid for fid, x in ledger.findings.items() if x.get("role") == role]
            open_ = [fid for fid in own if ledger.outcome(fid) == "open"]
            said = (f"{len(own)} findings, " + ("all answered" if not open_ else f"{len(open_)} open")) if own else "no findings"
            models = sorted({r["model"] for r in ledger.runs(role) if r.get("model")})
            by = f" by {', '.join(models)}" if models else ""
            rows.append(f"| {role} | ran, {len(ledger.runs(role))} runs{by}, {said} |")
    changed = project.changed_files(t.ref)
    lockfiles = [p for p in changed if os.path.basename(p) in rules.LOCKFILES]
    migrations = "No migrations." if not ticket.get("reversibility") else (
        f"Migrations: {ticket.get('reversibility')}; rollback: {ticket.get('rollback')}.")
    risk = (f"{tier}. Touches {', '.join(ticket.scope)}. {migrations} "
            f"Changed lockfiles: {', '.join(lockfiles) or 'none'}.")
    external = ticket.get("external_id", "") or ""
    body = [
        "## Why", f"{ticket.sections.get('Why', '')} (ticket {t.id})", "",
        "## Look at", ticket.sections.get("Look at") or "(not written)", "",
        "## Evidence", "| Step | Status |", "|---|---|", *rows, "",
        "## Risk", risk, "",
        f"Ticket: {t.id}", f"Tier: {tier}",
    ]
    if external.startswith("github#"):
        body.append(f"Closes #{external.split('#', 1)[1]}")
    if external.startswith("sweep#"):
        body.append(f"Sweep: since {external.split('#', 1)[1]}")  # where the next sweep starts
    sessions = [e["session_url"] for e in t.events if e.get("event") == "claimed" and e.get("session_url")]
    if sessions:
        body.append(f"Claude-Session: {sessions[-1]}")  # the cloud session that worked it, for a person to open
    return subject, "\n".join(body)


def merge_local(project, f, run):
    """Squash-merge a shipped ticket into the base branch, with no remote."""
    t = f.t
    base_ref = f"refs/heads/{project.base}"
    base_tip = gitx.rev(base_ref, project.root)
    ticket = Ticket(gitx.read_blobs([f"{t.ref}:{ticket_path(t.id)}"], project.root)[f"{t.ref}:{ticket_path(t.id)}"])
    subject, body = describe(project, t, ticket, f.tier)
    tree = gitx.out(["rev-parse", f"{t.ref}^{{tree}}"], project.root)
    commit = gitx.out(["commit-tree", tree, "-p", base_tip, "-m", subject, "-m", body], project.root)
    base_wt = gitx.worktrees(project.root).get(project.base)
    if base_wt:
        result = gitx.git(["merge", "--quiet", "--ff-only", commit], base_wt, check=False)
        moved = result.returncode == 0
        why = (result.stderr or result.stdout).strip()
    else:
        moved = gitx.update_ref(project.root, base_ref, commit, base_tip)
        why = f"{project.base} moved during the merge"
    detail = f"squash {commit[:12]} onto {project.base}" if moved else why
    run.record("merge", moved, f.patch_id, detail if moved else f"not merged: {why}", output=why)
    return commit if moved else None


def remove_ticket(project, t):
    """Remove a finished ticket's worktree and branches. Returns the leftovers it couldn't remove."""
    leftovers = []
    if t.worktree:
        changes = gitx.dirty(t.worktree)
        if changes:
            leftovers.append({"kind": "worktree", "ref": project.rel(t.worktree),
                              "reason": f"uncommitted changes ({len(changes)} files); left for you"})
        elif gitx.git(["worktree", "remove", "--force", t.worktree], project.root, check=False).returncode == 0:
            t.worktree = None
        else:
            leftovers.append({"kind": "worktree", "ref": project.rel(t.worktree), "reason": "git refused to remove it"})
    if t.branch and not t.worktree:
        if gitx.git(["branch", "-D", t.branch], project.root, check=False).returncode == 0:
            t.branch = None
        else:
            leftovers.append({"kind": "branch", "ref": t.branch, "reason": "git refused to delete it"})
    if t.remote_branch and project.remote:
        result = gitx.push(project.root, project.remote, f":refs/heads/{t.remote_branch}") if project.online else "unavailable"
        if result == "ok":
            t.remote_branch = None
        else:
            leftovers.append({"kind": "remote branch", "ref": t.remote_branch, "reason": "deletion refused here"})
    return leftovers
