"""Ticket files: TOML front matter between '+++' lines, then markdown sections."""

import difflib
import hashlib
import json
import re
import tomllib

# AUTO: the engine accepts the contract and merges. PERSON: a person approves the contract and merges.
TIERS = ("AUTO", "PERSON")
# What a revert doesn't undo (rail docs kinds). A ticket is PERSON when its change does something of one of these kinds.
# engine/reviewer.md names all but public-release, on purpose: a release that can't be pulled back takes effect only
# at release (docs/kinds.md), so it is a person's question there, not one a reviewer answers from a ticket's diff. The
# review schema's enum holds all of them: review.py checks an id against this one tuple, and naming it isn't wrong.
KINDS = ("data-loss", "data-shape", "data-exposure", "external-effect", "access", "runs-with-secrets", "controls",
         "infrastructure", "money", "licence", "public-release")
FIELDS = {
    "id": str, "title": str, "tier": str, "scope_paths": list, "after": list,
    "caused_by": str, "external_id": str, "reversibility": str, "rollback": str, "person_reason": str,
    "kind": str, "reverts": str,
}
TICKET_KINDS = ("revert",)  # `kind`: a ticket whose contract is built in. A revert takes ticket `reverts` out again
# The `## Grilling` record a bot or a session writes when it questioned the person who asked for the ticket.
TOPICS = ("scope", "done", "behaviour", "tier", "out-of-scope", "other")
TAKEN = ("accepted", "edited", "rejected", "answered")  # answered: there was no recommendation to take
NO_RECOMMENDATION = {"", "-", "(none)", "none"}
GRILL_KEYS = {"channel": "channel", "agent": "agent", "person": "person", "started": "started",
              "confirmed": "confirmed", "drafts shown": "drafts"}
