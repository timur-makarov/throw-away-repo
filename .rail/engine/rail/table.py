"""The first-match table: for one ticket's facts, the first matching row names the next legal move.

Rows whose code is in TRANSITIONS are moves `next` makes itself (accepting an AUTO ticket, claiming, resuming, asking
consult); `next` makes the move, derives the facts again, and reads the table once more.
"""

import json
import os

from . import flakes, gitx, history, tools
from .project import advice_path, ticket_path
from .ticket import Ticket
from .util import MISSING_HELP, NOT_COUNTED, tried_help

TRANSITIONS = {"ACCEPT_AUTO", "CLAIM", "RESUME", "CONSULT", "GO", "REBASE_BEHIND", "CONTRACT_MERGED", "STUCK"}
MERGE_PATIENCE = 600  # seconds a requested merge may take before a person looks
OPEN = ("implementing", "reviewing", "in-ci", "merge-ready")


def _spent(f):
    return ", ".join(f"{what} ${usd:.2f}" for what, usd in sorted(f.spent_by.items(), key=lambda x: -x[1]))


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
        f"Fix each blocking finding in the worktree. Then answer each one: rail answer {f.id} F1 fixed \"what you"
        f" changed\", or declined \"why it is not a problem\", or parked \"a real problem this change didn't cause\".",
        "Declining or parking a blocking finding disputes it, and a fresh refuter decides whether it holds and whether"
        " this change caused it. An advisory finding doesn't hold the ticket: fix and answer it too, or leave it"
        " unanswered for the sweep.",
        *[f"- {f.ledger.describe(fid, scripts=True)}" for fid in ids + f.ledger.open_advisory()],
    ])


def _not_taken(f):
    """An issue that held a whole ticket, taken as a request only: say why, so whoever runs the bot can fix it."""
    req = next((e for e in f.t.events if e.get("event") == "requested"), None)
    if not req or not req.get("not_taken"):
        return ""
    return (f"\nThe issue held a whole ticket, and Rail took it only as a request: {req['not_taken']}. Write the"
            f" contract from it, keeping what it says.")


def _size(f):
    from . import rules
    if not f.auto or not f.worktree:
        return ""
    cap = f.project.config["size"]["cap"]
    count, _ = rules.size(f.project, None, f.worktree)
    line = f"size {count}/{cap}"
    if count >= 0.8 * cap:
        line += (": past 80% of the cap. Split what is left into a new ticket (rail add); over the cap, ship offers"
                 " a split once, because a reviewer checks a small change better")
    return line


def _migration(f):
    from .state import floor
    if not any(key == "migration_paths" for _, _, key in floor(f.project, f.ticket.scope)[1]):
        return ""
    return ("Migrations: expand, then contract. Write the down step and test the rollback. Set reversibility (such as"
            " expand-contract) and rollback in the ticket's front matter.")


def _base_green(f):
    """Every check of the contract as it stands passed on the base before any work: the checks can't tell done
    from not done yet. Quiet once the contract's checks differ from the ones run on the base."""
    found = f.t.last("base_checks")
    checks = (found or {}).get("checks") or []
    if not checks or any(c.get("result") != "green" for c in checks):
        return ""
    if [c.get("command") for c in checks] != f.ticket.checks():
        return ""
    return (f"Every Check: above already passed on the base branch before any work, so the contract can't tell done"
            f" from not done. A new test in a file these checks already run does not change the contract. Add a Check:"
            f" line that fails now and passes once the work is done, such as one that runs your new test by name: edit"
            f" the Done Contract in {ticket_path(f.id)}, then run rail amend {f.id} \"why\".")


def _ticket_now(f):
    """The ticket as the worktree has it: the agent writes ## Tried and ## Look at there before a ship commits them."""
    if f.worktree:
        try:
            with open(os.path.join(f.worktree, ticket_path(f.id)), encoding="utf-8") as copy:
                return Ticket(copy.read())
        except OSError:
            pass
    return f.ticket


