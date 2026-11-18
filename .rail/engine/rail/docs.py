"""`rail docs [topic]`: the framework's docs, shipped inside the engine.

Pages are markdown files in engine/docs. The config and CLI reference pages are generated from the engine itself,
so they can't drift from what the engine reads.
"""

import os
import re

from . import config as configmod

DOCS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")

# Every config field names its reader. A test checks this covers config.DEFAULTS.
READERS = {
    "base_branch": "claim, ship, CI and the merge: the branch tickets start from and merge into",
    "person_paths": "add (matched against scope_paths) and ship (changed files): a ticket that touches one is"
                    " PERSON, so a person approves its contract and merges it",
    "migration_paths": "add and ship: PERSON as well; tickets touching them need reversibility and rollback",
    "commands.setup": "the claim: runs in each new ticket worktree, with RAIL_TICKET set; rail adopt: runs in the"
                      " throwaway worktrees on the base and the branch before its checks",
    "commands.verify": "ship and CI: the whole project's checks, scanners included",
    "commands.provision": "rail provision, next in a cloud session, and CI: installs what the machine lacks, once"
                          " per machine, as root. Never run on a person's own machine",
    "commands.timeout_secs": "every command: setup, verify, provision, each check, each review run",
    "commands.base_checks": "next, at a ticket's first claim: runs each Check: line once on the untouched base and"
                            " records red or green in a base_checks event. Never a gate: it fails nothing",
    "size.cap": "ship and CI: an AUTO change with more changed lines than this is offered a split at its first ship"
                " (no attempt spent); the next ship over it, and CI, make it PERSON",
    "size.exclude": "ship and CI: globs left out of the size count, besides generated files and lockfiles",
    "review.command": "advance: the reviewer, run in the ticket's worktree with the brief on stdin",
    "review.model": "advance and sweep: the model the reviewer runs on (ANTHROPIC_MODEL and RAIL_MODEL for the"
                    " command); empty leaves the command's default",
    "review.skip_paths": "advance and CI: an AUTO change gets no reviewer when every file it changes matches one of"
                         " these globs. The sweep reviews such changes afterwards",
    "retry.budget": "next and advance: failures in a row at one step with the same signature before consult advises"
                    " once; the attempt after that failing too waits for a person",
    "retry.cap": "next and advance: failed attempts at one step, whatever their signatures, after which the ticket"
                 " waits for a person",
    "consult.command": "the consult pack: a read-only model, with the brief on stdin",
    "consult.model": "the consult pack: the model consult runs on, set the same way as review.model",
    "claim.stale_minutes": "next: minutes without a journal event after which another session's work in flight is"
                           " taken to be abandoned and resumed. Keep it above your longest command",
    "claim.save_minutes": "the save hooks and advance: work in flight is saved, and shows it is alive, at least this"
                          " often while a session works",
    "worker.ladder": "next and advance: the model and effort an agent_task names for an AUTO ticket's work, as"
                     " model:effort, one rung per failed attempt at the step the ticket is failing. Empty names none",
    "worker.person_ladder": "next and advance: the same ladder for a PERSON ticket, which starts higher",
    "sweep.after": "next: changes merged with no review (tickets inside review.skip_paths, and commits with no"
                   " ticket) since the last sweep before one is offered",
    "sweep.every": "next: tickets merged since the last sweep, reviewed or not, before one is offered; it then"
                   " gathers the findings reviewers parked and the checks they proposed. 0 switches this off",
    "map.depth": "doc-lint: the directory depth ## Areas must cover",
    "map.ignore": "doc-lint: directories that need no ## Areas row",
    "rules": "ship and CI: structure rules on added lines and files (rail docs rules)",
    "guides.start": "next and advance: the page named in a ticket's first IMPLEMENT brief, once per ticket. Each"
                    " guides key is a path from the repository root, or empty for none; the seed config names the"
                    " rail-* skills, and a config with no [guides] table names none (rail docs guides)",
    "guides.stuck": "next and advance: the page named in a STEP_FAILED brief once the same failure has repeated",
    "guides.findings": "next and advance: the page named in the brief that asks for answers to review findings",
    "guides.conflict": "next and advance: the page named in the brief while a rebase is stopped on a conflict",
    "guides.contract": "next: the page named in the brief that asks for the contract of a ticket that came in as a"
                       " request",
    "guides.split": "advance and next: the page named in the SPLIT brief",
    "guides.setup": "next: the page named in the init task",
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
    lines += ["", "A `[[rules]]` table takes: " + ", ".join(f"`{k}`" for k in configmod.RULE_KEYS) + "."]
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


def topics():
    pages = sorted(f[:-3] for f in os.listdir(DOCS) if f.endswith(".md")) if os.path.isdir(DOCS) else []
    return pages + ["config", "cli"]


def page(topic, parser):
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
        title = "Config reference" if topic == "config" else "CLI reference" if topic == "cli" else topic
        path = os.path.join(DOCS, f"{topic}.md")
        if os.path.exists(path):
            with open(path) as f:
                first = f.readline().lstrip("# ").strip()
            title = first or topic
        lines.append(f"- {topic}: {title}")
    return "\n".join(lines) + "\n"
