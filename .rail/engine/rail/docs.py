"""`rail docs [topic]`: the framework's docs, shipped inside the engine.

Pages are markdown files in engine/docs. The config and CLI reference pages are generated from the engine itself,
so they can't drift from what the engine reads.
"""

import os
import re
import tomllib

from . import config as configmod
from .ticket import KINDS

DOCS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")

# Every config field names its reader. A test checks this covers config.DEFAULTS.
READERS = {
    "base_branch": "claim, ship, CI and the merge: the branch tickets start from and merge into",
    "person_paths": "add and amend (matched against scope_paths) and ship (changed files): the kind `controls`, so a"
                    " ticket that touches one is PERSON: a person approves its contract and merges it",
    "migration_paths": "add, amend and ship: the kind `data-loss`, PERSON as well; tickets touching them need"
                       " reversibility and rollback",
    **{f"kinds.{kind}": f"add, amend and ship: paths that hold the kind `{kind}` (rail docs kinds); a ticket whose"
                        f" scope or changed files match one is PERSON" for kind in KINDS},
    "commands.setup": "the claim: runs in each new ticket worktree, with RAIL_TICKET set; rail adopt: runs in the"
                      " throwaway worktrees on the base and the branch before its checks",
    "commands.verify": "ship and CI: the whole project's checks, scanners included",
    "commands.provision": "rail provision, next in a cloud session, and CI: installs what the machine lacks, once"
                          " per machine, as root. Never run on a person's own machine",
    "commands.timeout_secs": "every command: setup, verify, provision, each check, each review run, each source's"
                             " fetch; setup and verify take their own limit instead when it is set",
    "commands.setup_timeout_secs": "the claim, rail adopt and CI: the seconds setup may run, for a setup that needs"
                                   " longer than the other commands, such as a cold build in a new worktree. 0 takes"
                                   " timeout_secs",
    "commands.verify_timeout_secs": "ship and CI: the seconds verify may run, on the ticket and on the base. 0 takes"
                                    " timeout_secs. Each check and each review run still stops at timeout_secs",
    "commands.base_checks": "next, at a ticket's first claim: runs each Check: line once on the untouched base and"
                            " records red or green in a base_checks event. Never a gate: it fails nothing. When every"
                            " check was green, the IMPLEMENT brief asks for a check that fails now (rail amend)",
    "size.cap": "ship: an AUTO change with more changed lines than this is offered a split at its first ship (no"
                " attempt spent); the next ship goes on to review as AUTO. Size raises no tier",
    "size.exclude": "ship and CI: globs left out of the size count, besides generated files and lockfiles",
    "review.command": "advance: the reviewer, run in the ticket's worktree with the brief on stdin",
    "review.model": "advance and sweep: the model the reviewer runs on (ANTHROPIC_MODEL and RAIL_MODEL for the"
                    " command); empty leaves the command's default",
    "review.skip_paths": "advance and CI: an AUTO change gets no reviewer when every file it changes matches one of"
                         " these globs. The sweep reviews such changes afterwards",
    "retry.budget": "next and advance: failures in a row at one step with the same signature before consult advises"
                    " once; the attempt after that failing too is stuck: an AUTO ticket is dropped with a record, a"
                    " PERSON ticket waits for a person",
    "retry.cap": "next and advance: failed attempts at one step, whatever their signatures, after which the ticket"
                 " is stuck: an AUTO ticket is dropped with a record (STUCK), a PERSON ticket waits for a person",
    "consult.command": "the consult pack: a read-only model, with the brief on stdin",
    "consult.model": "the consult pack: the model consult runs on, set the same way as review.model",
    "claim.stale_minutes": "next: minutes without a journal event after which another session's work in flight is"
                           " taken to be abandoned and resumed. No event is written while a command runs, so keep it"
                           " above the longest command's limit (timeout_secs, or setup's or verify's own) plus"
                           " claim.save_minutes; a worker run (rail work) saves as it goes, so it doesn't count",
    "claim.save_minutes": "advance, rail save and rail work: a ticket with nothing to save and no pushed event for"
                          " this long gets a saved event, the sign that a session is at work on it. rail work saves"
                          " this often while its worker runs. How often the save hook runs is the -mmin number in the"
                          " hook's own command in .claude/settings.json (10)",
    "worker.ladder": "next, advance and work: the model and effort an agent_task names for an AUTO ticket's work, as"
                     " model:effort, one rung per failed attempt at the step the ticket is failing. Empty names none",
    "worker.person_ladder": "next, advance and work: the same ladder for a PERSON ticket, which starts higher",
    "worker.contract": "next and work: the model:effort the task that writes a ticket's contract (TICKET_LINT), the"
                       " task that files a sweep's tickets (SWEEP_TICKETS) and the task that decides on a dropped"
                       " `after` (AFTER_DROPPED) name. An AUTO contract is accepted with nobody looking, so it gets a"
                       " stronger model. Empty: the ladder's",
    "worker.command": "work: the worker, run in the answer's cwd with the brief on stdin and RAIL_TICKET, RAIL_MODEL,"
                      " RAIL_EFFORT, RAIL_SESSION (a session to resume, or empty), ANTHROPIC_MODEL and RAIL_WORKER=1"
                      " set. The engine reads total_cost_usd, session_id, num_turns and subtype from its last JSON"
                      " result line, when there is one. Not every CLI version honours --max-turns: worker.timeout_minutes is"
                      " the bound every run has. Empty: rail work runs nothing (rail docs loop)",
    "worker.timeout_minutes": "work: one worker run's wall clock, after which the engine ends it and records"
                              " timeout. Keep it under the Bash tool's BASH_MAX_TIMEOUT_MS; rail doctor says when it"
                              " isn't",
    "worker.ticket_usd": "next and every command that answers for a ticket: when the cost its worker and review runs"
                         " reported since a person last acted passes this many dollars, the ticket waits for a person"
                         " (BUDGET). 0 switches it off (rail docs retries)",
    "worker.daily_usd": "next and work: while the cost every ticket's runs reported in the last 24 hours passes this"
                        " many dollars, next rests and work starts no worker (BUDGET_DAY). 0 switches it off",
    "sweep.after": "next: changes merged with no review (tickets inside review.skip_paths, and commits with no"
                   " ticket) since the last sweep before one is offered",
    "sweep.every": "next: tickets merged since the last sweep, reviewed or not, before one is offered; it then"
                   " gathers the findings reviewers parked and the checks they proposed. 0 switches this off",
    "stats.held_days": "stats: the days a merged ticket must have been on the base branch before it can count as"
                       " held (not reverted, and named in no later ticket's caused_by)",
    "map.depth": "doc-lint: the directory depth ## Areas must cover",
    "map.ignore": "doc-lint: directories that need no ## Areas row",
    "tests.paths": "nothing yet: globs of the files that hold tests and their runner's settings, which rail init"
                   " writes from the language profiles it finds (rail docs languages)",
    "rules": "ship and CI: structure rules on added lines and files (rail docs rules)",
    "sensors": "ship and CI, last: each entry runs a tool when the change touches its paths, and a line of its output"
               " on a line the change adds fails the step (rail docs sensors)",
    "init.skill_dirs": "init: the folders, from the repository root, that rail init writes the skills to. An agent"
                       " other than Claude Code reads SKILL.md files from a folder of its own: add it, and run rail"
                       " init again. The [guides] pages that are skills name the first",
    "init.other_manifests": "init, doctor and the sweep: globs of tracked manifests that mark no code of the project's"
                            " own, such as a package.json kept for a formatter. Any other manifest of Python,"
                            " TypeScript, Rust or Go needs a [[profiles]] entry that covers it (rail docs languages)",
    "tools": "next, advance, review and doctor: a [tools.NAME] table for each thing the work reaches outside the"
             " repository, listed in the briefs; a ticket is not claimed while a name in its `env` is not set, and"
             " only the key of a tool with `ci = true` may be in a ticket branch's reach (rail docs tools)",
    "profiles": "nothing yet: the language profiles rail init found, each a name and the paths that hold its files"
                " (rail docs languages)",
    "guides.start": "next and advance: the page whose text a ticket's first IMPLEMENT brief carries, once per"
                    " ticket. Each guides key is a path from the repository root, optionally followed by #Heading"
                    " for each section to take, or empty for none; a config with no [guides] table adds none"
                    " (rail docs guides)",
    "guides.stuck": "next and advance: the page a STEP_FAILED brief carries once the same failure has repeated",
    "guides.findings": "next and advance: the page the brief that asks for answers to review findings carries",
    "guides.conflict": "next and advance: the page the brief carries while a rebase is stopped on a conflict",
    "guides.contract": "next: the page the brief carries that asks for the contract of a ticket that came in as a"
                       " request",
    "guides.split": "advance and next: the page the SPLIT brief carries",
    "guides.setup": "next: the page the init task carries",
}


