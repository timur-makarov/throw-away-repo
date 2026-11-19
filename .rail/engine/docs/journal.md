# The journal

`.rail/journal/` holds each ticket's record. Only the engine writes it, it is committed on the ticket's
branch, and it merges with the code. State is derived from it each time (`rail docs states`); nothing else
stores state. Never edit it by hand: the guard denies it.

| File | Holds |
|---|---|
| `NN-events.jsonl` | Every step and decision, one JSON object per line |
| `NN-review.json` | The review runs: each run's findings as the reviewer wrote them |
| `NN-advice.md` | What consult advised, one section per consult |
| `NN-summary.md` | A sweep ticket only: what the sweep found |

## Events: `NN-events.jsonl`

- One JSON object per line. The engine appends; nothing is rewritten.
- Every line has `v` (1), `at` (UTC, ISO 8601, to the second), `ticket` and `event`.
- A reader ignores fields and events it doesn't know.
- Between green CI and the merge the engine writes nothing here except `continued`, because a journal commit
  would move the head CI just passed. What is needed then lives on GitHub (labels) or in the local cache.

| Event | Written when | Fields | Read by |
|---|---|---|---|
| `requested` | The ticket is made: `rail add`, intake, a sweep, `rail adopt` | `via` (`add`, `intake`, `sweep`, `adopt`), `channel` (`session`, `github`, `tracker`, `engine`, or the `## Grilling` record's channel), `grilled`, `assumed` (open ASSUMED rows at the start), `filed_by` (the issue's author), `not_taken` (why an issue's whole ticket became a request), `external_id` (the ticket's, when it has one). When grilled: `agent`, `person`, `started`, `confirmed`, `drafts`, and `questions` with each one's `id`, `topic`, `recommended` and `taken` | `rail stats`. A drop mark on the counter branch keeps a copy, since the journal goes with the branch |
| `accepted` | Ticket lint first passes on an AUTO ticket; a person approves; an amend takes effect | `by` (`engine`, `person`), `via` (`lint`, `label`, `accept`, `amend`, `merge`), `tier`, `contract`, `done`, `scope_paths`, `note` | The `accepted` state. Ship and CI compare `contract` and `tier` with the ticket: that is the freeze. `via: merge` is a contract pull request that a person merged |
| `amended` | `rail amend NN` | `contract` (the new hash), `changed` (any of `done_contract`, `scope`, `tier`), `added_paths`, `needs_approval`, `reason` (when one was given) | When `needs_approval` is true, the ticket waits until a later `accepted` |
| `adopted` | `rail adopt BRANCH FILE` filed the ticket with a branch's work on it | `branch` (the adopted branch), `head` (its head commit, 12 characters) | `rail stats` |
| `drafting` | `next`, when it hands a session the brief to write an unfinished ticket's contract | `session` | Other sessions leave that contract alone for `[claim] stale_minutes`; `rail next --ticket NN` takes it over |
| `claimed` | A claim or a takeover inside `next`, or `rail adopt` | `session`, `takeover`, and in a cloud session `session_url` | The `implementing` state. `next` finds this session's ticket by it, and the pull request ends with the last `session_url` |
| `base_checks` | `next`, at a ticket's first claim, once setup has passed, unless `[commands] base_checks` is false. Not for a ticket with no `Check:` line. `rail adopt` writes it from its gate, where every check was red | `base` (the base branch's commit, 12 characters), `checks`: each check's `command` and `result` (`red`: it ran and failed; `green`: it ran and passed; `could_not_run`: exit 127 or 126; `timed_out`: past `timeout_secs`) | `rail stats`; the IMPLEMENT brief and the reviewer's brief, when every check was green. It is no step, no attempt and no state |
| `saved` | `rail save`, the save hooks, and `advance` before a long command | `via` (`save`, `stop`, `pulse`, `advance`), `files` | Shows the ticket is alive: its `at` is what `[claim] stale_minutes` is measured from |
| `step` | Every step the engine runs (below) | `step`, `status` (`ran`, or `could_not_run` when the shell couldn't start the command: exit 127 or 126), `result` (`pass`, `fail`; always `fail` when it couldn't run), `patch_id`, `counted`, `detail`, `duration_ms`, `cost_usd`. A failed step has `signature`: the step's name and 12 hex characters of a hash of its normalised output (below) | The retry budget and cap, and the pull request's Evidence table |
| `shipped` | Every ship step passed for the current patch | `patch_id`, `head`, `tier`, `size` | CI's "not shipped yet" test, and the `reviewing` and `in-ci` states |
| `split_offered` | The first ship of an AUTO ticket whose change is over `[size] cap`, when no `person_paths` or `migration_paths` file raised it. Once per ticket | `patch_id`, `size`, `cap` | The `SPLIT` brief; the next ship raises the tier as usual. No step failed, so it spends no attempt. `rail stats` |
| `guided` | `next` or `advance` named a `[guides]` page in a brief, the first time for each situation. Not while a rebase is stopped | `situation` (`start`, `stuck`, `findings`, `conflict`, `contract`, `split`), `path` | `start` is named once per ticket. `rail stats` (`rail docs guides`) |
| `tier_raised` | Ship makes an AUTO ticket PERSON, or a review run asks for a person | `from`, `to`, `reason` (`size`, `person_paths`, `migration_paths`, `reviewer`), `detail` (for `reviewer`: the reviewer's sentence) | The ticket's tier from then on, CI included |
| `finding` | A review run reports or repeats a finding; `rail answer`; a refuter or the owner decides one | `id`, `outcome` (`open`, `fixed`, `declined`, `parked`), `by` (`reviewer`, `author`, `refuter`, `owner`), `reason`, `disputed`. The first event for an id also has `severity`, `claim` and `check` | `advance` and CI: no finding may be open. The sweep reads the parked ones and the `check` of fixed ones |
| `consulted` | Consult ran | `trigger` (`retry_cap`, `request`), `step`, `verdict` (`proceed`, `change`, `stop`), `same_model` | The retry rule below, and the limit of three per ticket |
| `continued` | A person continued a wait with `rail:go` or `rail accept` | `via` (`label`, `accept`), `note` | A fresh retry budget, and the agent's next brief |
| `dropped` | `rail drop` | `by` (`agent`, `person`), `reason` | The `dropped` state |

`contract` is the first 12 hex characters of the SHA-256 of the Done Contract section and the sorted
`scope_paths`, with whitespace normalised. The tier is not in the hash: it is compared by rank, so it may
rise and may not fall.

A sample:

```jsonl
{"v":1,"at":"2026-01-11T13:58:02Z","ticket":"14","event":"accepted","by":"engine","via":"lint","tier":"AUTO","contract":"9c1f04e2a7b3"}
{"v":1,"at":"2026-01-11T14:00:10Z","ticket":"14","event":"claimed","session":"0f3a9d1c","takeover":false}
{"v":1,"at":"2026-01-11T14:10:12Z","ticket":"14","event":"saved","via":"pulse","files":3}
{"v":1,"at":"2026-01-11T14:21:40Z","ticket":"14","event":"step","step":"verify","status":"ran","result":"fail","patch_id":"3f9c6e0d","detail":"exit 1","duration_ms":41200}
{"v":1,"at":"2026-01-11T14:30:02Z","ticket":"14","event":"step","step":"verify","status":"ran","result":"pass","patch_id":"77aa0b12","duration_ms":39800}
{"v":1,"at":"2026-01-11T14:30:05Z","ticket":"14","event":"shipped","patch_id":"77aa0b12","head":"a1b2c3d","tier":"AUTO","size":212}
{"v":1,"at":"2026-01-11T14:34:51Z","ticket":"14","event":"step","step":"review","status":"ran","result":"fail","patch_id":"77aa0b12","detail":"run 1: 1 blocking, 1 findings","cost_usd":0.41}
{"v":1,"at":"2026-01-11T14:34:51Z","ticket":"14","event":"finding","id":"F1","outcome":"open","by":"reviewer","severity":"blocking","claim":"A long-lived token is returned without retiring the old one."}
{"v":1,"at":"2026-01-11T14:41:13Z","ticket":"14","event":"finding","id":"F1","outcome":"fixed","by":"author","reason":"Both paths now revoke the old token."}
```

## Steps

| `step` | Run at | Fails when |
|---|---|---|
| `setup` | Claim | The command fails |
| `rebase` | Ship, and `next` for a pull request behind its base | The rebase onto the base conflicts |
| `ticket-lint` | Ship, CI | The ticket is malformed, its contract differs from the accepted one, or its tier is below the accepted one |
| `assumptions` | Ship, CI | An ASSUMED row is open |
| `scope` | Ship, CI | A changed product file is outside `scope_paths` |
| `change` | Ship, after every other check has passed | The ticket changes no file (a sweep ticket may). Recorded only when it fails |
| `rules` | Ship, CI | A structure rule matches an added line or file |
| `migration` | Ship, CI | A ticket on `migration_paths` lacks `reversibility` or `rollback` |
| `size` | Ship, CI | Never. On an AUTO ticket, a count over `[size] cap` writes `split_offered` at the first ship that meets it and stops there; after that, and in CI, `tier_raised` |
| `doc-lint` | Ship, CI | `ARCHITECTURE.md` no longer matches the tree |
| `verify` | Ship, CI | The command fails. When it fails on the base branch too, the event has `counted: false` |
| `checks` | Ship, CI | A `Check:` line fails; `detail` names it |
| `review`, `security` | `advance` | The run leaves a blocking finding open, or its output is invalid. A run past `timeout_secs` fails with `detail: "timeout"` and `counted: false`. No run and no step when the change needs no review |
| `refuter` | `advance` | The refuter upholds the finding. A pass means it dismissed it |
| `sweep` | `rail sweep` | Never |
| `harvest` | `rail sweep`, when nothing merged without a review: no review run | Never. `detail: "nothing to file"` when the sweep found nothing, and its ticket then merges with no task |
| `merge` | `advance`, with no remote | The base branch moved during the merge |

**The retry budget.** A step's attempts are its `step` events with `result: "fail"` and `counted` not false
(a command that couldn't run is an attempt too),
since that step last passed or since a person's `continued` or approval, whichever is later. Two attempts in a
row are the same failure when their `signature`s are equal, or when either has none (an older engine wrote
it). At `[retry] budget` same failures in a row consult runs once for that step and the agent gets one more
attempt; if that fails too, the ticket waits for a person. At `[retry] cap` attempts, whatever their
signatures, the ticket waits for a person (`rail docs retries`).

**The signature** is `STEP:HASH`. The hash is the first 12 hex characters of the SHA-256 of the tail of the
failure's output, lower-cased, with absolute paths, temp-folder names, hex strings and runs of digits
replaced by placeholders and whitespace collapsed. Every failed run of `review`, `security` or `refuter` gets
the same signature for its step, so the budget there is a plain count.

## Review runs: `NN-review.json`

One file per ticket. The engine appends one entry per run.

```json
{
  "schema": "review/v1",
  "ticket": "14",
  "runs": [
    {
      "run": 1,
      "role": "review",
      "patch_id": "77aa0b12",
      "head": "a1b2c3d",
      "tier": "AUTO",
      "at": "2026-01-11T14:34:51Z",
      "model": "claude-opus-5-5",
      "cost_usd": 0.41,
      "summary": "Read the diff and the store, ran the tests, and replayed a long-lived token.",
      "findings": [
        {
          "id": "F1",
          "severity": "blocking",
          "file": "auth/refresh.py",
          "line": 50,
          "claim": "A long-lived token is returned without retiring the old one, so the old token works again.",
          "check": "A test that refreshes a long-lived token twice with the same value.",
          "evidence": {"command": "python3 scratch_replay.py", "output": "second refresh accepted"}
        }
      ]
    }
  ]
}
```

| Field | Values | Read by |
|---|---|---|
| `role` | `review`, `security`, `refuter`, `sweep` | State derivation and CI |
| `patch_id` | `git patch-id --stable` of the branch's product diff against the base, with no context lines | Binds the run to the patch: a change to the product files needs a new run, and a clean rebase doesn't |
| `head` | The commit the reviewer saw | The person, and the reset after the run |
| `tier` | The tier at the time | CI: was a `security` run needed |
| `disputes` | A refuter run only: the finding's id | `advance`: which finding the refuter judged |
| `needs_person` | A `review` or `security` run that asked for a person: its sentence | The pull request's Risk section and the wait for a person |
| `model`, `cost_usd` | From the command's JSON, when it gives them. `model` is the one that did the work | The Evidence table |

**A review is complete for a patch** when all three hold. The `reviewing` state and CI use the same test:

1. A `review` run exists with this `patch_id`. On a PERSON ticket, a `security` run exists too. An AUTO
   ticket whose every changed product file is in `[review] skip_paths`, or that changes no product file,
   needs no run.
2. No finding is open: the last `finding` event for every id has another outcome.
3. A blocking finding marked `fixed` counts only once a later run of the same role didn't repeat it. Marking
   it fixed and changing nothing doesn't pass.

## What a reviewer returns: `review/v1`

Every run of `[review] command` returns this shape: the review, the security seat, the refuter and the
sweep. The schema is `.rail/engine/review-v1.json`; the default command passes its text to
`claude -p --json-schema`.

| Field | Holds | Read by |
|---|---|---|
| `summary` | One or two sentences: what was checked and how. In a refuter run: why the finding holds or doesn't | The pull request's Evidence row; the reason on a finding the refuter dismisses |
| `findings[].severity` | `blocking` (must not merge as it is), `advisory` (worth fixing, safe to merge), `parked` (a real problem this change didn't cause) | `advance`: a blocking finding holds the ticket; a parked one needs no answer |
| `findings[].file`, `line` | A path from the repository root, and a line in the file as it is after the change | The author's next brief |
| `findings[].claim` | What is wrong, and the input or sequence that shows it | The author, the refuter and the person |
| `findings[].check` | A deterministic check that would catch this kind of mistake, when one exists | The sweep, which turns repeated kinds into checks |
| `findings[].evidence` | `command` and `output`: what the reviewer ran | The refuter, which runs it again |
| `findings[].repeats` | On a re-review: the id of the earlier finding this one repeats | The engine: the finding keeps its id and is open again |
| `needs_person` | Optional, rarely given: one sentence on why a person should see the change although no finding blocks it | `advance`: from a `review` or `security` run, an AUTO ticket becomes PERSON. A refuter's or a sweep's is ignored |

After the schema, the engine checks what only it can: `file` is a tracked path at the reviewed commit and
`line` is inside it (within two lines, because reviewers are sometimes off by one or two); `repeats` names
an earlier finding of this ticket; a refuter returns at most one finding, and it repeats the disputed id. A
run that fails one of these has invalid output, and its step fails. The engine trims `evidence.output` to
2,000 characters.

The engine assigns the ids, `F1`, `F2` and so on, per ticket and across all runs. An id is never reused,
and the reviewer never writes one except in `repeats`.

## What reads it afterwards

`rail stats` counts over the journals of merged tickets: tickets by tier, how often every check was green on
the base before the work, the steps that failed, and the review runs with their cost and how each finding
ended (`rail docs stats`).

## What is not in the journal

- **Waits.** A wait has no event of its own: it is derived from the events above and from the pull
  request's labels, so `rail status`, the label and every session agree. The one exception is `continued`,
  which records that a person ended a wait.
- **Ticket IDs.** They are taken from the counter branch `rail/ids` on the remote (`rail docs tickets`).
- **A dropped ticket's journal** goes with its branch. Its ID, the title it was added with and the drop
  itself (a `rail drop NN` commit, which keeps the `requested` event) stay in the counter branch, so a dropped ticket stays dropped when its
  branch is deleted.
- **The local cache** in the git directory (`rail/cache/`): a requested merge, the waits already announced,
  when the save hook last ran. Nothing else needs it, and a fresh clone works without it.