def _tried(f):
    """What earlier attempts at this ticket tried, for an agent that starts with none of their context."""
    tried = _ticket_now(f).tried()
    if not tried:
        return []
    return ["Tried before on this ticket, and it didn't work (## Tried in the ticket):", *[f"- {t}" for t in tried]]


def _implement(f):
    out_of_scope = f.ticket.sections.get("Out of scope", "")
    decided = f.ticket.decided()
    lines = [
        f"Implement ticket {f.id}: {f.ticket.title}",
        f"Work in {f.cwd}, on branch {f.t.branch}. The ticket is {ticket_path(f.id)}.",
        "", "Why:", f.ticket.sections.get("Why", ""), "",
        *(["Decided when the ticket was written, and not checked. Keep to each one, or write in the ticket why it is"
           " wrong:", *[f"- {row}" for row in decided], ""] if decided else []),
        "Done Contract:", _done_contract(f), "",
    ]
    if _base_green(f):
        lines += [_base_green(f), ""]
    lines += [
        f"Change only paths inside scope_paths: {_join(f.ticket.scope)}.",
    ]
    if out_of_scope:
        lines += ["Out of scope:", out_of_scope]
    for extra in (_size(f), _migration(f)):
        if extra:
            lines.append(extra)
    past = history.text(history.of(f.project, f.ticket.scope, skip=f.id))
    for extra in (tools.lines(f.project), _tried(f), past):
        if extra:
            lines += ["", *extra]
    lines += [
        *([""] if _tried(f) or past or f.project.config["tools"] else []),
        "Before you ship, write \"## Look at\" in the ticket: what a reader of this change should check. A problem you"
        " see outside this ticket is not yours to fix here: leave it, and write a line there that starts \"Noticed:\".",
        f"When the Done Contract holds, run: rail advance {f.id}",
    ]
    return "\n".join(lines) + _save_note(f) + _findings(f, "Open review findings:") + _note(f)


def _revert(f):
    """A revert ticket's work, where the engine couldn't leave it done."""
    r, nn = f.revert, f.id
    if not r["sha"]:
        return (f"Ticket {nn} reverts ticket {r['ticket']}, and no commit on the base branch merged a ticket"
                f" {r['ticket']}: there is nothing to reverse. `reverts` names the id of a merged ticket. End this"
                f" one: rail drop {nn} --reason \"ticket {r['ticket']} was never merged\"")
    short = r["sha"][:12]
    head = f"Ticket {nn} reverts ticket {r['ticket']}: take its change (commit {short}) out again. Work in {f.cwd}."
    if r["applies"] and not r["failed"]:
        from .revert import RESTORE
        return (f"{head}\nThe reverse of that change still applies as it is, and the worktree holds something else."
                f" Put the exact reverse in its place:\n  git restore --source={r['base'][:12]} --staged --worktree -- .\n"
                f"  {RESTORE.format(sha=short)}\nThen run: rail advance {nn}\nIf verify fails on it, later work depends"
                " on what that change removes: adapt the revert by hand, inside scope_paths, and run rail advance"
                f" {nn} again. A revert made by hand is accepted once verify has failed on the exact one."
                + _save_note(f) + _note(f))
    why = ("Verify failed on the exact reverse of that change: later work depends on what it removes." if r["failed"] else
           "The reverse of that change no longer applies, because later tickets changed the same lines.")
    return (f"{head}\n{why} Undo"
            f" by hand what ticket {r['ticket']} changed, and keep the later work: `git show {short}` shows the change."
            f" Change only paths inside scope_paths: {_join(f.ticket.scope)}.\nWhen the project holds without that"
            f" change, run: rail advance {nn}" + _save_note(f) + _findings(f, "Open review findings:") + _note(f))


