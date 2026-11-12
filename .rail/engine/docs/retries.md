# Retries, consult and waits

## The retry budget

Each step has a budget of failed attempts, `[retry] budget` (2 by default), counted since the step last
passed or since a person last continued the ticket. Changing an error's text doesn't reset it. A review
run counts when it leaves a blocking finding open, or when its output is invalid. A review run that timed
out doesn't count: it is started once more, and two review timeouts in a row wait for a person. A
command that times out at ship, such as `verify` or a check, counts like any other failure.

At the budget, the consult pack advises once, and you get one more attempt. If that fails too, the ticket
waits for a person. Without the pack, it waits for a person at the budget.

## Consult

Consult asks a different model for advice when you are stuck. Its brief is the ticket, the diff and the
failing step's raw output, plus one question; your own story is left out. It answers `proceed`, `change`
or `stop`, and the engine keeps the advice in `.rail/journal/NN-advice.md`. It is read-only, never a gate,
and at most three run per ticket. Ask it yourself with `rail consult NN "question"`.

## Waits

A ticket waits for a person (`owner: human`) for an approval, a person's merge, the retry budget, a finding
the refuter upheld, a review that timed out twice, or an amended Done Contract. The brief says what is
needed. One act continues any wait:

```text
rail accept NN "what to do differently"
```

The note goes into your next brief, with a fresh retry budget. If it holds beyond this ticket, open a
ticket that writes it into the project's part of `AGENTS.md`, or into a rule.
