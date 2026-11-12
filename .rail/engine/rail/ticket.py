"""Ticket files: TOML front matter between '+++' lines, then markdown sections."""

import difflib
import hashlib
import re
import tomllib

TIERS = ("LOW", "MEDIUM", "HIGH")
FIELDS = {
    "id": str, "title": str, "tier": str, "scope_paths": list, "after": list,
    "caused_by": str, "external_id": str, "reversibility": str, "rollback": str,
}
VACUOUS = {"", "true", ":", "exit 0", "/bin/true", "/usr/bin/true", "pass", "ok", "works"}
_CHECK = re.compile(r"^\s*[-*]\s+Check:\s*(.*)$")
_ASSUMED = re.compile(r"^\s*[-*]\s+ASSUMED:\s*(.*)$")


def rank(tier):
    return TIERS.index(tier) if tier in TIERS else -1


def highest(*tiers):
    return max((t for t in tiers if t in TIERS), key=rank)


class Ticket:
    def __init__(self, text):
        self.text = text
        self.meta, self.front, self.sections, self.errors = {}, "", {}, []
        lines = text.split("\n")
        if not lines or lines[0].strip() != "+++":
            self.errors.append("the ticket must start with TOML front matter between '+++' lines")
            return
        try:
            end = next(i for i in range(1, len(lines)) if lines[i].strip() == "+++")
        except StopIteration:
            self.errors.append("the front matter has no closing '+++' line")
            return
        self.front = "\n".join(lines[1:end])
        try:
            self.meta = tomllib.loads(self.front)
        except tomllib.TOMLDecodeError as e:
            self.errors.append(f"the front matter is not valid TOML: {e}")
        name = None
        for line in lines[end + 1:]:
            heading = re.match(r"^## (.+?)\s*$", line)
            if heading:
                name = heading.group(1)
                self.sections[name] = []
            elif name:
                self.sections[name].append(line)
        self.sections = {k: "\n".join(v).strip() for k, v in self.sections.items()}

    def get(self, key, default=None):
        value = self.meta.get(key, default)
        return default if value is None else value

    @property
    def id(self):
        return str(self.get("id", ""))

    @property
    def title(self):
        return self.get("title", "")

    @property
    def tier(self):
        return self.get("tier", "")

    @property
    def scope(self):
        return [p for p in self.get("scope_paths", []) if isinstance(p, str)]

    @property
    def after(self):
        return [str(a) for a in self.get("after", [])]

    def check_lines(self):
        """The payload of each 'Check:' line in the Done Contract, as written."""
        lines = self.sections.get("Done Contract", "").splitlines()
        return [m.group(1).strip() for m in map(_CHECK.match, lines) if m]

    def checks(self):
        """The runnable command of each 'Check:' line (the text inside the backticks)."""
        return [p[1:-1].strip() for p in self.check_lines() if _ticked(p)]

    def open_assumptions(self):
        lines = self.sections.get("Assumptions", "").splitlines()
        return [m.group(1).strip() for m in map(_ASSUMED.match, lines) if m]

    def done_hash(self):
        """The Done Contract alone, so `amend` can tell what changed."""
        return hashlib.sha256(" ".join(self.sections.get("Done Contract", "").split()).encode()).hexdigest()[:12]

    def contract_hash(self):
        """SHA-256 of the Done Contract and the sorted scope_paths, whitespace normalised."""
        done = " ".join(self.sections.get("Done Contract", "").split())
        text = done + "\n" + "\n".join(sorted(self.scope))
        return hashlib.sha256(text.encode()).hexdigest()[:12]


def _ticked(payload):
    return len(payload) >= 2 and payload.startswith("`") and payload.endswith("`") and "`" not in payload[1:-1]


def vacuous(command):
    c = " ".join(command.split()).lower()
    if c in VACUOUS:
        return True
    if re.fullmatch(r"(echo|printf)\b[^|&;]*", c):
        return True
    return bool(re.search(r"\|\|\s*(true|:|exit 0)\s*$", c))


def lint(ticket, expect_id=None):
    """Ticket lint: everything that makes a ticket malformed. Open ASSUMED rows are not checked here."""
    errors = list(ticket.errors)
    if errors:
        return errors
    for key, value in ticket.meta.items():
        if key not in FIELDS:
            close = difflib.get_close_matches(key, list(FIELDS), n=1)
            errors.append(f"unknown front matter key '{key}'" + (f" (did you mean '{close[0]}'?)" if close else ""))
        elif not isinstance(value, FIELDS[key]):
            errors.append(f"'{key}' must be a {'list' if FIELDS[key] is list else 'string'}")
    if expect_id is not None and ticket.id != expect_id:
        errors.append(f"id is '{ticket.id}', expected '{expect_id}'")
    if not str(ticket.title).strip():
        errors.append("title is empty")
    if ticket.tier not in TIERS:
        errors.append(f"tier must be one of {', '.join(TIERS)}")
    scope = ticket.get("scope_paths", [])
    if not scope or not all(isinstance(p, str) and p.strip() for p in scope):
        errors.append("scope_paths must list at least one path glob")
    elif any(p.startswith("/") or ".." in p.split("/") for p in scope):
        errors.append("scope_paths must be relative to the repository root")
    if ticket.id and ticket.id in ticket.after:
        errors.append("a ticket can't come after itself")
    if not ticket.sections.get("Why"):
        errors.append("'## Why' is missing or empty")
    if "Done Contract" not in ticket.sections:
        errors.append("'## Done Contract' is missing")
    elif not ticket.check_lines():
        errors.append("the Done Contract needs at least one '- Check: `command`' line")
    for payload in ticket.check_lines():
        if not _ticked(payload):
            errors.append(f"Check: put the command in backticks (got '{payload}')")
        elif vacuous(payload[1:-1]):
            errors.append(f"vacuous Check: '{payload}' can't fail; name a command that tests the change")
    return errors


def with_id(text, ticket_id):
    """The ticket text with `id` set, as the first front matter line."""
    lines = text.split("\n")
    end = next(i for i in range(1, len(lines)) if lines[i].strip() == "+++")
    front = [l for l in lines[1:end] if not re.match(r"^\s*id\s*=", l)]
    return "\n".join(["+++", f'id = "{ticket_id}"', *front, *lines[end:]])


def with_tier(text, tier):
    """The ticket text with its tier raised to `tier` (the engine may only raise it)."""
    lines = text.split("\n")
    end = next(i for i in range(1, len(lines)) if lines[i].strip() == "+++")
    for i in range(1, end):
        if re.match(r"^\s*tier\s*=", lines[i]):
            lines[i] = re.sub(r'=\s*"[^"]*"', f'= "{tier}"', lines[i], count=1)
    return "\n".join(lines)


def slug(title):
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:40].strip("-") or "ticket"


def branch_name(ticket):
    parts = [ticket.id]
    if ticket.get("external_id"):
        parts.append(slug(ticket.get("external_id")))
    parts.append(slug(ticket.title))
    return "-".join(parts)