def _split(f):
    e, nn = f.split, f.id
    return "\n".join([
        f"This change is {e.get('size')} lines, over [size] cap of {e.get('cap')}. A reviewer checks a change of that"
        " size badly, so see whether it splits into tickets that each stand alone.", "",
        "It splits when you can name a first part that is under the cap, meets at least one Check: of the Done Contract"
        " on its own, and leaves the code working. If you can:",
        f"1. Keep the first part on this ticket's branch, {f.t.branch}. Move the rest to a branch of its own, so"
        f" nothing is lost: git branch split/{nn}-rest, then take the rest out of {f.cwd}."
        + (f" Push that branch (git push {f.project.remote} split/{nn}-rest): another session may work the later"
           " tickets." if f.project.remote else ""),
        f"2. Narrow this ticket's contract to the first part: in {f.cwd}, edit {ticket_path(nn)} (the Done Contract,"
        f" and scope_paths if they shrink), then run rail amend {nn} \"why\". On an AUTO ticket the engine accepts the"
        " narrowed contract at once: no person approves it.",
        f"3. File one ticket for each remaining part with rail add: its own Check: lines, after = [\"{nn}\"] (or the"
        f" part before it), a line in ## Request saying it was split from ticket {nn}, and under ## Look at the branch"
        f" that holds its code, split/{nn}-rest.",
        f"4. Run rail advance {nn}.", "",
        f"If it does not split (the parts would not work alone, or each Check: needs all of it), change nothing and run"
        f" rail advance {nn}: the ticket stays AUTO and goes on to review as it is.",
    ]) + _note(f)


def _assumptions(f):
    rows = "\n".join(f"- {r}" for r in f.open_assumptions)
    return (f"Ticket {f.id} has open ASSUMED rows. Verify each one in the code or the docs before you implement,"
            f" then change \"ASSUMED:\" to \"VERIFIED:\" in {ticket_path(f.id)} and say how you checked."
            f" A row you can't verify is a choice, not a fact, and nobody is here to ask. Decide it: keep the reading"
            f" the ticket's `## Why` supports, change the row to `VERIFIED:` and start it with `decided, not checked:`,"
            f" then your reason and what it costs if you are wrong. On a PERSON ticket the person approved the contract"
            f" with these rows in it.\n{rows}\nWork in {f.cwd}.")


def _failure_output(f, e):
    """The output of the failed ship step `e`, which the answer of that `advance` showed. The journal keeps only the
    step's detail; advance keeps the output in the local cache, so a later brief for the same failure has it too."""
    try:
        kept = json.loads(f.project.cache_read("failure", f.id) or "null")
    except ValueError:
        return ""
    if not isinstance(kept, dict) or kept.get("patch_id") != e.get("patch_id") or \
            e.get("signature") not in (kept.get("signatures") or []):
        return ""
    return kept.get("output") or ""


def _step_failed(f):
    e = f.last_fail
    output = _failure_output(f, e)
    if flakes.TOLD not in output and any(x["step"] == e.get("step") and x["patch_id"] == e.get("patch_id")
                                         for x in flakes.of(f.t.events)):
        output = f"{output}\n\n{flakes.TOLD}".strip()  # another machine's ship: the journal still says so
    end = f".\n{output}\n\n" if output else ". "
    if e.get("status") == "could_not_run":
        from . import sensors
        # A sensor that ended with an exit it doesn't declare crashed or is set up wrongly: no tool is missing.
        crashed = e.get("step") == "sensors" and "could not run (" not in (e.get("detail") or "")
        told = MISSING_HELP if not crashed else "" if sensors.HELP in output else sensors.HELP
        return (f"The last ship of ticket {f.id} could not run '{e.get('step')}': {e.get('detail', '')}{end}"
                f"{told} Then run: rail advance {f.id}".replace("\n\n Then", "\n\nThen")
                + (f"\n{NOT_COUNTED}" if e.get("counted") is False else "")
                ) + _findings(f, "Open review findings:") + _note(f)
    if e.get("tools_down"):
        from . import tools
        return (f"The last ship of ticket {f.id} failed at '{e.get('step')}': {e.get('detail', '')}{end}A tool the"
                f" project declares was out of reach ({tools.down_said(e['tools_down'])}). {tools.DOWN_HELP} Then run:"
                f" rail advance {f.id}") + _findings(f, "Open review findings:") + _note(f)
    tried = "".join(f"\n{line}" for line in _tried(f))
    return (f"The last ship of ticket {f.id} failed at '{e.get('step')}': {e.get('detail', '')}{end}Nothing has changed"
            f" since. Fix the cause in {f.cwd}, then run: rail advance {f.id}\n"
            f"{tried_help(e.get('step'), ticket_path(f.id))}{tried}".rstrip()) + _advice(f, e.get("step")) \
        + _findings(f, "Open review findings:") + _note(f)


