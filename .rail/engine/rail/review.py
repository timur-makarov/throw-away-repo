"""The review: its runs, its findings and their answers.

The gate launches the reviewer: `advance` runs `review.command` in the ticket's worktree with the brief on stdin,
reads its structured output, binds the run to the patch, and resets the worktree. The engine assigns finding ids.
"""

import json
import os
import re

from . import areas, gitx
from .project import event, review_path, ticket_path
from .ticket import rank
from .util import now_iso, run_shell, tail

SECURITY = """Security. This list is a checklist, not a ceiling. Report only what someone could exploit in this application:
1. authorization: checked at object level and on every path;
2. authentication and sessions;
3. injection into SQL, shell, templates, paths or deserialisers;
4. outbound requests, webhooks and redirects;
5. secrets and personal data in code, logs or URLs;
6. business logic: invariants, replay, check-then-act;
7. fail-open defaults and error paths;
8. crypto misuse;
9. supply chain and CI;
10. model output reaching a sink, or untrusted text reaching a tool."""

DO_NOT_REPORT = """Do not report:
- Denial of service, resource exhaustion, or a race that stays inside one trust boundary.
- A missing hardening header or rate limit.
- A missing check in client-side code.
- Behaviour the ticket or the project's conventions describe as intended.
- What the ticket lists as out of scope.
- Anything a structure rule or the project's checks already report.
- Style, naming and formatting."""

REVIEW_LOOK_FOR = """- a Done Contract item the diff doesn't meet;
- a bug: a wrong result, a crash, data loss, a race;
- missing or weak checks for behaviour the diff adds;
- code in the wrong area, or a doc the change makes wrong;
- what generated code gets wrong: a check weakened, skipped or deleted so that it passes; a call to a function, flag or
  API that doesn't exist; state that is set but never cleared, or cleared on only one path; debug output or temporary
  code left in;"""

SECURITY_LOOK_FOR = ("Only security: trust boundaries, input handling, auth, secrets and data exposure, including unchanged "
                     "code the diff now reaches. Read THREAT_MODEL.md if it exists.")

SEVERITIES = ("blocking", "advisory", "parked")
EVIDENCE_LIMIT = 2000


def load_doc(text, nn):
    try:
        doc = json.loads(text) if text else None
    except ValueError:
        doc = None
    return doc if isinstance(doc, dict) and isinstance(doc.get("runs"), list) else {"schema": "review/v1", "ticket": nn, "runs": []}


# --- the findings ledger -------------------------------------------------------------


