"""The engine's side of the consult pack (plan, sections 7 and 18): it asks the pack and records the answer.

The pack only advises. The engine writes the `consulted` event and NN-advice.md, because only the engine writes the
journal, and it keeps the limit of three per ticket.
"""

import json
import os

from . import gitx
from .project import advice_path, event, ticket_path
from .util import now_iso, run_shell, tail

LIMIT = 3


def pack(project):
    return os.path.join(project.root, ".rail", "packs", "consult", "bin", "consult")


def ask(project, f, trigger, step, question, output, receipt):
    """Run the consult pack. Adds its event and advice to `receipt`; returns the advice, or None."""
    t = f.t
    if not os.path.exists(pack(project)) or f.consults >= LIMIT:
        return None
    blobs = gitx.read_blobs([f"{t.ref}:{ticket_path(t.id)}", f"{t.ref}:{advice_path(t.id)}"], project.root)
    diff = gitx.out(["diff", "--no-color", f"{project.base_ref}...{t.ref}", "--", ".", ":(exclude).rail/tickets",
                     ":(exclude).rail/journal"], project.root)
    request = {"ticket": t.id, "trigger": trigger, "step": step, "question": question,
               "ticket_text": blobs[f"{t.ref}:{ticket_path(t.id)}"] or "", "diff": diff, "output": tail(output, 120, 12000)}
    code, out, _ = run_shell(f'"{pack(project)}"', t.worktree or project.root,
                             {"RAIL_TICKET": t.id, "RAIL_ROOT": project.root},
                             project.config["commands"]["timeout_secs"] + 60, stdin=json.dumps(request))
    try:
        answer = json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        # A broken pack mustn't hold the ticket in a loop: its silence counts as "stop", and a person looks.
        answer = {"verdict": "stop", "advice": f"The consult pack failed: {tail(out, 5, 500)}", "same_model": False}
    verdict = answer.get("verdict") if answer.get("verdict") in ("proceed", "change", "stop") else "change"
    same_model = bool(answer.get("same_model"))
    receipt.events.append(event(t.id, "consulted", trigger=trigger, step=step, verdict=verdict, same_model=same_model))
    label = " (same-model)" if same_model else ""
    section = (f"## {now_iso()}: {trigger} at '{step}', {verdict}{label}\n\nQuestion: {question}\n\n"
               f"{answer.get('advice', '').strip()}\n\n")
    receipt.files[advice_path(t.id)] = (blobs[f"{t.ref}:{advice_path(t.id)}"] or "") + section
    receipt.steps.append({"step": "consult", "status": "ran", "result": "pass", "detail": verdict + label})
    f.consults += 1
    return f"consult says {verdict}{label}: {answer.get('advice', '').strip()}"
