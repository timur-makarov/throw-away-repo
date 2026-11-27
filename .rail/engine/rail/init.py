"""`rail init`: set a project up. It never overwrites a file of the project's."""

import json
import os
import re
import shlex
import shutil
import stat
import tomllib

from . import gitx
from .util import RailError, globmatch, match_any

# The framework this engine came from: engine/rail/init.py -> the framework's root.
FRAMEWORK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
PROFILES = os.path.join(FRAMEWORK, "profiles")

# Each language's manifest names, and the folders whose manifests mark no code of the project's own: the lists of
# profiles/*/profile.toml, which a project's copy of the engine doesn't have, so `rail doctor` reads them here.
MANIFESTS = {"go": ["go.mod"], "python": ["pyproject.toml", "setup.cfg", "requirements*.txt"],
             "rust": ["Cargo.toml"], "typescript": ["package.json"]}
VENDORED = ["node_modules", "vendor", "target", ".venv", "dist"]

LAUNCHER = '''#!/usr/bin/env python3
"""This project's rail launcher: it runs the engine in ../engine. The SessionStart hook puts this folder on PATH."""
import os
import sys

if sys.version_info < (3, 11):
    sys.stderr.write("rail needs Python 3.11 or newer (found %d.%d). On macOS: brew install python\\n" % sys.version_info[:2])
    sys.exit(2)

# Compiled engine files go to the home folder: no __pycache__ under .rail/engine to commit by mistake, and the
# engine isn't compiled again on every call.
sys.pycache_prefix = os.path.join(os.path.expanduser("~"), ".cache", "rail", "pycache")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "engine"))
from rail.cli import main  # noqa: E402

sys.exit(main())
'''

INIT_TASK = """Rail is installed, and this project isn't set up for it yet: .rail/config.toml isn't on {base}.
{profiles}Read the repository to learn its stack, then propose each of these to the person and make the changes they confirm:
1. [commands] in .rail/config.toml: `setup`, which runs in each new ticket worktree (install dependencies), and `verify`,
   the whole project's checks: tests, lint, a secret scan over the branch's commits ($RAIL_BASE..HEAD; RAIL_BASE is
   set for every command) and, when a lockfile changes, a dependency scan for this stack. When no scanner is
   installed, ask the person which to install, or leave it out and say so. A monorepo makes verify affected-aware.
   Also `provision`: the command that installs those tools, as root, on a cloud session's machine and on a CI
   runner. It never runs on the person's own computer, where installing is theirs.
2. ARCHITECTURE.md with a `## Areas` table: | Area | Paths | Holds |, one row per area. Paths are globs, separated
   by commas; Holds says what lives there in a bug reporter's words. Cover every directory at depth {depth}; hidden
   directories such as .rail and .claude need no row, and neither do files at the root. At most 150 lines.
3. [kinds] in .rail/config.toml: a person is asked only about changes a revert doesn't undo. Keep the defaults,
   and for each kind id list the paths that hold it in this project: schemas (data-shape), auth (access),
   infrastructure code (infrastructure), payment code (money), code that emails or pays real people
   (external-effect), and the files that set an agent's permissions, tools or spend (controls). A ticket that touches
   one is PERSON, so a person approves its contract and merges it. Every other ticket is AUTO and gets the reviewer
   before the engine merges it. [review] skip_paths lists paths whose changes need no reviewer, such as docs; leave
   it empty when unsure.
4. The [[rules]] in .rail/config.toml: keep, drop or add structure rules for this project.
5. .worktreeinclude at the root: one glob per line for local files a ticket worktree needs that git doesn't
   track, such as .env. Leave it out when there are none.
6. [tools.NAME] in .rail/config.toml: one table for each thing the work reaches outside the repository (a service
   with a key, a CLI that signs in, an MCP server): `use`, one line the agents read; `env`, the names of the
   variables it needs, never a value; `probe`, a fast command that changes nothing and fails when the tool is out
   of reach; `ci = true` only for a test or dev key that a pull request's run may be given, with its line in
   .github/workflows/rail.yml.{tools} Leave it out when the work reaches nothing.
If the project already has its own agent workflow, hooks, guards, CI gates or repo map, list them and ask the
person whether to keep, merge or retire each one; until they decide, both run, and a hook of theirs may block a
step below. Then ask the person to make that commit.
Then commit what rail init added together with these changes to {base}. With a remote, push a branch and open a
pull request with `gh api` (gh pr doesn't work in cloud sessions); the person merges it.
Finally run `rail doctor` and make the one-time settings it lists."""


