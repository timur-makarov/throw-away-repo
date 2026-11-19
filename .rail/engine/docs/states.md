# States

State is derived each time from git and the journal; nothing stores it.

```text
new -> accepted -> implementing -> reviewing -> in-ci -> merge-ready -> merged
```

| State | Means |
|---|---|
| `new` | The ticket has no `accepted` event. The engine accepts an AUTO ticket once its lint passes; a person approves a PERSON ticket: `rail accept NN` |
| `accepted` | Accepted, not claimed yet |
| `implementing` | Claimed, and the current patch hasn't passed the ship steps, or the worktree has uncommitted changes |
| `reviewing` | Shipped, the change needs a review, and no complete review is bound to this patch |
| `in-ci` | Shipped and reviewed, with a remote: waiting for the required checks on the pull request |
| `merge-ready` | Ready to merge. An AUTO ticket merges with `rail advance NN`; a PERSON ticket waits for a person |
| `merged` | A squash commit with `Ticket: NN` is on the base branch |
| `dropped` | `rail drop NN` ended it, or its pull request was closed without a merge |

With a pull request, a conflict with the base or a red required check returns a shipped ticket to
`implementing`, with the check's output in the brief.

Any state can wait for a person: `owner` is `human`, and the brief says what is needed. The engine labels
the ticket's pull request `rail:needs-you`. One act continues any wait: the label `rail:go` on the pull
request, or `rail accept NN "note"`. The note, and any comments the person wrote on the pull request during
the wait, go into the agent's next brief. A person can hold any ticket by adding the label `rail:hold`. The engine never
sets that one, and never reads its own `rail:needs-you` as a hold.

A pull request merged before its ticket shipped doesn't make the ticket `merged`. It counts as the
person's approval: `rail next` records it, starts the branch again from the base, and opens a new pull
request for the work.

## The journal

`.rail/journal/` holds each ticket's evidence, written only by the engine and merged with the code:
`NN-events.jsonl` (every step and decision), `NN-review.json` (the review runs) and `NN-advice.md`
(consult's advice). Never edit it by hand. `rail docs journal` describes each file and event.
