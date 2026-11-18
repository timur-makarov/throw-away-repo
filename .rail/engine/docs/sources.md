# Sources

A source turns one signal into tickets: failed CI runs, an error tracker's export, last week's merges. It
is a file, `.rail/sources/NAME.md`, with TOML front matter between `+++` lines, as a ticket has, and a body
that is the prompt.

```markdown
+++
fetch = "gh run list --status failure --limit 20 --json name,headSha,url"   # its output is the signal
max_open = 3        # at most this many of this source's tickets open (not merged, not dropped) at once
+++

What to look for in the signal, what is worth a ticket, and how to build the key.
```

A source files tickets and never edits. The engine schedules nothing: something runs the source.

## rail source NAME

`rail source NAME` runs `fetch` in the project's root, the same way as the other commands: through
`bash -o pipefail`, within `[commands] timeout_secs`, with `RAIL_BASE` set to the base branch's ref. It
answers with an `agent_task` whose brief holds:

- the source's prompt;
- what `fetch` printed, cut to its last 20,000 characters (the brief says when it was cut);
- how many tickets the agent may file now: `max_open` minus the source's open tickets;
- the `external_id`s of the source's tickets that exist, so the agent doesn't draft them again;
- the rules: file tickets only and change no file; write each ticket to a file outside the repository and
  file it with `rail add FILE`; set its `external_id` to `NAME#KEY`, where KEY names the underlying problem,
  so the same problem found on a later run gets the same key; when nothing is worth a ticket, file none.

When `max_open` tickets are open, it says so and `fetch` doesn't run. When `fetch` fails or times out, the
answer carries the failure and nothing is filed. `rail source` with no name lists the sources, each with its
open tickets and `max_open`.

A source's name takes lowercase letters, digits and hyphens. `sweep`, `red-base` and `github` are taken:
the engine writes those `external_id`s itself. A malformed source file is an error that names the file,
and `rail doctor` checks every source file.

## A source's tickets

A ticket belongs to a source when its `external_id` starts with `NAME#` and `.rail/sources/NAME.md` exists.
`rail add` refuses such a ticket when one with the same `external_id` is open, and when the source has
`max_open` tickets open. Any other ticket is taken as before, a repeated `external_id` included.

Otherwise a source's ticket is an ordinary ticket. An AUTO ticket that passes lint is accepted by the
engine at `rail add`; a PERSON ticket waits for a person to approve its contract. The sweep's tickets follow
the same rule. Tier, review and merge don't change.

`rail stats` counts each source's tickets: filed, merged, reverted, dropped and open, for the tickets
requested in the period.

## Running a source

A scheduled cloud task runs one source. Its prompt is: Run `rail source NAME --json` and do its brief.
Make one task per source, on the schedule that suits the signal (`rail docs cloud`). The source only files
tickets; the runner picks them up on its own schedule.

## The seed source

`rail init` copies one source, `.rail/sources/weekly-review.md`. Its `fetch` lists the commits merged to
the base branch in the last seven days with the files each one changed, and its prompt looks across them
for what a review of one change can't see: the same logic written twice, code in the wrong area, behaviour
no test exercises together, a doc the week made wrong. It files at most three tickets. A project set up
before sources existed doesn't have it: copy `seed/sources/weekly-review.md` from the framework to use it.

## Two more examples

Failed CI runs on the base branch:

```markdown
+++
fetch = 'gh run list --branch main --status failure --limit 20 --json databaseId,name,headSha,createdAt,url'
max_open = 2
+++

These are the CI runs that failed on main. For each workflow that fails, read its log with
`gh run view ID --log-failed`. A failure is worth a ticket when it repeats or when it fails on the latest
commit; a run that failed once and passed afterwards is a flake: file it only when the same test flaked
more than once. Write the failing command as the ticket's `Check:` line.

Key: the workflow and the failing test, such as `ci-test/tests/test_billing.py::test_total`.
```

An error tracker's export, a file the tracker writes or a job downloads:

```markdown
+++
fetch = "cat exports/errors-latest.json"
max_open = 3
+++

These are the errors from production in the last day, grouped by fingerprint. Find the code that raises
each of the five most frequent, and file a ticket for each one that comes from a bug in this repository,
not from bad input or a third party. Give the stack trace's top frames in the ticket's `## Why`, and a
`Check:` line that reproduces the error.

Key: the error's fingerprint, such as `sentry-4f2a9c`.
```