class Ledger:
    """Every finding of a ticket, from its `finding` events and the stored runs."""

    def __init__(self, events, doc):
        self.events, self.doc = events, doc
        self.findings = {}
        for run in doc["runs"]:
            for finding in run.get("findings", []):
                if finding.get("id") and finding["id"] not in self.findings:
                    self.findings[finding["id"]] = dict(finding, role=run.get("role"), history=[])
        for i, e in enumerate(events):
            if e.get("event") == "finding" and e.get("id") in self.findings:
                self.findings[e["id"]]["history"].append((i, e))

    def last(self, fid):
        history = self.findings[fid]["history"]
        return history[-1][1] if history else {"outcome": "open"}

    def outcome(self, fid):
        return self.last(fid).get("outcome")

    def unanswered(self):
        """Open findings the author must answer: fix and mark fixed, decline, or park."""
        waiting = set(self.disputed())
        return [fid for fid in self.findings if self.outcome(fid) == "open" and not self.last(fid).get("disputed")
                and fid not in waiting]

    def upheld_before(self, fid):
        return any(e.get("by") == "refuter" and e.get("outcome") == "open" for _, e in self.findings[fid]["history"])

    def refuted(self, fid):
        return any(e.get("by") == "refuter" for _, e in self.findings[fid]["history"])

    def disputed(self):
        """Blocking findings a fresh refuter decides: those the author disputes, and each new one from the HIGH
        security seat."""
        found = []
        for fid, f in self.findings.items():
            if self.outcome(fid) != "open":
                continue
            last = self.last(fid)
            if last.get("disputed") and not self.upheld_before(fid):
                found.append(fid)
            elif (f.get("role") == "security" and f.get("severity") == "blocking" and last.get("by") == "reviewer"
                  and not self.refuted(fid)):
                found.append(fid)
        return found

    def disputed_again(self):
        """Disputed after a refuter upheld them: the agent can't fix them, so a person decides."""
        return [fid for fid in self.findings if self.outcome(fid) == "open" and self.last(fid).get("disputed")
                and self.upheld_before(fid)]

    def next_id(self):
        numbers = [int(fid[1:]) for fid in self.findings if fid[1:].isdigit()]
        return f"F{max(numbers, default=0) + 1}"

    def runs(self, role, patch_id=None):
        return [r for r in self.doc["runs"] if r.get("role") == role and (patch_id is None or r.get("patch_id") == patch_id)]

    def run_after(self, role, index):
        return any(e.get("event") == "step" and e.get("step") == role and e.get("status") == "ran" and i > index
                   for i, e in enumerate(self.events))

    def needed_run(self, patch_id, tier):
        """The role whose run the patch still needs, or None."""
        roles = ["review"] + (["security"] if tier == "HIGH" else [])
        for role in roles:
            if not self.runs(role, patch_id):
                return role
            for fid, f in self.findings.items():
                if f.get("role") != role or f.get("severity") != "blocking" or self.outcome(fid) != "fixed":
                    continue
                fixed_at = self.findings[fid]["history"][-1][0]
                if not self.run_after(role, fixed_at):
                    return role
        return None

    def complete(self, patch_id, tier):
        return not self.unanswered() and not self.disputed() and not self.disputed_again() \
            and self.needed_run(patch_id, tier) is None

    def describe(self, fid, with_answer=True):
        f = self.findings[fid]
        where = f"{f.get('file')}:{f['line']}" if f.get("line") else f.get("file")
        text = f"{fid} ({f.get('severity')}, {f.get('role')}) {where}: {f.get('claim')}"
        if f.get("evidence"):
            text += f"\n    evidence: $ {f['evidence'].get('command')}\n    {tail(f['evidence'].get('output', ''), 8, 600)}"
        if with_answer and f["history"]:
            last = self.last(fid)
            text += f"\n    now {last.get('outcome')} (by {last.get('by')})" + (f": {last.get('reason')}" if last.get("reason") else "")
        return text


# --- the brief -----------------------------------------------------------------------------


def project_conventions(project, ref):
    """The project's own part of AGENTS.md: everything except the ## Rail section."""
    text = gitx.read_blobs([f"{ref}:AGENTS.md"], project.root).get(f"{ref}:AGENTS.md") or ""
    kept, skipping = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            skipping = line.strip() == "## Rail"
        if not skipping:
            kept.append(line)
    return "\n".join(kept).strip()


def brief(project, f, role, ledger, disputed=None):
    t, ref = f.t, f.t.ref
    ticket_text = gitx.read_blobs([f"{ref}:{ticket_path(t.id)}"], project.root)[f"{ref}:{ticket_path(t.id)}"] or ""
    diff = gitx.out(["diff", "--no-color", "--no-ext-diff", f"{project.base_ref}...{ref}", "--", ".",
                     ":(exclude).rail/tickets", ":(exclude).rail/journal"], project.root)
    found = areas.context(project, ref, f.ticket.scope)
    rows = "\n".join(f"| {a['area']} | {', '.join(a['paths'])} | {a['holds']} |" for a in found["areas"]) or "(none match)"
    if role == "review":
        look_for = REVIEW_LOOK_FOR + ("\n- " + SECURITY if f.tier == "MEDIUM" else
                                      "\n(Security is the security seat's job on this HIGH ticket.)")
        job = "Review this change."
    elif role == "security":
        look_for = SECURITY_LOOK_FOR + "\n" + SECURITY
        job = "Review this change for security only. You are the security seat."
    else:
        look_for = (f"Only whether this one finding holds. If it does, return it with `repeats` set to {disputed} and its "
                    "severity. If it doesn't, return an empty list. `summary` says why. When it has evidence, run the "
                    "command again.")
        job = f"Decide whether finding {disputed} holds. You are the refuter."
    parts = [
        f"# Review brief: ticket {t.id}, {f.tier}", "", f"This run's job: {job}", "",
        "## The ticket", ticket_text.strip(), "",
        f"Risk: tier {f.tier}. scope_paths: {', '.join(f.ticket.scope)}.", "",
        "## The diff", "```diff", diff, "```", "",
        "## Areas this change touches", "| Area | Paths | Holds |", "|---|---|---|", rows, "",
        "Directories:", found["digest"], "",
        "## The project's conventions (from AGENTS.md)", project_conventions(project, ref) or "(none written)", "",
        "## What to look for", look_for, "", DO_NOT_REPORT,
    ]
    if role == "refuter":
        parts += ["", "## The finding", ledger.describe(disputed, with_answer=False)]
    elif ledger.findings:
        own = [fid for fid, x in ledger.findings.items() if x.get("role") == role]
        if own:
            parts += ["", "## Earlier findings and the author's answers",
                      "Review the whole change again. When an earlier finding still stands, report it with its id in "
                      "`repeats` and keep its severity.", *[ledger.describe(fid) for fid in own]]
    return "\n".join(parts) + "\n"


