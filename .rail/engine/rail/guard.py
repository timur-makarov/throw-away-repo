"""The guard hook (plan, section 15): what depends on a flag or a refspec anywhere in a Bash command.

Guards prevent mistakes; they are not a boundary. Permission rules in .claude/settings.json cover what a rule
can express, and this hook covers the rest.
"""

import os
import re
import shlex

WRAPPERS = {"sudo", "env", "command", "exec", "time", "nohup", "nice"}
SEPARATORS = {";", "&&", "||", "|", "&", "|&"}


def pipelines(line, unwrap=True):
    """Each line's pipelines, as lists of simple commands (word lists). ;, &&, || and & end a pipeline; | joins one.
    With unwrap, `sudo`, `env`, VAR=value and the like are dropped from the front of each command."""
    keep = _unwrap if unwrap else (lambda words: words)
    found = []
    for part in line.splitlines():
        lexer = shlex.shlex(part, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        try:
            tokens = list(lexer)
        except ValueError:  # an unclosed quote: judge the words we have
            tokens = part.split()
        pipeline, words = [], []
        for token in tokens:
            if token in ("|", "|&"):
                pipeline.append(keep(words))
                words = []
            elif token in SEPARATORS:
                pipeline.append(keep(words))
                found.append(pipeline)
                pipeline, words = [], []
            elif not set(token) <= set("()"):
                words.append(token)
        pipeline.append(keep(words))
        found.append(pipeline)
    return [[words for words in pipeline if words] for pipeline in found]


def commands(line):
    """The simple commands in a command line, as word lists."""
    return [words for pipeline in pipelines(line) for words in pipeline]


def _unwrap(words):
    """Drop `sudo -E`, `env`, VAR=value and the like, so `sudo git push -f` is still a push."""
    while words and (words[0] in WRAPPERS or ("=" in words[0] and not words[0].startswith("-"))):
        words = words[1:]
        while words and words[0].startswith("-"):  # the wrapper's own options, such as sudo -E
            words = words[1:]
    return words


def _git(words):
    """(subcommand, its arguments) for a git command, skipping git's own options such as -C path."""
    i = 1
    while i < len(words) and words[i].startswith("-"):
        i += 2 if words[i] in ("-C", "-c", "--git-dir", "--work-tree") else 1
    return (words[i], words[i + 1:]) if i < len(words) else (None, [])


# Options that take a value: their value is not a flag or a positional argument.
VALUED = {
    "commit": {"-m", "-F", "-c", "-C", "-t", "--message", "--file", "--template", "--author", "--date"},
    "push": {"-o", "--push-option", "--repo", "--receive-pack", "--exec"},
}


def _short_flags(args, sub):
    """The single-letter flags in args. A letter that takes a value ends its group: -m"now" is -m, not -n."""
    letters = []
    for a in args:
        if not a.startswith("-") or a.startswith("--"):
            continue
        for ch in a[1:]:
            letters.append(ch)
            if f"-{ch}" in VALUED.get(sub, ()):
                break
    return "".join(letters)


def _positional(args, sub):
    """Arguments that are not options or option values."""
    found, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a.startswith("-"):
            skip = a in VALUED.get(sub, ())
        else:
            found.append(a)
    return found


def _push(args, base, branch):
    if "--no-verify" in args:
        return "git push --no-verify skips the project's hooks"
    if any(a in ("--force", "--force-with-lease", "--force-if-includes") or a.startswith("--force-with-lease=")
           for a in args) or "f" in _short_flags(args, "push"):
        return "a force push rewrites history others may have"
    if "--all" in args or "--mirror" in args:
        return f"git push --all pushes {base}, which only the engine's merge changes"
    positional = _positional(args, "push")
    if any(a.startswith("+") for a in positional[1:]):
        return "a +refspec is a force push"
    for refspec in positional[1:]:
        target = refspec.split(":", 1)[-1].removeprefix("refs/heads/")
        if target == base or (":" not in refspec and refspec in ("HEAD", "@") and branch == base):
            return f"a push to {base}: only the engine's merge changes it"
    if len(positional) <= 1 and branch == base:
        return f"a push from {base}: only the engine's merge changes it"
    return None


INTERPRETERS = {"sh", "bash", "zsh", "dash", "ksh", "fish", "python", "python3", "perl", "ruby", "node"}
# sh -c "$(curl ...)" and bash <(curl ...): a shell, at the start of a command, running a download.
SUBSTITUTED = re.compile(r"(?:^|[;&|]\s*)(?:sudo\s+(?:-\S+\s+)*)?(?:sh|bash|zsh|dash|ksh)\b[^;&|\n]*"
                         r"(?:\$\(|`|<\()\s*(?:curl|wget)\b")
# The flags that make an interpreter run a program from its arguments instead of stdin.
PROGRAM_FLAGS = {"sh": "c", "bash": "c", "zsh": "c", "dash": "c", "ksh": "c", "fish": "c",
                 "python": "cm", "python3": "cm", "perl": "eE", "ruby": "e", "node": "ep"}
SAFE_ENV = {".env.example", ".env.sample", ".env.template", ".env.dist"}
WRITE_REDIRECTS = {">", ">>", ">|", "&>", "&>>"}


def _reads_program_from_stdin(words):
    """An interpreter that runs what comes in on stdin: no script and no -c, -e or -m, or an explicit - or -s."""
    name = os.path.basename(words[0])
    if name not in INTERPRETERS:
        return False
    args = words[1:]
    if "-" in args or "-s" in args:
        return True
    for a in args:
        if a.startswith("--"):
            continue
        if a.startswith("-"):
            if set(a[1:]) & set(PROGRAM_FLAGS[name]):
                return False
            continue
        return False  # a script file
    return True


def _downloads_into_interpreter(line):
    for pipeline in pipelines(line):
        for i, words in enumerate(pipeline):
            if os.path.basename(words[0]) in ("curl", "wget") and any(
                    _reads_program_from_stdin(later) for later in pipeline[i + 1:]):
                return True
    return any(SUBSTITUTED.search(part) for part in line.splitlines())


def _secret(word):
    name = os.path.basename(word.rstrip("/"))
    return bool(re.fullmatch(r"\.env(\..+)?", name)) and name not in SAFE_ENV


def _wipes_disk(words):
    if words[0].startswith("mkfs") or words[0] in ("wipefs", "fdisk", "sfdisk"):
        return True
    harmless = {"/dev/null", "/dev/zero", "/dev/stdout", "/dev/stderr"}
    if words[0] == "dd" and any(w.startswith("of=/dev/") and w[3:] not in harmless for w in words[1:]):
        return True
    if words[0] == "shred" and any(w.startswith("/dev/") and w not in harmless for w in words[1:]):
        return True
    if words[0] == "rm":
        recursive = any(w in ("-r", "-R", "--recursive") or (w.startswith("-") and not w.startswith("--")
                                                            and set("rR") & set(w)) for w in words[1:])
        roots = {"/", "/*", "~", "~/", "~/*", "$HOME", "${HOME}", "$HOME/", "$HOME/*"}
        return recursive and ("--no-preserve-root" in words or any(w in roots for w in words[1:]))
    return False


def _journal_writes(words):
    """The .rail/journal paths a command writes: redirect targets, and the files rm, mv, cp, tee, truncate,
    sed -i and dd of= change."""
    targets = [words[i + 1] for i, w in enumerate(words[:-1]) if w in WRITE_REDIRECTS]
    redirected = {i + 1 for i, w in enumerate(words[:-1]) if w in WRITE_REDIRECTS or w in ("<", "<<", "<<<")}
    cmd = words[0]
    args = [w for i, w in enumerate(words[1:], 1) if not w.startswith("-") and i not in redirected
            and w not in WRITE_REDIRECTS and w not in ("<", "<<", "<<<")]
    in_place = any(w.startswith("--in-place") or (w.startswith("-") and not w.startswith("--") and "i" in w[1:])
                   for w in words[1:])
    if cmd in ("rm", "mv", "tee", "truncate", "touch") or (cmd in ("sed", "perl") and in_place):
        targets += args
    elif cmd == "cp" and args:
        targets.append(args[-1])
    elif cmd == "dd":
        targets += [w[3:] for w in words[1:] if w.startswith("of=")]
    return [t for t in targets if ".rail/journal" in t]


def deny(line, base, branch):
    """Why a command line is denied, or None (plan, section 15)."""
    if _downloads_into_interpreter(line):
        return "piping a download into a shell runs code nobody has read"
    for words in commands(line):
        if not words:
            continue
        if _wipes_disk(words):
            return "this command can wipe a disk or a home folder"
        secret = next((w for w in words if _secret(w)), None)
        if secret:
            return (f"{secret} holds secrets; read and write it yourself, outside the agent"
                    f" ({', '.join(sorted(SAFE_ENV))} are fine)")
        if _journal_writes(words):
            return "only the engine writes .rail/journal/; record a finding's answer with rail answer"
        if words[0] == "git":
            sub, args = _git(words)
            if sub == "push":
                reason = _push(args, base, branch)
                if reason:
                    return reason
            elif sub == "commit" and ("--no-verify" in args or "n" in _short_flags(args, "commit")):
                return "git commit --no-verify skips the project's hooks"
            elif sub == "merge" and branch == base:
                return f"a merge into {base} goes through the engine: rail advance merges a shipped ticket"
        elif words[0] == "gh":
            if words[1:3] == ["pr", "merge"]:
                return "gh pr merge merges outside the engine: rail advance merges a shipped ticket"
            if len(words) > 1 and words[1] == "api" and any("/merge" in w and "/pulls/" in w for w in words[2:]):
                return "a merge through gh api goes around the engine: rail advance merges a shipped ticket"
    return None


def _resolve(target, cwd):
    """A path as the shell would see it: variables from the hook's environment (the agent's), then ~."""
    path = os.path.expanduser(os.path.expandvars(target))
    return os.path.realpath(os.path.join(cwd, path))


def _outside(target, cwd, top):
    """Whether a path an rm -r names lies outside the worktree. Real paths, so a symlinked /tmp agrees.
    A variable the hook can't expand could point anywhere, so it counts as outside."""
    if "$" in os.path.expandvars(target) or "$" in cwd:
        return True
    path, top = _resolve(target, cwd), os.path.realpath(top)
    return path != top and not path.startswith(top.rstrip("/") + "/")


def ask(line, cwd, top):
    """Why the person should answer before a command runs, or None (plan, section 15)."""
    for pipeline in pipelines(line, unwrap=False):
        for words in pipeline:
            prefix = words[:len(words) - len(_unwrap(words))]  # sudo, env, time, VAR=value and their options
            if "sudo" in prefix:
                return "sudo runs as root"
    for words in commands(line):
        if not words:
            continue
        if words[0] == "cd":  # follow cd through the line: cd .. && rm -rf other is outside
            cwd = _resolve(words[1] if len(words) > 1 and words[1] != "-" else "~", cwd)
        elif words[0] == "git":
            sub, args = _git(words)
            if sub == "reset" and "--hard" in args:
                return "git reset --hard throws away uncommitted work"
            if sub == "clean" and ("--force" in args or "f" in _short_flags(args, "clean")):
                return "git clean -f deletes untracked files"
        elif words[0] == "rm":
            recursive = any(w in ("-r", "-R", "--recursive") or (w.startswith("-") and not w.startswith("--")
                                                                and set("rR") & set(w)) for w in words[1:])
            targets = [w for w in words[1:] if not w.startswith("-")]
            outside = [t for t in targets if _outside(t, cwd, top)]
            if recursive and outside:
                return f"rm -r outside the worktree: {', '.join(outside)}"
    return None

