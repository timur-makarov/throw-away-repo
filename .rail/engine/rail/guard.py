"""The guard hook: what depends on a flag or a refspec anywhere in a Bash command.

Guards prevent mistakes; they are not a boundary. Permission rules in .claude/settings.json cover what a rule
can express, and this hook covers the rest.
"""

import fnmatch
import os
import re
import shlex

# Commands that run another command. The guard judges the command inside: `timeout 60 git push -f` is a push.
WRAPPERS = {"sudo", "doas", "env", "command", "builtin", "exec", "time", "timeout", "nohup", "nice", "ionice",
            "stdbuf", "setsid", "xargs"}
# A wrapper's options that take a value, and its own arguments before the command (the duration of timeout).
WRAPPER_VALUED = {"sudo": {"-u", "-g", "-h", "-p", "-C", "-D", "-R", "-T", "-U", "-r", "-t"}, "doas": {"-u", "-C"},
                  "env": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}, "exec": {"-a"},
                  "time": {"-o", "-f"}, "timeout": {"-s", "--signal", "-k", "--kill-after"},
                  "nice": {"-n", "--adjustment"}, "ionice": {"-c", "-n", "-p"}, "stdbuf": {"-i", "-o", "-e"},
                  "xargs": {"-n", "-P", "-I", "-L", "-d", "-E", "-s", "-a"}}
WRAPPER_ARGUMENTS = {"timeout": 1}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
BY_PATH = {"git", "gh", "rm"} | SHELLS  # /usr/bin/git push -f is a push too
# Shell words that come before a command without being one: `then git push -f` and `{ cd -; ... }` are still a push
# and a cd.
KEYWORDS = {"{", "!", "if", "then", "elif", "else", "do", "while", "until"}
SEPARATORS = {";", "&&", "||", "|", "&", "|&"}


def _tokens(part):
    """One line's shell tokens. shlex keeps a run of punctuation together, so `);` and `)&&` come as one token:
    parentheses are split off, or the operator next to them would be missed."""
    def lex(text):
        lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        lexer.commenters = ""  # to shlex a # inside a word (a#b, a URL's #fragment) starts a comment; to the shell it doesn't
        return list(lexer)

    try:
        tokens = lex(part)
    except ValueError:
        # An unclosed quote or a backslash at the end: the line is part of something longer. Its words are judged
        # with the quotes taken out, so `bash -c 'git push -f` and `git push -f origin x'` are still read.
        tokens = lex(re.sub(r"['\"\\]", " ", part))
    found = []
    for token in tokens:
        if token and set(token) <= set("();<>|&") and set(token) & set("()"):
            found += re.findall(r"[()]|[^()]+", token)
        else:
            found.append(token)
    return found


def _readings(text):
    """The texts to judge for one command: as written, and with each backslash before a newline taken out, which
    is how the shell joins two lines. Both are judged: a backslash that ends a comment joins nothing."""
    joined = text.replace("\\\n", "")
    return [text] if joined == text else [text, joined]


def _lines(text):
    """A command text as the lines to judge, each with whether it runs in a child shell.

    Every line is judged as a command line of its own, whatever quotes or here-documents surround it. The guard
    doesn't parse the shell, so it can't tell text from commands for certain, and a line it took for text by
    mistake would run unjudged. The price is a false deny when a message has a line that starts with a denied
    command. The command lines inside $(...), <(...), >(...) and backticks are judged too, quoted or not.
    """
    rows = text.split("\n")
    # Substitutions are looked for everywhere but in the body of a here-document with a quoted delimiter, which the
    # shell takes letter for letter: a message there may name `a command` in backticks. Its rows are still judged.
    code, i = list(rows), 0
    while i < len(rows):
        quoted = re.search(r"(?<!<)<<(?!<)(-?)[ \t]*(['\"])(\w+)\2(?=[\s);|>&]|$)", rows[i])
        i += 1
        if quoted:
            ends = [k for k in range(i, len(rows)) if (rows[k].lstrip("\t") if quoted.group(1) else rows[k]) == quoted.group(3)]
            if ends:
                code[i:ends[0]] = [""] * (ends[0] - i)
                i = ends[0] + 1
    found = [(row, True) for inner in _substituted("\n".join(code)) for row in inner.split("\n")]
    certain = _plain(text)
    for row in rows:
        found.append((row, False))
        if not certain and ("'" in row or '"' in row):
            # A quote may run from one line to the next here, so the quotes on this line may pair up otherwise
            # than they look: `b" ; git push -f ; echo "c` is three commands. Its words are judged bare as well.
            found.append((re.sub(r"['\"]", " ", row), False))
    return [(row, child) for row, child in found if row.strip()]


