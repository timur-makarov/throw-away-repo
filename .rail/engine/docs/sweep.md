# The sweep

LOW tickets merge with no reviewer. The sweep reviews them afterwards. Once `[sweep] after` LOW tickets and
ticketless commits (20 by default) have merged since the last sweep, `rail next` offers `rail sweep` when no
ticket work is waiting. A person can run `rail sweep` at any time.

A sweep is itself a LOW ticket that changes only its journal summary, so it merges on its own. Its squash
commit carries a `Sweep:` trailer, which marks where the next sweep starts. The first sweep starts where
Rail was set up.

- **Free part:** doc-lint on the base branch, and each structure rule counted over the whole tree.
- **Review part:** one pass of the reviewer over the combined changes, looking for duplication across
  tickets, logic in the wrong area, weak checks, security and stale docs. It also reads the findings parked
  in those tickets and the checks reviewers proposed for fixed findings.
- **Output:** tickets, never edits, and a one-page summary in `.rail/journal/NN-summary.md`. The agent opens
  a ticket for each finding worth one, and one ticket "make it a check: ..." for each kind of proposed check,
  so a mistake that could happen again ends as a test, a rule or a lint.

A sweep never blocks a merge.