def _advice(f, step):
    """Consult's latest advice, while the attempt it was given for is still to come. `rail advance` shows it once;
    a fresh worker gets its brief from `rail next` and would otherwise never see it."""
    if step not in f.advised:
        return ""
    ref = f"{f.t.ref}:{advice_path(f.id)}"
    text = gitx.read_blobs([ref], f.project.root).get(ref) or ""
    last = text.strip().rsplit("\n## ", 1)[-1].strip()
    return f"\n\nConsult advised on this failure:\n## {last.removeprefix('## ')}" if last else ""


def _could_not_run(f, steps):
    """For a person at the retry cap: which of the capped steps last ended without running at all."""
    last = {}
    for e in f.t.events:
        if e.get("event") == "step" and e.get("step") in steps:
            last[e["step"]] = e
    missing = [f"'{s}' ({e.get('detail')})" for s, e in last.items() if e.get("status") == "could_not_run"]
    if not missing:
        return ""
    return (f" Its last attempt at {_join(missing)} could not run: the shell couldn't start the command or a tool it"
            f" calls, so nothing was checked.")


def _setup_failed(f):
    return (f"setup failed in {f.cwd}: {f.setup_failed.get('detail', '')}. Fix the cause, then run"
            f" rail next --ticket {f.id} to run setup again.")


def _answer(f):
    return (f"The review of ticket {f.id} left findings open. When you fix one, rail advance {f.id} ships the fix and"
            f" reviews it again." + _findings(f, "Findings:") + _note(f))


def _stuck(f, step):
    """Why a step waits for a person: the same failure at the budget, or the cap on failures of any kind."""
    if f.capped_why[step] == "cap":
        return f"'{step}' failed {f.attempts[step]} times since it last passed, whatever the output ([retry] cap)"
    after = ", then once more after consult" if f.capped_why[step] == "consulted" else ""
    return f"'{step}' failed the same way {f.project.config['retry']['budget']} times in a row{after} ([retry] budget)"


def _capped(f):
    return (f"Ticket {f.id} is stuck: {'; '.join(_stuck(f, s) for s in f.capped)}.{_could_not_run(f, f.capped)} A person"
            f" looks at the journal and the branch {f.t.name}, then continues it: rail accept {f.id} \"what to do"
            f" differently\". That gives a fresh budget and a fresh cap." + _go(f))


def _tool_down(f):
    """A step failed for the machine's own reason more than once in a row: more attempts would not mend it."""
    e, times = f.machine_stuck
    step = e.get("step")
    if e.get("tools_down"):
        from . import tools
        said = (f"it failed {times} times in a row while a tool the project declares was out of reach"
                f" ({tools.down_said(e['tools_down'])}). No failure of these counted as an attempt, since it may not be"
                f" the change's. A person checks that the tool answers and that its credential is valid on this machine")
    else:
        said = (f"its command could not run {times} times in a row ({e.get('detail', '')}), so nothing was checked and"
                f" no attempt was counted. A person installs what it needs on this machine, and adds it to [commands]"
                f" provision so that every cloud machine and CI runner gets it")
    return (f"Ticket {f.id} can't get past '{step}' on this machine: {said}, then continues the ticket:"
            f" rail accept {f.id}." + _go(f))


