# Review

Every ticket gets a review after ship. The engine launches it, so it can't be skipped or written by hand:
`advance` runs `[review] command` in the ticket's worktree with a brief on stdin, reads the `review/v1`
output, binds the run to the patch, and resets the worktree afterwards. The reviewer may run commands and
write scratch files to test an idea; all of it is thrown away.

**Which changes skip it.** `[review] skip_paths` lists paths whose changes need no reviewer, such as docs. An
AUTO ticket merges without a review when every product file it changes matches that list. The paths decide,
not the author: one changed file outside the list, and the reviewer reads the whole change. A PERSON ticket
is always reviewed. The squash commit says which happened in its `Review:` trailer (`reviewer`,
`reviewer, security seat` or `none`), and [the sweep](sweep.md) reads afterwards what merged with `none`.

**The reviewer's model** is `[review] model` in `.rail/config.toml`, such as `model = "claude-opus-5-5"`.
The engine passes it to the command as `ANTHROPIC_MODEL`, which the `claude` CLI reads, and as `RAIL_MODEL`
for any other command. Empty leaves the command's own default. The model that answered is stored with each
run and shown in the pull request's Evidence table. `[consult] model` does the same for consult.

The brief holds the ticket, the diff, the matching `## Areas` rows, the project's own part of `AGENTS.md`
(never the `## Rail` section), the project's `REVIEW.md` files, what to look for, and the do-not-report
list. On an AUTO ticket, what to look for includes a security checklist. On a re-review the brief also
holds the earlier findings and your answers.

**`REVIEW.md`** is review guidance a project writes for itself: what to always flag, what never to report.
The brief takes the one at the repository root and one in each directory above a file the change touches
(`src/api/REVIEW.md` when `src/api/x.py` changed), root first, from the ticket's branch. Together they are
cut at 8,000 characters, and the brief names the files that were cut. Every run gets them: the review, the
security seat and the refuter.

**When the checks can't show the work.** When every `Check:` line already passed on the base branch before
the work began (the `base_checks` event, `rail docs loop`), the review run's brief says so, and asks the
reviewer to look at whether the change is tested.

## Findings

Each finding has an id (`F1`, `F2`, ...), a severity, a location and a claim, and sometimes `evidence`: a
command the reviewer ran and its output.

- `blocking`: the change must not merge as it is.
- `advisory`: worth fixing, safe to merge.
- `parked`: a real problem this change didn't cause.

Answer every finding:

```text
rail answer NN F1 fixed "what you changed"
rail answer NN F2 declined "why it is not a problem"
rail answer NN F3 parked "a real problem this change didn't cause"
```

You can't decline or park a blocking finding: either answer disputes it, and a fresh refuter decides at the
next `advance`. The refuter sees the location, the claim and the evidence, not your argument. It dismisses
the finding, parks it (the problem is real, but this change didn't cause it), or upholds it. If it upholds
the finding and you still can't fix it, a person decides, with `rail answer NN F1 declined "why" --owner`
or `rail answer NN F1 parked "why" --owner`.

When you fix a finding, `advance` ships the fix and reviews the whole change again. A finding marked fixed
counts only once a later run doesn't repeat it.

## PERSON tickets

A PERSON ticket adds a security seat: a second run whose brief asks only about security. Each blocking
finding it reports goes to a refuter at once. A person merges a PERSON ticket.

**The reviewer may ask for a person.** A review or security run can return `needs_person`: one sentence on
why a person should see the change before it merges although no finding blocks it, such as a pattern other
code will copy. On an AUTO ticket the engine writes `tier_raised` with the reason `reviewer`, and the ticket
is PERSON from then on: the security seat runs next, and a person merges. A later run that doesn't ask
never lowers it. On a PERSON ticket the sentence is only recorded. Either way the sentence is kept with the
run and shown in the pull request's Risk section and in the wait for a person. A refuter's is ignored.

## What the reviewer costs and finds

`rail stats` counts, over the merged tickets, the review runs, their cost and time by role and by model, how
each finding ended, and the share of decided blocking findings that ended in a fix. See [stats](stats.md).
