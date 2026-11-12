"""doc-lint (plan, section 13): ARCHITECTURE.md's ## Areas keeps matching the tree.

It skips a project until ARCHITECTURE.md exists. Hidden directories, such as .rail and .claude, hold
configuration rather than areas, so they need no row.
"""

import os
import re

from . import gitx
from .areas import parse_areas
from .util import globmatch

DOCS = ("ARCHITECTURE.md", "AGENTS.md")
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")

CAP = 150


def areas(project, ref):
    """What is wrong with the ## Areas table at `ref`: [problem]. Empty when it is fine or absent."""
    text = gitx.read_blobs([f"{ref}:ARCHITECTURE.md"], project.root).get(f"{ref}:ARCHITECTURE.md")
    if text is None:
        return []
    problems = []
    if len(text.splitlines()) > CAP:
        problems.append(f"ARCHITECTURE.md has {len(text.splitlines())} lines; keep it to {CAP} or fewer")
    rows = parse_areas(text)
    if not rows:
        return problems + ["ARCHITECTURE.md has no ## Areas table"]
    files = [f for f in gitx.git(["ls-tree", "-r", "-z", "--name-only", ref], project.root).stdout.split("\0") if f]
    globs = [g for row in rows for g in row["paths"]]
    for row in rows:
        for glob in row["paths"]:
            if not any(globmatch(glob, f) for f in files):
                problems.append(f"## Areas row '{row['area']}': {glob} matches no tracked file")
    dirs = _mapped_dirs(project, files)
    for d in sorted(dirs):
        if not any(globmatch(g, f) for g in globs for f in dirs[d]):
            problems.append(f"{d}/ is in no ## Areas row; add a row, or list it in [map] ignore")
    return problems


def _mapped_dirs(project, files):
    """{directory at [map] depth: its files}, leaving out hidden directories and [map] ignore."""
    depth = project.config["map"]["depth"]
    ignore = [i.rstrip("/") for i in project.config["map"]["ignore"]]  # "docs/" and "docs" mean the same
    dirs = {}
    for f in files:
        parts = f.split("/")
        if len(parts) <= depth or any(p.startswith(".") for p in parts[:depth]):
            continue
        d = "/".join(parts[:depth])
        if d in ignore or any(d.startswith(i + "/") for i in ignore):
            continue
        dirs.setdefault(d, []).append(f)
    return dirs


def _unfenced(text):
    """The text outside fenced code blocks, where # comments are not headings."""
    kept, fenced = [], False
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        elif not fenced:
            kept.append(line)
    return "\n".join(kept)


def _prose(text):
    """The text outside code, fenced or inline, where example links don't count."""
    return re.sub(r"`[^`]*`", "", _unfenced(text))


def _anchors(markdown):
    """The heading anchors GitHub makes, with -1, -2 on repeated headings."""
    found, seen = set(), {}
    for heading in re.findall(r"^#+\s+(.+)$", markdown, re.M):
        slug = _slug(heading)
        found.add(f"{slug}-{seen[slug]}" if slug in seen else slug)
        seen[slug] = seen.get(slug, 0) + 1
    return found


def _tracked(project, ref):
    return [f for f in gitx.git(["ls-tree", "-r", "-z", "--name-only", ref], project.root).stdout.split("\0") if f]


def _slug(heading):
    """The anchor GitHub gives a heading: a closing ## dropped, lower case, punctuation (backticks too) dropped,
    spaces to hyphens. Code in a heading keeps its text: `rail` next -> rail-next."""
    heading = re.sub(r"\s+#+\s*$", "", heading.strip())
    return re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")


def links(project, ref):
    """Relative links in ARCHITECTURE.md and AGENTS.md that point at no tracked path, or at no heading there."""
    files = _tracked(project, ref)
    dirs = {"/".join(f.split("/")[:i]) for f in files for i in range(1, f.count("/") + 1)}
    blobs = gitx.read_blobs([f"{ref}:{d}" for d in DOCS], project.root)
    problems = []
    for doc in DOCS:
        text = blobs.get(f"{ref}:{doc}")
        if text is None:
            continue
        for target in LINK.findall(_prose(text)):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
                continue  # a URL
            path, _, anchor = target.partition("#")
            if path.startswith("/"):  # GitHub resolves /x from the repository root
                path = os.path.normpath(path.lstrip("/"))
            else:
                path = os.path.normpath(os.path.join(os.path.dirname(doc), path)) if path else doc
            if path not in files and path not in dirs:
                problems.append(f"{doc} links to {target}, which isn't a tracked path")
                continue
            if anchor and path.endswith(".md") and path in files:
                body = gitx.read_blobs([f"{ref}:{path}"], project.root)[f"{ref}:{path}"] or ""
                if anchor not in _anchors(_unfenced(body)):
                    problems.append(f"{doc} links to {target}, and {path} has no such heading")
    return problems


def directories(project, ref):
    """A change that adds or removes a directory at [map] depth must update ARCHITECTURE.md (plan, section 13)."""
    def top(rev):
        return set(_mapped_dirs(project, _tracked(project, rev)))

    base = gitx.out(["merge-base", project.base_ref, ref], project.root)
    changed = sorted(top(ref) ^ top(base))
    touched = "ARCHITECTURE.md" in gitx.out(["diff", "--name-only", f"{base}...{ref}", "--", "ARCHITECTURE.md"],
                                             project.root).splitlines()
    if changed and not touched:
        return [f"this change adds or removes {', '.join(d + '/' for d in changed)}; update ## Areas in ARCHITECTURE.md"]
    return []


def lint(project, ref):
    """Every doc-lint problem at `ref`. Nothing until ARCHITECTURE.md exists."""
    if gitx.read_blobs([f"{ref}:ARCHITECTURE.md"], project.root).get(f"{ref}:ARCHITECTURE.md") is None:
        return []
    return areas(project, ref) + links(project, ref) + directories(project, ref)