def _plain(text):
    """Whether every line of a command text is certain to be a command line: it has no here-document, and no
    line leaves a quote open. Then no line can be the text of a message."""
    if "<<" in text:
        return False
    return not any(len(re.findall(r"(?<!\\)(?:\\\\)*" + mark, row)) % 2 for row in text.split("\n") for mark in "'\"")


def _substituted(text):
    """What stands inside each $(...), <(...), >(...) and pair of backticks, the nested ones too."""
    found, opened, i = [], [], 0
    while i < len(text):
        if text.startswith(("$(", "<(", ">("), i):
            opened.append(i + 2)
            i += 2
            continue
        if text[i] == "(" and opened:
            opened.append(None)  # a plain parenthesis inside a substitution
        elif text[i] == ")" and opened:
            start = opened.pop()
            if start is not None:
                found.append(text[start:i])
        i += 1
    found += [text[start:] for start in opened if start is not None]  # left open: the shell runs what it has
    return found + text.split("`")[1::2]


def pipelines(line, unwrap=True, depth=0):
    """Each line's pipelines, as lists of simple commands (word lists). ;, &&, || and & end a pipeline; | joins one.
    With unwrap, `sudo`, `env`, VAR=value and the like are dropped from the front of each command. The pipelines
    of a script handed to a shell (`bash -c "..."`, `eval ...`) come after the pipeline that runs it."""
    keep = _unwrap if unwrap else (lambda words: words)
    found = []
    for part, child in _lines(line):
        tokens = _tokens(part)
        pipeline, words, scripts = [], [], []
        for token in [*tokens, ";"]:
            if token in SEPARATORS:
                pipeline.append(keep(words))
                scripts.append(_script(_unwrap(words), depth))
                words = []
                if token not in ("|", "|&"):
                    found.append(pipeline)
                    for script in filter(None, scripts):
                        found += pipelines(script, unwrap, depth + 1)
                    pipeline, scripts = [], []
            elif not set(token) <= set("()"):
                words.append(token)
    return [[words for words in pipeline if words] for pipeline in found]


def commands(line):
    """The simple commands in a command line, as word lists."""
    return [words for pipeline in pipelines(line) for words in pipeline]


def sequence(line, depth=0):
    """Each simple command as (its words as written, its words unwrapped, the operator after it, whether its line
    uses parentheses). The operator and the parentheses say whether a `cd` still holds for the next command.
    The commands of a script handed to a shell come after the command that runs it. `eval` runs them in this
    shell, so the last one carries the eval's operator; `bash -c` runs them in a child, so they count as grouped:
    a cd in there says nothing about where the next command runs."""
    found = []
    for part, child in _lines(line):
        tokens = _tokens(part)
        grouped = child or any(token and set(token) <= set("()") for token in tokens)
        words = []
        for token in [*tokens, None]:  # None ends the line; "" is a word, the empty argument of -m ""
            if token is None or token in SEPARATORS:
                command, after = _unwrap(words), token or ""
                found += [(words, reading, after, grouped) for reading in _variants(command)]
                inner = sequence(_script(command, depth) or "", depth + 1)
                if inner and command[0] == "eval":
                    inner[-1] = (*inner[-1][:2], after, inner[-1][3])
                elif inner:
                    inner = [(*item[:3], True) for item in inner]
                found += inner
                words = []
            elif token == "" or not set(token) <= set("()"):
                words.append(token)
    return [item for item in found if item[1]]


