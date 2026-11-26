"""A revert as a ticket (rail docs loop).

A ticket with `kind = "revert"` and `reverts = "NN"` takes ticket NN's change out again. Its change is the reverse
of NN's squash commit on the project's own files; tickets and journals are left alone, since a whole `git revert`
would delete another ticket's file and journal. It has no Check: lines: ship compares the change with that reverse.
The label rail:revert on a merged pull request files such a ticket.
"""

import json
import os
import re
import tempfile

from . import gitx
from .project import PRODUCT_SPEC

LABEL = "rail:revert"
RESTORE = "git diff --binary {sha}^ {sha} -- . ':(exclude).rail/tickets' ':(exclude).rail/journal' | git apply -R"


def target(project, ticket, tickets):
    """(the reverted ticket's id, its squash commit on the base branch or None) for a revert ticket; None for any
    other ticket."""
    if not ticket or ticket.get("kind") != "revert":
        return None
    nn = str(ticket.get("reverts") or "")
    reverted = tickets.get(nn)
    return nn, (reverted.merged if reverted else None)


def _diff(project, sha, *flags):
    return gitx.git(["diff", *flags, f"{sha}^", sha, *PRODUCT_SPEC], project.root).stdout


def files(project, sha):
    """The project's files the commit changed; a rename counts as both its paths."""
    return _diff(project, sha, "--name-only", "--no-renames").splitlines()


def _patch_id(project, diff):
    found = gitx.git(["patch-id", "--stable"], project.root, input=diff).stdout.split() if diff else []
    return found[0] if found else ""


def exact(project, sha):
    """The patch id of the commit's change reversed, as Project.patch_id counts a branch's change."""
    # From the commit back to its parent, not `diff -R`: -R swaps the a/ and b/ of the file names, and with them the id.
    return _patch_id(project, gitx.git(["diff", "-U0", sha, f"{sha}^", *PRODUCT_SPEC], project.root).stdout)


def in_worktree(project, cwd):
    """The patch id of everything a worktree holds beyond the base branch, uncommitted work included."""
    base = gitx.git(["merge-base", project.base_ref, "HEAD"], cwd, check=False).stdout.strip()
    if not base:
        return ""
    gitx.forget()  # the files may have changed since this command last asked
    return _patch_id(project, gitx.git(["diff", "-U0", base, *PRODUCT_SPEC], cwd).stdout)


def applies(project, sha, ref):
    """Whether the commit's change reversed still applies to the tree at `ref`. Nothing is touched: the patch is
    tried on an index of its own."""
    patch = _diff(project, sha, "--binary")
    if not patch:
        return False
    with tempfile.TemporaryDirectory(prefix="rail-revert-") as tmp:
        env = {"GIT_INDEX_FILE": os.path.join(tmp, "index")}
        if gitx.git(["read-tree", ref], project.root, check=False, env=env).returncode != 0:
            return False
        return gitx.git(["apply", "--cached", "-R", "--check", "-"], project.root, check=False, input=patch,
                        env=env).returncode == 0


def apply(project, sha, cwd):
    """Put the commit's change reversed into the worktree's files, all of it or nothing. False when it doesn't
    apply."""
    patch = _diff(project, sha, "--binary")
    return bool(patch) and gitx.git(["apply", "-R", "-"], cwd, check=False, input=patch).returncode == 0


def failed_verify(events, patch_id):
    """Whether verify has failed on this very patch: the exact reverse was tried, and the project doesn't hold with it."""
    return any(e.get("event") == "step" and e.get("step") == "verify" and e.get("result") == "fail"
               and e.get("patch_id") == patch_id for e in events)


def check(project, t, tickets, patch_id, ref):
    """The built-in check of a revert ticket at ship, in place of Check: lines. Returns (passed, detail, output).

    The change has to be the exact reverse of the reverted ticket's change. A revert made by hand passes in two
    cases, and the reviewer reads it like any change: the exact reverse no longer applies, because later tickets
    changed the same lines; or it applies and verify failed on it, because later work depends on what it removes."""
    nn, sha = target(project, t.ticket, tickets)
    if not sha:
        return False, f"ticket {nn} has no merge commit to reverse", (
            f"This ticket reverts ticket {nn}, and no commit on {project.base} merged a ticket {nn}. `reverts` names"
            " the id of a merged ticket.")
    short = sha[:12]
    wanted = exact(project, sha)
    if patch_id and patch_id == wanted:
        return True, f"the reverse of ticket {nn}'s change ({short})", ""
    base = gitx.git(["merge-base", project.base_ref, ref], project.root, check=False).stdout.strip()
    if not applies(project, sha, base):
        return True, f"undone by hand: the reverse of ticket {nn}'s change ({short}) no longer applies", ""
    if failed_verify(t.events, wanted):
        return True, f"undone by hand: verify failed on the exact reverse of ticket {nn}'s change ({short})", ""
    return False, f"not the reverse of ticket {nn}'s change ({short})", (
        f"This ticket reverts ticket {nn}, and the reverse of its change ({short}) still applies as it is. The change"
        " here is something else. Put the exact reverse in its place and ship that:\n"
        f"  git restore --source={base[:12]} --staged --worktree -- .\n  {RESTORE.format(sha=short)}\n"
        "If verify then fails, later work depends on what that change removes: adapt the revert by hand, inside"
        " scope_paths, and ship again. A revert made by hand is accepted once verify has failed on the exact one.")


def text(nn, title, sha, paths, source, said):
    """The revert ticket for ticket NN. `source` is the number of the pull request a person labelled rail:revert,
    with `said` what people wrote there; or the external id of another source, with `said` its one-line reason."""
    labelled = isinstance(source, int)
    external = f"revert#{source}" if labelled else source
    front = ["+++", f"title = {json.dumps(f'Revert ticket {nn}: {title}')}", 'tier = "AUTO"', 'kind = "revert"',
             f"reverts = {json.dumps(nn)}", f"caused_by = {json.dumps(nn)}", f"external_id = {json.dumps(external)}",
             f"scope_paths = {json.dumps(paths)}", "+++", ""]
    why = [f"A person put the label {LABEL} on pull request #{source}, which merged ticket {nn} ({title}) as commit"
           f" {sha[:12]}. This ticket takes that change out again."] if labelled else [said]
    if said and labelled:
        why += ["", "What people who can push said on that pull request after the merge:", ""]
        why += ["> " + line for comment in said for line in (comment.splitlines() + [""])][:-1]
    done = [f"The change is the reverse of ticket {nn}'s change ({sha[:12]}) on the project's own files. The engine"
            " checks that at ship, and verify runs as always."]
    return "\n".join(front + ["## Why", *why, "", "## Done Contract", *done, ""])


def said_after_merge(comments, merged_at, trusted, mark, strip):
    """The comments of people who can push, written after the merge, with what GitHub hides taken out."""
    found = [strip(c["body"])[0].strip() for c in comments
             if c.get("body") and c.get("author_association") in trusted and mark not in c["body"]
             and (c.get("created_at") or "") >= (merged_at or "")]
    return [s for s in found if s]


def branch_ticket(ref):
    """The ticket id a pull request's head branch names, or None."""
    found = re.match(r"^(\d+)-", ref or "")
    return found.group(1) if found else None
