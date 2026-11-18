"""`rail adopt`: work that already exists on a branch with no ticket comes onto the railroad.

The first step reads the branch and hands the agent a ticket draft; the second runs the draft's checks on the base
and on the branch, then files the ticket with the branch's commits on it. The orchestration is in cli.cmd_adopt.
"""

import os
import re
import tempfile

from . import gitx, rules, steps
from .project import PRODUCT_SPEC
from .state import raised_tier
from .util import RailError, match_any, run_shell, tail

SECTIONS = ("Why", "Done Contract", "Out of scope", "Assumptions", "Look at")


def current_branch(cwd):
    head = gitx.git(["rev-parse", "--abbrev-ref", "HEAD"], cwd, check=False).stdout.strip()
    return None if head in ("", "HEAD") else head


def resolve(project, tickets, branch):
    """The branch's head commit, or a RailError that says why it can't be adopted. A branch only on the remote
    will do: the engine never needs the adopted branch pushed."""
    cwd = os.getcwd()
    here = current_branch(cwd)
    if not branch:
        branch = here
        if not branch:
            raise RailError("this checkout is on no branch: name the branch, rail adopt BRANCH", code="NO_BRANCH")
    head = gitx.rev(f"refs/heads/{branch}", project.root) or (
        project.remote and gitx.rev(f"refs/remotes/{project.remote}/{branch}", project.root))
    if not head:
        raise RailError(f"there is no branch '{branch}'", code="NO_BRANCH")
    if branch == project.base:
        raise RailError(f"'{branch}' is the base branch: adopt a branch with work on it", code="NOT_ADOPTABLE")
    owner = next((t.id for t in tickets.values() if branch in (t.branch, t.remote_branch)), None)
    if owner:
        raise RailError(f"'{branch}' is ticket {owner}'s own branch: it is on the rail already", code="NOT_ADOPTABLE")
    owner = next((t.id for t in tickets.values() if (t.last("adopted") or {}).get("branch") == branch
                  and t.branch and not t.merged and not t.last("dropped") and not t.dropped_mark), None)
    if owner:
        raise RailError(f"ticket {owner} adopted '{branch}' already: rail next --ticket {owner}", code="NOT_ADOPTABLE")
    if gitx.out(["rev-list", "--count", f"{project.base_ref}..{head}"], project.root) == "0":
        raise RailError(f"'{branch}' has no commits beyond {project.base}: there is no work to adopt", code="NO_COMMITS")
    if not project.changed_files(head):
        raise RailError(f"the commits on '{branch}' change no file against {project.base}: there is no work to adopt",
                        code="NO_COMMITS")
    if branch == here and gitx.dirty(cwd):
        raise RailError(f"'{branch}' is checked out here with uncommitted changes. Only committed work can be adopted:"
                        " commit it (or stash what isn't part of it), then run rail adopt again.", code="UNCOMMITTED")
    return branch, head


def files(project, head):
    """[(path, added, deleted)] for each product file the branch changes against the base."""
    rows = []
    numstat = gitx.out(["diff", "--numstat", "--no-color", f"{project.base_ref}...{head}", *PRODUCT_SPEC], project.root)
    for line in numstat.splitlines():
        added, deleted, path = line.split("\t", 2)
        rows.append((path, int(added) if added.isdigit() else 0, int(deleted) if deleted.isdigit() else 0))
    return rows


def tier(project, changed, size):
    """The tier the branch's paths and size give, and why."""
    needed, reason = raised_tier(project, changed)
    if needed == "PERSON":
        hits = [p for p in changed if match_any(project.config[reason], p)]
        return "PERSON", f"it changes {', '.join(hits[:5])}, on {reason}"
    cap = project.config["size"]["cap"]
    if rules.size_tier(project, "AUTO", size) == "PERSON":
        # As for any AUTO ticket, its first ship offers a split before a person has to merge it.
        return "AUTO", (f"no changed file is on person_paths or migration_paths; at {size} lines it is over [size]"
                        f" cap of {cap}, so its first ship offers a split, and it becomes PERSON when the split isn't"
                        " taken")
    return "AUTO", f"no changed file is on person_paths or migration_paths, and {size} lines are within [size] cap"


def scope(project, head, changed):
    """scope_paths for the changed files: a directory becomes DIR/** only when every file under it is one the branch
    changes, so the glob lets the work reach nothing it didn't touch, and only when that saves a line."""
    tracked = gitx.out(["ls-tree", "-r", "--name-only", head], project.root).splitlines()
    changed_set, found = set(changed), []
    for path in sorted(changed):
        if match_any(found, path):
            continue
        parts, glob = path.split("/"), path
        for i in range(1, len(parts)):
            folder = "/".join(parts[:i]) + "/"
            mine = [p for p in changed if p.startswith(folder)]
            if len(mine) > 1 and all(p in changed_set for p in tracked if p.startswith(folder)):
                glob = folder + "**"
                break
        found.append(glob)
    return found