def stuck_reason(f):
    """(reason, step, signature) for an AUTO ticket the engine drops at the retry cap: what was tried and why it
    stopped. It goes into the dropped event, the drop mark and the issue's comment."""
    step = f.capped[0]
    last = [e for e in f.t.events if e.get("event") == "step" and e.get("step") == step and e.get("result") == "fail"]
    detail = last[-1].get("detail") if last else ""
    reason = f"stuck: {_stuck(f, step)}" + (f"; the last failure: {detail}" if detail else "")
    return reason, step, last[-1].get("signature") if last else None


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
    if f.project.session and f.project.cache_read("hooks", f.project.session):
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
    asked = "".join(f"\nThe reviewer found what a revert doesn't undo: {said}" for said in f.ledger.asked_for_person())
    if f.project.remote:
        return f"Ticket {f.id} ({f.tier}) is ready: a person reviews and merges {_pr(f)}." + asked
    return (f"Ticket {f.id} ({f.tier}) is ready to merge. A person reviews branch {f.t.name} and approves the merge:"
            f" rail accept {f.id}. The engine then merges it." + asked)


def stop_brief(stop, what):
    """What a brake's wait says, about one ticket or about the repository."""
    where = f" for the paths {', '.join(stop['paths'])}" if stop["paths"] else ""
    return (f"A person stopped Rail{where}: issue #{stop['number']} ({stop['title']}) is open with the label rail:stop."
            f" Nothing is done on {what} until that issue is closed or loses the label; a run that then starts goes on"
            f" by itself. Do no work on it meanwhile. {stop['url']}").rstrip()


