---
name: rail-build
description: Work a claimed Rail ticket from its contract to a change that is ready for rail advance. Use at the start of work on a ticket, when rail next returns an agent_task for a ticket in implementing.
---

# Build a ticket

- **Assumes:** you hold a claimed ticket and work in its worktree (`cwd` in the answer of `rail next`). The
  contract (Done Contract, `scope_paths`, tier) is frozen. No person is present unless the brief says one is.
- **Produces:** a change inside `scope_paths` that makes every `Check:` pass, every `ASSUMED:` row turned
  into `VERIFIED:`, and a `## Look at` section.
- **Done means:** you ran each check in this session and saw it pass, and the self-check is done. Then
  run `rail advance`.

## 1. Read the contract before the code

Say in one sentence what a user or caller will observe after this ticket that they can't observe now. If you
can't, the contract is unclear. Nobody is there to ask, so pick the reading the `## Why` supports, write it
as an `ASSUMED:` row, and go on. If two readings need different checks, change the contract with
`rail amend NN` instead; an amend is recorded.

## 2. Run every check now

Run each `Check:` line before you change anything, and read the output.

- **It fails for the reason the ticket gives:** good. That check will show your work.
- **It fails because a file or test does not exist yet:** you write that test first (step 4).
- **It already passes:** it can't show that your work was done. Add a check that fails today, with
  `rail amend NN`. This does not apply when the ticket keeps behaviour the same on purpose (a refactor, a
  dependency update): there, "the existing tests still pass" is the right contract.

## 3. Orient cheaply

Run `rail context NN`. Read the code the change touches and the tests that call it. For reading across many
files, start a read-only subagent on a cheaper model and ask for conclusions with `file:line`. Keep the
edits and the decisions in your own context.

Verify the `ASSUMED:` rows now. They are the cheapest things to be wrong about.

## 4. Test where behaviour is visible

A good test fails when the behaviour breaks and still passes when the internals change. Put it at the seam
callers use. A test that repeats the code's own arithmetic proves nothing; no new test is better than that
one.

For a bug, first write the test that reproduces the reported symptom, and watch it fail. Then fix.

## 5. Make the smallest change that meets the contract

Before you write new code, stop at the first of these that holds:

1. The contract can be met without it.
2. This codebase already has it. Search for the helper, the pattern, or the neighbour that does the same
   thing, and use it.
3. The language's standard library or the platform has it.
4. A dependency the project already installs has it.

Only then write it, and only as much as the contract needs. A new dependency comes last: say in
`## Look at` which of the four you checked and why none served.

- **Abstraction:** add one after the second real duplication, not before.
- **Place:** the smallest change in the wrong place is a second bug. When several callers share the fault,
  fix the shared code, and check the other callers.
- **Where small does not apply:** checking input where it enters from outside, handling an error that could
  lose data, security, and anything the contract asks for.
- **A shortcut you take on purpose:** mark it with a comment `SHORTCUT(NN):` that carries this ticket's
  number, the known limit, and what to do when the limit is reached. A structure rule refuses the marker
  without a number.

- **You need a path outside `scope_paths`:** widen the scope with `rail amend NN`. Don't work around it.
- **You notice a problem the ticket didn't ask about:** leave it. Name it in `## Look at`, or open a ticket
  with `rail add`.
- **The same edit repeats in many places:** write the script. Do one place by hand, check the script gives
  the same result there, then run it everywhere.

## 6. Decide and record

When a choice comes up and no person is present, decide. Record what you chose, why, and what it costs if
you are wrong: as a `VERIFIED:` row when you could check it, in `## Look at` when you could not.

Leave a decision to a person in two cases only: the act can't be undone and reaches outside the repository,
or the contract can't be met as written. For the second, amend the contract and say why.

## 7. Before `rail advance`

Do the self-check (`rail-self-check`), then write `## Look at`: what a reader of the change should check,
and what you did not test and why.
