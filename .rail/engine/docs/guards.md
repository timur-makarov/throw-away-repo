# Guards

Guards prevent mistakes; they are not a boundary. `rail init` merges them into `.claude/settings.json`,
and `rail doctor` reports when they are missing.

**Permission rules come first**, because deny rules hold in every permission mode:

- deny reading or writing the common `.env` files at any depth (`.env.example` stays readable);
- deny editing `.rail/journal/`, which only the engine writes;
- ask the person before `sudo`, `git reset --hard` and `git clean -f`.

**The guard hook** (PreToolUse on Bash) covers what a rule can't express, because rules match only the
start of a command:

- deny a force push, a push to the base branch, `--no-verify`, a merge outside the engine (`gh pr merge`,
  the merge endpoints through `gh api`, `git merge` on the base branch), a download run as code (`curl` or
  `wget` piped into a shell, python, perl, ruby or node that reads its program from stdin, or a shell running
  `"$(curl ...)"` or `<(curl ...)`), a disk wipe, any Bash use of a `.env` file, and a Bash write into
  `.rail/journal/`;
- ask before `sudo` anywhere in a command, `git reset --hard`, `git clean -f`, and `rm -r` outside the
  worktree.

No git hooks are installed: they would collide with a project's own hook manager, and CI repeats the
checks. The sandbox is turned on with `"sandbox": {"enabled": true}`; where its tools (bubblewrap and socat
on Linux) are missing, Claude Code runs without it and says so.