VACUOUS = {"", "true", ":", "exit 0", "/bin/true", "/usr/bin/true", "pass", "ok", "works"}
_CHECK = re.compile(r"^\s*[-*]\s+Check:\s*(.*)$")
_ASSUMED = re.compile(r"^\s*[-*]\s+ASSUMED:\s*(.*)$")
_DECIDED = re.compile(r"^\s*[-*]\s+VERIFIED:\s*decided, not checked\s*:\s*(\S.*)$", re.I)
_NOT_TESTED = re.compile(r"^\s*(?:[-*]\s+)?not tested:\s*(\S.*)$", re.I)
_NOTICED = re.compile(r"^\s*(?:[-*]\s+)?Noticed:\s*(\S.*)$")
_DECIDED_BARE = re.compile(r"^\s*[-*]\s+VERIFIED:\s*decided, not checked\s*:?[\s.]*$", re.I)


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

    def reason_parts(self):
        """Each part of `person_reason` ("kind id: where", parts separated by "; ") as (kind or None, the part)."""
        reason = self.get("person_reason", "")
        parts = [p.strip() for p in reason.split(";")] if isinstance(reason, str) else []
        kinds = [p.partition(":")[0].strip() if ":" in p else "" for p in parts]
        return [(k if k in KINDS else None, p) for k, p in zip(kinds, parts) if p]

    @property
    def kinds(self):
        """The kinds `person_reason` names, in the order written, each once; [] when a part names none."""
        parts = self.reason_parts()
        if not parts or not all(k for k, _ in parts):
            return []
        return list(dict.fromkeys(k for k, _ in parts))

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

    def why_line(self):
        """The first line of `## Why`."""
        return next((line.strip() for line in self.sections.get("Why", "").splitlines() if line.strip()), "")

    def decided(self):
        """What each 'VERIFIED: decided, not checked:' row decided: a choice nobody checked, with its reason."""
        return self._rows(_DECIDED, "Assumptions")

    def tried(self):
        """The lines of `## Tried`: what an attempt at this ticket tried and why it didn't work."""
        return [re.sub(r"^[-*]\s+", "", line.strip()) for line in self.sections.get("Tried", "").splitlines()
                if line.strip()]

    def not_tested(self):
        """What the 'not tested: X, because Y' lines say, wherever the worker wrote them."""
        return self._rows(_NOT_TESTED)

    def noticed(self):
        """What the 'Noticed:' lines say: problems seen outside the ticket and left alone."""
        return self._rows(_NOTICED)

    def _rows(self, pattern, section=None):
        text = self.sections.get(section, "") if section else "\n".join(self.sections.values())
        return [m.group(1).strip() for m in map(pattern.match, text.splitlines()) if m]

    def open_assumptions(self):
        lines = self.sections.get("Assumptions", "").splitlines()
        return [m.group(1).strip() for m in map(_ASSUMED.match, lines) if m]

    def grilling(self):
        """The `## Grilling` record as (record, errors); (None, []) when the ticket has none."""
        if "Grilling" not in self.sections:
            return None, []
        record, questions, errors = {}, [], []
        for line in self.sections["Grilling"].splitlines():
            bullet = re.match(r"^\s*[-*]\s+([A-Za-z ]+):\s*(.*?)\s*$", line)
            if bullet:
                key = GRILL_KEYS.get(bullet.group(1).strip().lower())
                if key is None:
                    errors.append(f"Grilling: unknown line '{bullet.group(1).strip()}'; the lines are "
                                  + ", ".join(k.capitalize() for k in GRILL_KEYS))
                else:
                    record[key] = bullet.group(2)
                continue
            if not line.strip().startswith("|"):
                continue
            cells = [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
            if not cells or set(cells[0]) <= set("-: ") or cells[0] in ("#", "Q"):
                continue  # the heading row and the line under it
            if len(cells) != 5:
                errors.append(f"Grilling: a question row needs 5 cells (#, Topic, Recommended, Answer, Taken), got"
                              f" {len(cells)}: {line.strip()}")
                continue
            qid, topic, recommended, answer, taken = cells
            topic, taken = topic.lower(), taken.lower()
            has = recommended.lower() not in NO_RECOMMENDATION
            if topic not in TOPICS:
                errors.append(f"Grilling {qid}: topic must be one of {', '.join(TOPICS)}, not '{topic}'")
            if taken not in TAKEN:
                errors.append(f"Grilling {qid}: Taken must be one of {', '.join(TAKEN)}, not '{taken}'")
            elif has == (taken == "answered"):
                errors.append(f"Grilling {qid}: " + ("a question with a recommendation was accepted, edited or rejected"
                                                     if has else "a question with no recommendation was answered"))
            if not answer:
                errors.append(f"Grilling {qid}: the Answer is empty")
            questions.append({"id": qid, "topic": topic, "recommended": has, "taken": taken})
        if not record.get("channel"):
            errors.append("Grilling: '- Channel:' is missing (slack, telegram, session, ...)")
        elif not re.fullmatch(r"[a-z0-9][a-z0-9-]*", record["channel"]):
            errors.append(f"Grilling: Channel is one lowercase word, such as slack, not '{record['channel']}'")
        for key in ("started", "confirmed"):
            if record.get(key) and not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d(:\d\d)?Z", record[key]):
                errors.append(f"Grilling: {key.capitalize()} is a UTC time like 2026-11-16T09:12:00Z")
        if record.get("drafts") is not None:
            if record["drafts"].isdigit():
                record["drafts"] = int(record["drafts"])
            else:
                errors.append("Grilling: Drafts shown is a number")
        record["questions"] = questions
        return record, errors

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
    reason = ticket.get("person_reason", "")
    if isinstance(reason, str) and (reason.strip() or ticket.tier == "PERSON") and not ticket.kinds:
        bad = next((part for kind, part in ticket.reason_parts() if not kind), reason)
        errors.append(f"a PERSON ticket needs person_reason: the id of what in the change can't be undone"
                      f" ({', '.join(KINDS)}), a colon, and where, such as"
                      " person_reason = \"access: src/auth/session.py\". Separate several with \"; \". A change with"
                      " none of those kinds is AUTO"
                      if not reason.strip() else
                      f"person_reason must start with a kind's id and a colon, and so must each part after a \"; \""
                      f" ({', '.join(KINDS)}); got '{bad}'")
    scope = ticket.get("scope_paths", [])
    if not scope or not all(isinstance(p, str) and p.strip() for p in scope):
        errors.append("scope_paths must list at least one path glob")
    elif any(p.startswith("/") or ".." in p.split("/") for p in scope):
        errors.append("scope_paths must be relative to the repository root")
    if ticket.id and ticket.id in ticket.after:
        errors.append("a ticket can't come after itself")
    if not ticket.sections.get("Why"):
        errors.append("'## Why' is missing or empty")
    kind = ticket.get("kind")
    if kind is not None and kind not in TICKET_KINDS:
        errors.append(f"kind must be one of {', '.join(TICKET_KINDS)}, or left out")
    reverts = ticket.get("reverts")
    if kind == "revert" and not (isinstance(reverts, str) and reverts.strip().isdigit()):
        errors.append('a revert ticket needs reverts = "NN", the id of the merged ticket it takes out')
    elif kind != "revert" and reverts is not None:
        errors.append("'reverts' belongs to a ticket with kind = \"revert\"")
    if "Done Contract" not in ticket.sections:
        errors.append("'## Done Contract' is missing")
    elif not ticket.check_lines() and kind != "revert":
        # A revert's check is built in: ship compares the change with the reverse of the reverted ticket's.
        errors.append("the Done Contract needs at least one '- Check: `command`' line")
    if any(_DECIDED_BARE.match(line) for line in ticket.sections.get("Assumptions", "").splitlines()):
        errors.append("a 'VERIFIED: decided, not checked:' row needs, after the colon, what you decided, your reason and"
                      " what it costs if you are wrong: a decision with no reason can't be checked later")
    errors += ticket.grilling()[1]
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


def with_field(text, key, value):
    """The ticket text with the front matter string `key` set to `value`."""
    lines = text.split("\n")
    end = next(i for i in range(1, len(lines)) if lines[i].strip() == "+++")
    front = [l for l in lines[1:end] if not re.match(rf"^\s*{key}\s*=", l)]
    return "\n".join(["+++", *front, f"{key} = {json.dumps(value)}", *lines[end:]])


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