ROWS = [
    # (code,               owner,   kind,          when,                                         brief)
    ("MERGED",             "none",  "rest",        lambda f: f.state == "merged",
     lambda f: f"Ticket {f.id} is merged."),
    # A drop whose mark on the counter branch couldn't be written: everything stays until a later rail next writes it.
    ("DROP_PENDING",       "none",  "rest",        lambda f: f.state == "dropped" and f.drop_pending,
     lambda f: f"Ticket {f.id} is dropped, and its mark on the counter branch isn't written yet: the remote can't be"
               f" reached or refused the push. Its worktree, branches and pull request stay until a later rail next"
               f" writes the mark and finishes the drop."),
    ("DROPPED",            "none",  "rest",        lambda f: f.state == "dropped",
     lambda f: f"Ticket {f.id} was dropped."),
    # A person's brake, an open issue labelled rail:stop, comes before every row that sends anyone to the ticket.
    ("STOPPED",            "person", "person_wait",  lambda f: f.stopped and f.state not in ("merged", "dropped"),
     lambda f: stop_brief(f.stopped, f"ticket {f.id}")),
    # A rebase stopped in the ticket's worktree. Until it ends the engine writes nothing to the ticket: git moves
    # the branch when the rebase finishes. Another session's fresh work is still left alone (CLAIMED_ELSEWHERE).
    ("REBASING",           "agent", "agent_task",  lambda f: f.rebasing and f.state in OPEN and not (f.held and not f.explicit),
     lambda f: f"A rebase is under way in {f.cwd} (ticket {f.id}, branch {f.t.branch}). Finish it there: resolve each"
               f" conflicted file, git add it, then git rebase --continue. To give the rebase up: git rebase --abort."
               f" Then run: rail advance {f.id}\nRail writes nothing to the ticket until the rebase has ended."),
    # A ticket whose runs cost more than [worker] ticket_usd since a person last acted stops in every state, before
    # any row that sends an agent to it. A person's answer comes first, so it can go on.
    ("GO",                 "agent", "script",      lambda f: f.over_budget and "rail:go" in f.labels
                                                   and f.state not in ("merged", "dropped"),
     lambda f: f"rail next --ticket {f.id}"),
    ("BUDGET",             "person", "person_wait",  lambda f: f.over_budget and f.state not in ("merged", "dropped"),
     lambda f: f"Ticket {f.id} has spent ${f.spent:.2f} since a person last acted, over [worker] ticket_usd"
               f" (${f.project.config['worker']['ticket_usd']:g}): {_spent(f)}. These are the costs the runs reported,"
               f" not the bill. To let it go on, with the count starting again: rail accept {f.id}, or the rail:go label"
               f" on its pull request. To end it: rail drop {f.id} --by person"),
    # One session writes a contract: four that start at once would each send a worker to write the same one.
    ("CONTRACT_ELSEWHERE", "none",  "rest",        lambda f: f.state == "new" and f.lint_errors and f.drafted_elsewhere
                                                   and not f.explicit,
     lambda f: f"Another session is writing the contract of ticket {f.id}. Leave it; rail next --ticket {f.id} takes it over"
               " when that session is gone."),
    ("TICKET_LINT",        "agent", "agent_task",  lambda f: f.state == "new" and f.lint_errors,
     lambda f: f"Ticket {f.id} isn't complete: {'; '.join(f.lint_errors)}. Read it ({ticket_path(f.id)} on branch"
               f" {f.t.name}), write the whole ticket to a file with its Done Contract, tier and scope_paths, and run:"
               f" rail amend {f.id} --file FILE" + _not_taken(f)),
    ("GO",                 "agent", "script",      lambda f: "rail:go" in f.labels and f.state not in ("merged", "dropped")
                                                   and not (f.state == "new" and f.lint_errors),
     lambda f: f"rail next --ticket {f.id}"),
    ("CONTRACT_MERGED",    "agent", "script",      lambda f: f.state == "new" and f.contract_merged,
     lambda f: f"rail next --ticket {f.id}"),
    ("ACCEPT_AUTO",        "agent", "script",      lambda f: f.state == "new" and f.auto,
     lambda f: f"rail next --ticket {f.id}"),
    ("APPROVE_CONTRACT",   "person", "person_wait",  lambda f: f.state == "new",
     lambda f: f"Approve the contract of ticket {f.id} ({f.tier}): read {ticket_path(f.id)} on branch {f.t.name},"
               f" then run: rail accept {f.id}. To change it, say what to change. To reject it, run: rail drop {f.id} --by person"
               + (f" On GitHub: {_pr(f)} shows the contract; the label rail:go approves it, a comment asks for a"
                  f" change, and closing it rejects it." if f.pr_open else "")),
    # On AUTO no person is asked: whether the ticket stands without the dropped one is the contract writer's call,
    # and either answer is recorded and can be undone.
    ("AFTER_DROPPED",      "agent", "agent_task",  lambda f: f.state == "accepted" and f.after_dropped and f.auto,
     lambda f: f"Ticket {f.id} comes after ticket {_join(f.after_dropped)}, which was dropped. Read both tickets and"
               f" decide whether ticket {f.id} still stands without it. If it does, remove {_join(f.after_dropped)}"
               f" from `after`: write the whole ticket to a file and run rail amend {f.id} \"why it stands without"
               f" it\" --file FILE. If it doesn't, drop it: rail drop {f.id} --reason \"why\"."),
    ("AFTER_DROPPED",      "person", "person_wait",  lambda f: f.state == "accepted" and f.after_dropped,
     lambda f: f"Ticket {f.id} comes after ticket {_join(f.after_dropped)}, which was dropped. A person decides:"
               f" remove it from `after` (rail amend {f.id} \"why\" --file FILE), or drop ticket {f.id}."),
    ("WAITING_AFTER",      "none",  "rest",        lambda f: f.state == "accepted" and f.after_open,
     lambda f: f"Ticket {f.id} waits for ticket {_join(f.after_open)} to merge."),
    ("SCOPE_OVERLAP",      "none",  "rest",        lambda f: f.state == "accepted" and f.overlaps,
     lambda f: f"Ticket {f.id} can't be claimed while ticket {_join(f.overlaps)} changes the same paths."),
    ("TOOL_MISSING",       "person", "person_wait",  lambda f: f.state == "accepted" and f.tools_missing,
     lambda f: tools.wait_brief(f.id, f.tools_missing)),
    ("CLAIM",              "agent", "script",      lambda f: f.state == "accepted",
     lambda f: f"rail next --ticket {f.id}"),
    ("APPROVE_AMEND",      "person", "person_wait",  lambda f: f.amend_pending,
     lambda f: f"The Done Contract of ticket {f.id} changed (rail amend)."
               + (f" The agent's reason: {f.amend_reason}" if f.amend_reason else "") + f" Read {ticket_path(f.id)} on branch {f.t.name},"
               f" then approve it: rail accept {f.id}." + _go(f)),
    ("RETRY_CAP",          "person", "person_wait",  lambda f: f.state in OPEN and f.capped and not f.auto,
     _capped),
    ("TOOL_DOWN",          "person", "person_wait",  lambda f: f.state in OPEN and f.machine_stuck,
     lambda f: _tool_down(f)),
    ("STUCK_REVIEW",       "person", "person_wait",  lambda f: f.state == "reviewing" and f.stuck_review,
     lambda f: f"The review of ticket {f.id} failed twice in a row with no verdict: it timed out (timeout_secs) or its"
               f" output was invalid. A person looks at why, for example a command that waits for input or a reviewer"
               f" that can't return review/v1, then continues it: rail accept {f.id}." + _go(f)),
    ("FINDING_UPHELD",     "person", "person_wait",  lambda f: f.ledger.disputed_again(),
     lambda f: f"The refuter upheld {_join(f.ledger.disputed_again())} on ticket {f.id}, and the agent still disputes it."
               f" A person decides: rail answer {f.id} F1 declined \"why\" --owner, rail answer {f.id} F1 parked"
               f" \"why\" --owner when this change didn't cause it, or rail accept {f.id} \"how to fix it\"."),
    ("MERGE_FAILED",       "person", "person_wait",  lambda f: f.state == "merge-ready" and _merge_stale(f),
     lambda f: f"The merge of {_pr(f)} was requested and hasn't landed. A person looks at the pull request, then"
               f" continues: rail accept {f.id}." + _go(f)),
    ("HOLD",               "person", "person_wait",  lambda f: "rail:hold" in f.labels,
     lambda f: f"A person holds ticket {f.id} with the label rail:hold on {_pr(f)}. They continue it with the"
               f" label rail:go, or: rail accept {f.id} \"note\""),
    # A claim protects work in flight. The waits above show from any session, and a shipped ticket (in CI, ready to
    # merge) needs no claim: the rows below move it from whichever session looks.
    ("CLAIMED_ELSEWHERE",  "none",  "rest",        lambda f: f.held and not f.explicit,
     _held),
    # An AUTO ticket at the retry cap: nothing merged, so nothing needs undoing, and the engine drops it with a
    # record instead of asking a person. A PERSON ticket waits (RETRY_CAP).
    ("STUCK",              "agent", "script",      lambda f: f.state in OPEN and f.capped and f.auto,
     lambda f: f"rail next --ticket {f.id}"),
    ("RESUME",             "agent", "script",      lambda f: f.in_flight and (f.claimed_elsewhere or not f.worktree),
     lambda f: f"rail next --ticket {f.id}"),
    ("CONSULT",            "agent", "script",      lambda f: f.state in OPEN and f.consult_due,
     lambda f: f"rail next --ticket {f.id}"),
    ("SWEEP_RUN",          "agent", "script",      lambda f: f.state == "implementing" and f.sweep and not f.sweep_done,
     lambda f: "rail sweep"),
    # A sweep that found nothing has no task for the agent: it ships and merges, which moves the Sweep: marker.
    ("SWEEP_EMPTY",        "agent", "script",      lambda f: f.state == "implementing" and f.sweep and f.sweep_empty
                                                   and not f.dirty and not f.last_fail,
     lambda f: f"rail advance {f.id}"),
    ("SWEEP_TICKETS",      "agent", "agent_task",  lambda f: f.state == "implementing" and f.sweep and not f.dirty
                                                   and not f.last_fail,
     lambda f: f"The sweep ran: read .rail/journal/{f.id}-summary.md in {f.cwd}. Open a ticket with rail add for each"
               f" finding that names something wrong: an input or a sequence that fails, or a doc that no longer"
               f" matches the code (set caused_by when a ticket caused it); a finding about style, naming or where a"
               f" test lives gets no ticket. Open one ticket \"make it a check: ...\" for"
               f" each kind of proposed check. Open one ticket for each pattern in the worker runs, for what would have"
               f" told the worker: a setup or provision command, a line in the project's part of AGENTS.md, or a guide's"
               f" text. Open one ticket for each flaky check, to make it deterministic, with the Check: line the summary"
               f" gives for it. Drop duplicates. Change no code here. Then run: rail advance {f.id}"),
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
    ("SPLIT",              "agent", "agent_task",  lambda f: f.state == "implementing" and f.split and not f.dirty,
     _split),
    ("STEP_FAILED",        "agent", "agent_task",  lambda f: f.state == "implementing" and f.last_fail and not f.dirty,
     _step_failed),
    # A revert ticket: the engine put the reverse into the worktree at the claim, so the ship is all that is left;
    # where it couldn't, an agent undoes the change by hand.
    ("REVERT_SHIP",        "agent", "script",      lambda f: f.state == "implementing" and f.revert and f.revert["exact"],
     lambda f: f"rail advance {f.id}"),
    ("REVERT",             "agent", "agent_task",  lambda f: f.state == "implementing" and f.revert,
     _revert),
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
               f"Ticket {f.id} shipped; its branch isn't pushed to {_pr(f)} yet: run rail advance {f.id}. If that answer"
               " has a `push` step that failed, the remote refuses the push: do what the step says, and don't run"
               " rail advance again until the two branches agree."),
    ("MERGE_REQUESTED",    "none",  "rest",        lambda f: f.state == "merge-ready" and _merge_requested(f),
     lambda f: f"The merge of {_pr(f)} is requested; rail next sees it on the base branch once GitHub lands it."),
    ("MERGE",              "agent", "script",      lambda f: f.state == "merge-ready" and (f.auto or f.merge_approved)
                                                   and not (f.project.remote and not f.auto),
     lambda f: f"rail advance {f.id}"),  # it merges, and removes the worktree: run it from the project's root
    ("MERGE_BY_PERSON",    "person", "person_wait",  lambda f: f.state == "merge-ready",
     _merge_by_person),
]


# What a person's wait asks of them: an approval of something a revert doesn't undo (money included), a grant (the
# machine lacks something a person gives once: a tool, a key, a setting to repair), or a hold (the person's own brake).
WAIT_KINDS = {
    "APPROVE_CONTRACT": "approval", "APPROVE_AMEND": "approval", "MERGE_BY_PERSON": "approval", "RETRY_CAP": "approval",
    "FINDING_UPHELD": "approval", "AFTER_DROPPED": "approval", "BUDGET": "approval",
    "TOOL_MISSING": "grant", "TOOL_DOWN": "grant", "STUCK_REVIEW": "grant", "MERGE_FAILED": "grant",
    "HOLD": "hold", "STOPPED": "hold",
}


def first_match(f):
    """(code, owner, action) for the first row that matches."""
    for code, owner, kind, when, brief in ROWS:
        if when(f):
            action = {"kind": kind, "brief": brief(f)}
            if kind == "script":
                action["command"] = action["brief"]
            return code, owner, action
    raise AssertionError(f"no row matches ticket {f.id} in state {f.state}")
