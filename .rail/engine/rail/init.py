"""`rail init`: set a project up (plan, section 14). It never overwrites a file of the project's."""

import json
import os
import shutil
import stat

from . import gitx
from .util import RailError

# The framework this engine came from: engine/rail/init.py -> the framework's root.
FRAMEWORK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

LAUNCHER = '''#!/usr/bin/env python3
"""This project's rail launcher: it runs the engine in ../engine. The SessionStart hook puts this folder on PATH."""
import os
import sys

if sys.version_info < (3, 11):
    sys.stderr.write("rail needs Python 3.11 or newer (found %d.%d). On macOS: brew install python\\n" % sys.version_info[:2])
    sys.exit(2)

sys.dont_write_bytecode = True  # no __pycache__ under .rail/engine to commit by mistake
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "engine"))
from rail.cli import main  # noqa: E402

sys.exit(main())
'''

INIT_TASK = """Rail is installed, and this project isn't set up for it yet: .rail/config.toml isn't on {base}.
Read the repository to learn its stack, then propose each of these to the person and make the changes they confirm:
1. [commands] in .rail/config.toml: `setup`, which runs in each new ticket worktree (install dependencies), and `verify`,
   the whole project's checks: tests, lint, a secret scan over the branch's commits ($RAIL_BASE..HEAD; RAIL_BASE is
   set for every command) and, when a lockfile changes, a dependency scan for this stack. When no scanner is
   installed, ask the person which to install, or leave it out and say so. A monorepo makes verify affected-aware.
2. ARCHITECTURE.md with a `## Areas` table: | Area | Paths | Holds |, one row per area. Paths are globs, separated
   by commas; Holds says what lives there in a bug reporter's words. Cover every directory at depth {depth}; hidden
   directories such as .rail and .claude need no row, and neither do files at the root. At most 150 lines.
3. [risk_paths] in .rail/config.toml: keep the defaults, and add the paths a person should see changed
   (auth, payments, infrastructure) to HIGH or MEDIUM.
4. The [[rules]] in .rail/config.toml: keep, drop or add structure rules for this project.
5. .worktreeinclude at the root: one glob per line for local files a ticket worktree needs that git doesn't
   track, such as .env. Leave it out when there are none.
If the project already has its own agent workflow, hooks, guards, CI gates or repo map, list them and ask the
person whether to keep, merge or retire each one; until they decide, both run, and a hook of theirs may block a
step below. Then ask the person to make that commit.
Then commit what rail init added together with these changes to {base}. With a remote, push a branch and open a
pull request with `gh api` (gh pr doesn't work in cloud sessions); the person merges it.
Finally run `rail doctor` and make the one-time settings it lists."""


def _write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    if mode:
        os.chmod(path, mode)


def _merge(project_value, ours):
    """Add our settings to the project's. Existing values win; lists gain the items they lack."""
    for key, value in ours.items():
        if key not in project_value:
            project_value[key] = value
        elif isinstance(project_value[key], dict) and isinstance(value, dict):
            _merge(project_value[key], value)
        elif isinstance(project_value[key], list) and isinstance(value, list):
            project_value[key] += [item for item in value if item not in project_value[key]]
    return project_value


