"""The first-match table: for one ticket's facts, the first matching row names the next legal move.

Rows whose code is in TRANSITIONS are moves `next` makes itself (accepting an auto tier, claiming, resuming, asking
consult); `next` makes the move, derives the facts again, and reads the table once more.
"""

from .project import ticket_path

TRANSITIONS = {"ACCEPT_AUTO", "CLAIM", "RESUME", "CONSULT", "GO", "REBASE_BEHIND", "CONTRACT_MERGED"}
MERGE_PATIENCE = 600  # seconds a requested merge may take before a person looks
OPEN = ("implementing", "reviewing", "in-ci", "merge-ready")


def _join(items):
    return ", ".join(items)


def _done_contract(f):
    return f.ticket.sections.get("Done Contract", "") if f.ticket else ""


def _note(f):
    if not f.person_note:
        return ""
    return (f"\n\nA person said: \"{f.person_note}\". If that holds beyond this ticket, open a ticket that writes it into"
            " the project's part of AGENTS.md, or into a rule, so nobody has to say it twice.")


def _findings(f, intro):
    ids = f.ledger.unanswered()
    if not ids:
        return ""
    return "\n".join([
        "", intro,
        f"Fix each blocking finding in the worktree. Then answer every finding: rail answer {f.id} F1 fixed \"what you"
        f" changed\", or declined \"why it is not a problem\", or parked \"a real problem this change didn't cause\".",
        "Declining a blocking finding disputes it, and a fresh refuter decides.",
        *[f"- {f.ledger.describe(fid)}" for fid in ids],
    ])


def _size(f):
    from . import rules
    cap = f.project.config["size"].get(f.tier)
    if not cap or not f.worktree:
        return ""
    count, _ = rules.size(f.project, None, f.worktree)
    line = f"size {count}/{cap}"
    if count >= 0.8 * cap:
        line += (": past 80% of the cap. Split what is left into a new ticket (rail add); over the cap, the tier rises"
                 " and the change gets a reviewer")
    return line


def _migration(f):
    from .state import floor
    if floor(f.project, f.ticket.scope)[1] != "migration_paths":
        return ""
    return ("Migrations: expand, then contract. Write the down step and test the rollback. Set reversibility (such as"
            " expand-contract) and rollback in the ticket's front matter.")


def _implement(f):
    out_of_scope = f.ticket.sections.get("Out of scope", "")
    lines = [
        f"Implement ticket {f.id}: {f.ticket.title}",
        f"Work in {f.cwd}, on branch {f.t.branch}. The ticket is {ticket_path(f.id)}.",
        "", "Done Contract:", _done_contract(f), "",
        f"Change only paths inside scope_paths: {_join(f.ticket.scope)}.",
    ]
    if out_of_scope:
        lines += ["Out of scope:", out_of_scope]
    for extra in (_size(f), _migration(f)):
        if extra:
            lines.append(extra)
    lines += [
        "Before you ship, write \"## Look at\" in the ticket: what a reader of this change should check.",
        f"When the Done Contract holds, run: rail advance {f.id}",
    ]
    return "\n".join(lines) + _save_note(f) + _findings(f, "Open review findings:") + _note(f)


def _assumptions(f):
    rows = "\n".join(f"- {r}" for r in f.open_assumptions)
    return (f"Ticket {f.id} has open ASSUMED rows. Verify each one in the code or the docs before you implement,"
            f" then change \"ASSUMED:\" to \"VERIFIED:\" in {ticket_path(f.id)} and say how you checked."
            f" If you can't verify one, ask the person and stop.\n{rows}\nWork in {f.cwd}.")


def _step_failed(f):
    e = f.last_fail
    return (f"The last ship of ticket {f.id} failed at '{e.get('step')}': {e.get('detail', '')}. Nothing has changed"
            f" since. Fix the cause in {f.cwd}, then run: rail advance {f.id}") + _findings(f, "Open review findings:") + _note(f)


def _setup_failed(f):
    return (f"setup failed in {f.cwd}: {f.setup_failed.get('detail', '')}. Fix the cause, then run"
            f" rail next --ticket {f.id} to run setup again.")


