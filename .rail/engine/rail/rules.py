"""Structure rules on added lines and files and the size count."""

import os
import re

from . import gitx
from .project import PRODUCT_SPEC
from .util import globmatch, match_any

LOCKFILES = {
    "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb", "bun.lock",
    "poetry.lock", "uv.lock", "Pipfile.lock", "pdm.lock", "Cargo.lock", "go.sum", "Gemfile.lock",
    "composer.lock", "mix.lock", "pubspec.lock", "Package.resolved", "flake.lock",
}


GO_GENERATED = re.compile(r"^// Code generated .* DO NOT EDIT\.$")


def _go_generated(text):
    """Whether a Go file says it is generated: the comment Go's own tools read, on a line of its own before the
    `package` line."""
    for line in (text or "").splitlines():
        if GO_GENERATED.match(line):
            return True
        if line.startswith("package "):
            return False
    return False


def _go_texts(project, paths, ref, cwd):
    """{path: text} of the changed Go files: as the ref or the worktree has them, and a deleted one as the base does."""
    if not paths:
        return {}
    texts = {}
    if ref:
        blobs = gitx.read_blobs([f"{ref}:{p}" for p in paths], cwd)
        texts = {p: blobs.get(f"{ref}:{p}") for p in paths}
    else:
        for p in paths:
            try:
                with open(os.path.join(cwd, p), encoding="utf-8", errors="replace") as f:
                    texts[p] = f.read()
            except OSError:
                texts[p] = None
    gone = [p for p in paths if texts[p] is None]
    base = gitx.read_blobs([f"{project.base_ref}:{p}" for p in gone], cwd)
    texts.update({p: base.get(f"{project.base_ref}:{p}") for p in gone})
    return texts


def _diff_range(project, ref, cwd):
    """With no ref: from the merge base of the checkout in `cwd`, which is a ticket's worktree, not the project's
    root, whose own branch may be behind the base."""
    return [f"{project.base_ref}...{ref}"] if ref else [gitx.out(["merge-base", project.base_ref, "HEAD"], cwd)]


def added(project, ref, cwd=None):
    """{path: [added lines]} and the files the change adds. --no-color, so color.ui=always can't hide a line."""
    cwd = cwd or project.root
    diff = gitx.out(["diff", "-U0", "--no-color", "--no-ext-diff", *_diff_range(project, ref, cwd), *PRODUCT_SPEC], cwd)
    lines, path = {}, None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
            if path:
                lines.setdefault(path, [])
        elif line.startswith("+") and path is not None:
            lines[path].append(line[1:])
    new_files = gitx.out(["diff", "--name-only", "--diff-filter=A", "--no-color", *_diff_range(project, ref, cwd),
                          *PRODUCT_SPEC], cwd).splitlines()
    return lines, new_files


def violations(project, ref, cwd=None):
    """[(rule, path, what)] for every structure rule an added line or file breaks. Old code never fails."""
    found = []
    if not project.config["rules"]:
        return found
    lines, new_files = added(project, ref, cwd)
    for rule in project.config["rules"]:
        if rule.get("flag"):
            continue  # a flag rule fails nothing: its matches go on the pull request's "Read these" list
        files, allow = rule.get("files", "**"), rule.get("allow", [])
        for path, added_lines in lines.items():
            if not globmatch(files, path) or match_any(allow, path):
                continue
            for text in added_lines:
                hit = next((word for word in rule.get("forbid", []) if word in text), None)
                if hit:
                    found.append((rule, path, f"adds '{hit}': {text.strip()[:120]}"))
        if rule.get("only_in"):
            for path in new_files:
                if globmatch(files, path) and not match_any(allow, path) and not globmatch(rule["only_in"], path):
                    found.append((rule, path, f"is a new file outside {rule['only_in']}"))
    return found


def size(project, ref=None, cwd=None):
    """Changed lines, added plus deleted. Renames count only their edits and binary files count
    zero; files marked linguist-generated or -diff, lockfiles, [size] exclude and Go files that carry the
    generated-code comment before their `package` line are left out.

    With no ref, it counts the worktree in `cwd` against the merge base, uncommitted changes included.
    Returns (count, excluded paths).
    """
    cwd = cwd or project.root
    numstat = gitx.git(["diff", "--numstat", "-M", "-z", "--no-color", *_diff_range(project, ref, cwd), *PRODUCT_SPEC],
                       cwd).stdout
    tokens, entries, i = numstat.split("\0"), [], 0
    while i < len(tokens):
        if not tokens[i]:
            i += 1
            continue
        added_n, deleted_n, path = tokens[i].split("\t", 2)
        if path == "":  # a rename: the old and new paths follow
            path = tokens[i + 2]
            i += 3
        else:
            i += 1
        entries.append((path, int(added_n) if added_n.isdigit() else 0, int(deleted_n) if deleted_n.isdigit() else 0))
    if not entries:
        return 0, []
    attrs = gitx.git(["check-attr", "-z", "--stdin", "linguist-generated", "diff"], cwd,
                     input="\0".join(p for p, _, _ in entries) + "\0").stdout.split("\0")
    generated = set()
    for j in range(0, len(attrs) - 2, 3):
        path, attr, value = attrs[j], attrs[j + 1], attrs[j + 2]
        if (attr == "linguist-generated" and value in ("set", "true")) or (attr == "diff" and value == "unset"):
            generated.add(path)
    total, excluded, kept = 0, [], []
    for path, added_n, deleted_n in entries:
        if path in generated or os.path.basename(path) in LOCKFILES or match_any(project.config["size"]["exclude"], path):
            excluded.append(path)
        else:
            kept.append((path, added_n + deleted_n))
    go = _go_texts(project, [path for path, _ in kept if path.endswith(".go")], ref, cwd)
    for path, lines in kept:
        if _go_generated(go.get(path)):
            excluded.append(path)
        else:
            total += lines
    return total, excluded
