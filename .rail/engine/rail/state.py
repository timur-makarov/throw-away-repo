"""State derivation. State is derived from git and the journal, never stored."""

import os

from . import gitx
from .project import NON_PRODUCT, ticket_path
from .ticket import KINDS, TIERS, Ticket, highest, lint
from .util import globs_overlap, match_any, minutes_since

OPEN = ("implementing", "reviewing", "in-ci", "merge-ready")  # claimed and not finished
SHIP_STEPS = ("rebase", "ticket-lint", "assumptions", "scope", "change", "rules", "migration", "size", "doc-lint", "verify",
              "checks", "sensors")


def kind_paths(config):
    """(kind, globs, key) for each place the config names paths of a kind, in the order of KINDS: `[kinds]`, and the
    two older keys, `migration_paths` for `data-loss` and `person_paths` for `controls`."""
    found = []
    for kind in KINDS:
        if config["kinds"].get(kind):
            found.append((kind, config["kinds"][kind], "kinds"))
        if kind == "data-loss":
            found.append((kind, config["migration_paths"], "migration_paths"))
        if kind == "controls":
            found.append((kind, config["person_paths"], "person_paths"))
    return found


def floor(project, scope):
    """The tier the paths of a scope set, and each kind they reach as (kind, path, key): the path is a tracked file
    both match, or else the scope glob. Matched at add and amend."""
    if not hasattr(project, "_tracked"):
        listing = gitx.git(["ls-tree", "-r", "--name-only", project.base_ref], project.root, check=False)
        project._tracked = listing.stdout.splitlines()

    inside = [f for f in project._tracked if match_any(scope, f)]

    def hit(globs):
        path = next((f for f in inside if match_any(globs, f)), None)
        return path or next((s for s in scope for g in globs if globs_overlap(s, g)), None)

    found = [(kind, path, key) for kind, globs, key in kind_paths(project.config) if (path := hit(globs))]
    return ("PERSON" if found else "AUTO"), found


def raised_tier(project, files):
    """The tier the changed files need, and each kind they hold as (kind, [files], key). Used at ship."""
    found = []
    for kind, globs, key in kind_paths(project.config):
        hits = [f for f in files if match_any(globs, f)]
        if hits:
            found.append((kind, hits, key))
    return ("PERSON" if found else "AUTO"), found