def _answer(f):
    return (f"The review of ticket {f.id} left findings open. When you fix one, rail advance {f.id} ships the fix and"
            f" reviews it again." + _findings(f, "Findings:") + _note(f))


def _capped(f):
    steps = _join(f.capped)
    return (f"Ticket {f.id} used its retry budget at '{steps}' ({f.project.config['retry']['budget']} attempts, then the"
            f" attempt after consult). A person looks at the journal and the branch {f.t.name}, then continues it:"
            f" rail accept {f.id} \"what to do differently\". That gives a fresh budget." + _go(f))


def _pr(f):
    return f"PR #{f.pr['number']} ({f.pr['html_url']})" if f.pr else "its pull request"


def _go(f):
    """How a person continues a wait from GitHub, where a cloud session leaves them: the label on the pull request."""
    return (f" On GitHub: add the label rail:go to {_pr(f)}; a comment there reaches the agent as your note."
            if f.pr_open else "")


def _held(f):
    where = f" ({f.claimed['session_url']})" if f.claimed and f.claimed.get("session_url") else ""
    quiet, limit = f.quiet_minutes, f.project.config["claim"]["stale_minutes"]
    if f.taken_from_me:
        return (f"Ticket {f.id} was taken over by another session{where}. Stop work on it here: its branch has moved on"
                f" from this session's copy, and whatever isn't saved stays in {f.cwd} for you to look at. Take other"
                f" work with rail next.")
    return (f"Ticket {f.id} is another session's work{where}, quiet for {quiet if quiet is not None else '?'} min."
            f" After {limit} min with no move, rail next resumes it here. To take it over now: rail next --ticket {f.id}")


def _save_note(f):
    """Where no hook saves for the session, the agent does: unsaved work is lost with the machine, and a ticket that
    shows no life is taken to be abandoned."""
    if f.project.cache_read("hooks", f.project.session or ""):
        return ""
    return (f"\nNothing saves your work for you in this session. Run rail save {f.id} every ten minutes or so of work"
            " and before you stop: it pushes what you have, and shows other sessions this ticket is alive.")


def _red_check(f):
    lines = [f"A required check failed on {_pr(f)}. Fix the cause in {f.cwd}, then run: rail advance {f.id}"]
    for name, summary in f.ci_failing:
        lines += ["", f"{name}:", summary or "(no output; open the check on GitHub)"]
    return "\n".join(lines) + _findings(f, "Open review findings:") + _note(f)


def _merge_requested(f):
    sha, _, at = (f.merge_note or "").partition(" ")
    return sha == (f.pr or {}).get("head", {}).get("sha") and f.pr_open


def _merge_stale(f):
    import time
    sha, _, at = (f.merge_note or "").partition(" ")
    return _merge_requested(f) and at.isdigit() and time.time() - int(at) > MERGE_PATIENCE


def _merge_by_person(f):
    if f.project.remote:
        return f"Ticket {f.id} ({f.tier}) is ready: a person reviews and merges {_pr(f)}."
    return (f"Ticket {f.id} ({f.tier}) is ready to merge. A person reviews branch {f.t.name} and approves the merge:"
            f" rail accept {f.id}. The engine then merges it.")