def _fields(value, prefix=""):
    for key, item in value.items():
        name = f"{prefix}{key}"
        if isinstance(item, dict):
            yield from _fields(item, f"{name}.")
        else:
            yield name, item


def config_page():
    lines = ["# Config reference", "", "`.rail/config.toml`, with each field's default and the step that reads it.",
             "An unknown key fails with a suggestion. A pack's settings live in a `[NAME]` section of its own.", "",
             "| Field | Default | Reader |", "|---|---|---|"]
    long = []
    for name, default in _fields(configmod.DEFAULTS):
        if isinstance(default, str) and len(default) >= 60:
            long.append((name, default))
            shown = "(below)"
        else:
            shown = f"`{str(default).lower() if isinstance(default, bool) else repr(default)}`"  # TOML spells true
        lines.append(f"| `{name}` | {shown} | {READERS.get(name, '')} |")
    for name, (keys, needed) in configmod.TABLE_ARRAYS.items():
        lines += ["", f"A `[[{name}]]` table takes: " + ", ".join(f"`{k}`" for k in keys) + f"; `{needed}` is needed."]
    from . import tools
    lines += ["", "A `[tools.NAME]` table takes: " + ", ".join(f"`{k}`" for k in tools.KEYS) + "; `use` is needed."]
    for name, default in long:
        lines += ["", f"## Default `{name}`", "", "```text", default, "```"]
    return "\n".join(lines) + "\n"