def _variants(words):
    """The readings of one command's words, each of them judged: as written, cut where a trailing comment would
    start, and without its redirections. The guard can't be sure which the shell takes, and the difference
    counts: to the shell `git push origin # now` and `git push origin 2>&1` are a bare push, while the words
    after `origin` would be refspecs."""
    def cut(ws):
        return next((ws[:i] for i, w in enumerate(ws) if i and w.startswith("#")), ws)

    def bare(ws):
        kept, i = [], 0
        while i < len(ws):
            if ws[i] and set(ws[i]) <= set("<>&|") and set(ws[i]) & set("<>"):
                if kept and kept[-1].isdigit():
                    kept.pop()  # the file descriptor of 2>&1
                i += 2  # the operator and its target
            else:
                kept.append(ws[i])
                i += 1
        return kept

    found = []
    for reading in (words, cut(words), bare(words), bare(cut(words)), [w for w in bare(cut(words)) if w]):
        if reading and reading not in found:
            found.append(reading)  # the last one: without empty arguments, which name no refspec either
    return found


def _unwrap(words):
    """The command inside its wrappers: `sudo -u root`, `env`, `timeout 60`, VAR=value, a shell keyword. So
    `sudo git push -f` and `timeout 60 /usr/bin/git push -f` are still a push."""
    while words and (words[0] in WRAPPERS or words[0] in KEYWORDS or ("=" in words[0] and not words[0].startswith("-"))):
        wrapper, words = words[0], words[1:]
        valued = WRAPPER_VALUED.get(wrapper, ())
        while words and words[0].startswith("-"):  # the wrapper's own options, such as sudo -E, and their values
            words = words[2:] if words[0] in valued else words[1:]
        words = words[WRAPPER_ARGUMENTS.get(wrapper, 0):]
    if words and "/" in words[0] and os.path.basename(words[0]) in BY_PATH:
        words = [os.path.basename(words[0]), *words[1:]]
    return words


def _moved(raw, words):
    """Whether a wrapper runs the command in another directory: env -C DIR, sudo -D DIR."""
    return any(w in ("-C", "-D") or w.startswith("--chdir") for w in raw[:len(raw) - len(words)])


def _script(words, depth=0):
    """The command line a command hands to a shell: the word after -c in `bash -c "..."`, the words of an `eval`.
    None for any other command, and below a few levels of nesting."""
    if not words or depth >= 3:
        return None
    if words[0] == "eval":
        return " ".join(words[1:])
    if words[0] in SHELLS:
        i = 1
        while i < len(words) and words[i].startswith(("-", "+")):
            if words[i].startswith("-") and not words[i].startswith("--") and "c" in words[i]:
                return " ".join(words[i + 1:]) or None  # with its arguments: a quote left open splits the script
            i += 2 if words[i] in ("-o", "+o", "-O", "+O") else 1
    return None


def _git(words):
    """(subcommand, its arguments) for a git command, skipping git's own options such as -C path."""
    i = 1
    while i < len(words) and words[i].startswith("-"):
        i += 2 if words[i] in ("-C", "-c", "--git-dir", "--work-tree") else 1
    return (words[i], words[i + 1:]) if i < len(words) else (None, [])


def _git_dir(words, here):
    """The directory a git command runs in: `here`, moved by each -C path. None when it can't be known: --git-dir
    and --work-tree point git at a repository from anywhere."""
    i = 1
    while i < len(words) and words[i].startswith("-"):
        if words[i].startswith(("--git-dir", "--work-tree")):
            return None
        if words[i] == "-C" and i + 1 < len(words):
            here = _known(words[i + 1], here)
        i += 2 if words[i] in ("-C", "-c") else 1
    return here


