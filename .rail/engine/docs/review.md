# Review

Every ticket gets a review after ship. The engine launches it, so the agent can't skip it or write it by hand:
`advance` runs `[review] command` in the ticket's worktree with a brief on stdin, reads the `review/v1`
output, binds the run to the patch, and resets the worktree afterwards. The reviewer may run commands and
write scratch files to test an idea; all of it is thrown away.

**The engine runs each finding's evidence again.** After the run, the engine restores the tracked files
(`git reset --hard` to the reviewed commit), keeping the reviewer's untracked scratch files. It reads the output,
then runs each finding's `evidence.command` in the worktree with `timeout_secs`, and only then removes the
scratch files (`git clean -fdq`, after another reset). It records the re-run's exit and output's tail, and
`reproduced`: whether every line the reviewer quoted shows up in the re-run's output, with numbers, hashes and
paths left out. When the command names an untracked file, such as `sh probe.sh`, the file's text is kept with
the evidence and shown to the author with the finding. A finding whose evidence doesn't reproduce stays as it
is: nothing is decided from `reproduced`; it is a record for measuring the reviewer. A re-run that passes
`timeout_secs` is recorded with no exit and fails nothing.

**Which changes skip it.** `[review] skip_paths` lists paths whose changes need no reviewer, such as docs. An
AUTO ticket merges without a review when every product file it changes matches that list. The paths decide,
not the author: one changed file outside the list, and the reviewer reads the whole change. A PERSON ticket
is always reviewed. The squash commit says which happened in its `Review:` trailer (`reviewer`,
`reviewer, security seat` or `none`), and [the sweep](sweep.md) reads afterwards what merged with `none`.

**The reviewer's model** is `[review] model` in `.rail/config.toml`, such as `model = "claude-opus-5-5"`.
The engine passes it to the command as `ANTHROPIC_MODEL`, which the `claude` CLI reads, and as `RAIL_MODEL`
for any other command. Empty leaves the command's own default. The model that answered is stored with each
run and shown in the pull request's Evidence table. `[consult] model` does the same for consult.

The seed sets the reviewer to `claude-opus-5-5` and consult to `claude-fable-5-2`, both at high effort. The
effort is the `--effort high` flag in each command, since the engine passes a model and no effort. The refuter,
the security seat and the sweep's review run through `[review] command`, so they get the same model and effort.

The brief holds the ticket, the diff, the matching `## Areas` rows, the project's own part of `AGENTS.md`
(never the `## Rail` section), the project's `REVIEW.md` files, what to look for, and the do-not-report
list. On an AUTO ticket, what to look for includes a security checklist. On a re-review the brief also
holds the earlier findings and your answers.

**`REVIEW.md`** is review guidance a project writes for itself: what to always flag, what never to report.
The brief takes the one at the repository root and one in each directory above a file the change touches
(`src/api/REVIEW.md` when `src/api/x.py` changed), root first. Together they are
cut at 8,000 characters, and the brief names the files that were cut. Every run gets them: the review, the
security seat and the refuter.

**What the reviewer is told comes from the base branch, not from the ticket.** The `REVIEW.md` files are read
from the base, so one that a ticket adds or edits counts from the next ticket on; the ticket's own review sees
that change only in the diff. Before each run the engine also writes the base's `.rail/engine/reviewer.md` and
`.rail/engine/review-v1.json` to a temporary folder and passes their paths as `RAIL_REVIEW_PROMPT` and
`RAIL_REVIEW_SCHEMA`; the seed's command reads them from there. The command runs in the ticket's worktree,
where those two files are the ticket's own copies: a command that names them by their path there lets a change
rewrite the prompt of its own review, and `rail doctor` says so.

**Flaky checks.** When a `verify` or `Check:` command both failed and passed on the patch under review, the
brief of the review and of the security seat lists it under "Flaky checks on this change": it may be an old
flake, or a race the change brought in (`rail docs retries`).