# In a cloud session the machine is nobody's own, and the person is usually away: the agent sets everything up and
# the person confirms it once, by merging the pull request.
INIT_TASK_CLOUD = """Rail is installed, and this project isn't set up for it yet: .rail/config.toml isn't on {base}.
This is a cloud session: the machine is yours to change. Set the project up yourself; the person confirms it all at
once by reading and merging one pull request. {profiles}Read the repository to learn its stack, then:
1. [commands] in .rail/config.toml:
   - `verify`: the whole project's checks: tests, lint, a secret scan over the branch's commits ($RAIL_BASE..HEAD;
     RAIL_BASE is set for every command) and, when a lockfile changes, a dependency scan for this stack. A monorepo
     makes it affected-aware.
   - `setup`: runs in each new ticket worktree (install dependencies).
   - `provision`: installs, as root, what verify and setup need that this machine lacks: scanners, CLIs, services.
     It runs once per cloud machine and on each CI runner. Install the tools now with the command you write there,
     and run verify until it passes.
2. ARCHITECTURE.md with a `## Areas` table: | Area | Paths | Holds |, one row per area. Paths are globs, separated
   by commas; Holds says what lives there in a bug reporter's words. Cover every directory at depth {depth}; hidden
   directories such as .rail and .claude need no row, and neither do files at the root. At most 150 lines.
3. [kinds] in .rail/config.toml: a person is asked only about changes a revert doesn't undo. Keep the defaults,
   and for each kind id list the paths that hold it in this project: schemas (data-shape), auth (access),
   infrastructure code (infrastructure), payment code (money), code that emails or pays real people
   (external-effect), and the files that set an agent's permissions, tools or spend (controls). A ticket that touches
   one is PERSON, so a person approves its contract and merges it. Every other ticket is AUTO and gets the reviewer
   before the engine merges it. [review] skip_paths lists paths whose changes need no reviewer, such as docs; leave
   it empty when unsure.
4. The [[rules]] in .rail/config.toml: keep, drop or add structure rules for this project.
5. [tools.NAME] in .rail/config.toml: one table for each thing the work reaches outside the repository (a service
   with a key, a CLI that signs in, an MCP server): `use`, one line the agents read; `env`, the names of the
   variables it needs, never a value; `probe`, a fast command that changes nothing and fails when the tool is out
   of reach; `ci = true` only for a test or dev key that a pull request's run may be given, with its line in
   .github/workflows/rail.yml.{tools} Leave it out when the work reaches nothing.
If the project already has its own agent workflow, hooks, guards, CI gates or repo map, leave them running and list
them in the pull request for the person to decide: keep, merge or retire.
Then commit what rail init added together with these changes to a new branch, push it, and open a pull request with
`gh api` (gh pr doesn't work in cloud sessions). In its description say what you chose and why, and list what only
the person can do, because a cloud session can't change a repository's settings:
- merge this pull request;
- import .rail/ruleset.json at Settings > Rules > Rulesets > New ruleset > Import a ruleset: it requires the
  rail check and a pull request on {base}, and allows squash merges only;
- in Settings > General > Pull Requests: allow squash merging with "Pull request title and description" as the
  default message, and turn on "Automatically delete head branches".
Finally run `rail doctor`. It prints the lines for the cloud environment's setup script: propose them with your
environment tool, so the person approves them once and every later session starts ready."""


INCLUDE = re.compile(r"^<!-- include (.+?) -->$", re.M)


def include(text):
    """A seed file's `<!-- include PAGE[#Heading...] -->` lines, replaced by that text of the framework's page: a
    skill carries what it would otherwise tell the agent to go and read. A heading is written as it stands, spaces
    and all."""
    from .docs import read_part

    def page(m):
        found = read_part(m.group(1), FRAMEWORK)
        if found is None:
            raise RailError(f"the seed includes {m.group(1)}, which isn't there")
        return found
    return INCLUDE.sub(page, text)


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


def _load_profile(name):
    with open(os.path.join(PROFILES, name, "profile.toml"), "rb") as f:
        return tomllib.load(f)


