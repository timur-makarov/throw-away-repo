# Tickets

A ticket is a markdown file with TOML front matter between `+++` lines. Write a draft like
`.rail/tickets/TEMPLATE.md` anywhere outside the repository (a temp file is fine), then run `rail add <file>`:
it sets the ID and commits the ticket on its own branch, so the draft can go. `## Request` and `## Split` are
optional sections.

```markdown
+++
title = "Rotate refresh tokens on use"
tier = "MEDIUM"                    # LOW, MEDIUM or HIGH; the engine may only raise it
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
  can't fail, such as `true` or `echo ok`, is rejected.
- **ASSUMED rows** are verified after the claim: change `ASSUMED:` to `VERIFIED:` and say how. An open
  row blocks ship.
- **Look at** is written before ship: what a reader of the change should check.
- The ticket file and the journal are outside `scope_paths` on purpose: editing the ticket (VERIFIED rows,
  Look at) never fails the scope check.
- **The tier** is the highest of the author's choice, the floors that `risk_paths` and `migration_paths`
  set from `scope_paths` at add, and the size cap at ship. Tickets touching `migration_paths` must set
  `reversibility` and `rollback`.
- **The contract** (Done Contract, scope and tier) freezes at acceptance. `rail amend NN` changes it.

## A ticket is its branch

Issues labelled `rail` come in with every `rail next` when GitHub can be reached (`rail intake github` does
the same on request), and work from any other tracker with
`rail intake --external-id KEY --title T --brief FILE`. Each makes a ticket with the request and an empty
contract; `rail next` asks the agent to write it, and `rail amend NN --file FILE` saves it. Intake is
idempotent by `external_id`.

`add` takes the next ID, makes the branch `NN-slug`, and commits the ticket there without touching your
checkout. With a remote, the ID is taken by moving one counter branch, `rail/ids`, a commit forward: if
another clone took the ID first, the push is refused and `add` takes the next one. Without a remote, a
folder in the git directory does the same. An ID is never reused, and `rail/ids` is the only branch the
IDs need, so leave it in place.