# --- running and reading a review -------------------------------------------------------------


def _structured(stdout):
    """The review/v1 object from the CLI's JSON (`structured_output`), plus the model and cost when given."""
    data = json.loads(stdout)
    meta = {}
    if isinstance(data, dict) and "structured_output" in data:
        usage = data.get("modelUsage") or {}
        # The model that did the work: a run can also bill a small helper model, so take the costliest.
        main = max(usage, key=lambda m: (usage[m] or {}).get("costUSD", 0), default=None) if isinstance(usage, dict) else None
        meta = {"model": main or data.get("model"), "cost_usd": data.get("total_cost_usd")}
        data = data["structured_output"]
    elif isinstance(data, dict) and isinstance(data.get("result"), str) and "findings" not in data:
        m = re.search(r"\{.*\}", data["result"], re.S)
        data = json.loads(m.group(0)) if m else None
    return data, meta


def validate(project, head, nn, data, ledger, role, disputed):
    """The schema's shape, and what only the engine can check: each finding names a tracked file and a line
    inside it, and `repeats` names an earlier finding of this ticket. Returns a list of errors."""
    if not isinstance(data, dict) or not isinstance(data.get("summary"), str) or not isinstance(data.get("findings"), list):
        return ["the output is not a review/v1 object with summary and findings"]
    errors = []
    allowed = {"severity", "file", "line", "claim", "check", "evidence", "repeats"}
    for n, f in enumerate(data["findings"]):
        where = f"finding {n + 1}"
        if not isinstance(f, dict) or set(f) - allowed or not {"severity", "file", "claim"} <= set(f):
            errors.append(f"{where} doesn't match the schema")
            continue
        if f["severity"] not in SEVERITIES:
            errors.append(f"{where}: severity '{f['severity']}'")
        text = gitx.read_blobs([f"{head}:{f['file']}"], project.root).get(f"{head}:{f['file']}")
        if text is None:
            errors.append(f"{where}: {f['file']} isn't a tracked file at {head[:12]}")
        elif "line" in f and (not isinstance(f["line"], int) or not 1 <= f["line"] <= max(1, len(text.splitlines()) + 2)):
            errors.append(f"{where}: line {f.get('line')} isn't inside {f['file']}")
        if "repeats" in f and f["repeats"] not in ledger.findings:
            errors.append(f"{where}: repeats {f['repeats']}, which isn't an earlier finding of ticket {nn}")
        ev = f.get("evidence")
        if ev is not None and (not isinstance(ev, dict) or set(ev) != {"command", "output"}):
            errors.append(f"{where}: evidence needs command and output")
    if role == "refuter" and (len(data["findings"]) > 1 or
                              any(f.get("repeats") != disputed for f in data["findings"] if isinstance(f, dict))):
        errors.append(f"a refuter returns at most one finding, and it repeats {disputed}")
    return errors


