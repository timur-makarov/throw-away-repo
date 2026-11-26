"""The review: its runs, its findings and their answers.

The gate launches the reviewer: `advance` runs `review.command` in the ticket's worktree with the brief on stdin,
reads its structured output, binds the run to the patch, and resets the worktree. The engine assigns finding ids.
"""

import json
import os
import re
import shlex
import tempfile

from . import areas, flakes, gitx
from .project import event, review_path, ticket_path
from .ticket import KINDS, Ticket
from .util import could_not_run, match_any, now_iso, run_shell, tail

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
SCRIPTS, SCRIPT_LIMIT = 3, 8000  # untracked files an evidence command names, kept in the journal: how many, how long
GUIDANCE_LIMIT = 8000  # characters of REVIEW.md in a brief, all files together

BASE_GREEN = ("Every check in the Done Contract already passed on the base branch before this work began, so the checks"
              " alone do not show the work was done. Look at whether the change is tested.")


def kind_line(k):
    where = f"{k.get('file')}:{k['line']}" if k.get("line") else k.get("file")
    return f"{k.get('kind')}: {where}: {k.get('why')}"


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
        """Open blocking findings the author must answer: fix and mark fixed, decline, or park. An advisory finding
        holds nothing: it stays open until answered, and the sweep gathers it once the ticket merged."""
        waiting = set(self.disputed())
        return [fid for fid in self.findings if self.outcome(fid) == "open" and not self.last(fid).get("disputed")
                and fid not in waiting and self.findings[fid].get("severity") == "blocking"]

    def open_advisory(self):
        return [fid for fid, f in self.findings.items() if self.outcome(fid) == "open" and f.get("severity") == "advisory"]

    def upheld_before(self, fid):
        return any(e.get("by") == "refuter" and e.get("outcome") == "open" for _, e in self.findings[fid]["history"])

    def refuted(self, fid):
        return any(e.get("by") == "refuter" for _, e in self.findings[fid]["history"])

    def disputed(self):
        """Blocking findings a fresh refuter decides: those the author disputes, and each new one from the PERSON
        tier's security seat."""
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
        """A run of `role` with a verdict after `index`: a timeout or invalid output (counted: false) is none."""
        return any(e.get("event") == "step" and e.get("step") == role and e.get("status") == "ran" and i > index
                   and e.get("counted", True) for i, e in enumerate(self.events))

    def needed_run(self, patch_id, tier):
        """The role whose run the patch still needs, or None."""
        roles = ["review"] + (["security"] if tier == "PERSON" else [])
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

    def asked_for_person(self):
        """What review and security runs found that a revert doesn't undo, each item once, as "kind: file:line: why".
        A run stored by an older engine may hold a `needs_person` sentence instead."""
        found = []
        for r in self.doc["runs"]:
            found += [kind_line(k) for k in r.get("kinds") or [] if isinstance(k, dict)]
            if r.get("needs_person"):
                found.append(r["needs_person"])
        return list(dict.fromkeys(found))

    def describe(self, fid, with_answer=True, scripts=False):
        f = self.findings[fid]
        where = f"{f.get('file')}:{f['line']}" if f.get("line") else f.get("file")
        text = f"{fid} ({f.get('severity')}, {f.get('role')}) {where}: {f.get('claim')}"
        if f.get("evidence"):
            text += f"\n    evidence: $ {f['evidence'].get('command')}\n    {tail(f['evidence'].get('output', ''), 8, 600)}"
            for path, script in (f["evidence"].get("scripts") or {}).items() if scripts else ():
                text += f"\n    {path}, the reviewer's scratch file (gone from the worktree):\n" + \
                        "\n".join("      " + line for line in script.splitlines())
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


def review_guidance(project, ref):
    """The project's REVIEW.md files: the root one, then one in each directory above a file the ticket changed,
    shallowest first. They are read from the base branch, not from the ticket's: the change under review doesn't
    write what its own review is told, and a REVIEW.md it adds or edits counts from the next ticket on. Empty when
    there is none. Cut at GUIDANCE_LIMIT characters, saying which files were."""
    dirs = {""}
    for path in project.changed_files(ref):
        parts = path.split("/")[:-1]
        dirs.update("/".join(parts[:n]) for n in range(1, len(parts) + 1))
    paths = [f"{d}/REVIEW.md" if d else "REVIEW.md" for d in sorted(dirs, key=lambda d: (d.count("/") + bool(d), d))]
    base = project.base_ref
    blobs = gitx.read_blobs([f"{base}:{p}" for p in paths], project.root)
    parts, cut, room = [], [], GUIDANCE_LIMIT
    for path in paths:
        text = (blobs.get(f"{base}:{path}") or "").strip()
        if not text:
            continue
        if len(text) > room:
            cut.append(path)
            text = text[:room]
        room -= len(text)
        where = os.path.dirname(path)
        parts += [f"For {where + '/' if where else 'the whole repository'} ({path}):", text, ""] if text else []
    if cut:
        parts.append(f"(Cut at {GUIDANCE_LIMIT} characters: {', '.join(cut)}.)")
    return "\n".join(parts).strip()


