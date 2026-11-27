"""Tools: what the work reaches outside the repository (rail docs tools).

A `[tools.NAME]` table declares a service with a key, a CLI or an MCP server: what it is for, the names of the
variables it needs (never their values), and a probe. The engine lists the tools in the briefs, stops before a
claim while a name is missing, and shows each tool in rail doctor.

A ticket branch runs its own copy of every workflow, so it can read any secret a run it starts is given. `ci = true`
marks a tool whose key may be read that way: a test or dev key. rail doctor checks that nothing else can be.
"""

import json
import os
import re
import urllib.parse

from .util import RailError, cloud, could_not_run, run_shell, tail

KEYS = {"use": str, "env": list, "probe": str, "review": bool, "ci": bool}
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PROBE_SECS = 60
MARK = "<!-- rail-tool: {name} -->"  # on the issue the engine opens for a tool whose name is missing


def check(value):
    """The [tools] table of a config, checked. Returns {name: declaration}."""
    if not isinstance(value, dict):
        raise RailError("config: tools must be a table of tables ([tools.NAME])")
    for name, tool in value.items():
        if not isinstance(tool, dict):
            raise RailError(f"config: tools.{name} must be a table")
        for key, item in tool.items():
            if key not in KEYS:
                raise RailError(f"config: unknown key 'tools.{name}.{key}'")
            if not isinstance(item, KEYS[key]):
                raise RailError(f"config: tools.{name}.{key} must be {KEYS[key].__name__}")
        if not tool.get("use", "").strip():
            raise RailError(f"config: tools.{name} needs use: one line saying what the tool is for, which the agents read")
        for var in tool.get("env", []):
            # A value written where a name belongs would be committed: only a name is accepted.
            if not isinstance(var, str) or not NAME.match(var):
                raise RailError(f"config: tools.{name}.env lists the names of environment variables, never their"
                                " values; one of its entries is no name")
        if tool.get("ci") and not tool.get("env"):
            raise RailError(f"config: tools.{name}.ci marks the tool's key as one a pull request's run may be given,"
                            " so the tool needs env: the name of that key")
    return value


def _dotenv(root):
    """The names the project root's .env gives a value. Only names are read: a value never leaves the file."""
    names = set()
    try:
        with open(os.path.join(root, ".env"), encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\S)", line)
                if m:
                    names.add(m.group(1))
    except OSError:
        pass
    return names


def missing(project):
    """{tool: [the names it declares that are not set here]}. A name is set when the environment has it, or the
    project root's .env gives it a value."""
    tools = project.config["tools"]
    if not any(tool.get("env") for tool in tools.values()):
        return {}
    local = _dotenv(project.root)
    found = {}
    for name, tool in tools.items():
        gone = [var for var in tool.get("env", []) if not os.environ.get(var) and var not in local]
        if gone:
            found[name] = gone
    return found


def where():
    """Where a person sets a name, for the machine this runs on."""
    if cloud():
        return ("Set it in this cloud environment's settings, as an environment variable; a session started after"
                " that has it. A key the environment's network proxy adds to requests never shows up as a variable:"
                " a tool reached that way declares no env and relies on its probe.")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return ("Set it as an Actions secret and pass it by name in the env of the job that runs Rail. A run that a"
                " pull request starts is given only the keys of tools declared ci = true.")
    return ("Set it in the shell that starts the agent, or in the project's .env (which .worktreeinclude copies into"
            " each ticket's worktree).")


def lines(project, review=False):
    """The tools as the lines of a brief: every tool for the worker; only `review = true` ones for the reviewer,
    the refuter and consult."""
    tools = {n: t for n, t in project.config["tools"].items() if t.get("review") or not review}
    if not tools:
        return []
    head = ("Tools this project declares for a reviewer, to read with and never to change anything:" if review else
            "Tools this project declares, for what the work reaches outside the repository:")
    return [head, *[f"- {name}: {tool['use'].strip()}"
                    + (f" (reads {', '.join(tool['env'])})" if tool.get("env") else "") for name, tool in tools.items()]]


def wait_brief(nn, gone):
    """The brief of TOOL_MISSING, for one ticket or for several ("1, 2")."""
    listed = "; ".join(f"{name} needs {', '.join(names)}" for name, names in gone.items())
    return (f"Ticket{'s' if ',' in nn else ''} {nn} can't be claimed on this machine: a tool the project declares has no credential here"
            f" ({listed}). {where()} Nothing was tried, so no attempt is counted. Then run: rail next")