def ticket_kinds(project, ticket):
    """The kinds a ticket holds as filed: those its person_reason names, in order, and those its scope's paths reach."""
    return list(dict.fromkeys(ticket.kinds + [k for k, _, _ in floor(project, ticket.scope)[1]]))


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
        # Dropped in its journal, with no mark on the counter branch yet: the drop keeps the ticket's worktree, branches
        # and pull request until the mark is written, so a drop never leaves no record at all.
        self.drop_pending = bool(t.last("dropped")) and not t.dropped_mark
        self.contract_merged = False
        self.patch_id = None
        self.dirty = []
        self.shipped = None
        self.last_fail = None
        self.machine_stuck = None
        self.split = None
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
        self.ci, self.ci_failing, self.conflict, self.behind, self.pushed = None, [], False, False, None
        self.merge_note = project.cache_read("merge", t.id)
        self.red_base = None
        self.sweep = bool(self.ticket) and (self.ticket.get("external_id") or "").startswith("sweep#")
        # A sweep is done once its review run is stored, or once its harvest step passed when nothing needed one.
        harvest = [e for e in t.events if e.get("event") == "step" and e.get("step") == "harvest"
                   and e.get("result") == "pass"]
        self.sweep_done = bool(harvest) or any(r.get("role") == "sweep" for r in self.ledger.doc["runs"])
        self.sweep_empty = bool(harvest) and harvest[-1].get("detail") == "nothing to file"

        author = self.ticket.tier if self.ticket and self.ticket.tier in TIERS else "AUTO"
        if self.accepted:
            raises = [e.get("to") for e in t.events if e.get("event") == "tier_raised"]
            self.tier = highest(self.accepted.get("tier"), author, *raises)
        elif self.ticket and not self.lint_errors:
            self.tier = highest(author, floor(project, self.ticket.scope)[0])
        else:
            self.tier = author
        self.auto = self.tier == "AUTO"  # the engine accepts its contract and merges it; a person does both for PERSON
        # A pull request is opened at the claim, or at add for a PERSON ticket's contract: only then is one that the
        # list of the newest pull requests lacks worth a call of its own.
        self.pr = self.forge.pr(t.name, expected=bool(claims) or not self.auto) if self.forge and t.name else None
        if self.forge and not t.name and t.on_base:
            # Its branch is gone. Only a merged pull request from that branch shows the ticket reached the base
            # branch by its own pull request, and not inside another ticket's merge.
            self.pr = self.forge.merged_from(t.id)
        self.labels = self.forge.labels(self.pr) if self.pr else set()
        self.stopped = self._stop()
        self.tools_missing = project.tools_missing()
        self.revert = self._revert(project)
        self._needs_review = None
        self.state = self._state()

    def _revert(self, project):
        """For a revert ticket with a worktree, what its brief says: the reverted ticket and its squash commit, whether
        the worktree holds exactly the reverse of that change, whether the reverse still applies to the base, and
        whether verify has failed on it."""
        from . import revert
        found = revert.target(project, self.ticket, project.tickets()) if self.ticket else None
        if not found:
            return None
        nn, sha = found
        tree = self.t.worktree if self.t.worktree and os.path.isdir(self.t.worktree) else None
        if not sha or not tree:
            return {"ticket": nn, "sha": sha, "exact": False, "applies": False, "failed": False}
        base = gitx.git(["merge-base", project.base_ref, "HEAD"], tree, check=False).stdout.strip()
        wanted = revert.exact(project, sha)
        return {"ticket": nn, "sha": sha, "exact": revert.in_worktree(project, tree) == wanted,
                "applies": bool(base) and revert.applies(project, sha, base), "base": base,
                "failed": revert.failed_verify(self.t.events, wanted)}

    def _stop(self):
        """The rail:stop issue that stops this ticket, or None: one with no paths stops every ticket, one with paths
        those whose scope can name a path the issue names. A revert ticket is never stopped: a brake can't block its
        own way out."""
        if self.ticket and self.ticket.get("kind") == "revert":
            return None
        scope = self.ticket.scope if self.ticket else []
        for stop in (self.forge.stops() if self.forge else []):
            if not stop["paths"] or any(globs_overlap(a, b) for a in scope for b in stop["paths"]):
                return stop
        return None

    def _budgets(self, project, events):
        """Retry budgets and the waits derived from the journal. A step is stuck when it fails the same way
        retry.budget times in a row; whatever the failures, retry.cap of them since it last passed wait for a person."""
        budget, cap = project.config["retry"]["budget"], project.config["retry"]["cap"]
        attempts, same, seen, consulted, since, failing = {}, {}, {}, {}, 0, None
        faults = {}      # step: [what failed, times in a row the same way, times in a row] for the machine's failures
        passed = None    # a step whose last event passed: its counts reset once the run leaves that step

        def settle():
            # Each Check: line is its own event at the step 'checks'. A line that passes before a later line
            # fails is no pass of the step, so a pass resets the counts only when no failure follows it.
            if passed is not None:
                attempts[passed] = same[passed] = 0
                seen.pop(passed, None)
                consulted.pop(passed, None)
                faults.pop(passed, None)

        accepted_at = amended_at = shipped_at = continued_at = -1
        self.amend_reason = ""
        spent = {}  # what the ticket's runs reported they cost since a person last acted, by what ran
        for i, e in enumerate(events):
            kind = e.get("event")
            if e.get("cost_usd") and kind in ("worked", "step"):
                what = (f"worker {e.get('model') or '(model not reported)'}" if kind == "worked"
                        else e.get("step") or "?")
                spent[what] = spent.get(what, 0.0) + e["cost_usd"]
            if passed is not None and not (kind == "step" and e.get("step") == passed):
                settle()
                passed = None
            if kind == "continued" or (kind == "accepted" and e.get("by") == "person"):
                # A person's act gives a fresh budget and a fresh cap, whether it continues a wait or approves.
                attempts, same, seen, consulted, since = {}, {}, {}, {}, i
                spent = {}
                faults.clear()
                if kind == "accepted":
                    accepted_at = i
                elif e.get("wait") != "BUDGET":  # going on past the budget is no approval of the merge
                    continued_at = i
            elif kind == "step" and e.get("status") in ("ran", "could_not_run"):
                step = e.get("step")
                if e.get("result") == "pass":
                    passed = step
                else:
                    passed = None
                if (e.get("result") != "pass" and e.get("counted") is False and step in SHIP_STEPS
                        and (e.get("status") == "could_not_run" or e.get("tools_down"))):
                    # The machine's failure, not the change's: a program the shell could not start, or a declared
                    # tool out of reach. It spends no attempt; the same one twice in a row waits for a person.
                    what = sorted(e["tools_down"]) if e.get("tools_down") else e.get("signature") or e.get("detail")
                    was = faults.get(step) or [None, 0, 0]
                    faults[step] = [what, was[1] + 1 if was[0] == what else 1, was[2] + 1, e]
                elif e.get("result") != "pass" and e.get("counted", True):
                    faults.pop(step, None)
                    # The same failure as the last one at this step, or a new one, which is progress. An event with
                    # no signature, from an older engine, is the same failure as its neighbour.
                    sig, last = e.get("signature"), seen.get(step)
                    repeat = attempts.get(step) and (not sig or not last or sig == last)
                    same[step] = same.get(step, 0) + 1 if repeat else 1
                    attempts[step] = attempts.get(step, 0) + 1
                    seen[step] = sig or last
                    if step in consulted:
                        consulted[step] += 1
                    failing = step
            elif kind == "consulted" and e.get("trigger") == "retry_cap":
                consulted[e.get("step")] = 0  # the failures since consult advised
            elif kind == "accepted":
                accepted_at = i
            elif kind == "amended" and e.get("needs_approval"):
                amended_at = i
                self.amend_reason = e.get("reason", "")
            elif kind == "shipped":
                shipped_at = i
        settle()
        self.consults = sum(1 for e in events if e.get("event") == "consulted")
        pack = os.path.join(project.root, ".rail", "packs", "consult", "bin", "consult")
        can_consult = os.path.exists(pack) and self.consults < 3
        self.attempts, self.same = attempts, same
        # (the failed step's event, times in a row), or None. The cap bounds failures that each look new.
        self.machine_stuck = next(((x[3], x[2]) for x in faults.values() if x[1] >= 2 or x[2] >= cap), None)
        self.failing = failing if attempts.get(failing) else None  # the step the ticket is failing now, if any
        # Why each step waits for a person: the cap, the attempt after consult, or the budget with
        # no consult to ask.
        self.capped_why = {}
        for s, n in attempts.items():
            if n >= cap:
                self.capped_why[s] = "cap"
            elif consulted.get(s):
                self.capped_why[s] = "consulted"
            elif s not in consulted and same[s] >= budget and not can_consult:
                self.capped_why[s] = "same"
        self.capped = list(self.capped_why)
        self.advised = [s for s, n in consulted.items() if n == 0]  # consult advised, and no attempt followed yet
        self.consult_due = next((s for s, n in same.items() if n >= budget and s not in consulted and can_consult
                                 and s not in self.capped_why), None)
        runs = [e for e in events[since:] if e.get("event") == "step" and e.get("step") in ("review", "security", "refuter")]
        # Two review runs in a row with no verdict, timed out or with invalid output: neither counts against the author.
        self.stuck_review = len(runs) >= 2 and all(e.get("counted") is False for e in runs[-2:])
        self.spent_by = {what: round(usd, 4) for what, usd in spent.items()}
        self.spent = round(sum(spent.values()), 4)
        limit = project.config["worker"]["ticket_usd"]
        self.over_budget = bool(limit) and self.spent > limit
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
    def rebasing(self):
        """The ticket's worktree is stopped in the middle of a rebase: only the agent there can end it."""
        return bool(self.t.rebasing)

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
        """Minutes since the last journal event the work on the ticket wrote: every engine move writes one and
        pushes it, and a session at work saves at least every claim.save_minutes. A person's answer is no such
        sign: the session that records a rail:go may be another one than the session that holds the claim."""
        times = [e.get("at", "") for e in list(self.t.events) + list(self.t.remote_events) if e.get("at") and not (
            e.get("event") == "continued" or (e.get("event") == "accepted" and e.get("by") == "person"))]
        return minutes_since(max(times)) if times else None

    @property
    def drafted_elsewhere(self):
        """Another session is writing this ticket's contract: it noted so less than claim.stale_minutes ago."""
        notes = sorted((e for e in list(self.t.events) + list(self.t.remote_events) if e.get("event") == "drafting"),
                       key=lambda e: e.get("at", ""))  # the remote's too: this clone's branch may be behind
        if self.state != "new" or not notes or notes[-1].get("session") == self.project.session:
            return False
        return minutes_since(notes[-1].get("at", "")) < self.project.config["claim"]["stale_minutes"]

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
        from .review import needs_review
        if self._needs_review is None:
            self._needs_review = needs_review(self.project, self.tier, self.project.changed_files(self.t.ref))
        return self._needs_review

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
        # The last word on the current patch: a shipped event, a split offered, or a ship step that failed.
        verdicts = [e for e in t.events if e.get("patch_id") == self.patch_id and (
            e.get("event") in ("shipped", "split_offered") or (e.get("event") == "step" and e.get("result") == "fail"
                                                              and e.get("step") in SHIP_STEPS))]
        if verdicts and verdicts[-1].get("event") == "shipped":
            self.shipped = verdicts[-1]
        elif verdicts and verdicts[-1].get("event") == "split_offered":
            self.split = verdicts[-1]
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
            # GitHub takes a while to see a push: a branch that already holds the base's tip is not behind, whatever
            # the pull request still says. Without this the engine rebases it again and again in one command.
            self.behind = (self.pr.get("mergeable_state") == "behind" and not gitx.ok(
                ["merge-base", "--is-ancestor", gitx.rev(project.base_ref, project.root), tip], project.root))
            if self.pushed:
                self.ci, self.ci_failing = self.forge.checks(tip)
            if self.conflict or self.ci == "red":
                return "implementing"  # a red required check or a conflict with base returns the ticket
        if self.needs_review and not self.ledger.complete(self.patch_id, self.tier):
            return "reviewing"
        if project.remote and (self.behind or not (self.pr_open and self.pushed and self.ci == "green")):
            return "in-ci"  # also green and behind its base: GitHub refuses that merge, so it is rebased first
        return "merge-ready"


def derive(project, tickets):
    """Facts for every ticket, with the cross-ticket facts: `after` and scope overlap."""
    facts = {nn: Facts(project, t) for nn, t in tickets.items()}
    # In flight until it merges: a ticket in review or CI still conflicts with one that starts on the same paths.
    implementing = [f for f in facts.values() if f.state in OPEN]
    for f in facts.values():
        if f.state != "accepted" or not f.ticket:
            continue
        f.after_open = [a for a in f.ticket.after if a not in facts or facts[a].state != "merged"]
        f.after_dropped = [a for a in f.after_open if a in facts and facts[a].state == "dropped"]
        f.overlaps = [o.id for o in implementing if o.ticket and any(
            globs_overlap(a, b) for a in f.ticket.scope for b in o.ticket.scope)]
    return facts
