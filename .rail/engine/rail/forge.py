"""`forge`: the engine's only way to talk to GitHub, through `gh api` REST calls.

`gh pr` and `gh issue` use GraphQL, which Claude Code cloud sessions block, so they are never used.
"""

import json
import re
import subprocess

from . import gitx, util

LABELS = {
    "rail": ("0e8a16", "Rail: an issue for rail intake to turn into a ticket"),
    "rail:go": ("1d76db", "Rail: a person approves or continues this ticket"),
    "rail:needs-you": ("d93f0b", "Rail: this ticket waits for a person"),
}


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


def github_repo(project):
    """'owner/name' from the origin remote's URL, or None when it isn't on GitHub."""
    url = gitx.git(["config", "--get", f"remote.{project.remote}.url"], project.root, check=False).stdout.strip()
    m = re.match(r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def api(method, path, body=None):
    """One REST call. Returns the decoded JSON, or None for an empty body. Raises ForgeError.

    Lists are read one page of 100, which is enough for labels, check runs and a ticket's comments.
    """
    args = ["gh", "api", "--method", method, path, "-H", "Accept: application/vnd.github+json", "--include"]
    if body is not None:
        args += ["--input", "-"]
    try:
        result = subprocess.run(args, input=json.dumps(body) if body is not None else None,
                                capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ForgeError(None, f"gh api {path}: {e}")
    head, _, payload = result.stdout.partition("\r\n\r\n") if "\r\n\r\n" in result.stdout else result.stdout.partition("\n\n")
    m = re.match(r"HTTP/[\d.]+ (\d+)", head)
    status = int(m.group(1)) if m else None
    if result.returncode != 0 or (status and status >= 400):
        message = payload.strip() or result.stderr.strip()
        try:
            message = json.loads(payload).get("message", message)
        except ValueError:
            pass
        raise ForgeError(status, f"gh api {method} {path}: {status or ''} {message}".strip())
    payload = payload.strip()
    return json.loads(payload) if payload else None


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
    found.append(("labels", not missing, "rail, rail:go and rail:needs-you exist" if not missing
                  else f"missing labels: {', '.join(missing)}; rail init creates them"))
    return found


def create_labels(repo):
    """Create the three labels that are missing. Returns the names created."""
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
        self._full = {}
        self._checks = {}
        self._required = earlier._required if earlier else None  # the base branch's rules don't change mid-command

    @property
    def stale(self):
        return self.epoch != _epoch

    def call(self, method, path, body=None):
        if method != "GET":
            expire()
        return api(method, f"repos/{self.repo}/{path}", body)

    # --- pull requests ----------------------------------------------------------

    def pulls(self):
        """{head branch: the newest PR from it}."""
        if self._pulls is None:
            self._pulls = {}
            try:
                for pr in self.call("GET", "pulls?state=all&per_page=100&sort=created&direction=desc") or []:
                    self._pulls.setdefault(pr["head"]["ref"], pr)
            except ForgeError:
                self.ok = False
        return self._pulls

    def pr(self, branch):
        """The newest pull request from a branch, as the list gives it: labels, head, title, merged_at."""
        if not self.ok or not branch:
            return None
        return self.pulls().get(branch)

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
        found = self.call("GET", f"issues?labels={label}&state=open&per_page=100") or []
        return [i for i in found if "pull_request" not in i]
