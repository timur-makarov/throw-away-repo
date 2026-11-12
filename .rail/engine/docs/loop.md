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
It prefers this session's own tickets, then new work in ID order. A ticket another session claimed is
listed as resumable; `rail next --ticket NN` takes it over after that session ends.

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