def _expand(target, here):
    """A word with ~, $HOME and $PWD filled in as the shell would at this point of the command; `here` is where
    the shell stands, None when that isn't known. Every other variable stays as written: the command itself may
    have set it, and the shell moves $OLDPWD with each cd, so the hook's own environment says nothing about them."""
    def value(match):
        name = match.group(1) or match.group(2)
        if name == "HOME":
            return os.path.expanduser("~")
        return here if name == "PWD" and here else match.group(0)
    return os.path.expanduser(re.sub(r"\$(?:(\w+)|\{(\w+)\})", value, target))


def _known(target, here):
    """A path as the shell would see it, or None when it can't be known: a variable the guard can't follow, or a
    relative path from an unknown place."""
    expanded = _expand(target, here)
    if "$" in expanded or (here is None and not os.path.isabs(expanded)):
        return None
    return _resolve(target, here or "/")


def _after_cd(words, operator, grouped, here, before=""):
    """Where the shell is after a cd, pushd or popd. Only `cd DIR &&` is followed: after ;, ||, & or |, inside
    parentheses, or with `cd -`, `popd` or a bare `cd`, the shell may be anywhere, so the answer is None and what
    follows is judged as this project's. So it is when the shell may skip the cd or run it in a child: after
    `||` (`true || cd DIR && ...`) or in a pipeline."""
    target = words[1] if len(words) == 2 else None
    if words[0] == "popd" or target is None or target.startswith(("-", "+")) or operator != "&&" or grouped \
            or before in ("||", "|", "|&"):
        return None
    return _known(target, here)


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
    return any(SUBSTITUTED.search(part) for part, child in _lines(line))


def _secret(word):
    name = os.path.basename(word.rstrip("/"))
    return bool(re.fullmatch(r"\.env(\..+)?", name)) and name not in SAFE_ENV


# File names that say the file holds secrets: private keys and credential stores, besides .env files.
SECRET_FILES = ("*.pem", "*.key", "*.p12", "*.pfx", "*.keystore", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".netrc")


def holds_secrets(path):
    """Whether a file's name says it holds secrets. A save leaves such a file out: it is pushed before any scan."""
    name = os.path.basename(path.rstrip("/"))
    return _secret(path) or any(fnmatch.fnmatch(name, pattern) for pattern in SECRET_FILES)


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


GH_API_VALUED = {"-X", "--method", "-H", "--header", "-f", "--raw-field", "-F", "--field", "--input", "-q", "--jq",
                 "-t", "--template", "--hostname", "-p", "--preview", "--cache"}


def _repo_name(text):
    """OWNER/NAME from [HOST/]OWNER/NAME, a URL, or an scp-style address; None when it is none of these."""
    text = re.sub(r"^[a-z+]+://", "", text.strip())
    text = re.sub(r"^[^/@]*@", "", text).replace(":", "/")
    parts = [x for x in text.split("/") if x]
    if len(parts) >= 3 and "." in parts[0]:
        parts = parts[1:]  # the host
    if len(parts) < 2:
        return None
    return f"{parts[0]}/{parts[1].removesuffix('.git')}".lower()


def _gh_sub(words):
    """A gh command's first two words past its options, so `gh pr -R owner/name merge 5` is `pr merge`."""
    found, i = [], 1
    while i < len(words) and len(found) < 2:
        if not words[i].startswith("-"):
            found.append(words[i])
        i += 2 if words[i] in ("-R", "--repo", "--hostname") else 1
    return found


REPO_NAME = r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+"