def draft(project, tier_, scope_paths):
    """The ticket draft: the front matter filled in, the template's sections empty."""
    spec = f"{project.base_ref}:.rail/tickets/TEMPLATE.md"
    text = gitx.read_blobs([spec], project.root).get(spec) or ""
    sections = re.findall(r"^## (.+?)\s*$", text, re.M) or list(SECTIONS)
    scope_list = ", ".join(f'"{p}"' for p in scope_paths)
    lines = ["+++", 'title = ""', f'tier = "{tier_}"', f"scope_paths = [{scope_list}]", "+++", ""]
    for name in sections:
        lines += [f"## {name}", ""]
    return "\n".join(lines)


def brief(project, branch, head, rows, size, tier_, why, path):
    cap = project.config["size"]["cap"]
    log = gitx.out(["log", "--format=- %h %s%n%w(0,2,2)%b", f"{project.base_ref}..{head}"], project.root)
    listing = "\n".join(f"- {p} (+{a} -{d})" for p, a, d in rows)
    return "\n".join([
        f"Adopt branch {branch} ({head[:12]}): its work becomes a ticket, with the checks, the review and the merge"
        " rules of any other. Nothing is created yet.", "",
        f"Changed files, against {project.base}:", listing,
        f"Size: {size} changed lines; [size] cap is {cap}.",
        f"Tier: {tier_}, because {why}.", "",
        "Commits:", tail(log, 40), "",
        f"The engine wrote a ticket draft to {path}, outside the repository: scope_paths from the changed files and"
        " the tier. Fill it in there:",
        f"1. Read the diff: git diff {project.base}...{branch}",
        "2. Write the title, as an imperative.",
        "3. Write ## Why and ## Out of scope. They come from the person: when the commit messages don't say why the"
        " work was done, ask the person for the intent in one question. When no person is here, write what the"
        " commit messages say and add an ASSUMED: row under ## Assumptions that says so.",
        "4. Under ## Done Contract, write one '- Check: `command`' line for each behaviour the branch adds or"
        f" changes: a command that fails on {project.base} and passes on {branch}. The engine runs each one on both"
        " before it files the ticket, and refuses one that doesn't.",
        f"5. Run: rail adopt {branch} {path}",
    ])


def write_draft(branch, text):
    fd, path = tempfile.mkstemp(prefix=f"rail-adopt-{re.sub(r'[^A-Za-z0-9]+', '-', branch).strip('-')[:40]}-",
                                suffix=".md")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    return path


def gate(project, commands, base_tip, head, run):
    """Run every check on the base and on the branch, each in a throwaway worktree after setup. Returns
    (base results, branch results), or None when setup failed in one of them (run says where)."""
    found = []
    for name, commit in (("base", base_tip), ("branch", head)):
        with steps.scratch(project, commit) as path:
            command = project.config["commands"]["setup"]
            if command:
                code, output, ms = run_shell(command, path, {"RAIL_TICKET": "", "RAIL_BASE": project.base_ref},
                                             project.config["commands"]["timeout_secs"])
                if code != 0:
                    detail = "timeout" if code is None else f"exit {code}"
                    run.steps.append({"step": "setup", "status": "ran", "result": "fail",
                                      "detail": f"on the {name}: {detail}"})
                    run.failure = ("setup", f"setup failed on the {name} ({commit[:12]}), so the checks couldn't"
                                            f" run there:\n$ {command}\n{tail(output)}")
                    return None
            found.append(steps.run_checks(project, commands, path, ""))
    return found


def refusal(project, branch, base_results, branch_results):
    """Why the checks don't show the work, check by check, or None when each is red on the base and green on the
    branch."""
    rows, bad = [], False
    for before, after in zip(base_results, branch_results):
        shown = before["result"] == "red" and after["result"] == "green"
        bad = bad or not shown
        rows.append(f"- {'ok' if shown else 'NO'}: `{before['command']}`: {before['result']} on {project.base},"
                    f" {after['result']} on {branch}")
    if not bad:
        return None
    return "\n".join([
        f"The ticket was not filed, and nothing was created. Each Check: line must fail on {project.base} and pass"
        f" on {branch}:", *rows, "",
        f"A check that is green on {project.base} can't show the work was done, and one that isn't green on {branch}"
        " isn't met. A check that could not run or timed out on the base counts as not red: it showed nothing there.",
        "Fix the checks in the draft, then run rail adopt again.",
    ])
