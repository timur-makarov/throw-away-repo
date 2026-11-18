# Retries, consult and waits

## The retry budget

A failure counts as stuck only when it repeats. Each failed step event carries a `signature`: the step's name
and a hash of the tail of its output, normalised so that the same failure gives the same signature on every
run. The engine lower-cases the output and replaces numbers, hex strings, absolute paths and temp-folder
names with placeholders, then collapses whitespace, so a new line number, commit or temp path doesn't make
the same failure look new.

`[retry] budget` (2 by default) counts the failures in a row at one step with the same signature. When a
step fails the same way twice, the consult pack advises once, and you get one more attempt. If that fails
too, whatever its output, the ticket waits for a person. Without the pack, it waits for a person at the
budget. A failure whose signature differs from the last failure at that step is progress: the count of
same failures starts again at 1.

`[retry] cap` (5 by default) bounds the rest: after that many failed attempts at one step, whatever their
signatures, the ticket waits for a person. This is what stops an agent that keeps producing new errors.
An agent could also make a failure look new by changing the text it prints; the cap bounds that too.

Both count since the step last passed or since a person last continued the ticket. A review run counts when
it leaves a blocking finding open, or when its output is invalid, and all such runs at a review step count
as the same failure, so the budget there is a plain count of failed runs. A review run that timed out
doesn't count: it is started once more, and two review timeouts in a row wait for a person. A command that
times out at ship, such as `verify` or a check, counts like any other failure. A failed step event with no
`signature`, written by an older engine, counts as the same failure as its neighbour.

A command the shell couldn't start (exit 127: not found; 126: found but not executable) is recorded as
`could_not_run`, not as a failure of the change: nothing was checked. It still counts as an attempt, so a
missing tool can't loop for ever, and a verify that couldn't run is never taken for a red base. Install the
tool to go on, and open a ticket so that `[commands] provision` (or `setup`) installs it on every machine.

## Consult

Consult asks a different model for advice when you are stuck. Its brief is the ticket, the diff and the
failing step's raw output, plus one question; your own story is left out. It answers `proceed`, `change`
or `stop`, and the engine keeps the advice in `.rail/journal/NN-advice.md`. It is read-only, never a gate,
and at most three run per ticket. Ask it yourself with `rail consult NN "question"`.

## Waits

A ticket waits for a person (`owner: human`) for an approval, a person's merge, the retry budget or cap, a finding
the refuter upheld, a review that timed out twice, or an amended Done Contract. The brief says what is
needed. One act continues any wait:

```text
rail accept NN "what to do differently"
```

The note goes into your next brief, with a fresh retry budget and a fresh cap. If it holds beyond this ticket, open a
ticket that writes it into the project's part of `AGENTS.md`, or into a rule.
