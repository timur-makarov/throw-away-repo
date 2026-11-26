# Retries, consult and waits

## The retry budget

A failure counts as stuck only when it repeats. Each failed step event carries a `signature`: the step's name
and a hash of the tail of its output, normalised so that the same failure gives the same signature on every
run. The engine lower-cases the output and replaces numbers, hex strings, absolute paths and temp-folder
names with placeholders, then collapses whitespace, so a new line number, commit or temp path doesn't make
the same failure look new.

`[retry] budget` (2 by default) counts the failures in a row at one step with the same signature. When a
step fails the same way twice, the consult pack advises once, and you get one more attempt. If that fails
too, whatever its output, the ticket is stuck. When there is no pack, it is stuck at the budget. A failure whose signature differs from the last failure at that step is progress: the count of
same failures starts again at 1.

`[retry] cap` (5 by default) bounds the rest: after that many failed attempts at one step, whatever their
signatures, the ticket is stuck. This is what stops an agent that keeps producing new errors.
An agent could also make a failure look new by changing the text it prints; the cap bounds that too.

**A stuck ticket.** An AUTO ticket that is stuck is dropped by the engine with a record (`STUCK`): nothing
merged, so nothing needs undoing, and a wait would only spend a person's attention on doubt. `rail next` writes a
`dropped` event with `by: "engine"`, the step and its last failure's signature; writes the drop's mark on the
counter branch; closes the pull request; takes the `rail` label off the issue with a comment that says what was
tried and why it stopped; and removes the worktree and branches. The closed pull request keeps the commits on
GitHub. To try again, label the issue `rail` again. A PERSON ticket that is stuck waits for a person
(`RETRY_CAP`): a person is there anyway.

**A flaky check.** A flake is a `verify` or `Check:` command that both failed and passed on the same code (the
same `patch_id`). When one of them fails at ship, the engine runs that one command once more, at once. When the
second run passes, the step still fails and counts like any failure: a race the change brought in looks exactly
like an old flake, so a pass on the second try proves nothing about the change. The engine writes a `flake`
event, and the failure's brief says to find why the command is not deterministic and to add no retry, sleep or
skip. A command that fails on a patch where another ship passed it, or the other way round, is a flake too.
A command the shell couldn't start is not run again, and `rail ci` runs nothing twice. The reviewer's brief
names each flake on the patch it reviews; the sweep opens a ticket for a command that was flaky in two or more
merged tickets (`rail docs sweep`); `rail stats` has a FLAKES table.

**Spending has two caps of its own.** They are sums of what the runs reported (`cost_usd` on the `worked`
events of `rail work` and on the review, security, refuter and sweep steps): the CLI's own estimate, not the
bill. Consult records no cost, and neither does a session a person drives.

- `[worker] ticket_usd` (40 by default; 0 switches it off) bounds one ticket. When its runs since a person
  last acted cost more, the ticket waits for a person (`BUDGET`) in whatever state it is, a ticket with no
  contract yet included, and the brief gives the sum by what ran. This holds on AUTO too: money spent is not
  undone by a revert. `rail accept NN` or `rail:go` lets it go on and starts the count again, as either gives
  a fresh retry cap; that answer approves nothing else, so a contract or a merge that waits still waits.
  `rail drop NN --by person` ends it. A rebase that is open in the worktree is finished first.
- `[worker] daily_usd` (0 by default: off) bounds every ticket together. While the runs of the last 24 hours
  cost more, `rail next` rests (`BUDGET_DAY`) and `rail work` starts no worker. No ticket changes state, and
  the rest lifts by itself as the runs get older: the answer's `wait_secs` and its brief say when. A dropped
  ticket's journal goes with its branch, so its drop mark keeps its cost, and the day's sum counts all of it
  when the drop was in the last 24 hours.

**The mark comes first.** When the counter branch can't be pushed (offline, or a push refused other than by
another clone's push), nothing is removed or closed: the ticket rests as `DROP_PENDING` until a later
`rail next` writes the mark and finishes the drop. `rail drop` works the same way.