**Sensor markers.** A `SENSOR(NN): why` comment tells a sensor that its violation on that line is wrong or
accepted (`rail docs sensors`). The brief of the review and of the security seat lists each marker the change
adds under "Sensor markers this change adds", and asks for the reason to be judged.

**When the checks can't show the work.** When every `Check:` line already passed on the base branch before
the work began (the `base_checks` event, `rail docs loop`), the review run's brief says so, and asks the
reviewer to look at whether the change is tested.

**After an amend nobody approved.** When `rail amend` changed the Done Contract or the scope after the ticket was
first accepted, and no person approved it (an AUTO ticket), the review run's brief also holds the contract as first
accepted: its `Check:` lines and its scope. The reviewer blocks when the amend dropped or weakened a check so that a
fault now passes, and lets an amend that corrects a wrong check go.

## Findings

Each finding has an id (`F1`, `F2`, ...), a severity, a location and a claim, and sometimes `evidence`: a
command the reviewer ran and its output.

- `blocking`: the change must not merge as it is.
- `advisory`: worth fixing, safe to merge.
- `parked`: a real problem this change didn't cause.

Answer every blocking finding. An advisory finding doesn't hold the ticket: fix and answer it in the same
round, or leave it unanswered; it is listed in the pull request, and [the sweep](sweep.md) gathers it after
the merge.

```text
rail answer NN F1 fixed "what you changed"
rail answer NN F2 declined "why it is not a problem"
rail answer NN F3 parked "a real problem this change didn't cause"
```

You can't decline or park a blocking finding: either answer disputes it, and a fresh refuter decides at the
next `advance`. The refuter's brief has the location, the claim and the evidence, and leaves your argument out. It works in
the ticket's worktree, so the argument is in the journal there if it looks; make the code show your point. It dismisses
the finding, parks it (the problem is real, but this change didn't cause it), or upholds it. If it upholds
the finding and you still can't fix it, a person decides, with `rail answer NN F1 declined "why" --owner`
or `rail answer NN F1 parked "why" --owner`.

When you fix a finding, `advance` ships the fix and reviews the whole change again. A finding marked fixed
counts only once a later run doesn't repeat it.

## PERSON tickets

A PERSON ticket adds a security seat: a second run whose brief asks only about security. Each blocking
finding it reports goes to a refuter at once. A person merges a PERSON ticket.

**The reviewer lists what a revert doesn't undo.** A review or security run returns `kinds`: each thing in the
change of a kind in `rail docs kinds`, as `{kind, file, line, why}`, on every ticket. The engine checks each
`kind` against the list, and an unknown id makes the output invalid: the run is started once more and counts
against no one. On an AUTO ticket a non-empty `kinds` writes `tier_raised` with the reason `reviewer` and the
kinds, and the ticket is PERSON from then on: the security seat runs next, and a person merges. A later run
with none never lowers it. On a PERSON ticket the kinds are only recorded. Either way they are kept with the
run and shown in the pull request's Risk section and in the wait for a person. A refuter's are ignored. A
change that is large or new but can be reverted is not a kind: the reviewer reports its problems as findings.

The reviewer's prompt says what the common kinds look like, not only their ids. In a test of 136 model runs,
a prompt with the ids alone listed a permission check the ticket asked to widen (`access`) in 1 of 4 runs;
the prompt as it is listed each of six planted kinds in 4 of 4 runs, and 20 of 20 runs on changes with no
kind listed none.

Don't rely on it for a path you already know holds a kind. The reviewer reads the diff and can miss one; put
such paths in `[kinds]` under their kind (the auth code under `access`, the dependency manifests under
`licence`): that rule is a path match and always fires.

## What the reviewer costs and finds

`rail stats` counts, over the merged tickets, the review runs, their cost and time by role and by model, how
each finding ended, and the share of decided blocking findings that ended in a fix. See [stats](stats.md).