ROWS = [
    # (code,               owner,   kind,          when,                                         brief)
    ("MERGED",             "none",  "rest",        lambda f: f.state == "merged",
     lambda f: f"Ticket {f.id} is merged."),
    ("DROPPED",            "none",  "rest",        lambda f: f.state == "dropped",
     lambda f: f"Ticket {f.id} was dropped."),
    ("TICKET_LINT",        "agent", "agent_task",  lambda f: f.state == "new" and f.lint_errors,
     lambda f: f"Ticket {f.id} isn't complete: {'; '.join(f.lint_errors)}. Read it ({ticket_path(f.id)} on branch"
               f" {f.t.name}), write the whole ticket to a file with its Done Contract, tier and scope_paths, and run:"
               f" rail amend {f.id} --file FILE"),
    ("GO",                 "agent", "script",      lambda f: "rail:go" in f.labels and f.state not in ("merged", "dropped")
                                                   and not (f.state == "new" and f.lint_errors),
     lambda f: f"rail next --ticket {f.id}"),
    ("CONTRACT_MERGED",    "agent", "script",      lambda f: f.state == "new" and f.contract_merged,
     lambda f: f"rail next --ticket {f.id}"),
    ("ACCEPT_AUTO",        "agent", "script",      lambda f: f.state == "new" and f.auto,
     lambda f: f"rail next --ticket {f.id}"),
    ("APPROVE_CONTRACT",   "human", "human_wait",  lambda f: f.state == "new",
     lambda f: f"Approve the contract of ticket {f.id} ({f.tier}): read {ticket_path(f.id)} on branch {f.t.name},"
               f" then run: rail accept {f.id}. To change it, say what to change. To reject it, run: rail drop {f.id}"
               + (f" On GitHub: {_pr(f)} shows the contract; the label rail:go approves it, a comment asks for a"
                  f" change, and closing it rejects it." if f.pr_open else "")),
    ("AFTER_DROPPED",      "human", "human_wait",  lambda f: f.state == "accepted" and f.after_dropped,
     lambda f: f"Ticket {f.id} comes after ticket {_join(f.after_dropped)}, which was dropped. A person decides:"
               f" remove it from `after` (rail amend {f.id} --file FILE), or drop ticket {f.id}."),
    ("WAITING_AFTER",      "none",  "rest",        lambda f: f.state == "accepted" and f.after_open,
     lambda f: f"Ticket {f.id} waits for ticket {_join(f.after_open)} to merge."),
    ("SCOPE_OVERLAP",      "none",  "rest",        lambda f: f.state == "accepted" and f.overlaps,
     lambda f: f"Ticket {f.id} can't be claimed while ticket {_join(f.overlaps)} changes the same paths."),
    ("CLAIM",              "agent", "script",      lambda f: f.state == "accepted",
     lambda f: f"rail next --ticket {f.id}"),
    ("APPROVE_AMEND",      "human", "human_wait",  lambda f: f.amend_pending,
     lambda f: f"The Done Contract of ticket {f.id} changed (rail amend). Read {ticket_path(f.id)} on branch {f.t.name},"
               f" then approve it: rail accept {f.id}." + _go(f)),
    ("RETRY_CAP",          "human", "human_wait",  lambda f: f.state in OPEN and f.capped,
     _capped),
    ("STUCK_REVIEW",       "human", "human_wait",  lambda f: f.state == "reviewing" and f.stuck_review,
     lambda f: f"The review of ticket {f.id} timed out twice (timeout_secs). A person looks at why, for example a command"
               f" that waits for input, then continues it: rail accept {f.id}." + _go(f)),
    ("FINDING_UPHELD",     "human", "human_wait",  lambda f: f.ledger.disputed_again(),
     lambda f: f"The refuter upheld {_join(f.ledger.disputed_again())} on ticket {f.id}, and the agent still disputes it."
               f" A person decides: rail answer {f.id} F1 declined \"why\" --owner, or rail accept {f.id} \"how to fix it\"."),
    ("HOLD",               "human", "human_wait",  lambda f: "rail:needs-you" in f.labels
                                                   and not (f.state == "merge-ready" and not f.auto),
     lambda f: f"A person holds ticket {f.id} with the label rail:needs-you on {_pr(f)}. They continue it with the"
               f" label rail:go, or: rail accept {f.id} \"note\""),
    # A claim protects work in flight. The waits above show from any session, and a shipped ticket (in CI, ready to
    # merge) needs no claim: the rows below move it from whichever session looks.
    ("CLAIMED_ELSEWHERE",  "none",  "rest",        lambda f: f.held and not f.explicit,
     _held),
    ("RESUME",             "agent", "script",      lambda f: f.in_flight and (f.claimed_elsewhere or not f.worktree),
     lambda f: f"rail next --ticket {f.id}"),
    ("CONSULT",            "agent", "script",      lambda f: f.state in OPEN and f.consult_due,
     lambda f: f"rail next --ticket {f.id}"),
    ("SWEEP_RUN",          "agent", "script",      lambda f: f.state == "implementing" and f.sweep and not f.sweep_done,
     lambda f: "rail sweep"),
    ("SWEEP_TICKETS",      "agent", "agent_task",  lambda f: f.state == "implementing" and f.sweep and not f.dirty
                                                   and not f.last_fail,
     lambda f: f"The sweep ran: read .rail/journal/{f.id}-summary.md in {f.cwd}. Open a ticket with rail add for each"
               f" finding worth one (set caused_by when a ticket caused it), and one ticket \"make it a check: ...\" for"
               f" each kind of proposed check. Drop duplicates. Change no code here. Then run: rail advance {f.id}"),
    ("SETUP_FAILED",       "agent", "agent_task",  lambda f: f.state == "implementing" and f.setup_failed,
     _setup_failed),
    ("VERIFY_ASSUMPTIONS", "agent", "agent_task",  lambda f: f.state == "implementing" and f.open_assumptions,
     _assumptions),
    ("RED_BASE",           "none",  "rest",        lambda f: f.state == "implementing" and f.red_base and f.last_fail
                                                   and f.last_fail.get("step") == "verify" and not f.dirty,
     lambda f: f"verify fails on the base branch too, so ticket {f.id} waits: a fix ticket for the base comes first."),
    ("CONFLICT",           "agent", "agent_task",  lambda f: f.state == "implementing" and f.conflict and not f.dirty,
     lambda f: f"{_pr(f)} conflicts with the base branch. Run: rail advance {f.id}. It rebases; when the rebase stops,"
               f" resolve the conflict in {f.cwd} and run it again."),
    ("RED_CHECK",          "agent", "agent_task",  lambda f: f.state == "implementing" and f.ci == "red" and not f.dirty,
     _red_check),
    ("STEP_FAILED",        "agent", "agent_task",  lambda f: f.state == "implementing" and f.last_fail and not f.dirty,
     _step_failed),
    ("IMPLEMENT",          "agent", "agent_task",  lambda f: f.state == "implementing",
     _implement),
    ("ANSWER_FINDINGS",    "agent", "agent_task",  lambda f: f.state == "reviewing" and f.ledger.unanswered(),
     _answer),
    ("REVIEW",             "agent", "script",      lambda f: f.state == "reviewing",
     lambda f: f"rail advance {f.id}"),
    ("FORGE_UNAVAILABLE",  "none",  "rest",        lambda f: f.state == "in-ci" and not f.forge,
     lambda f: f"Ticket {f.id} shipped. The forge can't be reached (no GitHub remote, offline, or gh not logged in),"
               f" so CI and the merge wait; rail doctor says which."),
    ("REBASE_BEHIND",      "agent", "script",      lambda f: f.state == "in-ci" and f.behind,
     lambda f: f"rail next --ticket {f.id}"),
    ("CI_WAIT",            "none",  "rest",        lambda f: f.state == "in-ci",
     lambda f: f"Ticket {f.id} shipped; CI runs on {_pr(f)}." if f.pushed else
               f"Ticket {f.id} shipped; its branch isn't pushed to {_pr(f)} yet: run rail advance {f.id}."),
    ("MERGE_FAILED",       "human", "human_wait",  lambda f: f.state == "merge-ready" and _merge_stale(f),
     lambda f: f"The merge of {_pr(f)} was requested and hasn't landed. A person looks at the pull request, then"
               f" continues: rail accept {f.id}." + _go(f)),
    ("MERGE_REQUESTED",    "none",  "rest",        lambda f: f.state == "merge-ready" and _merge_requested(f),
     lambda f: f"The merge of {_pr(f)} is requested; rail next sees it on the base branch once GitHub lands it."),
    ("MERGE",              "agent", "script",      lambda f: f.state == "merge-ready" and (f.auto or f.merge_approved)
                                                   and not (f.project.remote and not f.auto),
     lambda f: f"rail advance {f.id}"),  # it merges, and removes the worktree: run it from the project's root
    ("MERGE_BY_PERSON",    "human", "human_wait",  lambda f: f.state == "merge-ready",
     _merge_by_person),
]


def first_match(f):
    """(code, owner, action) for the first row that matches."""
    for code, owner, kind, when, brief in ROWS:
        if when(f):
            action = {"kind": kind, "brief": brief(f)}
            if kind == "script":
                action["command"] = action["brief"]
            return code, owner, action
    raise AssertionError(f"no row matches ticket {f.id} in state {f.state}")