def _gh_target(raw, words, repo):
    """Whose repository a gh command is about: "ours", "other", or None when where it runs decides.

    It is another repository's only on proof that nothing can take back:
    - `gh pr merge` and the like: -R or --repo with another OWNER/NAME, or a pull request URL of another repository
      as an argument, and every such word agrees;
    - a merge through `gh api`: every word with a merge path names another repository in that path itself
      (repos/OWNER/NAME/pulls/N/merge). A path by id, or for the current repository, proves nothing.
    This project's name anywhere in the command makes it ours, and so does a name the guard can't read (a
    variable). GH_REPO is no proof either way that the command is another's: a wrapper may unset it (env -u, env
    -i), and `gh api` reads it only to fill {owner}/{repo}.
    """
    if not repo:
        return None  # this project's own name isn't known, so no name can be told from it
    if any(repo in w.lower() for w in raw):
        return "ours"
    if any(w.startswith("GH_REPO=") and re.search(r"[$`]", w) for w in raw):
        return "ours"
    if _gh_sub(words)[:1] == ["api"]:
        merges = [w for w in words[2:] if "/pulls/" in w and "/merge" in w]
        named = [re.match(rf"(?:https://api\.github\.com)?/?repos/({REPO_NAME})/pulls/\d+/merge", w) for w in merges]
        return "other" if merges and all(named) else None
    hints = []
    for i, w in enumerate(words):
        if w in ("-R", "--repo") and i + 1 < len(words):
            hints.append(words[i + 1])
        elif w.startswith("--repo="):
            hints.append(w.split("=", 1)[1])
        elif i > 1 and re.match(r"(?:https?://)?(?:www\.)?github\.com/", w) and not words[i - 1].startswith("-"):
            hints.append(re.sub(r"^https?://", "", w))
    if not hints:
        return None
    readable = all(not re.search(r"[$`]", hint) and _repo_name(hint) for hint in hints)
    return "other" if readable else "ours"


def deny(line, base, branch, cwd=None, locate=None, repo=None, cloud=False):
    """Why a command is denied, or None. It is judged as written and with its continued lines joined."""
    for reading in _readings(line):
        reason = _deny(reading, base, branch, cwd, locate, repo, cloud)
        if reason:
            return reason + (MESSAGE_HINT if "\n" in line.strip() else "")
    return None


MESSAGE_HINT = (". Every line of a command is read as a command. If the line this is about is text in a message,"
                " reword it or pass the message from a file (git commit -F FILE)")


