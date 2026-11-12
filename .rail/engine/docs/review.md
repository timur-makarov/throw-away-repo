# Review

MEDIUM and HIGH tickets get a review after ship. The engine launches it, so it can't be skipped or written
by hand: `advance` runs `[review] command` in the ticket's worktree with a brief on stdin, reads the
`review/v1` output, binds the run to the patch, and resets the worktree afterwards. The reviewer may run
commands and write scratch files to test an idea; all of it is thrown away.

The brief holds the ticket, the diff, the matching `## Areas` rows, the project's own part of `AGENTS.md`
(never the `## Rail` section), what to look for, and the do-not-report list. On a re-review it also holds
the earlier findings and your answers.

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

You can't decline a blocking finding: declining one disputes it, and a fresh refuter decides at the next
`advance`. The refuter sees the location, the claim and the evidence, not your argument. If it upholds the
finding and you still can't fix it, a person decides, with `rail answer NN F1 declined "why" --owner`.

When you fix a finding, `advance` ships the fix and reviews the whole change again. A finding marked fixed
counts only once a later run doesn't repeat it.

## HIGH

HIGH adds a security seat: a second run whose brief asks only about security. Each blocking finding it
reports goes to a refuter at once. A person merges HIGH.