def _base_branch(root):
    """The remote's default branch; with no remote, the branch init runs on."""
    head = gitx.git(["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], root, check=False).stdout.strip()
    if head:
        return head.split("/", 1)[1]
    # A clone made without origin/HEAD (cloud sessions make them): ask the remote, so a setup branch isn't taken for the base.
    asked = gitx.git(["ls-remote", "--symref", "origin", "HEAD"], root, check=False).stdout
    for line in asked.splitlines():
        if line.startswith("ref: refs/heads/") and line.endswith("\tHEAD"):
            return line[len("ref: refs/heads/"):-len("\tHEAD")]
    current = gitx.git(["symbolic-ref", "--quiet", "--short", "HEAD"], root, check=False).stdout.strip()
    return current or "main"


def init(cwd):
    """Returns the receipts: one step per thing init adds, `not_run` when the project already has it."""
    seed = os.path.join(FRAMEWORK, "seed")
    if not os.path.isdir(seed):
        raise RailError("rail init runs from the framework: use the rail that install put on PATH")
    top = gitx.git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd, check=False)
    if top.returncode != 0:
        raise RailError("not inside a git repository: run git init first", code="NOT_A_PROJECT")
    common = top.stdout.strip()
    root = os.path.dirname(common) if os.path.basename(common) == ".git" else gitx.out(["rev-parse", "--show-toplevel"], cwd)
    receipts = []

    def step(name, done, detail):
        receipt = {"step": name, "status": "ran" if done else "not_run", "detail": detail}
        if done:
            receipt["result"] = "pass"
        receipts.append(receipt)

    rail_dir = os.path.join(root, ".rail")
    engine = os.path.join(rail_dir, "engine")
    if os.path.exists(engine):
        step("engine", False, ".rail/engine is there already; it is the project's")
    else:
        shutil.copytree(os.path.join(FRAMEWORK, "engine"), engine, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        step("engine", True, "copied to .rail/engine")

    launcher = os.path.join(rail_dir, "bin", "rail")
    if os.path.exists(launcher):
        step("launcher", False, ".rail/bin/rail is there already")
    else:
        _write(launcher, LAUNCHER, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
        step("launcher", True, "wrote .rail/bin/rail")

    source = os.path.join(rail_dir, "SOURCE")
    if os.path.exists(source):
        step("source", False, ".rail/SOURCE is there already")
    else:
        url = gitx.git(["remote", "get-url", "origin"], FRAMEWORK, check=False).stdout.strip() or FRAMEWORK
        commit = gitx.git(["rev-parse", "HEAD"], FRAMEWORK, check=False).stdout.strip()
        _write(source, f'url = "{url}"\ncommit = "{commit}"\n')
        step("source", True, f"framework {url} at {commit[:12]}")

    copies = {
        "config.toml": ".rail/config.toml",
        "tickets/TEMPLATE.md": ".rail/tickets/TEMPLATE.md",
        "rail.yml": ".github/workflows/rail.yml",
    }
    packs = os.path.join(FRAMEWORK, "packs")
    for name in sorted(os.listdir(packs)) if os.path.isdir(packs) else []:
        dest = os.path.join(rail_dir, "packs", name)
        if os.path.exists(dest):
            step(f"pack {name}", False, f".rail/packs/{name} is there already")
        else:
            shutil.copytree(os.path.join(packs, name), dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            step(f"pack {name}", True, f"copied to .rail/packs/{name}")
    for src, dest in copies.items():
        target = os.path.join(root, dest)
        if os.path.exists(target):
            step(dest, False, "the project has it already")
            continue
        with open(os.path.join(seed, src)) as f:
            text = f.read()
        if src == "config.toml":
            text = text.replace('base_branch = "main"', f'base_branch = "{_base_branch(root)}"', 1)
        _write(target, text)
        step(dest, True, "added")

    agents = os.path.join(root, "AGENTS.md")
    existing = open(agents).read() if os.path.exists(agents) else ""
    if any(line.strip() == "## Rail" for line in existing.splitlines()):
        step("AGENTS.md", False, "it has a ## Rail section already")
    else:
        with open(os.path.join(seed, "AGENTS.md")) as f:
            section = f.read()
        _write(agents, (existing.rstrip("\n") + "\n\n" if existing.strip() else "") + section)
        step("AGENTS.md", True, "added the ## Rail section")

    claude_md = os.path.join(root, "CLAUDE.md")
    if not os.path.exists(claude_md):
        step("CLAUDE.md", False, "the project has none, and Rail never creates one")
    else:
        text = open(claude_md).read()
        if "@AGENTS.md" in text:
            step("CLAUDE.md", False, "it imports AGENTS.md already")
        else:
            _write(claude_md, text.rstrip("\n") + "\n\n@AGENTS.md\n")
            step("CLAUDE.md", True, "added @AGENTS.md, so Claude Code reads AGENTS.md too")

    settings = os.path.join(root, ".claude", "settings.json")
    with open(os.path.join(seed, "settings.json")) as f:
        ours = json.load(f)
    try:
        theirs = json.load(open(settings)) if os.path.exists(settings) else {}
    except ValueError:
        theirs = None
    if theirs is None:
        step(".claude/settings.json", False, "not valid JSON, so left alone; merge seed/settings.json by hand")
    else:
        merged = _merge(json.loads(json.dumps(theirs)), ours)
        if merged == theirs:
            step(".claude/settings.json", False, "it has Rail's settings already")
        else:
            _write(settings, json.dumps(merged, indent=2) + "\n")
            step(".claude/settings.json", True, "merged hooks, permissions, sandbox and Bash timeouts")

    gitignore = os.path.join(root, ".gitignore")
    lines = open(gitignore).read().splitlines() if os.path.exists(gitignore) else []
    with open(os.path.join(seed, "gitignore")) as f:
        missing = [l for l in f.read().splitlines() if l and l not in lines]
    if missing:
        _write(gitignore, "\n".join(lines + missing) + "\n")
        step(".gitignore", True, f"added {', '.join(missing)}")
    else:
        step(".gitignore", False, "it has Rail's lines already")
    return root, receipts