def probe(project, name):
    """Run a tool's probe. Returns (passed, detail); (None, ...) when it has none."""
    command = project.config["tools"][name].get("probe", "").strip()
    if not command:
        return None, "no probe"
    code, output, _ = run_shell(command, project.root, {"RAIL_BASE": project.base_ref}, PROBE_SECS)
    if code == 0:
        return True, "its probe passed"
    said = "timed out" if code is None else could_not_run(code) or f"exit {code}"
    last = tail(output, 3, 300).strip()
    return False, f"its probe failed ({said})" + (f": {last}" if last else "")


def down(project):
    """{tool: what its probe said} for each declared tool whose names are set here and whose probe fails now."""
    gone, found = missing(project), {}
    for name in project.config["tools"]:
        if name not in gone:
            passed, detail = probe(project, name)
            if passed is False:
                found[name] = detail
    return found


def down_said(down):
    return "; ".join(f"{name}: {detail}" for name, detail in down.items())


DOWN_HELP = ("So the failure may be the machine's and not the change's: no attempt was counted. Run it once more. If"
             " the failure is the change's own, fix that first. A second failure in a row with the tool still out of"
             " reach waits for a person.")


def doctor(project):
    """One line per tool for rail doctor: each name present or missing, where to set it, and the probe's result."""
    found, gone = [], missing(project)
    for name, tool in project.config["tools"].items():
        if name in gone:
            found.append((f"tool {name}", False, f"{', '.join(gone[name])} not set here, so its probe was not run."
                                                   f" {where()}"))
            continue
        passed, detail = probe(project, name)
        names = f"{', '.join(tool['env'])} set; " if tool.get("env") else ""
        found.append((f"tool {name}", passed is not False, f"{names}{detail}"))
    return found


def candidates(root):
    """What in the repository looks like a tool, for the init task: MCP servers in .mcp.json, names in .env.example,
    and secrets the workflows read."""
    found = {"mcp": [], "env": [], "secrets": []}
    try:
        with open(os.path.join(root, ".mcp.json"), encoding="utf-8") as f:
            servers = json.load(f).get("mcpServers")
        found["mcp"] = sorted(servers) if isinstance(servers, dict) else []
    except (OSError, ValueError, AttributeError):
        pass
    try:
        with open(os.path.join(root, ".env.example"), encoding="utf-8", errors="replace") as f:
            found["env"] = sorted({m.group(1) for m in map(re.compile(
                r"^\s*#?\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=").match, f) if m})
    except OSError:
        pass
    workflows = os.path.join(root, ".github", "workflows")
    names = set()
    for name in sorted(os.listdir(workflows)) if os.path.isdir(workflows) else []:
        if name.endswith((".yml", ".yaml")):
            try:
                with open(os.path.join(workflows, name), encoding="utf-8", errors="replace") as f:
                    names |= {m for row in f if not row.lstrip().startswith("#")  # a comment's example is no secret
                              for m in re.findall(r"\bsecrets\.([A-Za-z_][A-Za-z0-9_]*)", row)}
            except OSError:
                pass
    found["secrets"] = sorted(names - {"GITHUB_TOKEN"})
    return found


def found_line(root):
    """The init task's sentence on what looks like a tool; "" when nothing does."""
    found = candidates(root)
    parts = [f"{what}: {', '.join(found[key])}" for key, what in (
        ("mcp", "MCP servers in .mcp.json"), ("env", "names in .env.example"),
        ("secrets", "secrets the workflows in .github/workflows read")) if found[key]]
    return f" rail init found what may be tools ({'; '.join(parts)}): declare the ones the work uses." if parts else ""


