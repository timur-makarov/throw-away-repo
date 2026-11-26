+++
title = "Say what changes, as an imperative"
tier = "AUTO"                      # AUTO: the reviewer checks it, the engine merges. PERSON: a person approves this
                                   # contract and merges. A kind's paths can raise AUTO to PERSON; nothing lowers it
person_reason = ""                 # on PERSON: what a revert doesn't undo, as a kind's id and where, such as
                                   # "access: src/auth/session.py". Separate several with "; "
scope_paths = ["src/feature/**"]   # globs; a change outside them fails at ship
after = []                         # ticket IDs that must merge first
caused_by = ""                     # on a fix ticket: the ticket that caused the defect
external_id = ""                   # "github#123" or "PROJ-123"
+++

## Request
(optional: the words the work came in with, verbatim)

## Why
(why this change is worth making)

## Done Contract
- Check: `a command that fails today and passes when this ticket is done`

## Out of scope
- (what this ticket does not change)

## Assumptions
- ASSUMED: (a fact the work rests on; after the claim, verify it and change ASSUMED to VERIFIED; if it can't be checked, decide it and write "decided, not checked:")

## Look at
(written before ship: what a reader of the change should check; "not tested: X, because Y" for what you didn't
test; "Noticed:" for a problem outside this ticket that you left alone)

## Tried
(written after a failed attempt: one line for what was tried and how it failed)

## Split
(optional work breakdown)