def detect(root):
    """The language profiles the tracked manifests mark: [{name, paths, dirs, manager, profile, type_check}]. A
    manifest at the root gives paths "**"; manifests only below it give the top-most folders that hold one, as
    "web/**" or "{a,b}/**". `dirs` are those folders ("" for the root), and `manager` is the profile's package
    manager whose lockfile is tracked in one of them, else its first one. type_check is None for a profile with no
    type_check_file, else whether one is tracked under its paths."""
    if not os.path.isdir(PROFILES):
        return []
    skip = set(_load_profile("common")["ignore"])
    tracked = [path for path in gitx.git(["ls-files", "-z"], root).stdout.split("\0")
               if path and not skip.intersection(path.split("/")[:-1])]
    found = []
    for name in sorted(os.listdir(PROFILES)):
        if name == "common" or not os.path.isfile(os.path.join(PROFILES, name, "profile.toml")):
            continue
        profile = _load_profile(name)
        folders = {os.path.dirname(path) for path in tracked if match_any(profile["manifests"], os.path.basename(path))}
        if not folders:
            continue
        top = sorted(f for f in folders if not any(f.startswith(other + "/") for other in folders))
        paths = "**" if "" in folders else f"{top[0]}/**" if len(top) == 1 else "{" + ",".join(top) + "}/**"
        type_check = None
        if profile.get("type_check_file"):
            type_check = any(os.path.basename(path) == profile["type_check_file"] and globmatch(paths, path)
                             for path in tracked)
        dirs = [""] if "" in folders else top
        managers = profile.get("managers") or []
        locked = [m for m in managers if any(os.path.join(d, m["lockfile"]).lstrip("/") in tracked for d in dirs)]
        found.append({"name": name, "paths": paths, "dirs": dirs, "profile": profile, "type_check": type_check,
                      "manager": (locked or managers[:1] or [None])[0]})
    return found


def default_parts(found, available=None):
    """(setup commands, verify parts, left out) for the profiles found. Each profile's setup and the parts of its
    verify run in each of its folders, then one secret scan over the branch's commits; a part named `types` is left
    out where type checking is off, and an `audit` runs only when the change touches the lockfile. A part is
    {profile, part, tool, run}. `available(tool)` says whether a part's tool may be used: parts it refuses are left
    out and named, which is how Rail's own tests run on a machine that lacks a scanner. With none, every part is
    kept."""
    def inside(folder, command):
        return f"(cd {shlex.quote(folder)} && {command})" if folder else command

    setup, parts, left = [], [], []
    for f in found:
        manager = f["manager"]
        if not manager:
            continue
        for folder in f["dirs"]:
            setup.append(inside(folder, manager["setup"]))
            for part in manager["verify"]:
                if part["part"] == "types" and f["type_check"] is False:
                    continue
                if available and not available(part["tool"]):
                    left.append(f"{f['name']} {part['part']} ({part['tool']})")
                    continue
                run = inside(folder, part["run"])
                if part["part"] == "audit":
                    lock = os.path.join(folder, manager["lockfile"])
                    run = f'{{ git diff --quiet "$RAIL_BASE"...HEAD -- {shlex.quote(lock)} || {run}; }}'
                parts.append({"profile": f["name"], "part": part["part"], "tool": part["tool"], "run": run})
    secrets = _load_profile("common").get("secrets")
    if found and secrets:
        if available and not available(secrets["tool"]):
            left.append(f"{secrets['part']} ({secrets['tool']})")
        else:
            parts.append({"profile": "common", "part": secrets["part"], "tool": secrets["tool"], "run": secrets["run"]})
    return setup, parts, left


def default_commands(found, available=None):
    """(setup, verify, left out): the commands a new config starts with, the parts joined with &&."""
    setup, parts, left = default_parts(found, available)
    return " && ".join(setup), " && ".join(part["run"] for part in parts), left


def toml_string(value):
    """A command as a TOML string: literal where it can be, so the command reads as it runs."""
    return f"'{value}'" if "'" not in value and "\n" not in value else json.dumps(value)


def _set_string(text, table, key, value):
    """The seed config's text with an empty string's value filled in, the line's comment kept."""
    start = text.index(f"\n[{table}]")
    found = re.compile(rf'^{key} = ""', re.M).search(text, start)
    if not found:
        raise RailError(f"the seed config has no empty {key} to fill in under [{table}]")
    return text[:found.start()] + f"{key} = {toml_string(value)}" + text[found.end():]


