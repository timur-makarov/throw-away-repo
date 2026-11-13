"""`context`: the `## Areas` rows of ARCHITECTURE.md that match a scope, and a directory digest."""

import re
from collections import Counter

from . import gitx
from .util import globs_overlap

DIGEST_LINES = 40


def parse_areas(text):
    """Rows of the table under '## Areas': [{'area', 'paths', 'holds'}]."""
    rows, inside = [], False
    for line in (text or "").splitlines():
        if line.startswith("## "):
            inside = line.strip() == "## Areas"
            continue
        if not inside or not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0].lower() == "area" or set(cells[0]) <= set("-: "):
            continue
        paths = [p for p in re.split(r"[,\s]+", cells[1].replace("`", "")) if p]
        rows.append({"area": cells[0], "paths": paths, "holds": cells[2]})
    return rows


def matching(rows, scope):
    return [r for r in rows if any(globs_overlap(p, s) for p in r["paths"] for s in scope)]


def digest(files, limit=DIGEST_LINES):
    """Directories with their file counts: top level first, then one level down while it fits."""
    top, second = Counter(), Counter()
    root_files = 0
    for path in files:
        parts = path.split("/")
        if len(parts) == 1:
            root_files += 1
            continue
        top[parts[0]] += 1
        if len(parts) > 2:
            second[(parts[0], parts[1])] += 1
    lines = [f"./ ({root_files} files)"] if root_files else []
    for name in sorted(top):
        lines.append(f"{name}/ ({top[name]} files)")
    budget = limit - len(lines)
    children = {}
    for (parent, child), count in second.items():
        children.setdefault(parent, []).append((child, count))
    out = []
    for line in lines:
        out.append(line)
        name = line.split("/")[0]
        for child, count in sorted(children.get(name, [])):
            if budget <= 0:
                break
            out.append(f"  {name}/{child}/ ({count} files)")
            budget -= 1
    return "\n".join(out[:limit])


def context(project, ref, scope=None):
    text = gitx.read_blobs([f"{ref}:ARCHITECTURE.md"], project.root)[f"{ref}:ARCHITECTURE.md"]
    rows = parse_areas(text)
    files = gitx.out(["ls-tree", "-r", "--name-only", ref], project.root).splitlines()
    return {
        "areas": matching(rows, scope) if scope is not None else rows,
        "architecture": text is not None,
        "digest": digest(files),
    }
