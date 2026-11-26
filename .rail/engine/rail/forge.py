"""`forge`: the engine's only way to talk to GitHub, through `gh api` REST calls.

`gh pr` and `gh issue` use GraphQL, which Claude Code cloud sessions block, so they are never used.
"""

import json
import re
import subprocess
import time

from . import gitx, util

LABELS = {
    "rail": ("0e8a16", "Rail: an issue for rail intake to turn into a ticket"),
    "rail:go": ("1d76db", "Rail: a person approves or continues this ticket"),
    "rail:needs-you": ("d93f0b", "Rail: this ticket waits for a person"),  # the engine sets it and never reads it
    "rail:hold": ("b60205", "Rail: a person stopped this ticket; rail:go continues it"),  # only a person sets it
    # only a person sets it, on an issue: the brake for the whole repository, or for the paths its body names
    "rail:stop": ("b60205", "Rail: while an issue with this label is open, Rail does nothing here"),
    # only a person sets it, on a merged pull request; the engine removes it once the revert ticket is filed
    "rail:revert": ("b60205", "Rail: on a merged pull request, files a ticket that reverts it"),
    "rail:look": ("fbca04", "Rail: merged with no person, and its Read these list is not empty"),  # the engine sets it
}

STOP_PATHS = re.compile(r"(?im)^[ \t]*paths:[ \t]*(\S.*)$")

# Whose comments speak for the repository: those of people who can push to it. GitHub gives every comment an
# author_association; a stranger's is NONE, CONTRIBUTOR or FIRST_TIME_CONTRIBUTOR, and so is most bots'.
TRUSTED = ("OWNER", "MEMBER", "COLLABORATOR")
# The engine comments with the person's own credentials, so its comments are told apart by this mark.
ENGINE_MARK = "<!-- rail -->"


# What one Forge has read from GitHub holds until something can have changed it: a write of the engine's own (a
# pull request, a label, a merge, a push), a fetch, or a shell command, during which CI may have finished.
_epoch = 0


def expire():
    global _epoch
    _epoch += 1


util.AFTER_SHELL.append(expire)


class ForgeError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class RateLimited(Exception):
    """GitHub refused a call because a rate limit is used up. `wait` is the seconds until it lifts. Not a
    ForgeError: nothing that treats GitHub as out of reach may catch it, since the command would go on and make
    more calls. It ends the command, and the answer says when to come back."""

    def __init__(self, wait, message):
        super().__init__(message)
        self.wait = wait