Both count since the step last passed or since a person last continued the ticket. A review run counts when
it leaves a blocking finding open, and all such runs at a review step count as the same failure, so the
budget there is a plain count of failed runs. A review run that timed out, or whose output is invalid (not
JSON, not `review/v1`, a finding on a file or line that doesn't exist, or a non-zero exit), is the reviewer's
fault, not the change's: it doesn't count and doesn't move the worker ladder. It is started once more, and
two such runs in a row wait for a person. A command that
times out at ship, such as `verify` or a check, counts like any other failure. A failed step event with no
`signature`, written by an older engine, counts as the same failure as its neighbour.

## The machine's failures

Some failures are the machine's and not the change's, and more attempts would not mend them. They spend no
attempt, the worker ladder doesn't move, and consult is not asked:

- **A command the shell couldn't start** (exit 127: not found; 126: found but not executable) is recorded as
  `could_not_run`: nothing was checked. A verify that couldn't run is never taken for a red base. The brief
  says to put the program back if the change removed it, or to install it and open a ticket so that
  `[commands] provision` (or `setup`) installs it on every machine.
  A sensor that ends with an exit code it doesn't declare is `could_not_run` too, with a brief of its own: the
  tool crashed or is set up wrongly, and nothing needs installing (`rail docs sensors`).
- **A declared tool out of reach.** After a failed `verify`, `Check:` line or sensor, the engine runs the
  probe of each declared tool whose names are set (`rail docs tools`). When one fails, the step's failure may
  be the tool's alone: the event keeps `tools_down`, and the brief says to run the ship once more. The
  base branch is not tried either, since it would fail the same way. A probe runs only then, so a tool that
  is up costs nothing.

The same such failure at one step twice in a row waits for a person (`TOOL_DOWN`), on an AUTO ticket too: the
brief names the program or the tool, and `rail accept NN` or `rail:go` continues the ticket and starts the
count again. "The same" is the same output for a command that couldn't start and the same tools for a probe;
`[retry] cap` such failures in a row at one step wait too, whatever they were. A failure that counts, or a
pass of the step, ends the row. The reviewer's command that can't start is the reviewer's fault and follows
the review rules above.

## Consult

Consult asks a different model for advice when you are stuck. Its brief is the ticket, the diff and the
failing step's raw output, plus one question; your own story is left out. It answers `proceed`, `change`
or `stop` (a product decision the ticket leaves open; a plainly wrong check is one you amend), and the engine keeps the advice in `.rail/journal/NN-advice.md`. It is read-only and never
checks the change, and at most three run per ticket. Every verdict is advice, `stop` too: you still get the one attempt after
it. The advice given at the budget is in the answer of
`rail advance` and, until the next attempt, in the brief of `rail next`, so a fresh worker gets it too. Ask it yourself with `rail consult NN "question"`.

## Waits

A ticket waits for a person (`owner: person`) for an approval, a person's merge, a review that timed out or gave
invalid output twice in a row, a failure of the machine's twice in a row, or an amended Done Contract; and a PERSON ticket also for the retry budget or cap,
a finding the refuter upheld, and a ticket it comes after that was dropped. On an AUTO ticket those three are no
wait: at the cap the ticket is dropped (above); a finding the refuter upheld stands, and disputing it again comes
back as a failed review that counts toward the cap; and when a ticket it comes after was dropped, the agent
decides, with the contract writer's model (`[worker] contract`), whether to remove that ticket from `after`
(`rail amend NN "why" --file FILE`) or to drop this one (`rail drop NN --reason "why"`). Both are recorded. The brief says what is
needed. One act continues any wait:

```text
rail accept NN "what to do differently"
```

The note goes into your next brief, with a fresh retry budget and a fresh cap. If it holds beyond this ticket, open a
ticket that writes it into the project's part of `AGENTS.md`, or into a rule.

Each entry of `rail next`'s `waits` list has `kind`, what the wait asks of the person:

- `approval`: something a revert doesn't undo, money included (`APPROVE_CONTRACT`, `APPROVE_AMEND`,
  `MERGE_BY_PERSON`, `BUDGET`, and on a PERSON ticket `RETRY_CAP`, `FINDING_UPHELD` and `AFTER_DROPPED`).
- `grant`: the machine lacks something a person gives once, or a setting needs repair (`TOOL_MISSING`,
  `TOOL_DOWN`, `STUCK_REVIEW`, `MERGE_FAILED`).
- `hold`: the person's own brake (`HOLD`, `STOPPED`).