def run(project, f, role, receipt, disputed=None, prompt=None):
    """One run of review.command. Adds its step and finding events to `receipt`, and returns the stored run entry.
    A sweep run brings its own brief, writes no finding events, and never fails."""
    from .steps import keep_alive

    t, wt = f.t, f.t.worktree
    keep_alive(project, t)  # it may commit and push an event: before the head the worktree is reset to is read
    head = gitx.rev(t.ref, project.root)
    text = gitx.read_blobs([f"{t.ref}:{review_path(t.id)}"], project.root)[f"{t.ref}:{review_path(t.id)}"]
    doc = load_doc(text, t.id)
    ledger = Ledger(t.events, doc)
    prompt = prompt or brief(project, f, role, ledger, disputed)
    timeout = project.config["commands"]["timeout_secs"]
    code, output, ms = run_shell(project.config["review"]["command"], wt,
                                 {"RAIL_TICKET": t.id, **model_env(project.config["review"]["model"])}, timeout, stdin=prompt)
    gitx.git(["reset", "--quiet", "--hard", head], wt)
    gitx.git(["clean", "-fdq"], wt)
    step = role
    if code is None:
        receipt.record(step, False, f.patch_id, "timeout", ms, counted=False,
                       output=f"The {role} run passed timeout_secs ({timeout}s).")
        return None
    try:
        data, meta = _structured(output)
        errors = validate(project, head, t.id, data, ledger, role, disputed) if code == 0 else [f"exit {code}"]
    except ValueError:
        data, meta, errors = None, {}, ["the output is not JSON"]
    if errors:
        receipt.record(step, False, f.patch_id, f"invalid output: {errors[0]}", ms,
                       output=f"The {role} run's output was invalid:\n- " + "\n- ".join(errors) + f"\n\n{tail(output, 30)}")
        return None

    entry = {"run": len(doc["runs"]) + 1, "role": role, "patch_id": f.patch_id, "head": head[:12], "tier": f.tier,
             "at": now_iso(), **{k: v for k, v in meta.items() if v is not None},
             "summary": data["summary"], "findings": []}
    if role == "refuter":
        entry["disputes"] = disputed
    events, next_number = [], int(ledger.next_id()[1:])
    for finding in data["findings"]:
        finding = dict(finding)
        if finding.get("evidence"):
            finding["evidence"] = {"command": finding["evidence"]["command"],
                                   "output": finding["evidence"]["output"][:EVIDENCE_LIMIT]}
        if finding.get("repeats"):
            fid = finding["repeats"]
            severity = ledger.findings[fid].get("severity")
            outcome = "parked" if severity == "parked" else "open"
            events.append(event(t.id, "finding", id=fid, outcome=outcome, by="refuter" if role == "refuter" else "reviewer"))
        else:
            fid = f"F{next_number}"
            next_number += 1
            severity = finding["severity"]
            first = {"severity": severity, "claim": finding["claim"]}
            if finding.get("check"):
                first["check"] = finding["check"]
            events.append(event(t.id, "finding", id=fid, outcome="parked" if severity == "parked" else "open",
                                by="reviewer", **first))
        finding["id"] = fid
        entry["findings"].append(finding)
    if role == "sweep":
        events = []  # the sweep's findings become tickets, not ledger entries
    if role == "refuter" and not data["findings"]:
        events.append(event(t.id, "finding", id=disputed, outcome="declined", by="refuter", reason=data["summary"]))
    blocking = [x for x in entry["findings"] if (ledger.findings.get(x.get("repeats"), x).get("severity") == "blocking")]
    if role == "security":
        # The seat's new blocking findings each go to a refuter at once; the refuter's
        # verdict is what fails. A repeat of one the refuter already upheld stays open.
        blocking = [x for x in blocking if x.get("repeats")]
    if role == "sweep":
        blocking = []  # a sweep never blocks a merge
    passed = not blocking
    detail = (f"run {entry['run']}: dismissed {disputed}" if role == "refuter" and passed else
              f"run {entry['run']}: upheld {disputed}" if role == "refuter" else
              f"run {entry['run']}: {len(blocking)} blocking, {len(entry['findings'])} findings")
    receipt.record(step, passed, f.patch_id, detail, ms, cost_usd=meta.get("cost_usd"),
                   output=f"{role}: {data['summary']}\n" + "\n".join(
                       f"- {x['id']} ({ledger.findings.get(x.get('repeats'), x).get('severity')}) {x['file']}"
                       f"{':' + str(x['line']) if x.get('line') else ''}: {x['claim']}" for x in entry["findings"]))
    receipt.events += events
    doc["runs"].append(entry)
    receipt.files[review_path(t.id)] = json.dumps(doc, indent=2) + "\n"
    return entry


def model_env(model):
    """[review] model and [consult] model name the model a command runs on. The claude CLI reads ANTHROPIC_MODEL;
    another vendor's command can read RAIL_MODEL. Empty leaves the command's own default."""
    return {"ANTHROPIC_MODEL": model, "RAIL_MODEL": model} if model else {}


def needs_review(tier):
    return rank(tier) >= rank("MEDIUM")
