---
name: rail-slice
description: Split work that is too large for one Rail ticket into tickets that each deliver testable behaviour, with the order between them. Use when a request holds several pieces of work, or its expected size is over the project's size cap.
---

# Slice into tickets

- **Assumes:** the work is understood well enough to draft tickets, and it is more than one ticket: several
  concerns, or more changed lines than `[size] cap` in `.rail/config.toml`.
- **Produces:** a set of ticket drafts, each with its own Done Contract and `scope_paths`, and `after`
  lines that give the order.
- **Done means:** each draft passes the three tests below. With a person present, they have seen the whole
  set and confirmed it before anything is filed.

## 1. Cut by behaviour

Each ticket delivers something a user, a caller or a test can observe. A ticket that only adds a table, or
only a screen with nothing behind it, can't be checked alone; cut through the layers so each ticket goes
end to end for one small behaviour.

Two exceptions come first in the order, each as its own ticket: a change that only prepares the code and
keeps behaviour the same (its contract is "the existing tests still pass"), and a test for behaviour that
has none today.

## 2. Three tests for each draft

1. **It can be checked alone.** It has a `Check:` line that fails today and passes when this ticket merges,
   with the later tickets not yet done.
2. **It fits one worker.** One agent can hold the ticket and the code it touches in one session, and the
   change stays under the size cap.
3. **Its paths are its own.** Where two drafts must edit the same files, give them an order with `after`.
   Drafts with no `after` between them may be worked at the same time, so their `scope_paths` should not
   overlap.

## 3. Order

Write `after = ["NN"]` only where a ticket really needs another one merged first. Every `after` you add
makes the set slower; every one you leave out by mistake produces a conflict.

`rail add` gives each ticket its ID when it is filed. File the tickets nothing waits for first, then use
their IDs in the `after` lines of the next ones.

## 4. Check for work that exists

Before filing, run `rail status` and look through the open tickets and issues for the same work. Say which
drafts overlap something open, and leave those out or point at the open one.

## 5. Show, then file

Show the whole set: the titles, the order, and each Done Contract. With a person present, file only what
they confirm. Each draft is filed like any ticket: `rail add FILE`, from a file outside the repository.

## When the engine offered the split

`rail advance` offers a split once when an AUTO change is over the size cap. The code is written already,
no person is present, and the brief lists the commands. Use the tests above to decide:

- The first part is the smallest one that passes test 1 with a `Check:` the ticket already has. It stays on
  the ticket's branch, and `rail amend` narrows the contract to it.
- Each remaining part becomes a draft with `after`, a line in `## Request` naming the ticket it was split
  from, and under `## Look at` the branch that holds its code.
- When no first part passes test 1, the change does not split. Change nothing and run `rail advance` again:
  a person merges it. That is a complete outcome, and a forced split that leaves the code broken between
  tickets is worse.
