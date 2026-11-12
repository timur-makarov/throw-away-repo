"""The project: its root, config, base branch and remote, and the tickets found in git."""

import json
import os
import re

from . import config as configmod
from . import gitx
from .ticket import Ticket
from .util import RailError, now_iso

REMOTE = "origin"
IDS_BRANCH = "rail/ids"  # one commit per ticket ID, each a child of the last: the counter two clones can't both move
WORKTREES = ".claude/worktrees"
NON_PRODUCT = (".rail/tickets", ".rail/journal")
PRODUCT_SPEC = ["--", "."] + [f":(exclude){p}" for p in NON_PRODUCT]


def ticket_path(nn):
    return f".rail/tickets/{nn}.md"


def events_path(nn):
    return f".rail/journal/{nn}-events.jsonl"


def review_path(nn):
    return f".rail/journal/{nn}-review.json"


def advice_path(nn):
    return f".rail/journal/{nn}-advice.md"


def event(ticket_id, name, **fields):
    record = {"v": 1, "at": now_iso(), "ticket": ticket_id, "event": name}
    record.update(fields)
    return record


def parse_events(text):
    events = []
    for line in (text or "").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and "event" in record:
            events.append(record)
    return events


class TicketInfo:
    """What git holds for one ticket ID."""

    def __init__(self, ticket_id):
        self.id = ticket_id
        self.branch = None         # local branch name
        self.remote_branch = None  # branch name on the remote
        self.ref = None            # the ref the ticket and journal are read from
        self.ticket = None
        self.events = []
        self.review_text = None    # NN-review.json, the stored review runs
        self.merged = None         # the squash commit on base
        self.id_taken = False      # the ID is in the remote's counter branch, or the mkdir without a remote
        self.label = ""            # the title the ticket was added with, kept by the counter branch
        self.worktree = None
        self.on_base = False       # the ticket file is on the base branch
        self.dropped_mark = False  # the counter branch says the ticket was dropped: it outlives the ticket's branch
        self.remote_events = []    # the remote branch's journal, when it differs from the local branch's

    @property
    def name(self):
        return self.branch or self.remote_branch

    def last(self, name):
        found = [e for e in self.events if e.get("event") == name]
        return found[-1] if found else None


