# Rail in a Claude Code cloud session

A cloud session is Rail's standard place to work: a machine made for the session, with the repository
cloned fresh, that nobody owns. Rail treats it differently from your own computer. `rail doctor` says which
of the two it is on.

| | In a cloud session | On your own machine |
|---|---|---|
| Tools the checks need | Rail installs them: `[commands] provision` runs as root, once per machine | You install them; `rail provision` only shows the command |
| Setting the project up | The agent does it all and opens one pull request; you confirm by merging it | The agent proposes each choice and you confirm it |
| Guard | The rules that protect the rail stay: no force push, no push to the base branch, no merge outside the engine, no journal edits, no `.env` | The same, plus asks before `sudo`, `git reset --hard`, `git clean -f` and `rm -r` outside the worktree, and no download piped into a shell |
| A person's acts | On GitHub: the label `rail:go`, a comment, the merge button | The same, or `rail accept` in the terminal |

## Set up, once

1. **Start a cloud session on the repository** and ask Claude to set Rail up from the framework's
   repository. It runs `rail init`, writes the project's commands, map and risk paths, installs what the
   checks need, and opens one pull request.
2. **Merge that pull request.**
3. **Make three settings on GitHub.** A cloud session can't change a repository's settings, so these are
   yours, and that is also why they are the guard an agent can't get around:
   - Settings > Rules > Rulesets > New ruleset > Import a ruleset: choose `.rail/ruleset.json`. GitHub
     asks for a file from your device, so download it first, from the repository or from the framework
     (`seed/ruleset.json`); it is the same file for every repository. It requires the `rail` check and a pull
     request on the default branch, keeps branches up to date before a merge, allows squash merges only, and
     blocks force pushes and deletion. It also stops a contract pull request being merged by mistake: its
     `rail` check stays red until the work ships.
   - Settings > General > Pull Requests: "Pull request title and description" as the default squash
     message.
   - Settings > General > Pull Requests: turn on "Automatically delete head branches". A cloud session
     can't delete branches, so merged tickets would pile up.
4. **Approve the environment's setup script.** `rail doctor` prints three lines; the agent proposes them for
   the session's cloud environment and you approve once. They run `rail provision` when the environment's
   machine is built: it links `rail` onto `PATH`, writes Rail's hooks into the machine's own Claude Code
   settings, and runs the project's `provision` command. The result is kept as a snapshot, so later sessions
   start with everything in place. A machine without it provisions itself on the first `rail next`.

`rail doctor` checks all of it and says what is left.

## Hand work over

- **In a session:** say what you want. The agent writes a ticket and runs `rail add`.
- **From GitHub:** label an issue `rail`. Every `rail next` takes labelled issues in.
- **While you are away:** a scheduled task runs the loop with no session open (below).

## What a session does when it starts

Each cloud session is a new session on a new clone, and `rail next` is all it needs:

- It takes in issues labelled `rail`.
- It moves every shipped ticket, whoever shipped it: it waits for CI, rebases a pull request that fell
  behind, and merges a green one. A claim protects only work in flight.
- It resumes work an ended session left. A ticket another session is implementing or reviewing is left
  alone while it keeps moving; after `[claim] stale_minutes` (30) with no journal event, the next session
  resumes it from the pushed branch. `rail next --ticket NN` takes one over at once.
- Then it takes new work, in ID order.

Work that isn't pushed is lost when a machine goes away. So the work in flight is saved as it goes: hooks
run `rail save` at the end of each turn and at most every ten minutes of work, and `rail advance` commits
and pushes every time. A reclaimed machine, a usage limit or a crash costs minutes, and the next session
starts from the last save.

## Run with no session open

Make one scheduled task for the repository, on the environment from step 4, with this prompt:

    Run `rail next` and do what it says, then `rail advance`, and repeat until `rail next` answers that
    only a person can act or that there is no work. Then say which tickets wait for a person, and stop.

Give it these triggers:

- **GitHub events:** an issue labelled, a pull request labelled, and a pull request closed. They cover new
  work, your `rail:go`, and a merge that unblocks the next ticket.
- **A schedule,** hourly or nightly, as a net for anything an event missed.

Each run is a fresh session, and the section above is why that is enough. For more work at once, start
more sessions: claims are taken on the remote, so two never take the same ticket. `rail status --json`
lists the tickets whose owner is `agent`.

## Where your acts go

- **Your inbox** is one saved search: `is:open label:rail:needs-you`. Every wait gets the label as soon as
  any session sees it.
- **Approve or continue:** add the label `rail:go` to the pull request. A comment you leave there reaches
  the agent as your note. Don't merge a contract pull request: it holds only the contract. If you do, Rail
  takes it as your approval and opens a new pull request for the work.
- **Change a contract:** comment on its pull request. **Reject it:** close the pull request.
- **Merge a HIGH ticket:** the merge button.
- Each pull request ends with `Claude-Session:` and a link to the session that worked the ticket.

## Session shapes

Claude Code loads a repository's hooks and permission rules only in a session that starts with that one
repository. A session with several repositories, and a thread in a project, load neither. So
`rail provision` also writes the hooks into the machine's own settings, which every session loads:

- the guard finds the project a command runs in (`cd repo && git push origin main` is still denied), and
  the saves and the session's snapshot cover every Rail repository below the session's folder;
- where the repository's own hooks did load, the machine's step aside, so nothing runs twice;
- `rail` works everywhere, because provision linked it onto `PATH`;
- the allow rules are a repository's and don't load there, so auto mode reviews `rail` commands itself;
- the ruleset on GitHub stays the guard nothing can get around, and `rail ci` repeats every ship check.

`rail doctor` says which hooks ran in the session.

## What the cloud refuses

Branch deletion, tag pushes, GraphQL (so `gh pr` and `gh issue`), and writes to repository settings and
rulesets. Rail needs none of them: it talks to GitHub through `gh api` REST calls, takes ticket IDs from
one counter branch (`rail/ids`), and leaves settings to you.
