"""The steps the engine runs: claim and setup, ship, the local merge and the PR description."""

import contextlib
import hashlib
import os
import re
import shutil
import tempfile
from pathlib import Path

from . import config as configmod, doclint, flakes, gitx, rules, tools
from .project import event, events_path, ticket_path
from .state import raised_tier
from .util import cloud
from .ticket import Ticket, lint, rank
from .util import MISSING_HELP, NOT_COUNTED, could_not_run, match_any, minutes_since, run_shell, tail, tried_help

# A step's status: it ran and passed or failed, or the shell could not start its command (could_not_run, a failure
# that checked nothing). A ship step that could not run counts as no attempt: twice in a row it waits for a person.
TRIED = ("ran", "could_not_run")
REVIEW_STEPS = ("review", "security", "refuter")  # every failed run at one of these is the same failure: plain count


def signature(step, output):
    """The step and a hash of its failure's output, normalised so that the same failure gives the same signature
    across runs: what changes from run to run (numbers, hashes, paths, temp folders) and spacing are left out."""
    text = "" if step in REVIEW_STEPS else normalise(tail(output))
    return f"{step}:{hashlib.sha256(text.encode()).hexdigest()[:12]}"


def normalise(text):
    """Output with what changes from run to run (numbers, hashes, paths, temp folders) and spacing left out."""
    text = text.lower()
    text = re.sub(r"(?<![\w.~-])/[^\s:'\"(),]+", "<path>", text)  # absolute paths, temp folders among them
    text = re.sub(r"\btmp[\w.-]*", "<tmp>", text)                   # temp names: tmpab12_cd, tmp.x8Q2
    text = re.sub(r"\b(?:0x[0-9a-f]+|(?=[a-f]*\d)[0-9a-f]{7,})\b", "<hex>", text)  # commits, ids, addresses
    text = re.sub(r"\d+", "<n>", text)
    return re.sub(r"\s+", " ", text).strip()


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
        if status in TRIED:
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
            if not passed:
                fields["signature"] = signature(step, output or detail or "")
            self.events.append(event(self.t.id, "step", **fields))
        if detail:
            receipt["detail"] = detail
        self.steps.append(receipt)
        if status in TRIED and not passed and not self.failure:
            self.failure = (step, output or detail or "")
        return passed

    def not_run(self, *names):
        for name in names:
            if name == "sensors" and not self.project.config["sensors"]:
                continue  # a project with no sensor has no such step
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


def run_command(project, cwd, nn, step, command, run, patch_id=None, label=None, again=False):
    """Run one configured command in `cwd` and record it. With `again`, a command that fails is run once more at
    once: when that passes, the step still fails, and a `flake` event and the brief say that it did both on the same
    code. A race the change brought in looks exactly like a flake, so the second run proves nothing about the change."""
    keep_alive(project, run.t)
    env = {"RAIL_TICKET": nn, "RAIL_BASE": project.base_ref}
    code, output, ms = run_shell(command, cwd, env, configmod.timeout(project.config, step))
    missing = could_not_run(code)
    status = missing or ("timeout" if code is None else f"exit {code}")
    detail = (f"{label}: {status}" if code != 0 else label) if label else status
    shown = f"$ {command}\n{tail(output)}"
    if again and code != 0 and not missing:
        keep_alive(project, run.t)
        second, _, _ = run_shell(command, cwd, env, configmod.timeout(project.config, step))
        if second == 0:
            run.events.append(event(nn, "flake", step=step, command=command, patch_id=patch_id,
                                    codes=["timeout" if code is None else code, 0]))
            shown += f"\n\n{flakes.TOLD}"
    return run.record(step, code == 0, patch_id, detail, ms, output=shown,
                      status="could_not_run" if missing else "ran")


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


def base_checks(project, t):
    """Run each Check: line once in a freshly claimed ticket's worktree, which is still the base branch, and return
    the base_checks event: per check, red, green, could_not_run or timed_out. A check already green on the base
    can't show that the work was done. It is a recorded fact, never a gate: no step, no attempt, no state. None when
    it is switched off, already recorded, the ticket has no checks yet, or something went wrong."""
    commands = t.ticket.checks() if t.ticket else []
    if not commands or not project.config["commands"]["base_checks"] or t.last("base_checks"):
        return None
    head = gitx.rev(t.ref, project.root)
    try:
        return event(t.id, "base_checks", base=gitx.rev(project.base_ref, project.root)[:12],
                     checks=run_checks(project, commands, t.worktree, t.id))
    except Exception:
        return None  # a fact the engine couldn't gather; the claim goes on without it
    finally:
        # Checks may write files: the worktree goes back to what it was, as after a review.
        gitx.git(["reset", "--quiet", "--hard", head], t.worktree, check=False)
        gitx.git(["clean", "-fdq"], t.worktree, check=False)


