---
name: rail-blast-radius
description: Map what a planned change touches and what it could break, by reading the code, and turn that into a ticket's scope, tier and size. Use before drafting a Rail ticket for a change to existing code, or when asked for the impact or risk of a change.
---

# Blast radius

- **Assumes:** there is a change to judge: a request, a draft ticket, an issue or a branch. You only read.
  You change no code, data or outside system.
- **Produces:** a short report: what the change touches, what it could break, and from that the ticket's
  `scope_paths`, tier and expected size.
- **Done means:** every item is marked **confirmed**, with a `file:line` or a symbol, or **inferred**, with
  the reason; and what you could not check is listed.

## 1. Find where the change lands

Find the code the change will modify: symbols, routes, commands, tables, settings. If the request is too
vague to place, say which two or three places it could mean, and ask, or pick one and record it as an
assumption when no person is present.

When the change rests on something outside the repository (a library's behaviour, an API's limits, a format
someone else defines), look it up now: the installed dependency's own source and docs first, then the web.
What you checked goes into the ticket as a fact, with where you read it; what you could not check goes in as
an `ASSUMED:` row for the worker to verify.

## 2. Trace outward

From each place, follow what depends on it. Stop where the change can't reach, and say where you stopped.

- **Callers:** what imports, calls, renders, queries or schedules this code.
- **Data:** changes to a schema, a migration, a backfill, writes to records that already exist. A change
  that alters or deletes existing data is the hardest to undo.
- **Contracts:** what something outside this code relies on. The shape of responses and files, events,
  flags of a command, names of settings and environment variables, URLs.
- **Untested neighbours:** behaviour that shares code with the change and that no test exercises. Check what
  the tests call, not what their files are named.
- **Outside the repository:** other services, cost, permissions, the order of deploys.

## 3. Turn it into the contract

Read `.rail/config.toml` for `[kinds]`, `person_paths`, `migration_paths` and `[size] cap`.

| From the trace | Goes into the ticket as |
|---|---|
| The paths the change must edit | `scope_paths`, as narrow as the trace allows |
| A kind of change a revert doesn't undo: `data-loss`, `data-shape`, `data-exposure`, `external-effect`, `access`, `runs-with-secrets`, `controls`, `infrastructure`, `money`, `licence`, `public-release` | tier `PERSON`, `person_reason` naming it (several separated by `; `); for a migration, `reversibility` and `rollback` |
| Each untested neighbour | a `Check:` line that exercises it, or a ticket that adds the test first (`after`) |
| A contract something outside relies on | a line in `## Out of scope` saying it does not change, or a `Check:` that it still holds |
| An expected size over the cap | a split into several tickets (`rail-slice`) |

## 4. Report

Lead with the size (small, medium, large) and the one item that drives it. Then the table above, filled in.
Then one recommended next step: draft the ticket (`rail-grill`), split first (`rail-slice`), or add tests
for the untested neighbours first.

When the ticket exists already and the brief asked you to write its contract, there is no next skill: put
the scope, the tier and the checks into that ticket with the command the brief names, and file nothing new.
