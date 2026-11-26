# Guards

Guards prevent mistakes; they are not a boundary. `rail init` merges them into `.claude/settings.json`,
and `rail doctor` reports when they are missing.

**Permission rules come first**, because deny rules hold in every permission mode:

- deny reading or writing the common `.env` files at any depth (`.env.example` stays readable);
- deny editing `.rail/journal/`, which only the engine writes;
- ask before `rail answer ... --owner`, which records a person's decision on a finding.

**The loop runs without asking.** Allow rules cover the agent's own verbs (`rail next`, `advance`, `add`,
`adopt`, `answer`, `amend`, `status`, `stats`, `context`, `docs`, `doctor`, `intake`, `sweep`, `source`, `consult`, `save`,
`provision`, `work`) and
`gh run watch`.
A matching allow rule is decided before any prompt and before auto mode's classifier, so the loop isn't
stopped by either. `rail advance` is one of them, and it merges an AUTO ticket with no person: that is the
policy you set with `[kinds]` and `person_paths` in `.rail/config.toml`. The person's verbs have no allow rule: `rail accept`, `rail drop` and
`rail init` are judged like any other command, and `rail answer ... --owner` always asks, in every mode.

**Looking things up.** `WebSearch` has an allow rule, so a worker, or you in your own session, can search for a
fact the repository doesn't hold: a library's behaviour in the installed version, what an error means. The
build guide tells the worker to write such a fact into the ticket as a `VERIFIED:` row with where it was read
(`rail docs guides`). Three limits, each on purpose:

- **Fetching a page has no allow rule.** A fetch names a URL, and a URL can carry data out of the repository,
  so `WebFetch` is left to the session's permission mode: auto mode's classifier judges each one, and a
  person's own session is asked. To let a documentation host through with no question, add
  `"WebFetch(domain:docs.example.com)"` to `permissions.allow` in `.claude/settings.json`.
- **The reviewer, the refuter, the security seat and consult have no web tools.** `[review] command` and
  `[consult] command` list their tools, and neither search nor fetch is among them. Their word decides a
  merge, a web page is text nobody here wrote, and a review should come out the same from the same
  repository. What they need to know of the outside is in the ticket's `VERIFIED:` rows.
- **A service you look things up in is a tool.** A documentation service, an MCP server or an API with a key is
  declared as `[tools.NAME]`, so every agent is told of it and a ticket isn't claimed while it is out of reach
  (`rail docs tools`).

What can be known before the work starts belongs in the contract: the contract writer checks it and writes it
as a fact, and leaves an `ASSUMED:` row for what it could not check. Looking up during the work is for what
nobody could foresee.

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
`cd` before `;` or `||` or after `||`, `--git-dir`, a variable other than `$HOME` and `$PWD`, or those two
once the command sets them itself) is judged as
this project's, and so is what follows a sourced file or an `eval` of words the guard can't read. A `cd` is
believed only as a plain command in a flat chain: not behind a keyword or in braces (`if ...; then cd DIR`,
`{ cd DIR; }`), where the shell may skip it, and one from the middle of an `&&` chain holds until that chain
ends. A `cd` on one line holds for the next line only when no line of the command can be text: with a
here-document or a quote that runs over lines, it holds for its own line.

A `gh` merge is another repository's only on proof in an exact shape: for `gh pr merge`, `-R OWNER/NAME`
or the pull request as `https://github.com/OWNER/NAME/pull/N`, spelled plainly and with every other word a
known option; for `gh api`, a merge path that names the repository itself (`repos/OWNER/NAME/pulls/N/merge`).
`GH_REPO` is no such proof: a wrapper may unset it, and `gh api` reads it only to fill `{owner}/{repo}`.
This project's name anywhere in the command makes it this project's, and so does a name the guard can't
read as `gh` will (a variable, `%2D`, a path by repository id). An exported `GIT_DIR` or `GH_REPO` only ever
makes the guard stricter. From a folder above the repositories, a command the guard can't place is judged
on the branch the project's own checkout is on.

**It reads the command that runs.** A command after a shell keyword (`then git push -f`, `{ cd -; ... }`),
behind a wrapper (`sudo -u root`, `env`, `timeout 60`, `xargs`, `nice`) or given by its path
(`/usr/bin/git`) is read as that command. So are the commands a line hands to a shell: `bash -c "..."`,
`eval ...`, `$(...)`, backticks and `<(...)`. Each command is judged as written, without a trailing
`# comment`, and without its redirections: to the shell `git push origin # now` and `git push origin 2>&1`
are a bare push. A script file is not read, and neither is a `case` arm or a command another program runs
(`find -exec`, `make`): the ruleset on GitHub is what holds there.

**Every line of a command is read as a command.** The guard doesn't parse the shell, so it can't tell
text from commands for certain, and a line it took for text by mistake would run unjudged. So a line that
starts with a denied command is denied wherever it stands: in a here-document, inside quotes, after a
comment sign. The price is a false deny when a commit message or a pull request body has such a line. The
answer says so; reword the line, or pass the message from a file (`git commit -F FILE`,
`gh pr create --body-file FILE`). A command named anywhere else in a line is left alone, and so are
backticks in a here-document with a quoted delimiter (`<<'EOF'`), which is how a message should be passed.

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

Two settings let the engine work inside it. `rail advance`, `rail next` and `rail work` are in
`excludedCommands`, so a call that holds only those commands runs outside the sandbox: the engine writes the
journal, which the deny rule on `.rail/journal/**` otherwise forbids to every sandboxed command, the engine
included. The price is that `verify`, the checks and the engine's re-run of a reviewer's evidence commands,
which `rail advance` starts, run outside the sandbox in such a call. The worker `rail work` starts is a `claude -p`
process with the repository's settings: their hooks run in it, the guard included, while their allow rules
apply only in a folder Claude Code trusts. The default `[worker] command` uses auto mode, and
`--permission-prompts none` turns a call nobody can approve into a denial the worker reads.
`api.anthropic.com` is an allowed domain, so the reviewer, which is a `claude -p` process the engine starts,
can answer when `rail advance` is one command of a longer call and stays sandboxed. `rail init` adds the
package registries of the languages it finds (`rail docs languages`). Add the other hosts your own `verify`
needs to `sandbox.network.allowedDomains`.
