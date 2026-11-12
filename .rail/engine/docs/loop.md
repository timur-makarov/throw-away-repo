# The loop

Rail keeps an agent on a railroad: the engine says what is legal next and what counts as done, and the
agent writes the code.

```text
rail next --json -> do action.brief -> rail advance --json -> repeat
```

- `owner` says who acts: `agent`, `human` or `none`. When it isn't `agent`, tell the person what is
  needed, then take the next ticket or stop.
- `action.kind` is `agent_task` (do the brief), `script` (run `action.command`), `human_wait` (a person
  acts; the brief says what) or `rest` (nothing to do).
- `steps` lists what the command ran: `ran` with `pass` or `fail`, `not_run`, or `unavailable`. A skipped
  step never looks like a pass.
- Exit codes: 0 when the command worked, 2 for a usage error, 3 when a step failed.

## What next does

`next` makes some moves itself: it accepts a ticket whose tier is in `auto_tiers`, claims a ticket, makes
its worktree in `.claude/worktrees/NN`, copies the files `.worktreeinclude` lists, and runs `setup` there.
It prefers this session's own tickets; then tickets no session holds (a shipped ticket, which any session
may move through CI and the merge, and work an ended session left); then new work in ID order. A ticket
another session is implementing or reviewing is left alone while it keeps moving. After
`[claim] stale_minutes` (30) with no journal event, the next `rail next` resumes it, and
`rail next --ticket NN` takes it over at once. A session whose ticket was taken over is told to stop work
on it.

**Work in flight is saved as it goes.** `rail save` commits a ticket's in-scope changes as they are and
pushes them, with no checks. Two hooks run it: at the end of each agent turn, and at most every ten minutes
while the agent works. So a machine that goes away takes minutes of work with it, and each save shows other
sessions that the ticket is alive. Where no hook runs, the brief asks the agent to run `rail save` itself.
A save is pushed before `verify` runs, the project's secret scan included, so it leaves out a file whose
name says it holds secrets (`.env`, `*.pem`, `*.key`, an SSH key) and says so; the ship commits it after
`verify`, or `.gitignore` keeps it out for good.
Saves carry `[skip ci]`; the commit a ship pushes is the one CI checks. With GitHub reachable, `next` also takes in issues labelled
`rail` and labels every wait `rail:needs-you`.

## What advance does

In the ticket's worktree, `advance` commits your in-scope changes and ships: it rebases onto a moved base,
then runs ticket lint, the ASSUMED rows, scope, structure rules, the migration fields, size, doc-lint,
`verify` and each `Check:` line. On MEDIUM and HIGH it then runs the review. With no remote, a ready
ticket in `auto_tiers` is merged by the next `advance` (run it from the project's root: the merge removes the
worktree), as a squash commit on the base branch; other tiers
wait for `rail accept NN` first. With a remote, every ticket has a pull request; once its required checks
are green, `advance` merges an `auto_tiers` ticket through GitHub's async merge, and a person merges the
rest. When only CI waits remain, `next` returns `gh run watch` for the run, then `rail next`.

## Other verbs

- `rail status`: every ticket, its state and owner, LAST (the age of its last journal event) and NOTE (what it
  waits for, a stale warning, or its pull request), then leftovers to clean up.
- `rail context NN`: the `## Areas` rows a ticket touches, and a directory digest.
- `rail docs TOPIC`: these pages. `rail docs cli` and `rail docs config` are the references.
