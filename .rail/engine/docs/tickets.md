# Tickets

A ticket is a markdown file with TOML front matter between `+++` lines. Write a draft like
`.rail/tickets/TEMPLATE.md` anywhere outside the repository (a temp file is fine), then run `rail add <file>`:
it sets the ID and commits the ticket on its own branch, so the draft can go. Its answer ends with a line for a
session that filed a person's request: stop there and tell them the ticket number, since another session builds
it. `## Request` and `## Split` are optional sections. A ticket made from a GitHub issue closes the issue when
it merges; with a `## Split` section it is one part of the issue, and its pull request says `Part of #N` and
leaves the issue open.

Ticket lint requires the front matter, `## Why` and `## Done Contract`. Every other section may be left out.

```markdown
+++
title = "Rotate refresh tokens on use"
tier = "AUTO"                      # AUTO or PERSON; the engine may only raise it
person_reason = ""                 # on PERSON: a kind's id and where, such as "access: auth/refresh.py";
                                   # separate several with "; "
scope_paths = ["auth/**", "tests/auth/**"]
after = ["12"]                     # waits for 12 to merge
caused_by = ""                     # on a fix ticket
external_id = "github#123"
kind = ""                          # "revert" on a ticket that takes another one out; then reverts = "NN"
+++

## Why
## Done Contract
- Check: `pytest tests/auth/test_refresh.py`
## Out of scope
## Assumptions
- ASSUMED: sessions are stored server-side.
## Look at
## Tried
```

- **The Done Contract** needs at least one `Check:` line with its command in backticks. A check that
  can't fail, such as `true` or `echo ok`, is rejected. Checks run through `bash -o pipefail`, so a
  failure anywhere in a pipe fails the check: `pytest | tail -20` fails with pytest, and `pytest | head`
  fails when head cuts pytest off before it ends. `| grep -q` cuts a command off the same way, at its
  first match: use `grep` without `-q`. Write checks that fail before the work: at the first
  claim, `next` runs each one once on the base branch and records whether it was already green there
  (`rail docs loop`). That is only recorded, and never stops the ticket.
- **ASSUMED rows** are verified after the claim: change `ASSUMED:` to `VERIFIED:` and say how. A row
  nobody can check in the code or the docs is a choice: the worker decides it and writes `VERIFIED: decided,
  not checked:`, the reason, and what it costs if wrong. An open row blocks ship.
- **Look at** is written before ship: what a reader of the change should check. Two kinds of line there are
  read by the engine: `not tested: X, because Y`, and `Noticed:` for a problem seen outside the ticket and left
  alone.
- **Tried** is written after a failed attempt: one line for what was tried and how it failed.
- The ticket file and the journal are outside `scope_paths` on purpose: editing the ticket (VERIFIED rows,
  Look at) never fails the scope check. That holds for the ticket's own file only. Another ticket's file on
  its branch fails the scope check: a new ticket comes in through `rail add`, on its own branch.
- **The tier** says who accepts the contract and who merges. On `AUTO` the engine does both, after the
  checks and the review. On `PERSON` a person approves the contract and merges. A person is asked only about
  what a revert doesn't undo: write `PERSON` when the change does something of a kind in `rail docs kinds`, and
  name it in `person_reason`: the kind's id, a colon, and where, such as `"access: auth/refresh.py"`, with
  `"; "` between several. Ticket lint fails a PERSON ticket without one, or with a part that names no kind. The engine makes a ticket PERSON by itself in three cases: its
  `scope_paths` reach the paths of a kind, which are `[kinds]`, `person_paths` (`controls`) and
  `migration_paths` (`data-loss`), at add or amend, where it writes the tier and `person_reason` into the
  ticket; it changes a file on those paths (at ship); or the reviewer lists something of a kind in the change (at review). Size raises
  no tier: over `[size] cap`, the first ship offers a split (`rail docs loop`), and the next goes on to review.
  A tier never goes down.
- **A migration ticket**, one whose change touches `migration_paths`, sets two more keys in the front
  matter, each a sentence: `reversibility` (how old and new code both run against the change, such as expand
  then contract) and `rollback` (the down step, and what it loses). Ship fails at `migration` without them,
  and the pull request's Risk section shows both.
- **Two tickets never work the same paths at once.** A ticket whose `scope_paths` overlap those of a ticket
  already under way is accepted and then waits (`SCOPE_OVERLAP`) until that one merges or is dropped. Give
  such tickets an order with `after` when one needs the other's result.
- **The contract** (Done Contract, scope and tier) freezes at acceptance. `rail amend NN "why"` changes it.
- **`## Grilling`** is optional: the record of questioning the person who asked for the ticket, written by the
  agent that did it (`rail docs grill`). Ticket lint checks its shape, and `rail stats` counts it.

## What a ticket carries on

A worker starts with none of what the last one knew: a new session, the next rung of the worker ladder, or
another ticket months later. So the engine puts what was learned into the brief, where it applies.

