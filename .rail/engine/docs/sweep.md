# The sweep

The sweep looks back over what merged since the last sweep. It does two things:

- It reviews the changes that merged with no reviewer: a ticket whose every changed file is in
  `[review] skip_paths`, and a commit a person made with no ticket. These are the commits on the base branch
  that have no `Ticket:` trailer, or whose `Review:` trailer says `none`. A merge commit counts once, however
  many commits it holds.
- It gathers what reviewers left behind in every ticket that merged, reviewed or not: the findings they
  parked, and the checks they proposed for findings that were fixed. Nothing else reads these.

`rail next` offers `rail sweep` when no ticket work is waiting and either is true:

- `[sweep] after` changes (20 by default) merged with no review;
- `[sweep] every` tickets (20 by default) merged, counted by the `Ticket:` trailers on the base branch. `0`
  switches this off.

With the default config every change is reviewed, so `every` is what brings the sweep. A person can run
`rail sweep` at any time.

A sweep is itself an AUTO ticket that changes only its journal summary. It changes no product file, so it
needs no review and merges on its own. Its squash commit carries a `Sweep:` trailer, which marks where the
next sweep starts. The first sweep starts where Rail was set up.

- **Free part:** doc-lint on the base branch, and each structure rule counted over the whole tree.
- **Review part:** only when something merged with no review. One pass of the reviewer over those changes,
  looking for duplication across tickets, logic in the wrong area, weak checks, security and stale docs. It
  also reads the parked findings and the proposed checks. With nothing unreviewed there is no model run: the
  journal gets a `harvest` step instead.
- **Output:** tickets, never edits, and a one-page summary in `.rail/journal/NN-summary.md`: the free part,
  the review's findings, the parked findings and the proposed checks by kind. The agent opens a ticket for
  each finding worth one, and one ticket "make it a check: ..." for each kind of proposed check, so a mistake
  that could happen again ends as a test, a rule or a lint.

When the sweep finds nothing (no unreviewed change, no parked finding, no proposed check, and doc-lint is
clean), the agent gets no task: `rail next` answers `SWEEP_EMPTY` with `rail advance NN`, and the sweep's
ticket merges, which moves the marker.

A sweep never blocks a merge. To turn other signals into tickets, such as failed CI runs or an error
tracker's export, write a [source](sources.md).
