"""`rail doctor`: check the setup and print what's missing (plan, section 14)."""

import json
import os
import platform
import shutil
import subprocess

from . import gitx


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
                                        ("Notification", "notify"))
               if f"rail hook {name}" not in json.dumps(hooks.get(event, []))]
    found.append(("hooks", not missing, "the session-start, guard and notify hooks are wired" if not missing
                  else f"not wired in .claude/settings.json: {', '.join(missing)}; run rail init"))
    permissions = settings.get("permissions", {})
    expected = [("deny", "Edit(./.rail/journal/**)"), ("deny", "Read(./**/.env)"), ("ask", "Bash(sudo *)"),
                ("allow", "Bash(rail advance *)"), ("ask", "Bash(rail answer * --owner)")]
    absent = [rule for kind, rule in expected if rule not in permissions.get(kind, [])]
    guard_on_bash = any(g.get("matcher") == "Bash" and "rail hook guard" in json.dumps(g)
                        for g in hooks.get("PreToolUse", []))
    if not guard_on_bash and "guard" not in missing:
        absent.append("the guard hook's Bash matcher")
    found.append(("guard rules", not absent, "the allow, deny and ask rules are in .claude/settings.json" if not absent
                  else f"missing from .claude/settings.json: {', '.join(absent)}; run rail init"))

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

    if project.remote:
        from . import forge
        repo = forge.github_repo(project)
        if not repo:
            found.append(("forge", None, "the remote isn't on GitHub, and only GitHub is supported"))
        else:
            for name, passed, detail in forge.doctor_checks(project, repo):
                found.append((name, passed, detail))
    return found


def as_steps(found):
    steps = []
    for name, passed, detail in found:
        if passed is None:
            steps.append({"step": name, "status": "unavailable", "detail": detail})
        else:
            steps.append({"step": name, "status": "ran", "result": "pass" if passed else "fail", "detail": detail})
    return steps