- **Why, and what was decided.** The implement brief carries the ticket's `## Why` and each `VERIFIED: decided,
  not checked:` row: the choices made when the ticket was written, which nobody could check.
- **What was tried.** After a ship fails at `verify`, at a `Check:` line or at a sensor, the brief asks for one
  line under `## Tried`. Every later brief for that ticket's work lists those lines, so the next attempt doesn't
  repeat one. Consult gets the ticket without `## Tried` and `## Look at`: it is asked for a second opinion,
  and the worker's own story would lead it.
- **What earlier tickets left.** The implement brief lists the last five merged tickets whose change touched
  the ticket's `scope_paths`, newest first: the title, the first line of `## Why`, the decided rows, and the
  `not tested:` and `Noticed:` lines. Under them are up to ten `SHORTCUT(NN)`, `TODO(NN)` and `FIXME(NN)`
  markers that stand in those paths on the base branch. `rail context NN` gives the same as `history`.
- **Work left for later names its ticket.** The seed rule `todo-names-its-ticket` refuses a new `TODO:` or
  `FIXME:` with no number: file the work with `rail add`, then write `TODO(NN): what is left`. `SHORTCUT(NN)`
  names the ticket that cut the corner; `TODO(NN)` names the one that will do the work. The rule is a text
  match (`rail docs rules`): it doesn't check that ticket NN exists.

## A revert is a ticket

A ticket with `kind = "revert"` and `reverts = "NN"` takes merged ticket NN out again. Put the label
`rail:revert` on NN's merged pull request and the next `rail next` files it: the label is a person's word,
since only someone who may triage the repository can set one, and it approves the contract. With no remote,
file one with `rail add`.

- **Its change** is the reverse of NN's squash commit on the project's own files. `.rail/tickets` and
  `.rail/journal` are left alone: a whole `git revert` would delete NN's ticket and journal, which the scope
  step refuses. The engine puts the reverse into the worktree at the claim, so `rail next` answers
  `REVERT_SHIP`, a script: `rail advance`.
- **Its contract is built in.** It needs no `Check:` line: at ship, `checks` compares the change with the
  reverse of NN's, and `verify` runs as always. `scope_paths` are the files NN changed.
- **A revert made by hand** is accepted in two cases, and the reviewer reads it like any change: the reverse
  no longer applies, because later tickets changed the same lines; or it applies and `verify` failed on it,
  because later work depends on what it removes. The answer is then `REVERT`, an agent's task, and the brief
  says which case it is. While the exact reverse applies and has not failed `verify`, any other change fails
  `checks`.
- **What the label files:** the ticket's `## Why` quotes what people who can push wrote on NN's pull request
  after the merge; `caused_by` is NN; `external_id` is `revert#` and the pull request's number, so one pull
  request has one revert open at a time. The engine comments on the pull request and takes the label off. A
  pull request that merged no ticket gets the comment and no ticket.
- **After a failed deploy to dev** the intake files the revert itself, with `external_id` `smoke#` and the
  issue's number, and the fix ticket comes `after` it (`rail docs environments`).
- **Its tier** follows its paths like any ticket's. A revert of a change on a kind's paths is PERSON: the
  label counted as the approval of its contract, and a person still merges it.
- **Its squash commit** carries `Reverts: <sha>`, which `rail stats` counts as a revert of NN.
- **A brake doesn't stop it** (`rail docs cloud`): `rail:stop` can't block its own way out.

## A ticket is its branch

Issues labelled `rail` come in with every `rail next` when GitHub can be reached (`rail intake github` does
the same on request), and work from any other tracker with
`rail intake --external-id KEY --title T --brief FILE`. An issue whose body is a whole ticket, starting with
the `+++` line, becomes that ticket as it is, when it passes lint and its author can push to the repository:
that is how a chat bot files what it grilled out of a person (`rail docs bots`). Anything else makes a ticket
with the request, quoted, and an empty contract; `rail next` asks the agent to write it, and
`rail amend NN --file FILE` saves it. Intake is idempotent by `external_id`.

**Text a person couldn't see doesn't reach the agent.** GitHub hides an HTML comment (`<!-- ... -->`) when it
shows an issue, so the person who labelled the issue never read it. Intake removes every such comment before
it makes the ticket, and before it checks a whole ticket; a comment with no `-->` takes the rest of the text
with it, as it does on the page. A comment inside a fenced code block that opens at the start of a line, or
inside a code span on one line, is shown as text and stays. Where GitHub might read the Markdown differently
(a fence inside a list or a quote, raw HTML around it), the comment goes: the rule errs towards removing. The
`requested` event records how many were removed (`hidden_removed`), and `rail stats` counts the tickets. A
person's pull request comments, which reach the next brief, are read the same way. Other ways to hide text
(a zero-width character, an attribute of a tag) are not looked for.

Work already done on a branch
with no ticket comes in with `rail adopt BRANCH`: the ticket's branch starts from that branch's commits, and
each check must fail on the base and pass on the branch before the ticket is filed (`rail docs adopt`).

`add` takes the next ID, makes the branch `NN-slug`, and commits the ticket there without touching your
checkout. With a remote, the ID is taken by moving one counter branch, `rail/ids`, a commit forward: if
another clone took the ID first, the push is refused and `add` takes the next one. Without a remote, a
folder in the git directory does the same. An ID is never reused, and `rail/ids` is the only branch the
IDs need, so leave it in place.