def _union(*lists):
    """The lists joined in order, each item once."""
    out = []
    for items in lists:
        out += [item for item in items if item not in out]
    return out


def _set_list(text, table, key, values):
    """The seed config's text with a list's value replaced, the line's comment kept. table None: a top-level key."""
    start = 0 if table is None else text.index(f"\n[{table}]")
    found = re.compile(rf"^{key} = \[[^\]]*\]", re.M).search(text, start)
    if not found:
        raise RailError(f"the seed config has no {key} to fill in" + (f" under [{table}]" if table else ""))
    return text[:found.start()] + f"{key} = {json.dumps(values)}" + text[found.end():]


def _toml_table(header, item, comment):
    lines = [f"[[{header}]]".ljust(42) + f"# {comment}"]
    lines += [f"{key} = {json.dumps(value)}" for key, value in item.items()]
    return "\n".join(lines) + "\n"


def with_profiles(text, found):
    """The seed config's text with what the profiles found add: migration paths, generated files left out of the
    size count, [tests] paths, each language's default setup and verify, a [[profiles]] entry each and their
    suppression-marker rules."""
    if not found:
        return text
    seed = tomllib.loads(text)
    profiles = [f["profile"] for f in found]
    text = _set_list(text, None, "migration_paths",
                     _union(seed["migration_paths"], *(p["migration_paths"] for p in profiles)))
    text = _set_list(text, "size", "exclude", _union(seed["size"]["exclude"], *(p["generated"] for p in profiles)))
    text = _set_list(text, "tests", "paths", _union(seed["tests"]["paths"], *(p["tests"] for p in profiles)))
    setup, verify, _ = default_commands(found)
    for key, command in (("setup", setup), ("verify", verify)):
        if command and not seed["commands"][key]:
            text = _set_string(text, "commands", key, command)
    tables = [_toml_table("profiles", {"name": f["name"], "paths": f["paths"]},
                          "written by rail init from the manifests it found (rail docs languages)") for f in found]
    tables += [_toml_table("rules", rule, f"from the {f['name']} profile")
               for f in found for rule in f["profile"]["rules"]]
    return text.rstrip("\n") + "\n\n" + "\n".join(tables)


FOUND = ("rail init found {found} and wrote each language's default `setup` and `verify` into [commands]. The"
         " repository's own commands win over a default: where a Makefile target, a package.json script or a CI step"
         " already runs a part (tests, lint, types, format), put that in the default's place, because it holds what the"
         " project knows. Where the repository has none, keep the default and say so in the pull request. Every tool"
         " verify names has to be on the machine that runs it.\n")


def found_line(config):
    """The init task's sentence on the language profiles the config names; "" when it names none."""
    profiles = config.get("profiles") or []
    if not profiles:
        return ""
    return FOUND.format(found=", ".join(f"{p['name']} ({p.get('paths') or '**'})" for p in profiles))


def _describe(found):
    words = []
    for f in found:
        note = f", no {f['profile']['type_check_file']}: type checking off" if f["type_check"] is False else ""
        words.append(f"{f['name']} ({f['paths']}{note})")
    return ", ".join(words)


def tracked_files(root):
    return [path for path in gitx.git(["ls-files", "-z"], root).stdout.split("\0") if path]


def unprofiled(files, config):
    """[(language, folder, manifest)]: the top-most folders holding a manifest that no [[profiles]] entry of its
    language covers, "" for the root, each with one such manifest's path. A manifest under a vendored folder, or one
    [init] other_manifests names, marks no language of the project's own."""
    entries, left_out = config.get("profiles") or [], (config.get("init") or {}).get("other_manifests") or []
    out = []
    for name, manifests in sorted(MANIFESTS.items()):
        paths = [e.get("paths") or "**" for e in entries if e.get("name") == name]
        bare = {}
        for path in files:
            if (match_any(manifests, os.path.basename(path)) and not set(VENDORED).intersection(path.split("/")[:-1])
                    and not match_any(paths, path) and not match_any(left_out, path)):
                bare.setdefault(os.path.dirname(path), path)
        out += [(name, folder, bare[folder]) for folder in sorted(bare)
                if not any(folder.startswith(above + "/") or (above == "" and folder) for above in bare)]
    return out