def run_checks(project, commands, cwd, nn):
    """Run each check once in `cwd`: per check, red, green, could_not_run or timed_out."""
    timeout = project.config["commands"]["timeout_secs"]
    results = []
    for command in commands:
        code, _, _ = run_shell(command, cwd, {"RAIL_TICKET": nn, "RAIL_BASE": project.base_ref}, timeout)
        result = "timed_out" if code is None else "could_not_run" if could_not_run(code) else "green" if code == 0 else "red"
        results.append({"command": command, "result": result})
    return results


@contextlib.contextmanager
def scratch(project, commit):
    """A throwaway worktree at `commit`, detached, with the files .worktreeinclude lists. Removed afterwards."""
    path = tempfile.mkdtemp(prefix="rail-scratch-")
    gitx.git(["worktree", "add", "--quiet", "--detach", path, commit], project.root)
    try:
        copy_includes(project, path)
        yield path
    finally:
        gitx.git(["worktree", "remove", "--force", path], project.root, check=False)
        shutil.rmtree(path, ignore_errors=True)


# --- ship and CI -------------------------------------------------------------------

CHECKS = ["ticket-lint", "assumptions", "scope", "rules", "migration", "size", "doc-lint", "verify", "checks",
          "sensors"]


def _stop(run, step):
    run.not_run(*CHECKS[CHECKS.index(step) + 1:])
    return None


