"""State derivation. State is derived from git and the journal, never stored."""

import os

from . import gitx
from .project import NON_PRODUCT, ticket_path
from .ticket import TIERS, Ticket, highest, lint, rank
from .util import globs_overlap, match_any, minutes_since

OPEN = ("implementing", "reviewing", "in-ci", "merge-ready")  # claimed and not finished
SHIP_STEPS = ("rebase", "ticket-lint", "assumptions", "scope", "rules", "migration", "size", "verify", "checks")


def floor(project, scope):
    """The tier the risk and migration paths set for a scope, and why. Matched at add."""
    cfg = project.config
    if not hasattr(project, "_tracked"):
        listing = gitx.git(["ls-tree", "-r", "--name-only", project.base_ref], project.root, check=False)
        project._tracked = listing.stdout.splitlines()

    def hits(globs):
        if any(globs_overlap(s, g) for s in scope for g in globs):
            return True
        return any(match_any(scope, f) and match_any(globs, f) for f in project._tracked)

    if hits(cfg["migration_paths"]):
        return "HIGH", "migration_paths"
    if hits(cfg["risk_paths"]["HIGH"]):
        return "HIGH", "risk_paths"
    if hits(cfg["risk_paths"]["MEDIUM"]):
        return "MEDIUM", "risk_paths"
    return "LOW", None


def raised_tier(project, files):
    """The tier the changed files need, and why. Used at ship."""
    cfg = project.config
    if any(match_any(cfg["migration_paths"], f) for f in files):
        return "HIGH", "migration_paths"
    if any(match_any(cfg["risk_paths"]["HIGH"], f) for f in files):
        return "HIGH", "risk_paths"
    if any(match_any(cfg["risk_paths"]["MEDIUM"], f) for f in files):
        return "MEDIUM", "risk_paths"
    return "LOW", None


