"""Git helpers. Everything the engine knows comes from git, so this module is the only one that runs it."""

import os
import subprocess
import tempfile

from . import util
from .util import RailError

_ENV = {"GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}


class GitError(RailError):
    def __init__(self, args, result):
        detail = (result.stderr or result.stdout or "").strip()
        super().__init__(f"git {' '.join(args)} failed: {detail}", code="GIT")
        self.result = result


# One command derives a ticket's state several times, and each derivation asks git the same questions. The answers
# to questions about refs and objects are kept until something can have changed them: any other git command, or a
# shell command. Questions about a working tree's files (status, a diff against the files) are always asked again.
_READS = {"rev-parse", "for-each-ref", "log", "ls-tree", "merge-base", "symbolic-ref", "check-attr", "patch-id",
          "remote", "cat-file"}
_answers = {}


def forget():
    _answers.clear()


util.AFTER_SHELL.append(forget)


def _reads_only(args):
    """Whether a git command only reads refs and objects, so its answer holds until the repository changes."""
    sub = args[0] if args else ""
    if sub in _READS:
        return sub != "remote" or len(args) == 1
    if sub == "config":
        return "--get" in args
    if sub == "worktree":
        return args[1:2] == ["list"]
    if sub == "diff":
        return any("..." in a for a in args)  # between two refs; without them it reads the working tree's files
    return False


def git(args, cwd, check=True, input=None, env=None):
    key = None
    if _reads_only(args) and not env:
        key = (tuple(args), cwd, input)
        if key in _answers:
            result = _answers[key]
            if check and result.returncode != 0:
                raise GitError(args, result)
            return result
    else:
        forget()
    full_env = dict(os.environ)
    full_env.update(_ENV)
    full_env.update(env or {})
    # core.quotePath=false: git would print a non-ASCII path such as café/x as "caf\303\251/x".
    result = subprocess.run(
        ["git", "-c", "core.quotePath=false", *args], cwd=cwd, input=input, capture_output=True, text=True,
        env=full_env,
    )
    if key is not None:
        _answers[key] = result
    if check and result.returncode != 0:
        raise GitError(args, result)
    return result


def out(args, cwd):
    return git(args, cwd).stdout.strip()


def ok(args, cwd):
    return git(args, cwd, check=False).returncode == 0


def rev(ref, cwd):
    """The commit a ref names, or None."""
    result = git(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], cwd, check=False)
    return result.stdout.strip() or None


def read_blobs(specs, cwd):
    """Read many 'ref:path' blobs in one call. Missing ones come back as None."""
    if not specs:
        return {}
    key = ("cat-file --batch", tuple(specs), cwd)
    if key in _answers:
        return dict(_answers[key])
    result = subprocess.run(
        ["git", "cat-file", "--batch"], cwd=cwd, input="\n".join(specs).encode() + b"\n",
        capture_output=True, check=True,
    )
    data, pos, found = result.stdout, 0, {}
    for spec in specs:
        end = data.index(b"\n", pos)
        header = data[pos:end].decode()
        pos = end + 1
        if header.endswith(" missing") or header.endswith(" ambiguous"):
            found[spec] = None
            continue
        size = int(header.split()[2])
        found[spec] = data[pos:pos + size].decode("utf-8", errors="replace")
        pos += size + 1
    _answers[key] = dict(found)
    return found


def commit_files(cwd, parent, files, message):
    """Make a commit on top of `parent` (or a root commit) that writes `files` ({path: text}).

    It uses a temporary index, so no checkout is touched. Returns the new commit.
    """
    fd, index = tempfile.mkstemp(prefix="rail-index-")
    os.close(fd)
    os.unlink(index)
    env = {"GIT_INDEX_FILE": index}
    try:
        if parent:
            git(["read-tree", parent], cwd, env=env)
        for path, text in files.items():
            blob = git(["hash-object", "-w", "--stdin"], cwd, input=text).stdout.strip()
            git(["update-index", "--add", "--cacheinfo", f"100644,{blob},{path}"], cwd, env=env)
        tree = git(["write-tree"], cwd, env=env).stdout.strip()
        args = ["commit-tree", tree, "-m", message] + (["-p", parent] if parent else [])
        return git(args, cwd).stdout.strip()
    finally:
        if os.path.exists(index):
            os.unlink(index)


def update_ref(cwd, ref, new, old):
    """Move a ref only if it still points at `old` (None: only if it doesn't exist). False if it moved."""
    return git(["update-ref", ref, new, old or ""], cwd, check=False).returncode == 0


def worktrees(cwd):
    """{branch name: worktree path} for every worktree with a branch checked out."""
    found, path = {}, None
    for line in out(["worktree", "list", "--porcelain"], cwd).splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line.startswith("branch refs/heads/"):
            found[line[len("branch refs/heads/"):]] = path
    return found


def dirty(cwd, exclude=()):
    """Uncommitted paths in a worktree, untracked files included. A staged rename is both of its names: the old
    one is a deletion."""
    spec = ["--", "."] + [f":(exclude){p}" for p in exclude]
    lines = git(["status", "--porcelain", "--untracked-files=all", *spec], cwd).stdout.splitlines()
    return [name.strip('"') for line in lines for name in line[3:].split(" -> ")]


def stage(cwd, paths):
    """git add -A for these paths. A deletion that is staged already (git rm, the old name of a git mv) is passed
    over: it is on disk and in the index no more, and git stops at a path it can't find."""
    tracked = set(out(["ls-files", "--cached", "-z", "--", *paths], cwd).split("\0"))
    left = [p for p in paths if p in tracked or os.path.lexists(os.path.join(cwd, p))]
    if left:
        git(["add", "-A", "--", *left], cwd)


def push(cwd, remote, refspec, force_with_lease=None):
    """Push one refspec. Returns 'ok', 'rejected' (someone got there first) or 'unavailable'."""
    args = ["push", "--porcelain", remote, refspec]
    if force_with_lease is not None:
        args.insert(1, f"--force-with-lease={force_with_lease}")
    result = git(args, cwd, check=False)
    if result.returncode == 0:
        return "ok"
    for line in result.stdout.splitlines():
        if line.startswith("!\t"):
            return "rejected"
    return "unavailable"


def fetch(cwd, remote):
    return git(["fetch", "--quiet", "--prune", remote], cwd, check=False).returncode == 0
