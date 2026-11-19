# Tickets

A ticket is a markdown file with TOML front matter between `+++` lines. Write a draft like
`.rail/tickets/TEMPLATE.md` anywhere outside the repository (a temp file is fine), then run `rail add <file>`:
it sets the ID and commits the ticket on its own branch, so the draft can go. `## Request` and `## Split` are
optional sections. A ticket made from a GitHub issue closes the issue when it merges; with a `## Split`
section it is one part of the issue, and its pull request says `Part of #N` and leaves the issue open.

Ticket lint requires the front matter, `## Why` and `## Done Contract`. Every other section may be left out.

```markdown
+++
title = "Rotate refresh tokens on use"
tier = "AUTO"                      # AUTO or PERSON; the engine may only raise it
scope_paths = ["auth/**", "tests/auth/**"]
after = ["12"]                     # waits for 12 to merge
caused_by = ""                     # on a fix ticket
external_id = "github#123"
+++

## Why
## Done Contract
- Check: `pytest tests/auth/test_refresh.py`
## Out of scope
## Assumptions
- ASSUMED: sessions are stored server-side.
## Look at
```

- **The Done Contract** needs at least one `Check:` line with its command in backticks. A check that
  can't fail, such as `true` or `echo ok`, is rejected. Checks run through `bash -o pipefail`, so a
  failure anywhere in a pipe fails the check: `pytest | tail -20` fails with pytest, and `pytest | head`
  fails when head cuts pytest off before it ends. Write checks that fail before the work: at the first
  claim, `next` runs each one once on the base branch and records whether it was already green there
  (`rail docs loop`). That is only recorded, and never stops the ticket.
- **ASSUMED rows** are verified after the claim: change `ASSUMED:` to `VERIFIED:` and say how. A row
  nobody can check in the code or the docs is a choice: the worker decides it and writes `VERIFIED: decided,
  not checked:`, the reason, and what it costs if wrong. An open row blocks ship.
- **Look at** is written before ship: what a reader of the change should check.
- The ticket file and the journal are outside `scope_paths` on purpose: editing the ticket (VERIFIED rows,
  Look at) never fails the scope check. That holds for the ticket's own file only. Another ticket's file on
  its branch fails the scope check: a new ticket comes in through `rail add`, on its own branch.
- **The tier** says who accepts the contract and who merges. On `AUTO` the engine does both, after the
  checks and the review. On `PERSON` a person approves the contract and merges. Write `PERSON` when a person
  should see this change. The engine makes a ticket PERSON by itself in four cases: its `scope_paths` reach
  `person_paths` or `migration_paths` (at add), it changes a file on those paths (at ship), it changes
  more lines than `[size] cap` (at ship), or the reviewer asks for a person (at review). Over the cap, the
  first ship offers a split instead (`rail docs loop`); only the next ship over the cap raises the tier. A tier never goes down.
- **A migration ticket**, one whose change touches `migration_paths`, sets two more keys in the front
  matter, each a sentence: `reversibility` (how old and new code both run against the change, such as expand
  then contract) and `rollback` (the down step, and what it loses). Ship fails at `migration` without them,
  and the pull request's Risk section shows both.
- **Two tickets never work the same paths at once.** A ticket whose `scope_paths` overlap those of a ticket
  already under way is accepted and then waits (`SCOPE_OVERLAP`) until that one merges or is dropped. Give
  such tickets an order with `after` when one needs the other's result.
- **The contract** (Done Contract, scope and tier) freezes at acceptance. `rail amend NN` changes it.
- **`## Grilling`** is optional: the record of questioning the person who asked for the ticket, written by the
  agent that did it (`rail docs grill`). Ticket lint checks its shape, and `rail stats` counts it.

## A ticket is its branch

Issues labelled `rail` come in with every `rail next` when GitHub can be reached (`rail intake github` does
the same on request), and work from any other tracker with
`rail intake --external-id KEY --title T --brief FILE`. An issue whose body is a whole ticket, starting with
the `+++` line, becomes that ticket as it is, when it passes lint and its author can push to the repository:
that is how a chat bot files what it grilled out of a person (`rail docs bots`). Anything else makes a ticket
with the request, quoted, and an empty contract; `rail next` asks the agent to write it, and
`rail amend NN --file FILE` saves it. Intake is idempotent by `external_id`. Work already done on a branch
with no ticket comes in with `rail adopt BRANCH`: the ticket's branch starts from that branch's commits, and
each check must fail on the base and pass on the branch before the ticket is filed (`rail docs adopt`).

`add` takes the next ID, makes the branch `NN-slug`, and commits the ticket there without touching your
checkout. With a remote, the ID is taken by moving one counter branch, `rail/ids`, a commit forward: if
another clone took the ID first, the push is refused and `add` takes the next one. Without a remote, a
folder in the git directory does the same. An ID is never reused, and `rail/ids` is the only branch the
IDs need, so leave it in place.