def checks_green_on_base(t):
    """Whether the ticket's base_checks event shows every check already passing before the work began."""
    found = t.last("base_checks")
    checks = (found or {}).get("checks") or []
    return bool(checks) and all(c.get("result") == "green" for c in checks)


def first_contract(project, t):
    """The Done Contract and scope as first accepted, when an amend that nobody approved has changed either since.
    None when there was no such amend."""
    events = t.events
    first = next((i for i, e in enumerate(events) if e.get("event") == "accepted"), None)
    if first is None or not any(e.get("event") == "amended" and not e.get("needs_approval")
                                and {"done_contract", "scope"} & set(e.get("changed") or []) for e in events[first:]):
        return None
    accepted, path, done = events[first], ticket_path(t.id), None
    for sha in gitx.out(["log", "--format=%H", t.ref, "--", path], project.root).split():
        old = Ticket(gitx.read_blobs([f"{sha}:{path}"], project.root).get(f"{sha}:{path}") or "")
        if old.done_hash() == accepted.get("done"):
            done = old.sections.get("Done Contract", "")
            break
    return ["## The contract as first accepted",
            "An amend nobody approved changed this ticket's contract after it was first accepted. As first accepted:",
            done or "(the Done Contract as first accepted is not in the branch's history)",
            f"scope_paths: {', '.join(accepted.get('scope_paths') or [])}.", ""]


