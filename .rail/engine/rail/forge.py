"""`forge`: the engine's only way to talk to GitHub, through `gh api` REST calls (plan, section 11).

`gh pr` and `gh issue` use GraphQL, which Claude Code cloud sessions block, so they are never used.
"""

import json
import re
import subprocess

from . import gitx

LABELS = {
    "rail": ("0e8a16", "Rail: an issue for rail intake to turn into a ticket"),
    "rail:go": ("1d76db", "Rail: a person approves or continues this ticket"),
    "rail:needs-you": ("d93f0b", "Rail: this ticket waits for a person"),
}


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


def doctor_checks(project, repo):
    """[(name, passed or None, detail)] for the GitHub side of the setup (plan, sections 11 and 14)."""
    found = []
    try:
        info = api("GET", f"repos/{repo}")
    except ForgeError as e:
        return [("gh", False, f"gh can't read {repo}: {e}. Log in with gh auth login")]
    found.append(("gh", True, f"gh reads {repo}"))
    squash_only = (info.get("allow_squash_merge") and not info.get("allow_merge_commit")
                   and not info.get("allow_rebase_merge"))
    message = info.get("squash_merge_commit_title") == "PR_TITLE" and info.get("squash_merge_commit_message") == "PR_BODY"
    found.append(("squash merging", bool(squash_only and message),
                  "squash only, with the PR title and description" if squash_only and message else
                  "in Settings > General > Pull Requests allow squash merging only, with 'Pull request title and "
                  "description' as the default message"))
    base = project.base
    contexts, plan_limit = set(), False
    try:
        for rule in api("GET", f"repos/{repo}/rules/branches/{base}") or []:
            if rule.get("type") == "required_status_checks":
                contexts |= {c.get("context") for c in rule.get("parameters", {}).get("required_status_checks", [])}
    except ForgeError as e:
        plan_limit = e.status == 403 and "Upgrade" in str(e)
    try:
        protection = api("GET", f"repos/{repo}/branches/{base}/protection/required_status_checks") or {}
        contexts |= set(protection.get("contexts", []))
        contexts |= {c.get("context") for c in protection.get("checks", [])}
    except ForgeError:
        pass
    if plan_limit and "rail" not in contexts:
        # Private repositories on GitHub's free plan have no rulesets or branch protection. The engine still merges
        # only on a green rail check, but nothing stops a person merging early.
        found.append(("required check", None, "this repository's GitHub plan offers no required checks; the engine"
                                              " merges only on a green rail check, and a person merging should check it"))
    else:
        found.append(("required check", "rail" in contexts,
                      f"rail is required on {base}" if "rail" in contexts else
                      f"make the rail check required on {base} (a ruleset or branch protection)"))
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
    """The GitHub side of the tickets, read once per command (plan, sections 7, 10 and 11).

    `ok` is False when there is no GitHub remote or the remote can't be reached; the steps that need the forge
    then report `unavailable`, and state comes from git and the journal alone.
    """

    def __init__(self, project):
        self.project = project
        self.repo = github_repo(project) if project.remote else None
        self.ok = bool(self.repo) and project.online
        self._pulls = None
        self._full = {}
        self._checks = {}
        self._required = None

    def call(self, method, path, body=None):
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
        if not self.ok or not branch:
            return None
        pr = self.pulls().get(branch)
        if pr and pr.get("state") == "open" and pr["number"] not in self._full:
            try:
                self._full[pr["number"]] = self.call("GET", f"pulls/{pr['number']}")
            except ForgeError:
                self._full[pr["number"]] = pr
        return self._full.get(pr["number"], pr) if pr else None

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
                    failing.append((name, "\n".join(x for x in (output.get("title"), output.get("summary"),
                                                                  output.get("text")) if x)[:3000]))
            self._checks[sha] = ("red" if failing else "pending" if waiting else "green", failing)
        return self._checks[sha]

    # --- issues -------------------------------------------------------------------------

    def issues(self, label="rail"):
        found = self.call("GET", f"issues?labels={label}&state=open&per_page=100") or []
        return [i for i in found if "pull_request" not in i]
