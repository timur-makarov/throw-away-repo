"""`rail doctor`: check the setup and print what's missing."""

import json
import os
import platform
import shutil
import subprocess

from . import gitx
from .util import cloud

# The cloud environment's setup script: it runs as root before each new machine's first session, from the folder
# that holds the repositories, and its result is kept as the environment's snapshot. `rail provision` links rail
# onto PATH, writes the machine's hooks, and runs the project's own provision command.
ENVIRONMENT_SCRIPT = """for d in */; do
  [ -x "$d.rail/bin/rail" ] && (cd "$d" && RAIL_CLOUD=1 .rail/bin/rail provision) || true
done"""


def _run(args, cwd):
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=30)
        return result.returncode, (result.stdout or result.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, str(e)


def checks(project):
    """[(name, passed or None for unavailable, detail)]."""
    root, found = project.root, []
    found.append(("python", True, platform.python_version()))
    code, out = _run(["git", "--version"], root)
    found.append(("git", code == 0, out))

    code, out = _run(["claude", "--version"], root) if shutil.which("claude") else (None, "")
    found.append(("claude", code == 0, out or "the claude CLI isn't on PATH: install Claude Code"))

    settings_path = os.path.join(root, ".claude", "settings.json")
    try:
        with open(settings_path) as f:
            settings = json.load(f)
    except (OSError, ValueError):
        settings = {}
    hooks = settings.get("hooks", {})
    missing = [name for event, name in (("SessionStart", "session-start"), ("PreToolUse", "guard"),
                                        ("Notification", "notify"), ("Stop", "stop"), ("PostToolUse", "pulse"))
               if f"rail hook {name}" not in json.dumps(hooks.get(event, []))]
    found.append(("hooks", not missing, "the session-start, guard, notify and save hooks are wired" if not missing
                  else f"not wired in .claude/settings.json: {', '.join(missing)}; run rail init"))
    permissions = settings.get("permissions", {})
    expected = [("deny", "Edit(./.rail/journal/**)"), ("deny", "Read(./**/.env)"),
                ("allow", "Bash(rail advance *)"), ("ask", "Bash(rail answer * --owner)")]
    absent = [rule for kind, rule in expected if rule not in permissions.get(kind, [])]
    # Ask rules prompt in every mode, auto mode included, so these three stop an unattended cloud session. The guard
    # hook asks the same on a person's own machine, where it matters.
    pausing = [rule for rule in ("Bash(sudo *)", "Bash(git reset --hard*)", "Bash(git clean -f*)")
               if rule in permissions.get("ask", [])]
    guard_on_bash = any(g.get("matcher") == "Bash" and "rail hook guard" in json.dumps(g)
                        for g in hooks.get("PreToolUse", []))
    if not guard_on_bash and "guard" not in missing:
        absent.append("the guard hook's Bash matcher")
    found.append(("guard rules", not absent, "the allow, deny and ask rules are in .claude/settings.json" if not absent
                  else f"missing from .claude/settings.json: {', '.join(absent)}; run rail init"))
    if pausing:
        found.append(("ask rules", False, f"remove {', '.join(pausing)} from permissions.ask in .claude/settings.json:"
                                          " they pause unattended cloud sessions, and the guard hook asks the same on"
                                          " your own machine"))

    worker = project.config["worker"]
    if worker["command"]:
        # The runner calls rail work in one Bash call: the Bash tool ends it at its ceiling, 10 minutes when unset.
        ceiling = (settings.get("env") or {}).get("BASH_MAX_TIMEOUT_MS")
        ceiling = int(ceiling) if str(ceiling).isdigit() else 600000
        under = worker["timeout_minutes"] * 60000 < ceiling
        found.append(("worker timeout", under, f"[worker] timeout_minutes ({worker['timeout_minutes']}) is under the Bash"
                      f" tool's ceiling ({ceiling // 60000} min)" if under else
                      f"[worker] timeout_minutes ({worker['timeout_minutes']}) is not under the Bash tool's ceiling"
                      f" ({ceiling // 60000} min, BASH_MAX_TIMEOUT_MS in .claude/settings.json's env; 10 when unset):"
                      " the Bash call that runs rail work would end first. Lower it, or raise the ceiling"))

    old = [name for name in ("reviewer.md", "review-v1.json") if f".rail/engine/{name}" in project.config["review"]["command"]]
    if old:
        found.append(("review command", False,
                      f"[review] command reads .rail/engine/{' and '.join(old)} from the ticket's worktree, so a ticket"
                      " that changes them is reviewed by its own copy. Use the paths the engine passes, which hold the"
                      ' base branch\'s: --system-prompt-file "$RAIL_REVIEW_PROMPT" and --json-schema'
                      ' "$(cat "$RAIL_REVIEW_SCHEMA")"'))

    agents = os.path.join(root, "AGENTS.md")
    has_section = os.path.exists(agents) and any(l.strip() == "## Rail" for l in open(agents).read().splitlines())
    found.append(("AGENTS.md", has_section, "has the ## Rail section" if has_section else "no ## Rail section: run rail init"))
    claude_md = os.path.join(root, "CLAUDE.md")
    if os.path.exists(claude_md):
        imports = "@AGENTS.md" in open(claude_md).read()
        found.append(("CLAUDE.md", imports, "imports AGENTS.md" if imports
                      else "CLAUDE.md stops Claude Code reading AGENTS.md: add a line @AGENTS.md"))
    if os.path.exists(os.path.join(root, "CLAUDE.local.md")):
        found.append(("CLAUDE.local.md", False, "CLAUDE.local.md stops Claude Code reading AGENTS.md: "
                                                "add @AGENTS.md to it, or remove it"))
    parent = os.path.dirname(root)
    while parent and parent != os.path.dirname(parent):
        if os.path.exists(os.path.join(parent, "CLAUDE.md")):
            found.append(("parent CLAUDE.md", False, f"{parent}/CLAUDE.md stops Claude Code reading AGENTS.md here"))
            break
        parent = os.path.dirname(parent)

    found.append(("config", True, ".rail/config.toml is valid"))  # Project() failed otherwise
    from . import sensors
    tools = sensors.tools(project)
    if tools:
        gone = [f"{tool} (sensor {name})" for name, tool in tools.items() if not shutil.which(tool)]
        found.append(("sensors", not gone, f"the tools of the {len(tools)} sensors are on this machine" if not gone else
                      f"not on this machine: {', '.join(gone)}; a sensor whose tool is missing can't run at ship"))
    from . import tools as toolsmod
    found += toolsmod.doctor(project)
    found += toolsmod.doctor_workflows(project)
    guides = {key: path for key, path in project.config["guides"].items() if path}
    if guides:
        from .docs import read_part
        gone = [f"{key} = {path}" for key, path in guides.items() if not read_part(path, root)]
        found.append(("guides", not gone, f"the {len(guides)} pages [guides] names are there" if not gone else
                      f"[guides] names pages or sections that aren't there, so no brief carries them:"
                      f" {', '.join(gone)}"))
    from . import init
    bare = init.unprofiled(init.tracked_files(root), project.config)
    if bare or project.config["profiles"]:
        found.append(("languages", not bare, "every tracked manifest is covered by a [[profiles]] entry" if not bare
                      else init.uncovered(bare)))
    from . import sources
    if sources.names(project):
        bad = sources.problems(project)
        found.append(("sources", not bad, f"{len(sources.names(project))} sources in {sources.DIR} load" if not bad
                      else "; ".join(bad)))

    if cloud():
        found += cloud_checks(project)

    if project.remote:
        from . import forge
        repo = forge.github_repo(project)
        if not repo:
            found.append(("forge", None, "the remote isn't on GitHub, and only GitHub is supported"))
        else:
            for name, passed, detail in forge.doctor_checks(project, repo):
                found.append((name, passed, detail))
            if found[-1][0] != "gh":  # gh reads the repository
                found += toolsmod.github_checks(project, repo)
    return found


def cloud_checks(project):
    """What a Claude Code cloud session needs beyond the repository."""
    from .cli import bin_dir, provisioned

    found = [("cloud", True, "a Claude Code cloud session: Rail installs what the checks need here")]
    done = provisioned(project)
    found.append(("provision", done, "this machine is provisioned: rail is linked, the machine's hooks are written,"
                                     " and [commands] provision ran" if done
                  else "this machine isn't provisioned: the environment's setup script does it, or rail provision"))
    try:
        with open(os.path.join(os.path.expanduser("~"), ".claude", "settings.json")) as f:
            machine = "hook guard --machine" in f.read()
    except OSError:
        machine = False
    launcher = os.path.realpath(os.path.join(project.root, ".rail", "bin", "rail"))
    linked = os.path.exists(os.path.join(bin_dir(), "rail"))
    ready = linked and machine
    found.append(("environment", ready, "rail is on PATH and the machine's hooks are in place" if ready else
                  "add these lines to the cloud environment's setup script (your agent can propose them with its"
                  " environment tool; you approve once). They provision each new machine before its first session,"
                  " so every session starts with rail, its hooks and the tools:\n" + ENVIRONMENT_SCRIPT))
    session = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if session:
        loaded = bool(project.cache_read("hooks", session))
        found.append(("session hooks", True if loaded or machine else None,
                      "the repository's hooks run in this session" if loaded else
                      "the repository's hooks didn't load in this session (it holds several repositories, or is a"
                      " project thread); the machine's hooks do their work" if machine else
                      "Rail's hooks didn't run in this session (it holds several repositories, or is a project"
                      " thread), so the guard and the saves aren't active here. The environment's setup script puts"
                      " them on the machine before a session starts; rail provision does it now if"
                      " this session lets it. Until then GitHub's ruleset is the guard"))
    return found


def as_steps(found):
    steps = []
    for name, passed, detail in found:
        if passed is None:
            steps.append({"step": name, "status": "unavailable", "detail": detail})
        else:
            steps.append({"step": name, "status": "ran", "result": "pass" if passed else "fail", "detail": detail})
    return steps