def cli_page(parser):
    lines = ["# CLI reference", "", "Every verb answers in one JSON shape with `--json`. Exit codes: 0 when the command"
             " worked (read `owner`), 2 for a usage error, 3 when a step failed.", ""]
    subparsers = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")
    helps = {c.dest: c.help for c in subparsers._choices_actions}
    for name, sub in subparsers.choices.items():
        if name not in helps:
            continue  # internal entries, such as hook
        usage = re.sub(r"\s+", " ", sub.format_usage().replace("usage: ", "")).strip()
        lines += [f"## rail {name}", "", helps[name] + ".", "", f"    {usage}", ""]
    return "\n".join(lines)


def part(text, spec):
    """The text a brief takes from a page. `spec` is "PATH" for the whole page, or "PATH#Heading#Heading" for those
    sections, in that order: each runs from its heading line to the next heading of any level, and a # inside a
    fenced block is no heading. A skill's front matter is left out. None when a named heading isn't there."""
    headings = spec.split("#")[1:]
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        text = text[end + 5:] if end >= 0 else text
    if not headings:
        return text.strip()
    found, current, fenced = {}, None, False
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        elif not fenced and (m := re.match(r"#+\s+(.+?)\s*$", line)):
            current = m.group(1) if m.group(1) in headings else None
        if current:
            found.setdefault(current, []).append(line)
    if any(h not in found for h in headings):
        return None
    return "\n\n".join("\n".join(found[h]).strip() for h in headings)


def read_part(spec, *roots):
    """`part` of the page at PATH, from the first root that has the file; None when none has it."""
    path = spec.split("#")[0]
    for root in roots:
        full = os.path.join(root, path)
        if root and os.path.isfile(full):
            with open(full) as f:
                return part(f.read(), spec)
    return None


TERMS = os.path.join(os.path.dirname(DOCS), "terms.toml")


def terms():
    """Rail's terms, as engine/terms.toml lists them: [{term, means, not, page}]."""
    with open(TERMS, "rb") as f:
        return tomllib.load(f)["terms"]


def terms_page():
    lines = ["# Terms", "", "One word for one thing. Rail's own text keeps to this list, and a test in Rail's suite fails"
             " when a word in the last column stands in it. Use the same words in a ticket, a guide or a source: the"
             " agents that read them know these.", "", "| Term | Means | Defined in | Not |", "|---|---|---|---|"]
    for t in terms():
        lines.append(f"| {t['term']} | {t['means']} | `rail docs {t['page']}` | {', '.join(t['not'])} |")
    return "\n".join(lines) + "\n"


def topics():
    pages = sorted(f[:-3] for f in os.listdir(DOCS) if f.endswith(".md")) if os.path.isdir(DOCS) else []
    return pages + ["config", "cli", "terms"]


def page(topic, parser):
    if topic == "terms":
        return terms_page()
    if topic == "config":
        return config_page()
    if topic == "cli":
        return cli_page(parser)
    path = os.path.join(DOCS, f"{topic}.md")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return f.read()


def index():
    lines = ["# Rail docs", "", "Read a topic with: rail docs TOPIC", ""]
    for topic in topics():
        title = {"config": "Config reference", "cli": "CLI reference", "terms": "Terms"}.get(topic, topic)
        path = os.path.join(DOCS, f"{topic}.md")
        if os.path.exists(path):
            with open(path) as f:
                first = f.readline().lstrip("# ").strip()
            title = first or topic
        lines.append(f"- {topic}: {title}")
    return "\n".join(lines) + "\n"