class Facts:
    """Everything the first-match table reads about one ticket."""

    def __init__(self, project, t):
        self.project, self.t, self.id = project, t, t.id
        self.ticket = t.ticket
        self.explicit = False
        self.lint_errors = lint(t.ticket, expect_id=t.id) if t.ticket else ["the ticket file is missing"]
        self.accepted = t.last("accepted")
        # The newest claim, the remote's journal included: after a takeover this clone's own branch doesn't have it.
        claims = [e for e in list(t.events) + list(t.remote_events) if e.get("event") == "claimed"]
        self.claimed = sorted(claims, key=lambda e: e.get("at", ""))[-1] if claims else None  # of equal times, the later
        # A drop is an event in the journal, and a mark in the counter branch for when the journal's branch is gone.
        self.dropped_event = t.last("dropped") or ({"event": "dropped"} if t.dropped_mark else None)
        self.contract_merged = False
        self.patch_id = None
        self.dirty = []
        self.shipped = None
        self.last_fail = None
        self.setup_failed = None
        self.after_open = []
        self.after_dropped = []
        self.overlaps = []
        self.open_assumptions = []
        from .review import Ledger, load_doc
        self.ledger = Ledger(t.events, load_doc(t.review_text, t.id))
        self._budgets(project, t.events)
        # The forge's side: the ticket's PR, its labels, CI on its head, and a merge the engine requested.
        forge = getattr(project, "forge", None)
        self.forge = forge if forge is not None and forge.ok else None
        self.pr = self.forge.pr(t.name) if self.forge and t.name else None
        if self.forge and not t.name and t.on_base:
            # Its branch is gone. Only a merged pull request from that branch shows the ticket reached the base
            # branch by its own pull request, and not inside another ticket's merge.
            self.pr = self.forge.merged_from(t.id)
        self.labels = self.forge.labels(self.pr) if self.pr else set()
        self.ci, self.ci_failing, self.conflict, self.behind, self.pushed = None, [], False, False, None
        self.merge_note = project.cache_read("merge", t.id)
        self.red_base = None
        self.sweep = bool(self.ticket) and (self.ticket.get("external_id") or "").startswith("sweep#")
        self.sweep_done = any(r.get("role") == "sweep" for r in self.ledger.doc["runs"])

        author = self.ticket.tier if self.ticket and self.ticket.tier in TIERS else "LOW"
        if self.accepted:
            raises = [e.get("to") for e in t.events if e.get("event") == "tier_raised"]
            self.tier = highest(self.accepted.get("tier"), author, *raises)
        elif self.ticket and not self.lint_errors:
            self.tier = highest(author, floor(project, self.ticket.scope)[0])
        else:
            self.tier = author
        self.auto = self.tier in project.config["auto_tiers"]
        self.state = self._state()

    def _budgets(self, project, events):
        """Retry budgets and the waits derived from the journal."""
        budget = project.config["retry"]["budget"]
        attempts, consulted, since = {}, set(), 0
        accepted_at = amended_at = shipped_at = continued_at = -1
        for i, e in enumerate(events):
            kind = e.get("event")
            if kind == "continued" or (kind == "accepted" and e.get("by") == "person"):
                # A person's act gives a fresh budget, whether it continues a wait or approves.
                attempts, consulted, since = {}, set(), i
                if kind == "continued":
                    continued_at = i
                else:
                    accepted_at = i
            elif kind == "step" and e.get("status") == "ran":
                step = e.get("step")
                if e.get("result") == "pass":
                    attempts[step] = 0
                    consulted.discard(step)
                elif e.get("counted", True):
                    attempts[step] = attempts.get(step, 0) + 1
            elif kind == "consulted" and e.get("trigger") == "retry_cap":
                consulted.add(e.get("step"))
            elif kind == "accepted":
                accepted_at = i
            elif kind == "amended" and e.get("needs_approval"):
                amended_at = i
            elif kind == "shipped":
                shipped_at = i
        self.consults = sum(1 for e in events if e.get("event") == "consulted")
        pack = os.path.join(project.root, ".rail", "packs", "consult", "bin", "consult")
        can_consult = os.path.exists(pack) and self.consults < 3
        self.attempts = attempts
        self.consult_due = next((s for s, n in attempts.items() if n >= budget and s not in consulted and can_consult), None)
        self.capped = [s for s, n in attempts.items()
                       if (s in consulted and n > budget) or (s not in consulted and n >= budget and not can_consult)]
        runs = [e for e in events[since:] if e.get("event") == "step" and e.get("step") in ("review", "security", "refuter")]
        self.stuck_review = len(runs) >= 2 and all(e.get("detail") == "timeout" for e in runs[-2:])
        self.amend_pending = amended_at > accepted_at
        self.merge_approved = continued_at > shipped_at >= 0
        # A person's note from `accept` goes into the agent's briefs until the next ship.
        notes = [(i, e) for i, e in enumerate(events) if e.get("note") and (
            e.get("event") == "continued" or (e.get("event") == "accepted" and e.get("by") == "person"))]
        self.person_note = notes[-1][1]["note"] if notes and notes[-1][0] > shipped_at else None

    @property
    def worktree(self):
        return self.t.worktree

    @property
    def cwd(self):
        return self.project.rel(self.t.worktree) if self.t.worktree else None

    @property
    def claimed_elsewhere(self):
        return bool(self.claimed) and self.claimed.get("session") != self.project.session

    @property
    def in_flight(self):
        """An agent is, or should be, at work on it. A shipped ticket waiting for CI or a merge has no work in
        flight: the engine moves it, from any session."""
        return self.state in ("implementing", "reviewing")

    @property
    def quiet_minutes(self):
        """Minutes since the ticket's last journal event: every engine move writes one and pushes it, and a
        session at work saves at least every claim.save_minutes."""
        times = [e.get("at", "") for e in list(self.t.events) + list(self.t.remote_events) if e.get("at")]
        return minutes_since(max(times)) if times else None

    @property
    def taken_from_me(self):
        """Another session took this ticket over while this session's worktree for it is still here."""
        mine = any(e.get("event") == "claimed" and e.get("session") == self.project.session for e in self.t.events)
        return bool(self.worktree) and mine and self.claimed_elsewhere

    @property
    def held(self):
        """Another session's work in flight. Its claim holds while the ticket keeps moving: after
        claim.stale_minutes with no event, the session is taken to have ended (a cloud VM is reclaimed, a laptop
        closes), and the next session to look resumes the ticket."""
        if not (self.claimed_elsewhere and self.in_flight):
            return False
        quiet = self.quiet_minutes
        return quiet is None or quiet < self.project.config["claim"]["stale_minutes"]

    @property
    def needs_review(self):
        return rank(self.tier) >= rank("MEDIUM")

    @property
    def pr_open(self):
        return bool(self.pr) and self.pr.get("state") == "open"

    def _state(self):
        t, project = self.t, self.project
        # GitHub's list of pull requests carries merged_at, and no merged flag.
        merged_at = (self.pr or {}).get("merged_at") or ("9" if (self.pr or {}).get("merged") else None)
        ships = [e.get("at", "") for e in t.events if e.get("event") == "shipped"]
        if t.merged or (merged_at and ships and merged_at >= max(ships)):
            return "merged"
        # The ticket's own pull request was merged before the ticket shipped. The engine merges only what has
        # shipped, so a person merged the contract: that is their approval, and the work is still to do. A ticket
        # file that is on the base branch with no such pull request proves nothing: it may have come in with
        # another ticket's merge.
        self.contract_merged = not self.dropped_event and bool(merged_at)
        if self.dropped_event or (not t.name and not self.contract_merged):
            return "dropped"  # a dropped event, or the ID is all that is left: its branch is gone
        if self.pr and self.pr.get("state") == "closed" and not merged_at:
            return "dropped"  # the PR was closed without a merge
        if not self.accepted:
            return "new"
        if not self.claimed:
            return "accepted"

        self.patch_id = project.patch_id(t.ref)
        self.open_assumptions = self.ticket.open_assumptions()
        if self.worktree:
            self.dirty = gitx.dirty(self.worktree, exclude=[NON_PRODUCT[1]])
            copy = os.path.join(self.worktree, ticket_path(t.id))
            if os.path.exists(copy):  # the agent marks rows VERIFIED here before advance commits them
                with open(copy) as f:
                    self.open_assumptions = Ticket(f.read()).open_assumptions()
        steps = [e for e in t.events if e.get("event") == "step"]
        setups = [e for e in steps if e.get("step") == "setup"]
        if setups and setups[-1].get("result") == "fail":
            self.setup_failed = setups[-1]
        # The last word on the current patch: a shipped event, or a ship step that failed.
        verdicts = [e for e in t.events if e.get("patch_id") == self.patch_id and (
            e.get("event") == "shipped" or (e.get("event") == "step" and e.get("result") == "fail"
                                            and e.get("step") in SHIP_STEPS))]
        if verdicts and verdicts[-1].get("event") == "shipped":
            self.shipped = verdicts[-1]
        elif verdicts:
            self.last_fail = verdicts[-1]
        red = project.cache_read("red-base", "base")
        fixing = (self.ticket.get("external_id") or "").startswith("red-base#")
        if red and not fixing and red == gitx.rev(project.base_ref, project.root):
            self.red_base = red
        if self.dirty or not self.shipped:
            return "implementing"
        if self.pr_open:
            # The engine reads CI only once the ticket has shipped this patch, and only on the head it pushed.
            self.pr = self.forge.full(self.pr)
            tip = gitx.rev(t.ref, project.root)
            self.pushed = self.pr["head"]["sha"] == tip
            self.conflict = self.pr.get("mergeable_state") == "dirty"
            self.behind = self.pr.get("mergeable_state") == "behind"
            if self.pushed:
                self.ci, self.ci_failing = self.forge.checks(tip)
            if self.conflict or self.ci == "red":
                return "implementing"  # a red required check or a conflict with base returns the ticket
        if self.needs_review and not self.ledger.complete(self.patch_id, self.tier):
            return "reviewing"
        if project.remote and not (self.pr_open and self.pushed and self.ci == "green"):
            return "in-ci"
        return "merge-ready"


def derive(project, tickets):
    """Facts for every ticket, with the cross-ticket facts: `after` and scope overlap."""
    facts = {nn: Facts(project, t) for nn, t in tickets.items()}
    implementing = [f for f in facts.values() if f.state == "implementing"]
    for f in facts.values():
        if f.state != "accepted" or not f.ticket:
            continue
        f.after_open = [a for a in f.ticket.after if a not in facts or facts[a].state != "merged"]
        f.after_dropped = [a for a in f.after_open if a in facts and facts[a].state == "dropped"]
        f.overlaps = [o.id for o in implementing if o.ticket and any(
            globs_overlap(a, b) for a in f.ticket.scope for b in o.ticket.scope)]
    return facts