def github_repo(project):
    """'owner/name' from the origin remote's URL, or None when it isn't on GitHub."""
    url = gitx.git(["config", "--get", f"remote.{project.remote}.url"], project.root, check=False).stdout.strip()
    m = re.match(r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    return f"{m.group(1)}/{m.group(2)}" if m else None


PAGE = 100          # the most GitHub gives in one page of a list
MAX_PAGES = 20      # of one list: a list longer than this is read no further
WRITE_GAP = 1.0     # seconds between two writes, as GitHub's guide to its REST API asks
_last_write = None


def _limit_wait(status, headers, message):
    """Seconds to wait when this refusal is a rate limit, else None. GitHub answers 403 or 429 with `retry-after`, or
    with `x-ratelimit-remaining: 0` and the time the limit resets; with neither, its docs say to wait a minute."""
    if status not in (403, 429):
        return None
    after, reset = headers.get("retry-after", ""), headers.get("x-ratelimit-reset", "")
    used_up = headers.get("x-ratelimit-remaining") == "0"
    if not (after.isdigit() or used_up or "rate limit" in message.lower()):
        return None
    if after.isdigit():
        return max(1, int(after))
    if used_up and reset.isdigit():
        return max(1, int(reset) - int(time.time()))
    return 60


def call(method, path, body=None):
    """One REST call. Returns (the decoded JSON or None for an empty body, the response's headers by lower-case
    name). Raises ForgeError, or RateLimited when a rate limit refused it."""
    global _last_write
    args = ["gh", "api", "--method", method, path, "-H", "Accept: application/vnd.github+json", "--include"]
    if body is not None:
        args += ["--input", "-"]
    if method != "GET" and _last_write is not None:
        time.sleep(max(0.0, WRITE_GAP - (time.monotonic() - _last_write)))
    try:
        result = subprocess.run(args, input=json.dumps(body) if body is not None else None,
                                capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ForgeError(None, f"gh api {path}: {e}")
    finally:
        if method != "GET":
            _last_write = time.monotonic()
    head, _, payload = result.stdout.partition("\r\n\r\n") if "\r\n\r\n" in result.stdout else result.stdout.partition("\n\n")
    m = re.match(r"HTTP/[\d.]+ (\d+)", head)
    status = int(m.group(1)) if m else None
    headers = {name.strip().lower(): value.strip() for name, _, value in
               (line.partition(":") for line in head.splitlines()[1:]) if value}
    if result.returncode != 0 or (status and status >= 400):
        message = payload.strip() or result.stderr.strip()
        try:
            message = json.loads(payload).get("message", message)
        except (ValueError, AttributeError):
            pass
        wait = _limit_wait(status, headers, message)
        if wait is not None:
            raise RateLimited(wait, f"gh api {method} {path}: {status} {message}".strip())
        raise ForgeError(status, f"gh api {method} {path}: {status or ''} {message}".strip())
    payload = payload.strip()
    return (json.loads(payload) if payload else None), headers


def api(method, path, body=None):
    """One REST call. Returns the decoded JSON, or None for an empty body. Raises ForgeError or RateLimited.

    A list read this way is one page of 100, which is enough for labels, check runs and a ticket's comments.
    """
    return call(method, path, body)[0]


def pages(path):
    """A whole list: every page, following the `Link` header's rel="next"."""
    found = []
    for _ in range(MAX_PAGES):
        rows, headers = call("GET", path)
        found += rows or []
        m = re.search(r'<([^>]+)>;\s*rel="next"', headers.get("link", ""))
        if not m:
            break
        path = m.group(1)
    return found


def raw(path):
    """A REST call whose answer isn't JSON, such as a job's log. Returns the text, or None."""
    try:
        result = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def log_tail(log, lines=60):
    """What a failed Actions job printed last: the failing step's output up to its first ##[error] line."""
    rows = [re.sub(r"\x1b\[[0-9;]*m", "", re.sub(r"^\ufeff?\d{4}-\d\d-\d\dT[\d:.]+Z ", "", row))
            for row in log.splitlines()]
    end = next((i for i, row in enumerate(rows) if row.startswith("##[error]")), len(rows) - 1)
    start = max((i for i, row in enumerate(rows[:end]) if row.startswith("##[endgroup]")), default=-1) + 1
    return "\n".join([row for row in rows[start:end + 1] if row.strip()][-lines:])


def doctor_checks(project, repo):
    """[(name, passed or None, detail)] for the GitHub side of the setup."""
    found = []
    try:
        info = api("GET", f"repos/{repo}")
    except ForgeError as e:
        return [("gh", False, f"gh can't read {repo}: {e}. Log in with gh auth login")]
    found.append(("gh", True, f"gh reads {repo}"))
    base = project.base
    contexts, plan_limit, ruleset_squash = set(), False, False
    try:
        for rule in api("GET", f"repos/{repo}/rules/branches/{base}") or []:
            parameters = rule.get("parameters") or {}
            if rule.get("type") == "required_status_checks":
                contexts |= {c.get("context") for c in parameters.get("required_status_checks", [])}
            elif rule.get("type") == "pull_request":
                ruleset_squash = parameters.get("allowed_merge_methods") == ["squash"]
    except ForgeError as e:
        plan_limit = e.status == 403 and "Upgrade" in str(e)
    try:
        protection = api("GET", f"repos/{repo}/branches/{base}/protection/required_status_checks") or {}
        contexts |= set(protection.get("contexts", []))
        contexts |= {c.get("context") for c in protection.get("checks", [])}
    except ForgeError:
        pass
    # Squash only: the repository's own setting, or the ruleset's allowed merge methods on the base branch.
    squash_only = ruleset_squash or (info.get("allow_squash_merge") and not info.get("allow_merge_commit")
                                     and not info.get("allow_rebase_merge"))
    message = info.get("squash_merge_commit_title") == "PR_TITLE" and info.get("squash_merge_commit_message") == "PR_BODY"
    found.append(("squash merging", bool(squash_only and message),
                  "squash only, with the PR title and description" if squash_only and message else
                  f"at https://github.com/{repo}/settings (General > Pull Requests) allow squash merging only (or let"
                  " the ruleset do it), with 'Pull request title and description' as the default message"))
    if plan_limit and "rail" not in contexts:
        # Private repositories on GitHub's free plan have no rulesets or branch protection. The engine still merges
        # only on a green rail check, but nothing stops a person merging early.
        found.append(("required check", None, "this repository's GitHub plan offers no required checks; the engine"
                                              " merges only on a green rail check, and a person merging should check it"))
    else:
        found.append(("required check", "rail" in contexts,
                      f"rail is required on {base}" if "rail" in contexts else
                      f"make the rail check required on {base}: import .rail/ruleset.json at"
                      f" https://github.com/{repo}/settings/rules (New ruleset > Import a ruleset). Only a person can:"
                      " a cloud session can't change repository settings"))
    deletes = bool(info.get("delete_branch_on_merge"))
    found.append(("merged branches", deletes, "GitHub deletes a merged ticket's branch" if deletes else
                  f"turn on \"Automatically delete head branches\" at https://github.com/{repo}/settings (General >"
                  " Pull Requests): a cloud session can't delete branches, so merged ones would pile up"))
    try:
        names = {label["name"] for label in api("GET", f"repos/{repo}/labels?per_page=100") or []}
    except ForgeError as e:
        names = set()
        found.append(("labels", False, str(e)))
        return found
    missing = [name for name in LABELS if name not in names]
    found.append(("labels", not missing, f"all {len(LABELS)} labels exist" if not missing
                  else f"missing labels: {', '.join(missing)}; rail init creates them"))
    return found


def create_labels(repo):
    """Create the labels that are missing. Returns the names created."""
    names = {label["name"] for label in api("GET", f"repos/{repo}/labels?per_page=100") or []}
    created = []
    for name, (color, description) in LABELS.items():
        if name not in names:
            api("POST", f"repos/{repo}/labels", {"name": name, "color": color, "description": description})
            created.append(name)
    return created


class Forge:
    """The GitHub side of the tickets, read once per command.

    `ok` is False when there is no GitHub remote or the remote can't be reached; the steps that need the forge
    then report `unavailable`, and state comes from git and the journal alone.
    """

    def __init__(self, project, earlier=None):
        self.project = project
        self.repo = github_repo(project) if project.remote else None
        self.ok = bool(self.repo) and project.online
        self.epoch = _epoch
        self._pulls = None
        self._more = False   # the list of pull requests filled its page: older ones exist that it doesn't hold
        self._by_branch = {}
        self._full = {}
        self._checks = {}
        self._required = earlier._required if earlier else None  # the base branch's rules don't change mid-command
        self._stops = earlier._stops if earlier else None        # a person's brake is read once per command

    @property
    def stale(self):
        return self.epoch != _epoch

    def call(self, method, path, body=None):
        if method != "GET":
            expire()
        return api(method, f"repos/{self.repo}/{path}", body)

    # --- pull requests ----------------------------------------------------------

    def _own(self, pr):
        """Not from a fork: anyone can name a branch there like a ticket's. Such a pull request is not the ticket's,
        and what is written on it is not the owner's word."""
        head = pr["head"]
        return "repo" not in head or ((head["repo"] or {}).get("full_name") or "").lower() == self.repo.lower()

    def pulls(self):
        """{head branch: the newest PR from it}, from the 100 newest pull requests."""
        if self._pulls is None:
            self._pulls = {}
            try:
                found = self.call("GET", f"pulls?state=all&per_page={PAGE}&sort=created&direction=desc") or []
                self._more = len(found) >= PAGE
                for pr in found:
                    if self._own(pr):
                        self._pulls.setdefault(pr["head"]["ref"], pr)
            except ForgeError:
                self.ok = False
        return self._pulls

    def pr(self, branch, expected=True):
        """The newest pull request from a branch, as the list gives it: labels, head, title, merged_at. One that is
        older than the 100 newest is asked for by its branch, when the caller expects the branch to have one."""
        if not self.ok or not branch:
            return None
        found = self.pulls().get(branch)
        if found is None and self._more and expected and self.ok:
            if branch not in self._by_branch:
                owner = self.repo.split("/")[0]
                try:
                    rows = self.call("GET", f"pulls?state=all&per_page={PAGE}&sort=created&direction=desc"
                                            f"&head={owner}:{branch}") or []
                except ForgeError:
                    rows = []
                self._by_branch[branch] = next((pr for pr in rows if self._own(pr) and pr["head"]["ref"] == branch), None)
            found = self._by_branch[branch]
        return found

    def merged_from(self, nn):
        """The newest merged pull request from one of ticket NN's branches (NN-...), or None. A ticket whose branch
        is gone shows by it that its own pull request was merged. Only the 100 newest pull requests are searched:
        the branch's name went with the branch, so there is nothing to ask GitHub for."""
        if not self.ok:
            return None
        return next((pr for ref, pr in self.pulls().items() if ref.startswith(f"{nn}-") and pr.get("merged_at")), None)

    def full(self, pr):
        """An open pull request read on its own, for mergeable_state: the list doesn't carry it. One call per pull
        request, so it is asked only for a shipped ticket, where a conflict or a base that moved matters."""
        if not pr or pr.get("state") != "open":
            return pr
        if pr["number"] not in self._full:
            try:
                self._full[pr["number"]] = self.call("GET", f"pulls/{pr['number']}")
            except ForgeError:
                self._full[pr["number"]] = pr
        return self._full[pr["number"]]

    def open_pr(self, branch, title, body):
        pr = self.call("POST", "pulls", {"title": title, "head": branch, "base": self.project.base, "body": body})
        self.pulls()[branch] = pr
        return pr

    def update_pr(self, number, **fields):
        return self.call("PATCH", f"pulls/{number}", fields)

    def labels(self, pr):
        return {label["name"] for label in (pr or {}).get("labels", [])}

    def add_labels(self, number, names):
        self.call("POST", f"issues/{number}/labels", {"labels": list(names)})

    def remove_label(self, number, name):
        try:
            self.call("DELETE", f"issues/{number}/labels/{name}")
        except ForgeError as e:
            if e.status != 404:
                raise

    def line_comments(self, number):
        """The review comments on a pull request's lines, every page."""
        return pages(f"repos/{self.repo}/pulls/{number}/comments?per_page={PAGE}")

    def post_review(self, number, sha, comments):
        """One review that only comments: each comment on a line of the pull request's head."""
        self.call("POST", f"pulls/{number}/reviews", {"commit_id": sha, "event": "COMMENT", "comments": comments})

    def comments(self, number):
        return self.call("GET", f"issues/{number}/comments?per_page=100") or []

    def comment(self, number, body):
        self.call("POST", f"issues/{number}/comments", {"body": body})

    def merge(self, number, sha, title, message):
        """The async merge endpoint: squash, the head pinned with sha. Returns (requested, why not)."""
        try:
            self.call("PUT", f"pulls/{number}/merge-async", {"merge_method": "squash", "sha": sha,
                                                             "commit_title": title, "commit_message": message})
            return True, None
        except ForgeError as e:
            return False, str(e)

    # --- checks -----------------------------------------------------------------------

    def required(self):
        """The contexts the base branch requires; `rail` when none are set."""
        if self._required is None:
            contexts = set()
            try:
                for rule in self.call("GET", f"rules/branches/{self.project.base}") or []:
                    if rule.get("type") == "required_status_checks":
                        contexts |= {c.get("context") for c in rule.get("parameters", {}).get("required_status_checks", [])}
            except ForgeError:
                pass
            try:
                protection = self.call("GET", f"branches/{self.project.base}/protection/required_status_checks") or {}
                contexts |= set(protection.get("contexts", []))
            except ForgeError:
                pass
            self._required = contexts or {"rail"}
        return self._required

    def checks(self, sha):
        """(state, failing): 'green' when every required check passed, 'red' when one failed, else 'pending'.
        `failing` lists (name, summary) for the brief."""
        if sha not in self._checks:
            runs = (self.call("GET", f"commits/{sha}/check-runs?per_page=100") or {}).get("check_runs", [])
            latest = {}
            for run in runs:
                latest.setdefault(run.get("name"), run)
            failing, waiting = [], False
            for name in self.required():
                run = latest.get(name)
                if not run or run.get("status") != "completed":
                    waiting = True
                elif run.get("conclusion") not in ("success", "neutral", "skipped"):
                    output = run.get("output") or {}
                    said = "\n".join(x for x in (output.get("title"), output.get("summary"), output.get("text")) if x)
                    failing.append((name, (said.strip() or self.job_output(run))[:3000]))
            self._checks[sha] = ("red" if failing else "pending" if waiting else "green", failing)
        return self._checks[sha]

    def job_output(self, run):
        """A check run from GitHub Actions carries no output of its own: what the job printed is in its log, and
        the check run's id is the job's."""
        if (run.get("app") or {}).get("slug") != "github-actions" or not run.get("id"):
            return f"(no output; open the check: {run.get('details_url')})" if run.get("details_url") else ""
        path = f"repos/{self.repo}/actions/jobs/{run['id']}/logs"
        log = raw(path)
        return (log_tail(log) if log else "") or f"(no output; read the job's log: gh api {path})"

    # --- issues -------------------------------------------------------------------------

    def issues(self, label="rail"):
        """Every open issue with the label, however many pages they fill."""
        found = pages(f"repos/{self.repo}/issues?labels={label}&state=open&per_page={PAGE}")
        return [i for i in found if "pull_request" not in i]

    def open_issue(self, title, body, labels):
        return self.call("POST", "issues", {"title": title, "body": body, "labels": list(labels)})

    def close_issue(self, number):
        self.call("PATCH", f"issues/{number}", {"state": "closed", "state_reason": "completed"})

    def asked_reverts(self):
        """The merged pull requests a person labelled rail:revert, each in full. The issues endpoint lists pull
        requests too, and only it filters by label."""
        found = pages(f"repos/{self.repo}/issues?labels=rail:revert&state=closed&per_page={PAGE}")
        merged = [i for i in found if (i.get("pull_request") or {}).get("merged_at")]
        return [self.call("GET", f"pulls/{i['number']}") for i in sorted(merged, key=lambda i: i["number"])]

    def stops(self):
        """A person's brake: the open issues labelled rail:stop, as [{number, title, url, paths}], oldest first.
        `paths` holds the globs of a `paths:` line in the issue's body, and is empty when the issue stops the whole
        repository. Only someone who may triage the repository can set a label, so the label is a person's word.
        Read once per command; with GitHub out of reach there is nothing to read, and nothing is stopped."""
        if self._stops is None:
            if not self.ok:
                return []
            try:
                found = self.issues("rail:stop")
            except ForgeError:
                return []
            self._stops = []
            for issue in sorted(found, key=lambda i: i["number"]):
                line = STOP_PATHS.search(issue.get("body") or "")
                paths = [p.strip("`") for p in re.split(r"[,\s]+", line.group(1).strip())] if line else []
                smoke = re.search(r"<!-- rail-smoke: (\d+) -->", issue.get("body") or "")
                self._stops.append({"number": issue["number"], "title": issue.get("title") or "",
                                    "url": issue.get("html_url") or "", "paths": [p for p in paths if p],
                                    # the engine's own brake names the smoke check's issue it was set for
                                    **({"smoke": int(smoke.group(1))} if smoke else {})})
        return self._stops

    def forget_stops(self):
        """The engine set or lifted a brake itself: read them again."""
        self._stops = None
