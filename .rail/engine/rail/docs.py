"""`rail docs [topic]`: the framework's docs, shipped inside the engine (plan, section 13).

Pages are markdown files in engine/docs. The config and CLI reference pages are generated from the engine itself,
so they can't drift from what the engine reads.
"""

import os
import re

from . import config as configmod

DOCS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")

# Every config field names its reader (plan, section 1). A test checks this covers config.DEFAULTS.
READERS = {
    "base_branch": "claim, ship, CI and the merge: the branch tickets start from and merge into",
    "auto_tiers": "acceptance and the merge: these tiers are accepted and merged with no person",
    "migration_paths": "add and ship: a HIGH floor; tickets touching them need reversibility and rollback",
    "commands.setup": "the claim: runs in each new ticket worktree, with RAIL_TICKET set",
    "commands.verify": "ship and CI: the whole project's checks, scanners included",
    "commands.timeout_secs": "every command: setup, verify, each check, each review run",
    "risk_paths.HIGH": "add (matched against scope_paths) and ship (changed files): a HIGH floor",
    "risk_paths.MEDIUM": "add and ship: a MEDIUM floor",
    "size.LOW": "ship and CI: changed lines over this raise a LOW ticket to MEDIUM",
    "size.MEDIUM": "ship and CI: changed lines over this raise a MEDIUM ticket to HIGH",
    "size.exclude": "ship and CI: globs left out of the size count, besides generated files and lockfiles",
    "review.command": "advance: the reviewer, run in the ticket's worktree with the brief on stdin",
    "retry.budget": "next and advance: failed attempts per step before consult, then a person",
    "consult.command": "the consult pack: a read-only model, with the brief on stdin",
    "sweep.after": "next: LOW tickets and ticketless commits since the last sweep before one is offered",
    "map.depth": "doc-lint: the directory depth ## Areas must cover",
    "map.ignore": "doc-lint: directories that need no ## Areas row",
    "rules": "ship and CI: structure rules on added lines and files (rail docs rules)",
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
            shown = f"`{default!r}`"
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