UNCOVERED = ("{what}: no [[profiles]] entry covers it, so its suppression rule, test paths, generated files and"
             " commands are not in .rail/config.toml. Run `rail init` here with the rail that install put on PATH: it"
             " prints what to add and writes nothing to the config. A manifest that marks no code of the project's"
             " own goes under [init] other_manifests")


def uncovered(bare):
    """One sentence on the manifests unprofiled() found, for doctor and the sweep."""
    return UNCOVERED.format(what="; ".join(f"{path} marks {name}" for name, _, path in bare))


def additions(found, config, files):
    """What a config that is there already lacks for the profiles found, as text for a person or a ticket to put
    into it: rail init never writes to a project's own config. "" when every manifest is covered."""
    bare, entries = unprofiled(files, config), config.get("profiles") or []
    blocks = []
    for f in found:
        folders = [folder for name, folder, _ in bare if name == f["name"]]
        if not folders:
            continue
        entry = next((e for e in entries if e.get("name") == f["name"]), None)
        profile = f["profile"]
        lines = [f"{f['name']} in {', '.join(folder or 'the root' for folder in folders)}:"]
        if entry:
            lines.append(f'- the {f["name"]} entry of [[profiles]]: paths = {json.dumps(f["paths"])}'
                         f' (it is {json.dumps(entry.get("paths") or "**")})')
        else:
            lines.append("- a new entry and its rules, at the end of the file:")
            lines.append(_toml_table("profiles", {"name": f["name"], "paths": f["paths"]},
                                     "from rail init (rail docs languages)").rstrip("\n"))
            lines += [_toml_table("rules", rule, f"from the {f['name']} profile").rstrip("\n") for rule in profile["rules"]]
            for label, have, want in (("migration_paths", config.get("migration_paths") or [], profile["migration_paths"]),
                                      ("[size] exclude", (config.get("size") or {}).get("exclude") or [], profile["generated"]),
                                      ("[tests] paths", (config.get("tests") or {}).get("paths") or [], profile["tests"])):
                new = [item for item in want if item not in have]
                if new:
                    lines.append(f"- {label} gains {', '.join(json.dumps(item) for item in new)}")
        setup, parts, _ = default_parts([dict(f, dirs=folders)])
        parts = [part for part in parts if part["profile"] != "common" or not entries]
        if setup:
            lines.append(f"- [commands] setup gains: {' && '.join(setup)}")
        if parts:
            lines.append(f"- [commands] verify gains: {' && '.join(part['run'] for part in parts)}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


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


SKILL_DIR = ".claude/skills"


def skill_dirs(root, asked=None):
    """The folders the skills are written to: `asked` (rail init --skills), else [init] skill_dirs of the project's
    config, else the default. Each is a path from the repository root."""
    dirs = list(asked or [])
    if not dirs:
        try:
            with open(os.path.join(root, ".rail", "config.toml"), "rb") as f:
                dirs = (tomllib.load(f).get("init") or {}).get("skill_dirs") or []
        except (OSError, tomllib.TOMLDecodeError):
            dirs = []
    dirs = [d.strip().strip("/") for d in dirs if isinstance(d, str) and d.strip().strip("/")] or [SKILL_DIR]
    bad = next((d for d in dirs if os.path.isabs(d) or d.startswith("/") or ".." in d.split("/")), None)
    if bad:
        raise RailError(f"a skill folder is a path inside the repository, from its root; got '{bad}'")
    return list(dict.fromkeys(dirs))


def with_skill_dirs(text, dirs):
    """The seed config's text for skill folders other than the default: [init] skill_dirs names them, and the
    [guides] pages that are skills are read from the first."""
    if dirs == [SKILL_DIR]:
        return text
    text = _set_list(text, "init", "skill_dirs", dirs)
    start = text.index("\n[guides]")
    end = text.find("\n[", start + 1)
    end = len(text) if end < 0 else end
    return text[:start] + text[start:end].replace(f'"{SKILL_DIR}/', f'"{dirs[0]}/') + text[end:]


def lacking(root, found):
    """The receipt's words on what the project's config lacks for the languages found; "" when it lacks nothing or
    can't be read."""
    try:
        with open(os.path.join(root, ".rail", "config.toml"), "rb") as f:
            config = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return ""
    text = additions(found, config, tracked_files(root))
    return ("" if not text else ". It lacks what follows, which is a change to .rail/config.toml for a person to"
            " approve; a manifest that marks no code of the project's own goes under [init] other_manifests instead:\n"
            + text)


def init(cwd, skills_to=None):
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

    found = detect(root)
    config_new = not os.path.exists(os.path.join(rail_dir, "config.toml"))
    if not found:
        step("profiles", False, "no tracked Python, TypeScript, Rust or Go manifest: nothing language-specific written")
    else:
        step("profiles", True, f"found {_describe(found)}; " + (
            "wrote each to .rail/config.toml with its default setup and verify, rules, migration paths, generated"
            " files and [tests] paths"
            if config_new else ".rail/config.toml was there already, so nothing was written to it" + lacking(root, found)))

    copies = {
        "config.toml": ".rail/config.toml",
        "tickets/TEMPLATE.md": ".rail/tickets/TEMPLATE.md",
        "rail.yml": ".github/workflows/rail.yml",
        "sources/weekly-review.md": ".rail/sources/weekly-review.md",  # a source: the week's merges read together
        "ruleset.json": ".rail/ruleset.json",  # for the person to import in GitHub: a session can't set it. It
                                               # names the default branch, so one file fits every repository
    }
    # The skills a person's session starts, as Claude Code skills. The engine's own pages for the briefs stay in
    # .rail/engine/guides; [guides] names both kinds.
    skills = os.path.join(seed, "skills")
    folders = skill_dirs(root, skills_to)
    skill_copies = [(f"skills/{name}/SKILL.md", f"{folder}/{name}/SKILL.md") for folder in folders
                    for name in sorted(os.listdir(skills)) if os.path.isfile(os.path.join(skills, name, "SKILL.md"))]
    packs = os.path.join(FRAMEWORK, "packs")
    for name in sorted(os.listdir(packs)) if os.path.isdir(packs) else []:
        dest = os.path.join(rail_dir, "packs", name)
        if os.path.exists(dest):
            step(f"pack {name}", False, f".rail/packs/{name} is there already")
        else:
            shutil.copytree(os.path.join(packs, name), dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            step(f"pack {name}", True, f"copied to .rail/packs/{name}")
    for src, dest in [*copies.items(), *skill_copies]:
        target = os.path.join(root, dest)
        if os.path.exists(target):
            step(dest, False, "the project has it already")
            continue
        with open(os.path.join(seed, src)) as f:
            text = f.read()
        if src == "config.toml":
            text = text.replace('base_branch = "main"', f'base_branch = "{_base_branch(root)}"', 1)
            text = with_skill_dirs(with_profiles(text, found), folders)
        text = include(text)
        _write(target, text)
        step(dest, True, "added")

    # GitHub folds a file marked linguist-generated in a pull request's diff, so a person reads what was written.
    from .rules import LOCKFILES
    try:
        with open(os.path.join(rail_dir, "config.toml"), "rb") as f:
            generated = [g for g in (tomllib.load(f).get("size") or {}).get("exclude") or [] if isinstance(g, str)]
    except (OSError, tomllib.TOMLDecodeError):
        generated = []
    attributes = os.path.join(root, ".gitattributes")
    had = open(attributes).read() if os.path.exists(attributes) else ""
    # A glob with braces has no spelling in .gitattributes; a lockfile stays in sight, since it says what is installed.
    new = [g for g in generated if "{" not in g and " " not in g and os.path.basename(g) not in LOCKFILES
           and not any(line.split()[:1] == [g] for line in had.splitlines())]
    if new:
        _write(attributes, (had.rstrip("\n") + "\n" if had.strip() else "")
               + "".join(f"{g} linguist-generated\n" for g in new))
        step(".gitattributes", True, f"marked as generated, so GitHub folds them in a diff: {', '.join(new)}")
    else:
        step(".gitattributes", False, "nothing in [size] exclude to mark as generated" if not generated
             else "the generated files are marked already")

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
    domains = _union(*(f["profile"]["domains"] for f in found))  # the package registries, for the agent's own installs
    ours["sandbox"]["network"]["allowedDomains"] += domains
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
            step(".claude/settings.json", True, "merged hooks, permissions, sandbox and Bash timeouts"
                 + (f"; the sandbox allows {', '.join(domains)}" if domains else ""))

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
