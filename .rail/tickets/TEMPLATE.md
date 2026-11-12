+++
title = "Say what changes, as an imperative"
tier = "LOW"                       # LOW, MEDIUM or HIGH: the author's choice; the engine may only raise it
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
- ASSUMED: (a fact the work rests on; after the claim, verify it and change ASSUMED to VERIFIED, or ask)

## Look at
(written before ship: what a reader of the change should check)

## Split
(optional work breakdown)
