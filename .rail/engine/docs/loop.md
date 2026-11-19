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
- `action.model` and `action.effort` name the model and effort for an `agent_task` that is a ticket's work,
  from `[worker] ladder` (`person_ladder` for a PERSON ticket). The rung is the number of failed attempts at
  the step the ticket is failing, 0 when there are none, capped at the last rung; a person's act starts it
  again at 0. With an empty ladder neither is there. A session a person is driving does the brief itself and
  may ignore them. An unattended runner, a cloud session a scheduled task starts, starts one subagent on
  that model and effort, gives it the brief word for word and the `cwd`, and runs `rail advance` itself when
  the subagent returns (`rail docs cloud`). The engine starts no agent.
- `reason.code` names the situation, and `reason.message` says it in a sentence on a refusal. The codes an
  agent meets most: `IMPLEMENT` (do the ticket's work), `VERIFY_ASSUMPTIONS` (open `ASSUMED:` rows),
  `TICKET_LINT` (fix the ticket), `STEP_FAILED` (a ship step failed; the output is in the brief),
  `ANSWER_FINDINGS`, `REBASING` and `CONFLICT`, `SPLIT`, `RED_BASE` (the base branch fails `verify`),
  `WAITING_AFTER` and `SCOPE_OVERLAP` (another ticket goes first), `CI_WAIT`, `NO_WORK`. A person's turn is
  `APPROVE_CONTRACT`, `APPROVE_AMEND`, `MERGE_BY_PERSON`, `RETRY_CAP` (the retry budget or the cap),
  `FINDING_UPHELD`, `STUCK_REVIEW`, `HOLD` or `MERGE_FAILED`. Act on `owner` and `action`; the code is for
  logs and for telling two briefs apart.
- `guide` names the page `[guides]` gives for the brief's situation, such as the start of a ticket or a
  failure that repeats; the brief's last line then says to read it (`rail docs guides`). It is a hint, and
  part of the brief, so a subagent that gets the brief word for word gets the guide too.
- `steps` lists what the command ran: `ran` with `pass` or `fail`, `could_not_run` with `fail` (the shell
  couldn't start the command: it isn't on the machine, or isn't executable), `not_run`, or `unavailable`. A
  skipped step never looks like a pass, and a step that couldn't start never looks like a check that ran.
- Exit codes: 0 when the command worked, 2 for a usage error, 3 when a step failed.

## What next does

`next` makes some moves itself: it accepts an AUTO ticket, claims a ticket, makes
its worktree in `.claude/worktrees/NN`, copies the files `.worktreeinclude` lists, and runs `setup` there.
It prefers this session's own tickets; then tickets no session holds (a shipped ticket, which any session
may move through CI and the merge, and work an ended session left); then new work in ID order. A ticket
another session is implementing or reviewing is left alone while it keeps moving. After
`[claim] stale_minutes` (30) with no journal event, the next `rail next` resumes it, and
`rail next --ticket NN` takes it over at once. A ticket that waited for a person goes on with whoever
reads the answer: the session that sees your `rail:go`, or the one you tell `accept NN`, takes it over at
once, because the session that claimed it rested at the wait. A session whose ticket was taken over is told
to stop work on it.

**The checks run once on the base.** At a ticket's first claim, once setup has passed, `next` runs each
`Check:` line of the Done Contract once in the new worktree, which still holds the base branch, the same way
ship runs it. It records each result in a `base_checks` event: `red`, `green`, `could_not_run` or `timed_out`.
Then it resets the worktree to what it was, because a check may write files. A check that is already green on
the base can't show that the work was done, and `rail stats` counts how often every check was. When every check
was green, the IMPLEMENT brief says so and asks for a `Check:` line that fails now, added with `rail amend`
(`rail docs contract`); it stops saying so once the contract's checks differ from the ones run on the base. A new
test in a file an old check already runs does not count: the contract stays the same. The reviewer is told as
well (`rail docs review`). This is never
a gate: the result fails nothing, spends no attempt, and changes neither the ticket's state nor its owner, and
a failure inside it doesn't stop `next`. It runs once per ticket: not on a resume, not on a takeover, and not
for a ticket with no `Check:` line yet. `[commands] base_checks = false` switches it off. An adopted ticket
has the event already: `rail adopt` ran its checks on the base before filing it, as a gate (`rail docs adopt`).

**Work in flight is saved as it goes.** `rail save` commits a ticket's in-scope changes as they are and
pushes them, with no checks. Two hooks run it: at the end of each agent turn, and at most every ten minutes
while the agent works. So a machine that goes away takes minutes of work with it, and each save shows other
sessions that the ticket is alive. Where no hook runs, the brief asks the agent to run `rail save` itself.
A save is pushed before `verify` runs, the project's secret scan included, so it leaves out a file whose
name says it holds secrets (`.env`, `*.pem`, `*.key`, an SSH key) and says so; the ship commits it after
`verify`, or `.gitignore` keeps it out for good.
Saves carry `[skip ci]`; the commit a ship pushes is the one CI checks, so a save with no changed file
leaves a shipped ticket's branch alone. A claim protects work in flight: a shipped ticket that came back
(a red check, a review finding) has none until a file changes, so a session that only reads for
`stale_minutes` may find the ticket taken over, and loses nothing by it. With GitHub reachable, `next`
also takes in issues labelled `rail`, and every command that meets a wait labels it `rail:needs-you`.

## What advance does

In the ticket's worktree, `advance` commits your in-scope changes and ships: it rebases onto a moved base,
then runs ticket lint, the ASSUMED rows, scope, structure rules, the migration fields, size, doc-lint,
`verify` and each `Check:` line. Then it runs the review, unless every changed file is in
`[review] skip_paths` (see [review](review.md)).

**Over the size cap, a split comes first.** When an AUTO ticket's change is over `[size] cap` and no file on
`person_paths` or `migration_paths` made it PERSON, its first such ship stops at `size` with a `SPLIT` task and
a `split_offered` event, and the ticket stays `implementing`. Nothing failed: it spends no attempt and doesn't
move the model ladder. The brief says how to split: keep a first part that is under the cap and meets a `Check:`
on its own, put the rest on a local branch `split/NN-rest`, narrow the contract with `rail amend` (accepted at
once on an AUTO ticket), and file the rest with `rail add` and `after`. The offer is made once per ticket: the
next ship goes on as AUTO under the cap, and over it the ticket becomes PERSON, so an agent that can't split
just runs `rail advance` again. CI never offers: it checks the tier the patch shipped with.

With no remote, a ready AUTO ticket is merged by the next
`advance` (run it from the project's root: the merge removes the worktree), as a squash commit on the base
branch; a PERSON ticket waits for `rail accept NN` first. With a remote, every ticket has a pull request;
once its required checks are green, `advance` merges an AUTO ticket through GitHub's async merge, and a
person merges a PERSON ticket. When only CI waits remain, `next` returns `gh run watch` for the run, then
`rail next`.

When the rebase meets a conflict, `advance` undoes it and asks you to rebase by hand. While that rebase is
open in the worktree, `next`, `advance` and `save` only say how to end it (`REBASING`), and nothing is
written to the ticket: git moves the branch when the rebase finishes, so a commit made meanwhile would be
lost.

## Other verbs

- `rail status`: every ticket, its state and owner, LAST (the age of its last journal event) and NOTE (what it
  waits for, a stale warning, or its pull request), then leftovers to clean up.
- `rail context NN`: the `## Areas` rows a ticket touches, and a directory digest.
- `rail adopt BRANCH`: put work already on a branch with no ticket onto the rail (`rail docs adopt`).
- `rail stats`: what the tickets' journals and the base branch say: tickets by tier, how many were reverted,
  how often every check was green on the base before the work, failed steps, the reviewer's cost and hit
  rate, and how the grilling went.
- `rail docs TOPIC`: these pages. `rail docs cli` and `rail docs config` are the references.