def sync_issues(project, gone):
    """In a cloud session nobody is there to read the answer: one open issue per tool whose name is missing, labelled
    rail:needs-you, and closed once the name is there. Never one per ticket."""
    from .forge import ForgeError

    forge = project.forge
    if not cloud() or not forge or not forge.ok or not any(t.get("env") for t in project.config["tools"].values()):
        return
    try:
        open_ = {name: issue for issue in forge.issues(label="rail:needs-you")
                 for name in project.config["tools"] if MARK.format(name=name) in (issue.get("body") or "")}
        for name, names in gone.items():
            if name not in open_:
                forge.open_issue(
                    f"Rail needs {', '.join(names)} for the tool {name}",
                    f"The project declares the tool `{name}` ({project.config['tools'][name]['use'].strip()}), and a"
                    f" cloud session found {', '.join(f'`{n}`' for n in names)} not set. No ticket is claimed there"
                    f" until it is. {where()}\n\nRail closes this issue once a session finds the name set."
                    f"\n\n{MARK.format(name=name)}", ["rail:needs-you"])
        for name, issue in open_.items():
            if name not in gone:
                forge.close_issue(issue["number"])
    except ForgeError:
        pass  # the wait is in the answer too; the issue is opened by the next run that reaches GitHub


# --- what a ticket branch can read ------------------------------------------------------

WORKFLOWS = ".github/workflows"
RAIL_YML = f"{WORKFLOWS}/rail.yml"
REACH = ("A ticket branch runs its own copy of every workflow, so it reads whatever such a run is given before a"
         " person sees the change. Give it only a key whose leak is undone by rotating it and costs nothing meanwhile"
         " (a test or dev key), declared by its tool with ci = true.")
_ON = re.compile(r"""^(?:on|"on"|'on'|true)\s*:(.*)$""")
_NAMED = re.compile(r"""\bsecrets\s*(?:\.\s*([A-Za-z_][A-Za-z0-9_]*)|\[\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]\s*\])""", re.I)
_ALL = re.compile(r"""toJSON\(\s*secrets\s*\)|^\s*secrets\s*:\s*inherit\b|\bsecrets\s*\[(?!\s*['"])""", re.I | re.M)


def ci_names(project):
    """{name: tool} for the keys of tools declared ci = true: the only secrets a ticket branch may read."""
    return {var: name for name, tool in project.config["tools"].items() if tool.get("ci") for var in tool.get("env", [])}


def _on_pull_request(text):
    """Whether a pull request starts this workflow: an event whose name starts with pull_request under its top-level
    `on`. The engine has no YAML reader, so this reads the key's own lines."""
    rows = text.splitlines()
    for i, row in enumerate(rows):
        m = _ON.match(row)
        if m:
            events = [m.group(1)]
            for later in rows[i + 1:]:
                if later.strip() and not later[0].isspace() and later[0] != "-":
                    break
                events.append(later)
            return bool(re.search(r"\bpull_request", "\n".join(events)))
    return False


def pull_request_secrets(root):
    """[(workflow, the secrets it names, whether it passes every secret)] for each workflow a pull request starts.
    GITHUB_TOKEN is left out: it is made for the run, and the workflow's permissions bound it."""
    found, folder = [], os.path.join(root, *WORKFLOWS.split("/"))
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if not name.endswith((".yml", ".yaml")):
            continue
        try:
            with open(os.path.join(folder, name), encoding="utf-8", errors="replace") as f:
                text = "\n".join(row for row in f.read().splitlines() if not row.lstrip().startswith("#"))
        except OSError:
            continue
        if _on_pull_request(text):
            names = {a or b for a, b in _NAMED.findall(text)}
            found.append((f"{WORKFLOWS}/{name}", sorted(n for n in names if n.upper() != "GITHUB_TOKEN"),
                          bool(_ALL.search(text))))
    return found


def doctor_workflows(project):
    """rail doctor's line on the secrets the workflows give a run a pull request starts; none when there are no such
    secrets and no ci = true tool."""
    allowed, reads = ci_names(project), pull_request_secrets(project.root)
    known = {name.upper() for name in allowed}
    wrong = []
    for path, names, everything in reads:
        if everything:
            wrong.append(f"{path} passes every secret to a run a pull request starts: pass each key by its own line")
        extra = [n for n in names if n.upper() not in known]
        if extra:
            wrong.append(f"{path} gives a run a pull request starts {', '.join(extra)}, which no tool declares with"
                         " ci = true: declare it so if it is a test or dev key, or take the line out")
    rail = next((r for r in reads if r[0] == RAIL_YML), None)
    passed_on = {n.upper() for n in rail[1]} if rail else set()
    unpassed = [n for n in sorted(allowed) if n.upper() not in passed_on] if rail and not rail[2] else []
    if not allowed and not any(names or everything for _, names, everything in reads):
        return []
    if wrong:
        return [("pull request secrets", False, "; ".join(wrong) + ". " + REACH)]
    if unpassed:
        lines_ = ", ".join(f"`{n}: ${{{{ secrets.{n} }}}}`" for n in unpassed)
        return [("pull request secrets", False,
                 f"{RAIL_YML} doesn't pass {', '.join(unpassed)}, declared ci = true, so a check that needs it fails"
                 f" in CI: add {lines_} to the env of the step that runs rail ci")]
    given = sorted({n for r in reads for n in r[1]})
    return [("pull request secrets", True, "a run a pull request starts is given only keys declared ci = true"
             + (f": {', '.join(given)}" if given else ", and none yet"))]