def _deny(line, base, branch, cwd=None, locate=None, repo=None, cloud=False):
    """Why one reading of a command is denied, or None.

    The git and gh rules protect this project's branches. With `cwd` and `locate`, a command that clearly runs in
    another repository (after `cd DIR &&`, or with git -C) is left alone: locate(directory) answers (ours, the
    branch there), or None when the directory can't be judged. Whatever can't be followed is judged as ours.
    `repo` is this project's OWNER/NAME on GitHub. In a cloud session the VM is nobody's machine, so the rule
    about running a download as code is left to the host.
    """
    if not cloud and _downloads_into_interpreter(line):
        return "piping a download into a shell runs code nobody has read"
    here = cwd
    repo = repo.lower() if repo else None
    git_exported = False  # an exported GIT_DIR or GIT_WORK_TREE points every later git command at a repository
    gh_exported = False  # and an exported GH_REPO that names this project points every later gh command at it
    certain = _plain(line)  # every line is a command line for sure: a cd on one line holds for the next
    moved = False  # a cd, an eval or a sourced file has been seen
    command, previous, before = None, "", ""  # the command at hand, and the operator in front of it
    for raw, words, operator, grouped in sequence(line):
        first = raw is not command  # the first reading of this command's words
        if first:
            if before == "" and moved and not certain:
                here = None  # a new line, and the cd before it may have stood in a message: it proves nothing
            command, previous, before = raw, before, operator
        if words[0] in ("export", "declare", "typeset"):
            # These only ever make the guard stricter. An export that names another repository is not believed:
            # it may never reach the command (a pipeline, a child shell, an unset in between).
            git_exported = git_exported or any(w.split("=")[0] in ("GIT_DIR", "GIT_WORK_TREE") for w in words[1:])
            gh_exported = gh_exported or any(w.startswith("GH_REPO=") and repo and _repo_name(w.split("=", 1)[1]) == repo
                                             for w in words[1:])
        if _wipes_disk(words):
            return "this command can wipe a disk or a home folder"
        secret = next((w for w in words if _secret(w)), None)
        if secret:
            return (f"{secret} holds secrets; read and write it yourself, outside the agent"
                    f" ({', '.join(sorted(SAFE_ENV))} are fine)")
        if _journal_writes(words):
            return "only the engine writes .rail/journal/; record a finding's answer with rail answer"
        if words[0] in ("cd", "pushd", "popd"):
            moved = True
            if first:  # as written only: a cd is believed when it is plain
                here = _after_cd(words, operator, grouped, here, previous)
        elif words[0] in ("source", ".") or (words[0] == "eval" and re.search(r"[$`]", " ".join(words[1:]))):
            moved = True
            here = None  # a file's commands, or words the guard can't read, may move the shell
        elif words[0] == "git":
            sub, args = _git(words)
            where = _git_dir(words, here)
            if git_exported or any(w.startswith(("GIT_DIR=", "GIT_WORK_TREE=")) for w in raw) or _moved(raw, words):
                where = None
            found = locate(where) if locate and where is not None else None
            ours, at = found if found else (True, branch)
            if sub == "push" and not ours:
                # A push from another repository can still name this one: by URL, or by its folder.
                target = next(iter(_positional(args, "push")), "")
                there = _known(target, where) if "/" in target or target.startswith((".", "~")) else None
                aimed = locate(there) if locate and there and os.path.isdir(there) else None
                if (repo and _repo_name(target) == repo and ("/" in target or ":" in target)) or (aimed and aimed[0]):
                    ours, at = True, ""
            if not ours:
                continue
            if sub == "push":
                reason = _push(args, base, at)
                if reason:
                    return reason
            elif sub == "commit" and ("--no-verify" in args or "n" in _short_flags(args, "commit")):
                return "git commit --no-verify skips the project's hooks"
            elif sub == "merge" and at == base:
                return f"a merge into {base} goes through the engine: rail advance merges a shipped ticket"
        elif words[0] == "gh":
            target = _gh_target(raw, words, repo)
            if target == "other":
                continue  # every word that names a repository names another one
            if target is None and not gh_exported:
                found = locate(here) if locate and here is not None and not _moved(raw, words) else None
                if found and not found[0]:
                    continue  # it names none, and it runs in another repository
            if _gh_sub(words) == ["pr", "merge"]:
                return "gh pr merge merges outside the engine: rail advance merges a shipped ticket"
            if _gh_sub(words)[:1] == ["api"] and any("/merge" in w and "/pulls/" in w for w in words[2:]):
                return "a merge through gh api goes around the engine: rail advance merges a shipped ticket"
    return None


def _resolve(target, cwd):
    """A path as the shell would see it from cwd. A variable the guard can't follow stays in it as written."""
    return os.path.realpath(os.path.join(cwd, _expand(target, cwd)))


def _outside(target, cwd, top):
    """Whether a path an rm -r names lies outside the worktree. Real paths, so a symlinked /tmp agrees.
    A variable the guard can't follow could point anywhere, so it counts as outside."""
    if "$" in _expand(target, cwd) or "$" in cwd:
        return True
    path, top = _resolve(target, cwd), os.path.realpath(top)
    return path != top and not path.startswith(top.rstrip("/") + "/")


def ask(line, cwd, top, cloud=False):
    """Why the person should answer before a command runs, or None. Judged like deny: every reading."""
    for reading in _readings(line):
        reason = _ask(reading, cwd, top, cloud)
        if reason:
            return reason
    return None


def _ask(line, cwd, top, cloud=False):
    """Why the person should answer before one reading of a command runs, or None.

    `rail answer --owner` records a person's decision, so it asks everywhere. The rest protects a person's own
    machine and work: in a cloud session the VM is disposable and an ask would only stop an unattended run.
    """
    for words in commands(line):
        if words and os.path.basename(words[0]) == "rail" and "answer" in words[1:3] and "--owner" in words:
            return "rail answer --owner records the owner's decision on a finding: that is a person's to make"
    if cloud:
        return None
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