class Project:
    def __init__(self, cwd):
        top = gitx.git(["rev-parse", "--show-toplevel"], cwd, check=False)
        if top.returncode != 0:
            raise RailError("not inside a git repository", code="NOT_A_PROJECT")
        common = gitx.out(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd)
        self.common = common
        self.root = os.path.dirname(common) if os.path.basename(common) == ".git" else top.stdout.strip()
        self.config = configmod.load(self.root)
        self.base = self.config["base_branch"]
        self.remote = REMOTE if REMOTE in gitx.out(["remote"], self.root).split() else None
        self.online = False
        self.session = os.environ.get("CLAUDE_CODE_SESSION_ID") or None
        self.ids_dir = os.path.join(common, "rail", "ids")
        self.orphans = []

    # --- refs ---------------------------------------------------------------

    @property
    def base_ref(self):
        if self.remote and gitx.rev(f"refs/remotes/{self.remote}/{self.base}", self.root):
            return f"refs/remotes/{self.remote}/{self.base}"
        return f"refs/heads/{self.base}"

    def sync(self):
        """Fetch from the remote when there is one. Offline is fine: the network steps say so."""
        if self.remote:
            from . import forge
            self.online = gitx.fetch(self.root, self.remote)
            forge.expire()  # what GitHub said before the fetch may be old too
        return self.online

    def worktree_path(self, nn):
        return os.path.join(self.root, WORKTREES, nn)

    def rel(self, path):
        return os.path.relpath(path, self.root) if path else None

    # --- discovery -------------------------------------------------------------

    def tickets(self):
        """{id: TicketInfo} for every ticket git knows about, in ID order."""
        found = {}

        def info(nn):
            return found.setdefault(nn, TicketInfo(nn))

        prefixes = ["refs/heads"] + ([f"refs/remotes/{self.remote}"] if self.remote else [])
        heads = gitx.out(["for-each-ref", "--format=%(objectname) %(refname)", *prefixes], self.root).splitlines()
        tips = {ref: sha for sha, ref in (line.split(" ", 1) for line in heads)}
        for ref in sorted(tips):
            if m := re.match(r"refs/heads/((\d+)-.+)$", ref):
                info(m.group(2)).branch = info(m.group(2)).branch or m.group(1)
            elif self.remote and (m := re.match(rf"refs/remotes/{self.remote}/((\d+)-.+)$", ref)):
                info(m.group(2)).remote_branch = info(m.group(2)).remote_branch or m.group(1)
        for nn, label in self.counter()[2].items():
            info(nn).id_taken = True
            info(nn).label = label
        if os.path.isdir(self.ids_dir):
            for nn in os.listdir(self.ids_dir):
                if nn.isdigit():
                    info(nn).id_taken = True
        for nn in self.dropped_marks():
            if nn in found:
                found[nn].dropped_mark = True

        base = self.base_ref
        if gitx.rev(base, self.root):
            log = gitx.out(["log", base, "--grep=^Ticket: ", "--format=%H%x1f%B%x1e"], self.root)
            for entry in log.split("\x1e"):
                if "\x1f" not in entry:
                    continue
                sha, body = entry.strip().split("\x1f", 1)
                for nn in re.findall(r"^Ticket: (\d+)\s*$", body, re.M):
                    info(nn).merged = info(nn).merged or sha
            listing = gitx.out(["ls-tree", "--name-only", base, ".rail/tickets/"], self.root)
            for path in listing.splitlines():
                if m := re.match(r"\.rail/tickets/(\d+)\.md$", path):
                    info(m.group(1)).on_base = True

        trees = gitx.worktrees(self.root)
        specs = []
        for nn, t in found.items():
            if t.branch:
                t.ref = f"refs/heads/{t.branch}"
                t.worktree = trees.get(t.branch)
            elif t.remote_branch:
                t.ref = f"refs/remotes/{self.remote}/{t.remote_branch}"
            source = t.ref or base
            specs += [f"{source}:{ticket_path(nn)}", f"{source}:{events_path(nn)}", f"{source}:{review_path(nn)}"]
            other = f"refs/remotes/{self.remote}/{t.remote_branch}" if t.branch and t.remote_branch else None
            if other and tips.get(other) != tips.get(t.ref):
                # The remote branch moved, or this one has commits it lacks: another session may have taken the
                # ticket over, and its journal says so.
                specs.append(f"{other}:{events_path(nn)}")
        blobs = gitx.read_blobs(specs, self.root)
        self.orphans = []
        for nn, t in list(found.items()):
            source = t.ref or base
            text = blobs.get(f"{source}:{ticket_path(nn)}")
            t.ticket = Ticket(text) if text is not None else None
            t.events = parse_events(blobs.get(f"{source}:{events_path(nn)}"))
            t.review_text = blobs.get(f"{source}:{review_path(nn)}")
            if t.branch and t.remote_branch:
                t.remote_events = parse_events(blobs.get(f"refs/remotes/{self.remote}/{t.remote_branch}:{events_path(nn)}"))
            if t.ticket is None and not t.merged and not t.id_taken:
                # A branch named like a ticket that belongs to no ticket: listed for the person, never touched.
                self.orphans.append(t.name)
                del found[nn]
        return dict(sorted(found.items(), key=lambda item: int(item[0])))

    def find(self, key, tickets=None):
        """A ticket by ID or external id."""
        tickets = tickets if tickets is not None else self.tickets()
        if key in tickets:
            return tickets[key]
        for t in tickets.values():
            if t.ticket and t.ticket.get("external_id") == key:
                return t
        raise RailError(f"no ticket '{key}'", code="NO_TICKET")

    def max_id(self, tickets):
        return max((int(nn) for nn in tickets), default=0)

    # --- product diff ------------------------------------------------------------

    def changed_files(self, ref):
        return gitx.out(["diff", "--name-only", f"{self.base_ref}...{ref}", *PRODUCT_SPEC], self.root).splitlines()

    def patch_id(self, ref):
        diff = gitx.git(["diff", "-U0", f"{self.base_ref}...{ref}", *PRODUCT_SPEC], self.root).stdout
        if not diff:
            return ""
        result = gitx.git(["patch-id", "--stable"], self.root, input=diff).stdout.split()
        return result[0] if result else ""

    # --- writing ---------------------------------------------------------------

    def cache_read(self, kind, key):
        """The local cache, keyed by ticket, in the git common dir: notes nothing else needs."""
        path = os.path.join(self.common, "rail", "cache", kind, key)
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return f.read().strip() or None

    def cache_write(self, kind, key, value):
        path = os.path.join(self.common, "rail", "cache", kind, key)
        if value is None:
            if os.path.exists(path):
                os.remove(path)
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(value)

    def _lease_note(self, branch):
        return os.path.join(self.common, "rail", "cache", "leases", branch.replace("/", "%"))

    def note_rewrite(self, branch):
        """Before the engine rewrites a pushed ticket branch (a rebase), note the remote tip it replaces. Pushes use
        it as their lease until one succeeds, so a rewrite made offline still reaches the remote later."""
        tip = gitx.rev(f"refs/remotes/{self.remote}/{branch}", self.root) if self.remote else None
        path = self._lease_note(branch)
        if tip and not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(tip)

    def push_branch(self, branch, lease=None):
        if not self.remote or not self.online:
            return "unavailable"
        note = self._lease_note(branch)
        if lease is None and os.path.exists(note):
            with open(note) as f:
                lease = f"{branch}:{f.read().strip()}"
        result = gitx.push(self.root, self.remote, f"refs/heads/{branch}:refs/heads/{branch}", lease)
        if result == "ok":
            from . import forge
            forge.expire()  # the pull request's head moved
            if os.path.exists(note):
                os.remove(note)
        return result

    def append_events(self, t, events, message, lease=None, files=None):
        """Commit events (and whole journal files such as NN-review.json) to the ticket branch, without touching any
        checkout, then push. Returns the push result: 'ok', 'rejected' or 'unavailable'.
        """
        path = events_path(t.id)
        ref = f"refs/heads/{t.branch}"
        old = gitx.rev(ref, self.root)
        existing = gitx.read_blobs([f"{old}:{path}"], self.root)[f"{old}:{path}"] or ""
        text = existing + "".join(json.dumps(e, separators=(",", ":")) + "\n" for e in events)
        writes = {path: text, **(files or {})}
        new = gitx.commit_files(self.root, old, writes, f"{t.id}: {message}")
        if not gitx.update_ref(self.root, ref, new, old):
            raise RailError(f"branch {t.branch} moved while the journal was written; run the command again")
        if t.worktree:
            gitx.git(["checkout", "HEAD", "--", *writes], t.worktree)
        t.events.extend(events)
        return self.push_branch(t.branch, lease)

    def counter(self, fetch=False):
        """(tip, highest ID, {ID: the title it was added with}) from the remote's counter branch. Each commit there
        is `rail id NN` with the ticket's title below, and its parent is the ID before it. The chain shares no
        history with the project, so it costs a shallow clone nothing."""
        if not self.remote:
            return None, 0, {}
        ref = f"refs/remotes/{self.remote}/{IDS_BRANCH}"
        if fetch:
            # By name, so a clone that fetches only some branches still reads the counter.
            gitx.git(["fetch", "--quiet", self.remote, f"+refs/heads/{IDS_BRANCH}:{ref}"], self.root, check=False)
        tip = gitx.rev(ref, self.root)
        if not tip:
            return None, 0, {}
        ids = {}
        log = gitx.out(["log", "--first-parent", "--format=%s%x1f%b%x1e", tip], self.root)
        for entry in log.split("\x1e"):
            subject, _, body = entry.strip().partition("\x1f")
            m = re.match(r"rail id (\d+)$", subject)
            if m:
                ids[m.group(1)] = body.strip()
        return tip, max((int(nn) for nn in ids), default=0), ids

    def dropped_marks(self):
        """The IDs the counter branch marks as dropped (`rail drop NN` commits), or, with no remote, the marks in
        the git directory. A ticket's journal goes with its branch; this stays."""
        marks = set()
        tip = gitx.rev(f"refs/remotes/{self.remote}/{IDS_BRANCH}", self.root) if self.remote else None
        if tip:
            for subject in gitx.out(["log", "--first-parent", "--format=%s", tip], self.root).splitlines():
                if m := re.match(r"rail drop (\d+)$", subject):
                    marks.add(m.group(1))
        if os.path.isdir(self.ids_dir):
            marks |= {name[:-len(".dropped")] for name in os.listdir(self.ids_dir) if name.endswith(".dropped")}
        return marks

    def mark_dropped(self, nn):
        """Record a drop where it outlives the ticket's branch: one more commit on the counter branch. A ticket
        whose file reached the base branch would otherwise look approved again once its branch is deleted."""
        if not self.remote:
            os.makedirs(self.ids_dir, exist_ok=True)
            with open(os.path.join(self.ids_dir, f"{nn}.dropped"), "w") as f:
                f.write("")
            return True
        if not self.online:
            return False
        empty = gitx.git(["mktree"], self.root, input="").stdout.strip()
        for _ in range(20):
            tip = self.counter(fetch=True)[0]
            if str(nn) in self.dropped_marks():
                return True
            marker = gitx.out(["commit-tree", empty, *(["-p", tip] if tip else []), "-m", f"rail drop {nn}"], self.root)
            result = gitx.push(self.root, self.remote, f"{marker}:refs/heads/{IDS_BRANCH}")
            if result == "ok":
                gitx.git(["update-ref", f"refs/remotes/{self.remote}/{IDS_BRANCH}", marker], self.root, check=False)
                return True
            if result != "rejected":
                return False
        return False

    def take_id(self, start, build, label=""):
        """Take the next free ID at or above `start`. `build(nn)` makes the ticket's first commit.

        With a remote, the ID is taken by moving the counter branch one commit forward with a plain push. Git
        accepts only a fast-forward, so when two clones try at once one push is refused, and that clone reads the
        counter again and takes the next ID. One branch holds every ID: a cloud session can't delete branches, so a
        branch per ID would stay for ever.
        """
        nn = start
        if self.remote:
            if not self.online:
                raise RailError("can't reach the remote to take a ticket ID; try again online", code="UNAVAILABLE")
            empty = gitx.git(["mktree"], self.root, input="").stdout.strip()
            for _ in range(100):
                tip, last, _ = self.counter(fetch=True)
                nn = max(start, last + 1)
                parent = ["-p", tip] if tip else []
                marker = gitx.out(["commit-tree", empty, *parent, "-m", f"rail id {nn}", "-m", label], self.root)
                result = gitx.push(self.root, self.remote, f"{marker}:refs/heads/{IDS_BRANCH}")
                if result == "ok":
                    gitx.git(["update-ref", f"refs/remotes/{self.remote}/{IDS_BRANCH}", marker], self.root, check=False)
                    return str(nn), build(str(nn))
                if result != "rejected":
                    raise RailError("can't push the ticket ID to the remote", code="UNAVAILABLE")
            raise RailError("the ticket ID counter keeps moving; try again", code="UNAVAILABLE")
        os.makedirs(self.ids_dir, exist_ok=True)
        while True:
            try:
                os.mkdir(os.path.join(self.ids_dir, str(nn)))
                return str(nn), build(str(nn))
            except FileExistsError:
                nn += 1
