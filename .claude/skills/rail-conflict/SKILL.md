---
name: rail-conflict
description: Resolve a rebase or merge conflict by deciding the final behaviour first. Use when rail next or rail advance answers REBASING, or when any rebase or merge stops on a conflict.
---

# Resolve a conflict

- **Assumes:** a rebase onto the base branch stopped on a conflict in the ticket's worktree.
- **Produces:** a finished rebase in which both the base's change and yours still do what they were meant
  to do.
- **Done means:** `git diff --check` reports no conflict markers, the ticket's checks pass, and the rebase
  is finished. Then run the command the brief names, `rail advance NN`.

While the rebase is open, `rail next`, `rail advance` and `rail save` only tell you how to end it. That is
on purpose: a commit made in the middle would be lost.

## 1. See all three sides

For each conflicted file, read what the base changed and what you changed against their common ancestor:
`git diff :1:FILE :2:FILE` and `git diff :1:FILE :3:FILE`. Setting `merge.conflictstyle` to `zdiff3` shows
the ancestor inside the markers.

## 2. Decide the behaviour, then write the code

Say what the file should do once both changes are in. Write code that does that. Choosing "mine" or
"theirs" line by line can produce a file that does neither.

- **The base's change belongs to another ticket and conflicts with yours in behaviour:** keep the base's
  behaviour, and build yours on top of it. That ticket is already merged; yours is not.
- **A generated file or a lock file conflicts:** resolve its sources, then generate it again. Don't edit it
  by hand.
- **You can't tell what the base's change was for:** read its commit message and its ticket in
  `.rail/tickets/` before you decide.

## 3. Finish

Run `git diff --check`, then the ticket's `Check:` lines and `verify`. Continue with
`git rebase --continue`, and run `rail advance NN`.

If you end up with a result you don't trust, `git rebase --abort` returns the worktree to where it was, and
you can start again.