def check(project, nn, ticket, ref, cwd, tier, run, patch_id, accepted=None, offer=False, again=False):
    """The checks ship and CI share, in order, stopping at the first failure.

    Returns the tier the change needs (it may rise), or None when a check failed or, with `offer`, when an AUTO change
    over [size] cap is offered a split (a split_offered event, and no failure).
    """
    errors = lint(ticket, expect_id=nn)
    if accepted and not errors:
        # The contract and tier freeze at acceptance: only `rail amend` changes them.
        if ticket.contract_hash() != accepted.get("contract"):
            errors.append(f"the contract (Done Contract and scope_paths) differs from the accepted one; change it with"
                          f" rail amend {nn} \"why\"")
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

    needed, kinds = raised_tier(project, changed)
    if rank(needed) > rank(tier):
        kind, hits, key = kinds[0]
        run.events.append(event(nn, "tier_raised", **{"from": tier, "to": needed, "reason": key, "kind": kind,
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
    cap = project.config["size"]["cap"] if tier == "AUTO" else None  # a PERSON change has no cap: a person reads it
    run.record("size", True, patch_id, f"size {count}/{cap}" if cap else f"size {count}")
    run.size = count
    if cap is not None and count > cap and offer:
        # Once per ticket: the agent may split the change, because a reviewer checks a small change better. No step
        # failed, so it spends no attempt. Size raises no tier: a large change is reverted like a small one.
        run.events.append(event(nn, "split_offered", patch_id=patch_id, size=count, cap=cap))
        return _stop(run, "size")

    if gitx.read_blobs([f"{ref}:ARCHITECTURE.md"], project.root).get(f"{ref}:ARCHITECTURE.md") is None:
        run.not_run("doc-lint")
    else:
        problems = doclint.lint(project, ref)
        if not run.record("doc-lint", not problems, patch_id, f"{len(problems)} problems" if problems else None,
                          output="ARCHITECTURE.md:\n" + "\n".join(f"- {p}" for p in problems)):
            return _stop(run, "doc-lint")

    verify = project.config["commands"]["verify"]
    if verify:
        if not run_command(project, cwd, nn, "verify", verify, run, patch_id, again=again):
            return _stop(run, "verify")
    else:
        run.not_run("verify")

    if ticket.get("kind") == "revert":
        # No Check: lines: the change is compared with the reverse of the reverted ticket's change.
        from . import revert
        passed, detail, output = revert.check(project, run.t, project.tickets(), patch_id, ref)
        if not run.record("checks", passed, patch_id, detail, output=output):
            return _stop(run, "checks")
    for command in ticket.checks():
        if not run_command(project, cwd, nn, "checks", command, run, patch_id, label=command, again=again):
            return _stop(run, "checks")
    # Last, so that verify and the Done Contract speak first.
    from . import sensors
    if not sensors.step(project, nn, ref, cwd, run, patch_id, changed):
        return None
    return tier


def base_fails_verify(project):
    """Run verify once more on the base branch, in a scratch worktree. Returns its output when it fails there too."""
    with scratch(project, gitx.rev(project.base_ref, project.root)) as path:
        if project.config["commands"]["setup"]:
            run_shell(project.config["commands"]["setup"], path, {"RAIL_TICKET": ""},
                      configmod.timeout(project.config, "setup"))
        code, output, _ = run_shell(project.config["commands"]["verify"], path, {"RAIL_TICKET": ""},
                                    configmod.timeout(project.config, "verify"))
        # verify that can't start on the base proves nothing about the base: the ticket's own failure stands
        if code is None or code == 0 or could_not_run(code):  # None: it timed out, which proves nothing either
            return None
        return tail(output) or f"verify exits {code} on the base branch and prints nothing."


def ship(project, f, run):
    """Rebase onto a moved base, run the checks, and add a shipped event when all pass."""
    t, ref = f.t, f.t.ref
    wt = t.worktree
    base_tip = gitx.rev(project.base_ref, project.root)
    remote_tip = gitx.rev(f"refs/remotes/{project.remote}/{t.branch}", project.root) if project.remote else None
    if remote_tip and not gitx.ok(["merge-base", "--is-ancestor", remote_tip, "HEAD"], wt):
        # The agent rebased by hand after a conflict: the push needs the lease the engine notes for its own rebase.
        project.note_rewrite(t.branch)
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
    tier = check(project, t.id, Ticket(text or ""), ref, wt, f.tier, run, patch_id, accepted=f.accepted,
                 offer=not t.last("split_offered"), again=True)
    last = run.events[-1] if run.events and run.events[-1].get("event") == "step" else {}
    if tier is None and run.failure and last.get("result") == "fail":
        # A failure that may be the machine's costs no attempt; the second in a row waits for a person (TOOL_DOWN).
        if last.get("status") == "could_not_run":
            last["counted"] = False  # the shell could not start the command: nothing was checked
        elif run.failure[0] in ("verify", "checks", "sensors"):
            down = tools.down(project)
            if down:  # a declared tool is out of reach: the check may have failed for that alone
                last["counted"], last["tools_down"] = False, down
                run.failure = (run.failure[0], f"{run.failure[1]}\n\nA tool the project declares is out of reach"
                                               f" ({tools.down_said(down)}). {tools.DOWN_HELP}")
    if (tier is None and run.failure and run.failure[0] == "verify" and last.get("status") != "could_not_run"
            and not last.get("tools_down")):
        # A red base spends no budget: two tickets that each pass can break main together. A verify that could
        # not start is the machine's lack, not the base's: it is never taken for a red base.
        red = base_fails_verify(project)
        if red:
            run.events[-1]["counted"] = False
            run.events[-1]["detail"] = "red base"
            [s for s in run.steps if s["step"] == "verify"][-1]["detail"] = "red base"
            project.cache_write("red-base", "base", gitx.rev(project.base_ref, project.root))
            project.cache_write("red-base", "output", red)
            run.failure = ("verify", "verify fails on the base branch too, so this attempt doesn't count. rail next"
                                     " opens one ticket that fixes the base; this ticket's ship waits until it merges.")
    if tier is None:
        return run
    # Every check passed and no file changed: the checks passed before the ticket too, so there is nothing to ship
    # or merge. A sweep ticket is the one exception: it merges to move the sweep's marker.
    if not project.changed_files(ref) and not (f.ticket.get("external_id") or "").startswith("sweep#"):
        run.record("change", False, patch_id, "no file changed",
                   output=f"Ticket {t.id} changes no file, so there is nothing to ship. If the work is already on the"
                          f" base branch, say so and close the ticket: rail drop {t.id} --reason \"already done:"
                          f" where\". If it is not, make the change, then run: rail advance {t.id}")
        return run
    head = gitx.rev(ref, project.root)
    run.events.append(event(t.id, "shipped", patch_id=patch_id, head=head[:12], tier=tier, size=run.size))
    return run


def ship_failed_brief(t, run):
    step, output = run.failure
    if any(s.get("status") == "could_not_run" for s in run.steps):
        from . import sensors
        told = "" if sensors.HELP in output else f"\n\n{MISSING_HELP}"  # a sensor that crashed says so itself
        return (f"Ship of ticket {t.id} could not run '{step}'.\n{output}{told} Then run: rail advance {t.id}\n"
                f"{NOT_COUNTED}")
    if any(e.get("tools_down") for e in run.events):
        return f"Ship of ticket {t.id} failed at '{step}'.\n{output}\n\nThen run: rail advance {t.id}"
    tried = tried_help(step, ticket_path(t.id))
    return (f"Ship of ticket {t.id} failed at '{step}'.\n{output}\n\nFix it in the worktree, then run: rail advance {t.id}"
            + (f"\n{tried}" if tried else ""))


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
        said = "could not run" if e.get("status") == "could_not_run" else f"{e.get('status')}, {e.get('result')}"
        rows.append(f"| {name} | {said} |")
    from .review import Ledger, load_doc, needs_review
    ledger = Ledger(t.events, load_doc(t.review_text, t.id))
    changed = project.changed_files(t.ref)
    reviewed = needs_review(project, tier, changed)
    if not reviewed:
        # The table says what didn't run, and why: a reader must not take a missing row for a review.
        why = "every changed file is in [review] skip_paths" if changed else "no product file changed"
        rows.append(f"| review | not needed: {why} |")
    for role in ("review", "security"):
        if ledger.runs(role):
            own = [fid for fid, x in ledger.findings.items() if x.get("role") == role]
            open_ = [fid for fid in own if ledger.outcome(fid) == "open"]
            said = (f"{len(own)} findings, " + ("all answered" if not open_ else f"{len(open_)} open")) if own else "no findings"
            models = sorted({r["model"] for r in ledger.runs(role) if r.get("model")})
            by = f" by {', '.join(models)}" if models else ""
            rows.append(f"| {role} | ran, {len(ledger.runs(role))} runs{by}, {said} |")
    lockfiles = [p for p in changed if os.path.basename(p) in rules.LOCKFILES]
    migrations = "No migrations." if not ticket.get("reversibility") else (
        f"Migrations: {ticket.get('reversibility')}; rollback: {ticket.get('rollback')}.")
    risk = (f"{tier}. Touches {', '.join(ticket.scope)}. {migrations} "
            f"Changed lockfiles: {', '.join(lockfiles) or 'none'}.")
    risk += "".join(f"\n\nThe reviewer found what a revert doesn't undo: {said}" for said in ledger.asked_for_person())
    advisory = [ledger.describe(fid, with_answer=False) for fid in ledger.open_advisory()]
    external = ticket.get("external_id", "") or ""
    from . import readthese
    listed = readthese.items(project, t, ticket, tier, ledger, changed)
    added_count = sum(len(lines) for lines in readthese.numbered(project, t.ref).values())
    body = [
        # First, and built from facts: the author's own "Look at" below frames the change as its author sees it.
        "## Read these", *readthese.section(project, ticket, listed, added_count, reviewed), "",
        "## Why", f"{ticket.sections.get('Why', '')} (ticket {t.id})", "",
        "## Look at", ticket.sections.get("Look at") or "(not written)", "",
        "## Evidence", "| Step | Status |", "|---|---|", *rows, "",
        *(["Advisory findings left open, for the sweep:", *[f"- {line}" for line in advisory], ""] if advisory else []),
        "## Risk", risk, "",
        # Trailers. The sweep reads Review: to find what merged with no reviewer.
        f"Ticket: {t.id}", f"Tier: {tier}",
        "Review: " + (("reviewer, security seat" if tier == "PERSON" else "reviewer") if reviewed else "none"),
    ]
    from . import revert
    reverted = revert.target(project, ticket, project.tickets())
    if reverted and reverted[1]:
        body.append(f"Reverts: {reverted[1]}")  # rail stats reads it: a squash has neither of git's revert wordings
    if external.startswith("github#"):
        # A ticket narrowed to the first part of its request leaves the issue open for the rest.
        word = "Part of" if ticket.sections.get("Split") else "Closes"
        body.append(f"{word} #{external.split('#', 1)[1]}")
    if external.startswith("smoke#"):
        body.append(f"Part of #{external.split('#', 1)[1]}")  # the fix after this revert closes the issue
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
    if t.remote_branch and project.remote and not cloud():
        # Not from a cloud session: its git access can't delete a branch, and GitHub's "automatically delete head
        # branches" does it there (rail doctor checks that setting).
        result = gitx.push(project.root, project.remote, f":refs/heads/{t.remote_branch}") if project.online else "unavailable"
        if result == "ok":
            t.remote_branch = None
        else:
            leftovers.append({"kind": "remote branch", "ref": t.remote_branch, "reason": "deletion refused here"})
    return leftovers