def brief(project, f, role, ledger, disputed=None):
    t, ref = f.t, f.t.ref
    ticket_text = gitx.read_blobs([f"{ref}:{ticket_path(t.id)}"], project.root)[f"{ref}:{ticket_path(t.id)}"] or ""
    diff = gitx.out(["diff", "--no-color", "--no-ext-diff", f"{project.base_ref}...{ref}", "--", ".",
                     ":(exclude).rail/tickets", ":(exclude).rail/journal"], project.root)
    found = areas.context(project, ref, f.ticket.scope)
    rows = "\n".join(f"| {a['area']} | {', '.join(a['paths'])} | {a['holds']} |" for a in found["areas"]) or "(none match)"
    if role == "review":
        look_for = REVIEW_LOOK_FOR + ("\n- " + SECURITY if f.tier == "AUTO" else
                                      "\n(Security is the security seat's job on this PERSON ticket.)")
        job = "Review this change."
    elif role == "security":
        look_for = SECURITY_LOOK_FOR + "\n" + SECURITY
        job = "Review this change for security only. You are the security seat."
    else:
        look_for = (f"Only whether this one finding holds. If it does, return it with `repeats` set to {disputed} and its "
                    "severity; when the problem is real but this change didn't cause it, the severity is parked. If it "
                    "doesn't hold, return an empty list. `summary` says why. When it has evidence, run the command again.")
        job = f"Decide whether finding {disputed} holds. You are the refuter."
    guidance = review_guidance(project, ref)
    patch = project.patch_id(ref)
    flaky = list(dict.fromkeys(flakes.name(x) for x in flakes.of(t.events) if x["patch_id"] == patch))
    from . import sensors
    marked = sensors.markers(project, ref)
    from . import tools
    reviewer_tools = tools.lines(project, review=True)
    parts = [
        f"# Review brief: ticket {t.id}, {f.tier}", "", f"This run's job: {job}", "",
        "## The ticket", ticket_text.strip(), "",
        f"Risk: tier {f.tier}. scope_paths: {', '.join(f.ticket.scope)}.", "",
        *((first_contract(project, t) or []) if role == "review" else []),
        *([BASE_GREEN, ""] if role == "review" and checks_green_on_base(t) else []),
        *(["## Flaky checks on this change",
           "Each of these both failed and passed on this same code. It may be an old flake, or a race this change"
           " brought in:", *[f"- `{name}`" for name in flaky], ""] if flaky and role != "refuter" else []),
        *(["## Sensor markers this change adds",
           "Each line below tells a sensor that its violation there is wrong or accepted. Judge the reason: a marker"
           " with no reason that holds is a finding.", *[f"- {line}" for line in marked], ""]
          if marked and role in ("review", "security") else []),
        *(["## Tools", *reviewer_tools, ""] if reviewer_tools else []),
        "## The diff", "```diff", diff, "```", "",
        "## Areas this change touches", "| Area | Paths | Holds |", "|---|---|---|", rows, "",
        "Directories:", found["digest"], "",
        "## The project's conventions (from AGENTS.md)", project_conventions(project, ref) or "(none written)", "",
        *(["## The project's review guidance (from REVIEW.md)", guidance, ""] if guidance else []),
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

REVIEWER_FILES = {"RAIL_REVIEW_PROMPT": "reviewer.md", "RAIL_REVIEW_SCHEMA": "review-v1.json"}


def reviewer_files(project, folder):
    """{RAIL_REVIEW_PROMPT, RAIL_REVIEW_SCHEMA}: paths of the reviewer's system prompt and of the schema its answer
    must match, as the base branch has them, written into `folder` for one run. The review command runs in the
    ticket's worktree, where both files are the ticket's own copies: read from there, a change could rewrite the
    prompt of its own review. A base branch without them (a project that keeps no engine there) gets the running
    engine's."""
    held = gitx.read_blobs([f"{project.base_ref}:.rail/engine/{name}" for name in REVIEWER_FILES.values()], project.root)
    env = {}
    for var, name in REVIEWER_FILES.items():
        text = held.get(f"{project.base_ref}:.rail/engine/{name}")
        if text is None:
            with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), name)) as f:
                text = f.read()
        env[var] = os.path.join(folder, name)
        with open(env[var], "w") as f:
            f.write(text)
    return env



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
    kinds = data.get("kinds", [])
    if not isinstance(kinds, list):
        errors.append("kinds is not a list")
        kinds = []
    for n, k in enumerate(kinds):
        where = f"kinds[{n}]"
        if not isinstance(k, dict) or set(k) - {"kind", "file", "line", "why"} or not {"kind", "file", "why"} <= set(k):
            errors.append(f"{where} doesn't match the schema")
        elif k["kind"] not in KINDS:
            errors.append(f"{where}: '{k['kind']}' is not a kind's id ({', '.join(KINDS)})")
        elif "line" in k and not isinstance(k["line"], int):
            errors.append(f"{where}: line is not a number")
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
    with tempfile.TemporaryDirectory(prefix="rail-review-") as held:
        code, output, ms = run_shell(project.config["review"]["command"], wt,
                                     {"RAIL_TICKET": t.id, **model_env(project.config["review"]["model"]),
                                      **reviewer_files(project, held)}, timeout, stdin=prompt)
    # Tracked files back as they were; the reviewer's untracked scratch files stay for the evidence re-runs.
    gitx.git(["reset", "--quiet", "--hard", head], wt)
    try:
        return _read(project, f, role, receipt, disputed, head, doc, ledger, code, output, ms, timeout)
    finally:
        gitx.git(["reset", "--quiet", "--hard", head], wt)  # a re-run may have changed a tracked file too
        gitx.git(["clean", "-fdq"], wt)


def rerun(wt, evidence, timeout):
    """A finding's evidence with the engine's own run of its command: `rerun` (its exit, null past timeout_secs,
    and its output's tail), `reproduced` (every non-empty line the reviewer quoted, normalised as failure signatures
    are, is in the re-run's output), and `scripts`: the text of each untracked file the command names, which the
    clean-up removes. `reproduced` is a record only: nothing is decided from it."""
    from .steps import normalise

    scripts = scratch_files(wt, evidence["command"])  # before the command, which may change them
    code, output, _ = run_shell(evidence["command"], wt, timeout=timeout)
    quoted = [normalise(line) for line in evidence["output"].splitlines() if line.strip()]
    seen = normalise(output)
    result = dict(evidence, rerun={"exit": code, "output_tail": tail(output, 60, EVIDENCE_LIMIT)},
                  reproduced=code is not None and bool(quoted) and all(line in seen for line in quoted))
    if scripts:
        result["scripts"] = scripts
    return result


def scratch_files(wt, command):
    """{path: text} of the untracked files inside the worktree that `command` names, at most SCRIPTS of them, each cut
    at SCRIPT_LIMIT characters."""
    try:
        words = shlex.split(command)
    except ValueError:
        words = command.split()
    found = {}
    for word in words:
        path = os.path.normpath(os.path.join(wt, word.split("::")[0].split("=")[-1]))
        if len(found) >= SCRIPTS or not path.startswith(os.path.join(wt, "")) or not os.path.isfile(path):
            continue
        rel = os.path.relpath(path, wt)
        if rel in found or gitx.out(["ls-files", "--", rel], wt):
            continue  # a tracked file is in the commit already
        with open(path, errors="replace") as fh:
            text = fh.read(SCRIPT_LIMIT + 1)
        found[rel] = text if len(text) <= SCRIPT_LIMIT else text[:SCRIPT_LIMIT] + f"\n(cut at {SCRIPT_LIMIT} characters)"
    return found


