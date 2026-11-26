# Answer review findings

- **Assumes:** a review left findings on your ticket, and the brief lists them. You are in the ticket's
  worktree.
- **Produces:** an answer to every blocking finding with `rail answer NN F1 fixed|declined|parked "why"`, and
  the fixes. An advisory finding doesn't hold the ticket: answer it too, or leave it unanswered for the sweep.
- **Done means:** no blocking finding is unanswered, the checks pass again, and you ran `rail advance`.

After your fixes the reviewer reads the whole change again. So the aim is one more round, not several.

## 1. Read all findings before you change anything

Two findings can have one cause, and a fix for one can undo another.

## 2. Test each claim

Run the command in the finding's `evidence`, or follow the named lines yourself. Then choose:

- **The claim is true.** Fix it. Then look for the same kind of mistake in the rest of your change and fix
  every place. A reviewer who found one will find the next one in the next round. Answer `fixed` and say
  what you changed.
- **The claim is false.** Answer `declined` with the fact that shows it: a command and its output, or the
  line that handles the case. If the finding is blocking, your answer starts a dispute. A fresh refuter
  decides it from the claim and the evidence and does not read your argument. So make the code show it:
  add a test that demonstrates the behaviour.
- **The problem is real and your change didn't cause it.** Answer `parked`, with what shows the problem
  was there before your change. On a blocking finding this starts a dispute too: the refuter decides
  whether your change caused it.

An answer states what is true or what changed. It needs no thanks and no agreement.

## 3. Keep each fix inside its finding

Don't tidy other code while you are there. A larger diff is a larger re-review.

When a finding carries a `check` (a test, rule or lint that would catch this kind of mistake) and it fits
inside `scope_paths`, add it. Outside the scope, open a ticket for it with `rail add`.

## 4. Before `rail advance`

Run every `Check:` line and `verify` again, read the diff of your fixes once, and update `## Look at` if
what a reader should check has changed.
