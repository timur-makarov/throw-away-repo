---
name: rail-self-check
description: Check your own finished change before rail advance, so the reviewer finds less and the ticket passes in fewer rounds. Use when a ticket's work looks complete, before shipping it.
---

# Self-check before shipping

- **Assumes:** you think the change is complete. You are in the ticket's worktree.
- **Produces:** the problems you found, fixed; and a `## Look at` section that says what you did not check.
- **Done means:** every step below is done or skipped for a reason this page allows.

Each review round costs a full review of the change. A problem you remove here costs one edit.

## 1. Run the proof again and read it

Run each `Check:` line and the project's `verify` command now. "It passes" means you saw the output in this
session, after your last edit. Output from before the last edit does not count.

## 2. Read the whole diff

Read `git diff` against the base branch from top to bottom. For each hunk ask whether the contract needs it.
Remove what it doesn't need: debug output, dead code, comments that tell the story of the change, edits you
made on the way and no longer use.

## 3. Ask a fresh reader

Start a subagent that has not seen your work. Give it the path of the ticket file and the command that shows
the diff. Do not give it your summary or your reasons: a reader who is told the conclusion tends to agree
with it.

Ask it for three things:

- for each Done Contract item, whether the change meets it, with `file:line`;
- concrete inputs or sequences that go wrong;
- only findings it can back with a command and its output, or with a trace through named lines.

Run any command it cites yourself before you act on the finding.

You may skip the fresh reader when the diff is under about 30 changed lines in one file and touches none of
the project's `person_paths`.

## 4. Look outside the diff

The reviewer reads the diff; breakage often sits next to it. Check what depends on what you changed: callers,
stored data, the shape of responses and files, names of settings and environment variables. For each, state
the one fact that keeps the change safe and how far you proved it: "read the caller" or "ran it".

## 5. Rule out a false green

Check that none of these happened, even by accident:

- a test skipped, deleted or made weaker;
- an expected value copied from the program's own output;
- a threshold lowered, or a lint or type error silenced;
- a `Check:` line edited without `rail amend`.

If a test was wrong and you changed it, say so in `## Look at`, with the reason.

## 6. Write `## Look at`

Say what a reader should check first, and list what you did not test in the form
"not tested: X, because Y". A gap you name is information. A gap you leave out looks like a pass.

For each fact you state there, say how you know it. **Confirmed** means you saw it in this session: give
the command and what it printed, or the `file:line`. **Inferred** means it follows from what you saw: give
the reason. When you are not sure which, write inferred.