def ci_note(project):
    """One line for a failed rail ci: the ci = true keys this job was not given. "" when it has them all."""
    gone = [f"{var} (tool {name})" for var, name in sorted(ci_names(project).items()) if not os.environ.get(var)]
    if not gone:
        return ""
    return (f"\nNot set in this job: {', '.join(gone)}. A check that needs it fails here. Add it to the repository's"
            f" Actions secrets and pass it in {RAIL_YML}. A pull request from a fork or from Dependabot is given"
            " no secret.")


def _names(api, path):
    return {row["name"] for row in (api("GET", f"{path}?per_page=100") or {}).get("secrets", []) if row.get("name")}


def github_checks(project, repo):
    """rail doctor's lines on what GitHub itself would give a ticket branch. A branch can add a workflow of its own,
    so every repository secret is in its reach; an environment's secrets are too unless only the base branch may
    deploy to it."""
    from .forge import ForgeError, api

    known, base, found = {name.upper() for name in ci_names(project)}, project.base, []
    try:
        names = _names(api, f"repos/{repo}/actions/secrets")
    except ForgeError as e:
        return [("repository secrets", None,
                 f"gh can't list this repository's Actions secrets here ({e.status or 'no answer'}), so they weren't"
                 f" checked. Every repository secret is in a ticket branch's reach. {REACH} Keep any other secret in a"
                 f" GitHub environment that only {base} may deploy to.")]
    try:
        names |= _names(api, f"repos/{repo}/actions/organization-secrets")
    except ForgeError:
        pass  # a repository no organization owns has none
    extra = sorted(n for n in names if n.upper() not in known)
    if names:
        found.append(("repository secrets", not extra,
                      f"every repository secret is the key of a tool declared ci = true: {', '.join(sorted(names))}"
                      if not extra else
                      f"{', '.join(extra)}: in a ticket branch's reach, and no tool declares it with ci = true. A"
                      f" branch can add a workflow of its own that reads any repository or organization secret. {REACH}"
                      f" Move any other secret to a GitHub environment that only {base} may deploy to, at"
                      f" https://github.com/{repo}/settings/environments"))
    try:
        environments = (api("GET", f"repos/{repo}/environments?per_page=100") or {}).get("environments", [])
    except ForgeError:
        environments = []
    for env in environments:
        name = env.get("name") or ""
        quoted = urllib.parse.quote(name, safe="")
        try:
            held = sorted(n for n in _names(api, f"repos/{repo}/environments/{quoted}/secrets") if n.upper() not in known)
        except ForgeError:
            held = None
        if held == []:
            continue  # it holds nothing a ticket branch must not read
        policy = env.get("deployment_branch_policy")
        if not policy:
            open_to = "any branch"
        elif policy.get("custom_branch_policies"):
            try:
                rows = (api("GET", f"repos/{repo}/environments/{quoted}/deployment-branch-policies?per_page=100")
                        or {}).get("branch_policies", [])
            except ForgeError:
                rows = None
            others = None if rows is None else [f"{r.get('type', 'branch')} {r.get('name')}" for r in rows
                                                if (r.get("type", "branch"), r.get("name")) != ("branch", base)]
            open_to = "branches gh couldn't list" if others is None else ", ".join(others)
        else:
            open_to = ""  # protected branches only: a ticket branch is not one
        holds = "secrets gh couldn't list" if held is None else ", ".join(held)
        found.append((f"environment {name}", not open_to,
                      f"only {'protected branches' if not (policy or {}).get('custom_branch_policies') else base}"
                      f" may deploy to it" if not open_to else
                      f"it holds {holds} and {open_to} may deploy to it, so a ticket branch can read them: at"
                      f" https://github.com/{repo}/settings/environments allow {base} alone (Deployment branches and"
                      " tags > Selected branches and tags)"))
    return found
