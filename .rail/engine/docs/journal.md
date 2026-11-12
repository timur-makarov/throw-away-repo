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
| `accepted` | Ticket lint first passes on an auto tier; a person approves; an amend takes effect | `by` (`engine`, `person`), `via` (`lint`, `label`, `accept`, `amend`, `merge`), `tier`, `contract`, `done`, `scope_paths`, `note` | The `accepted` state. Ship and CI compare `contract` and `tier` with the ticket: that is the freeze. `via: merge` is a contract pull request that a person merged |
| `amended` | `rail amend NN` | `contract` (the new hash), `changed` (any of `done_contract`, `scope`, `tier`), `added_paths`, `needs_approval` | When `needs_approval` is true, the ticket waits until a later `accepted` |
| `claimed` | A claim or a takeover inside `next` | `session`, `takeover`, and in a cloud session `session_url` | The `implementing` state. `next` finds this session's ticket by it, and the pull request ends with the last `session_url` |
| `saved` | `rail save`, the save hooks, and `advance` before a long command | `via` (`save`, `stop`, `pulse`, `advance`), `files` | Shows the ticket is alive: its `at` is what `[claim] stale_minutes` is measured from |
| `step` | Every step the engine runs (below) | `step`, `status` (`ran`), `result` (`pass`, `fail`), `patch_id`, `counted`, `detail`, `duration_ms`, `cost_usd` | The retry budget and the pull request's Evidence table |
| `shipped` | Every ship step passed for the current patch | `patch_id`, `head`, `tier`, `size` | CI's "not shipped yet" test, and the `reviewing` and `in-ci` states |
| `tier_raised` | Ship raises the tier | `from`, `to`, `reason` (`size`, `risk_paths`, `migration_paths`), `detail` | The ticket's tier from then on |
| `finding` | A review run reports or repeats a finding; `rail answer`; a refuter or the owner decides one | `id`, `outcome` (`open`, `fixed`, `declined`, `parked`), `by` (`reviewer`, `author`, `refuter`, `owner`), `reason`, `disputed`. The first event for an id also has `severity`, `claim` and `check` | `advance` and CI: no finding may be open. The sweep reads the parked ones and the `check` of fixed ones |
| `consulted` | Consult ran | `trigger` (`retry_cap`, `request`), `step`, `verdict` (`proceed`, `change`, `stop`), `same_model` | The retry rule below, and the limit of three per ticket |
| `continued` | A person continued a wait with `rail:go` or `rail accept` | `via` (`label`, `accept`), `note` | A fresh retry budget, and the agent's next brief |
| `dropped` | `rail drop` | `by` (`agent`, `person`), `reason` | The `dropped` state |

`contract` is the first 12 hex characters of the SHA-256 of the Done Contract section and the sorted
`scope_paths`, with whitespace normalised. The tier is not in the hash: it is compared by rank, so it may
rise and may not fall.

A sample:

```jsonl
{"v":1,"at":"2026-01-11T13:58:02Z","ticket":"14","event":"accepted","by":"engine","via":"lint","tier":"MEDIUM","contract":"9c1f04e2a7b3"}
{"v":1,"at":"2026-01-11T14:00:10Z","ticket":"14","event":"claimed","session":"0f3a9d1c","takeover":false}
{"v":1,"at":"2026-01-11T14:10:12Z","ticket":"14","event":"saved","via":"pulse","files":3}
{"v":1,"at":"2026-01-11T14:21:40Z","ticket":"14","event":"step","step":"verify","status":"ran","result":"fail","patch_id":"3f9c6e0d","detail":"exit 1","duration_ms":41200}
{"v":1,"at":"2026-01-11T14:30:02Z","ticket":"14","event":"step","step":"verify","status":"ran","result":"pass","patch_id":"77aa0b12","duration_ms":39800}
{"v":1,"at":"2026-01-11T14:30:05Z","ticket":"14","event":"shipped","patch_id":"77aa0b12","head":"a1b2c3d","tier":"MEDIUM","size":212}
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
| `rules` | Ship, CI | A structure rule matches an added line or file |
| `migration` | Ship, CI | A ticket on `migration_paths` lacks `reversibility` or `rollback` |
| `size` | Ship, CI | Never. A count over the cap writes `tier_raised` |
| `doc-lint` | Ship, CI | `ARCHITECTURE.md` no longer matches the tree |
| `verify` | Ship, CI | The command fails. When it fails on the base branch too, the event has `counted: false` |
| `checks` | Ship, CI | A `Check:` line fails; `detail` names it |
| `review`, `security` | `advance` | The run leaves a blocking finding open, or its output is invalid. A run past `timeout_secs` fails with `detail: "timeout"` and `counted: false` |
| `refuter` | `advance` | The refuter upholds the finding. A pass means it dismissed it |
| `sweep` | `rail sweep` | Never |
| `merge` | `advance`, with no remote | The base branch moved during the merge |

**The retry budget.** A step's attempts are its `step` events with `result: "fail"` and `counted` not false,
since that step last passed or since a person's `continued` or approval, whichever is later. At
`[retry] budget` attempts consult runs once for that step and the agent gets one more attempt; if that fails
too, the ticket waits for a person (`rail docs retries`).

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
      "tier": "MEDIUM",
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
| `model`, `cost_usd` | From the command's JSON, when it gives them. `model` is the one that did the work | The Evidence table |

**A review is complete for a patch** when all three hold. The `reviewing` state and CI use the same test:

1. A `review` run exists with this `patch_id`. On HIGH, a `security` run exists too.
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

After the schema, the engine checks what only it can: `file` is a tracked path at the reviewed commit and
`line` is inside it (within two lines, because reviewers are sometimes off by one or two); `repeats` names
an earlier finding of this ticket; a refuter returns at most one finding, and it repeats the disputed id. A
run that fails one of these has invalid output, and its step fails. The engine trims `evidence.output` to
2,000 characters.

The engine assigns the ids, `F1`, `F2` and so on, per ticket and across all runs. An id is never reused,
and the reviewer never writes one except in `repeats`.

## What is not in the journal

- **Waits.** A wait has no event of its own: it is derived from the events above and from the pull
  request's labels, so `rail status`, the label and every session agree. The one exception is `continued`,
  which records that a person ended a wait.
- **Ticket IDs.** They are taken from the counter branch `rail/ids` on the remote (`rail docs tickets`).
- **A dropped ticket's journal** goes with its branch. Its ID, the title it was added with and the drop
  itself (a `rail drop NN` commit) stay in the counter branch, so a dropped ticket stays dropped when its
  branch is deleted.
- **The local cache** in the git directory (`rail/cache/`): a requested merge, the waits already announced,
  when the save hook last ran. Nothing else needs it, and a fresh clone works without it.
