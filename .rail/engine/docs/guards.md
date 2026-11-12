# Guards

Guards prevent mistakes; they are not a boundary. `rail init` merges them into `.claude/settings.json`,
and `rail doctor` reports when they are missing.

**Permission rules come first**, because deny rules hold in every permission mode:

- deny reading or writing the common `.env` files at any depth (`.env.example` stays readable);
- deny editing `.rail/journal/`, which only the engine writes;
- ask before `rail answer ... --owner`, which records a person's decision on a finding.

**The loop runs without asking.** Allow rules cover the agent's own verbs (`rail next`, `advance`, `add`,
`answer`, `amend`, `status`, `context`, `docs`, `doctor`, `intake`, `sweep`, `consult`, `provision`) and
`gh run watch`.
A matching allow rule is decided before any prompt and before auto mode's classifier, so the loop isn't
stopped by either. `rail advance` is one of them, and it merges `auto_tiers` with no person: that is the
policy you set in `.rail/config.toml`. The person's verbs have no allow rule: `rail accept`, `rail drop` and
`rail init` are judged like any other command, and `rail answer ... --owner` always asks, in every mode.

Auto mode's own rule lists (the `autoMode` setting) can't be set here: Claude Code reads them from user or
managed settings only, never from a repository. Nothing Rail does needs them changed. The engine makes the
pushes and merges itself, inside `rail next` and `rail advance`.

**The guard hook** (PreToolUse on Bash) covers what a rule can't express, because rules match only the
start of a command:

- deny a force push, a push to the base branch, `--no-verify`, a merge outside the engine (`gh pr merge`,
  the merge endpoints through `gh api`, `git merge` on the base branch), a download run as code (`curl` or
  `wget` piped into a shell, python, perl, ruby or node that reads its program from stdin, or a shell running
  `"$(curl ...)"` or `<(curl ...)`), a disk wipe, any Bash use of a `.env` file, and a Bash write into
  `.rail/journal/`;
- ask before `rail answer --owner` in any position;
- on your own machine only: ask before `sudo` anywhere in a command, `git reset --hard`, `git clean -f`, and
  `rm -r` outside the worktree.

**The guard knows where it runs.** In a Claude Code cloud session the machine is disposable and nobody's own,
and an ask would stop an unattended run, so the rules that protect a machine step aside: the asks above, and
the deny of a download run as code. The rules that protect the rail stay. Ask rules prompt in every mode,
auto mode included, which is why `sudo` and the like are asked by the hook and not by a permission rule.

**It protects this project's branches, not every repository.** After `cd DIR &&`, or with `git -C DIR`, a
command in another repository is left alone. Whatever the guard can't follow (`cd -`, `popd`, a subshell, a
`cd` before `;` or `||`, `--git-dir`, a variable other than `$HOME` and `$PWD`) is judged as this
project's. A command after a shell keyword, as in `then git push -f` or `{ cd -; ... }`, is read as that
command. A `gh` merge is judged by the repository it names.

**A repository's hooks and permission rules load only in a session that starts with that one
repository.** For a cloud session with several repositories, or a project thread, `rail provision` writes
the same hooks into the machine's own settings: the guard then finds the project each command runs in, and
steps aside where the repository's own hooks loaded. The permission rules don't travel that way, and the
ruleset on GitHub is the guard nothing gets around (`rail docs cloud`).

**Two more hooks save the work in flight** (`rail docs loop`): Stop, at the end of each turn, and
PostToolUse, at most every ten minutes. They never block and never ask.

No git hooks are installed: they would collide with a project's own hook manager, and CI repeats the
checks. The sandbox is turned on with `"sandbox": {"enabled": true}`; where its tools (bubblewrap and socat
on Linux) are missing, Claude Code runs without it and says so.