def _read(project, f, role, receipt, disputed, head, doc, ledger, code, output, ms, timeout):
    """The run's output: checked, its evidence run again, and recorded. The worktree still holds the scratch files."""
    t, wt = f.t, f.t.worktree
    step = role
    if code is None:
        receipt.record(step, False, f.patch_id, "timeout", ms, counted=False,
                       output=f"The {role} run passed timeout_secs ({timeout}s).")
        return None
    if could_not_run(code):
        receipt.record(step, False, f.patch_id, could_not_run(code), ms, status="could_not_run",
                       output=f"The {role} command could not start, so nothing was reviewed. [review] command:\n"
                              f"$ {project.config['review']['command']}\n{tail(output, 30)}")
        return None
    try:
        data, meta = _structured(output)
        errors = validate(project, head, t.id, data, ledger, role, disputed) if code == 0 else [f"exit {code}"]
    except ValueError:
        data, meta, errors = None, {}, ["the output is not JSON"]
    if errors:
        # The reviewer's fault, not the author's: not counted, like a timeout.
        receipt.record(step, False, f.patch_id, f"invalid output: {errors[0]}", ms, counted=False,
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
            finding["evidence"] = rerun(wt, {"command": finding["evidence"]["command"],
                                             "output": finding["evidence"]["output"][:EVIDENCE_LIMIT]}, timeout)
        if finding.get("repeats"):
            fid = finding["repeats"]
            severity = ledger.findings[fid].get("severity")
            if role == "refuter" and finding.get("severity") == "parked":
                severity = "parked"  # real, but not this change's doing: the refuter parks it
            outcome = "parked" if severity == "parked" else "open"
            events.append(event(t.id, "finding", id=fid, outcome=outcome, by="refuter" if role == "refuter" else "reviewer",
                                **({"reason": data["summary"]} if role == "refuter" and outcome == "parked" else {})))
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
    found = (data.get("kinds") or []) if role in ("review", "security") else []
    if found:
        # Something a revert doesn't undo: recorded on every ticket, and an AUTO ticket becomes PERSON, never back.
        entry["kinds"] = found
        if f.tier == "AUTO":
            events.append(event(t.id, "tier_raised", **{"from": "AUTO", "to": "PERSON", "reason": "reviewer",
                                                         "kind": found[0]["kind"],
                                                         "kinds": list(dict.fromkeys(k["kind"] for k in found)),
                                                         "detail": kind_line(found[0])}))
    if role == "refuter" and not data["findings"]:
        events.append(event(t.id, "finding", id=disputed, outcome="declined", by="refuter", reason=data["summary"]))
    parked_by_refuter = [x["repeats"] for x in entry["findings"]
                         if role == "refuter" and x.get("repeats") and x.get("severity") == "parked"]
    blocking = [x for x in entry["findings"] if (ledger.findings.get(x.get("repeats"), x).get("severity") == "blocking")
                and x.get("repeats") not in parked_by_refuter]
    to_refuter = 0
    if role == "security":
        # The seat's new blocking findings each go to a refuter at once; the refuter's
        # verdict is what fails. A repeat of one the refuter already upheld stays open.
        to_refuter = len([x for x in blocking if not x.get("repeats")])
        blocking = [x for x in blocking if x.get("repeats")]
    if role == "sweep":
        blocking = []  # a sweep never blocks a merge
    passed = not blocking
    detail = (f"run {entry['run']}: parked {disputed}" if role == "refuter" and parked_by_refuter else
              f"run {entry['run']}: dismissed {disputed}" if role == "refuter" and passed else
              f"run {entry['run']}: upheld {disputed}" if role == "refuter" else
              f"run {entry['run']}: {len(blocking)} blocking, {to_refuter} more blocking to the refuter,"
              f" {len(entry['findings'])} findings"
              if role == "security" and to_refuter else
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


def needs_review(project, tier, changed):
    """Whether a change gets the reviewer before it merges: a PERSON ticket always, and an AUTO ticket unless every
    file it changes is in [review] skip_paths. The paths decide, not the author. A change to no product file has
    nothing to review. The sweep reviews afterwards what merged without one."""
    return tier == "PERSON" or not all(match_any(project.config["review"]["skip_paths"], path) for path in changed)
