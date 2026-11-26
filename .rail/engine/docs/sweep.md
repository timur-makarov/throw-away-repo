# The sweep

The sweep looks back over what merged since the last sweep. It does two things:

- It reviews the changes that merged with no reviewer: a ticket whose every changed file is in
  `[review] skip_paths`, and a commit a person made with no ticket. These are the commits on the base branch
  that have no `Ticket:` trailer, or whose `Review:` trailer says `none`. A merge commit counts once, however
  many commits it holds.
- It gathers what reviewers left behind in every ticket that merged, reviewed or not: the findings they
  parked, the advisory findings the author left open, and the checks they proposed for findings that were
  fixed. Nothing else reads these.

`rail next` offers `rail sweep` when no ticket work is waiting and either is true:

- `[sweep] after` changes (20 by default) merged with no review;
- `[sweep] every` tickets (20 by default) merged, counted by the `Ticket:` trailers on the base branch. `0`
  switches this off.

With the default config every change is reviewed, so `every` is what brings the sweep. A person can run
`rail sweep` at any time.

A sweep is itself an AUTO ticket that changes only its journal summary. It changes no product file, so it
needs no review and merges on its own. Its squash commit carries a `Sweep:` trailer, which marks where the
next sweep starts. The first sweep starts where Rail was set up.

- **Free part:** doc-lint on the base branch, each structure rule counted over the whole tree, and the
  manifests no `[[profiles]]` entry covers (`rail docs languages`, "A language added later").
- **Review part:** only when something merged with no review. One pass of the reviewer over those changes,
  looking for duplication across tickets, logic in the wrong area, weak checks, security and stale docs. It
  also reads the parked and open advisory findings and the proposed checks. With nothing unreviewed there is no model run: the
  journal gets a `harvest` step instead.
- **Patterns in the worker runs:** each `rail work` run records the dead ends its tool calls show, with a short
  key each (`rail docs journal`, the `worked` event): a command that failed before it first passed, a command
  the machine doesn't have, a call a rule or the guard denied, a file read more than twice. The same key in the
  runs of three or more tickets merged since the last sweep is a pattern: something the project could have
  told the worker. No model reads for this, and the run logs, which are never committed, aren't needed.
- **Flaky checks:** a command that both failed and passed on the same code (`rail docs retries`) in two or more
  tickets merged since the last sweep. Commands are matched as failure signatures are, with numbers, hashes and
  paths left out. The summary gives each with a `Check:` line that runs it 20 times in a row.
- **Output:** tickets, never edits, and a one-page summary in `.rail/journal/NN-summary.md`: the free part,
  the review's findings, the parked and open advisory findings, the proposed checks by kind, the patterns and the flaky checks. The agent opens a ticket for
  each finding that names something wrong (a finding about style gets none), and one ticket
  "make it a check: ..." for each kind of proposed check, so a mistake that could happen again ends as a
  test, a rule or a lint. It opens one ticket for each pattern, for what would have told the worker: a `setup`
  or `provision` command, a line in the project's part of `AGENTS.md`, or a guide's text; and one ticket for each
  flaky check, to make it deterministic, with the `Check:` line the summary gives. Filing tickets is writing contracts, so the answer (`SWEEP_TICKETS`) names
  `[worker] contract`'s model and effort, and `rail work NN` runs it like any ticket's work: a script that
  drives Rail with `rail next`, `rail work` and `rail advance` goes through a sweep with no step of its own.

When the sweep finds nothing (no unreviewed change, no parked or open advisory finding, no proposed check, no
pattern, no flaky check, no language without a profile, and doc-lint is clean), the agent gets no task: `rail next` answers `SWEEP_EMPTY` with `rail advance NN`, and the sweep's
ticket merges, which moves the marker.

A sweep never blocks a merge. To turn other signals into tickets, such as failed CI runs or an error
tracker's export, write a [source](sources.md).
