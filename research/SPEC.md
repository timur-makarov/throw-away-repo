# Rail: journal spec

Date: 2026-11-11. This file specifies two things [PLAN.md](PLAN.md) describes but doesn't contain: the `review/v1` schema, and the events in a ticket's journal. Section numbers refer to the plan. Where the two differ, the plan wins.

## 1. `review/v1`: what a reviewer returns

Every run of `review.command` returns this shape: the review, the security seat, the refuter and the sweep.

- **The file** is `.rail/engine/review-v1.json`.
- **`--json-schema` takes the schema itself, not a path.** So the command passes `"$(cat .rail/engine/review-v1.json)"`. Checked with Claude Code 2.1.292.
- **The file has no `$schema` or `$id` key.** The CLI rejects the 2020-12 `$schema` URL. Checked with the same version.
- **It uses only `type`, `enum`, `required` and `additionalProperties`.** The engine checks everything else (below).

```json
{
  "title": "review/v1",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "summary",
    "findings"
  ],
  "properties": {
    "summary": {
      "type": "string",
      "description": "One or two sentences: what you checked and how. In a refuter run: why the finding holds or does not."
    },
    "findings": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "severity",
          "file",
          "claim"
        ],
        "properties": {
          "severity": {
            "type": "string",
            "enum": [
              "blocking",
              "advisory",
              "parked"
            ],
            "description": "blocking: must not merge as it is. advisory: worth fixing, safe to merge. parked: a real problem this change did not cause."
          },
          "file": {
            "type": "string",
            "description": "Path from the repository root."
          },
          "line": {
            "type": "integer",
            "description": "Line in the file as it is after the change. Leave out when the problem is something missing."
          },
          "claim": {
            "type": "string",
            "description": "One or two sentences: what is wrong, and the input or sequence that shows it."
          },
          "check": {
            "type": "string",
            "description": "A deterministic check that would catch this kind of mistake, when one exists."
          },
          "evidence": {
            "type": "object",
            "additionalProperties": false,
            "required": [
              "command",
              "output"
            ],
            "properties": {
              "command": {
                "type": "string",
                "description": "The command you ran."
              },
              "output": {
                "type": "string",
                "description": "Its output, trimmed to the lines that show the problem."
              }
            }
          },
          "repeats": {
            "type": "string",
            "description": "On a re-review only: the id of the earlier finding this one repeats, such as F2."
          }
        }
      }
    }
  }
}
```

| Field | Reader |
|---|---|
| `summary` | The PR's Evidence row. In a refuter run it becomes the reason on a finding the refuter dismisses |
| `severity` | `advance`: a `blocking` finding holds the ticket, and a `parked` one is recorded at once and needs no answer |
| `file`, `line` | The author's next brief and the PR |
| `claim` | The author, the refuter and the person |
| `check` | The sweep, which turns repeated kinds into checks (section 8, item 9) |
| `evidence` | The refuter, which reruns the command; the author |
| `repeats` | The engine: the finding keeps its earlier id and is open again |

**What the engine checks after the schema.** A run that fails one of these has invalid output, and the step fails:

- `file` is a tracked path at the reviewed commit, and `line` is inside it.
- `repeats` names an earlier finding of this ticket.
- A refuter run returns at most one finding, and it `repeats` the disputed id.

The engine trims `evidence.output` to 2,000 characters. In test runs a `line` was sometimes off by one or two, so nothing may depend on the exact line.

**The engine assigns the ids:** `F1`, `F2` and so on, per ticket, across all runs. An id is never reused. The reviewer never writes one, except in `repeats`.

## 2. `NN-review.json`: the stored runs

One file per ticket. The engine appends one entry per run.

```json
{
  "schema": "review/v1",
  "ticket": "14",
  "runs": [
    {
      "run": 1,
      "role": "review",
      "patch_id": "3f9c6e0d…",
      "head": "a1b2c3d",
      "tier": "MEDIUM",
      "at": "2026-11-11T14:34:51Z",
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

| Field | Values | Reader |
|---|---|---|
| `role` | `review`, `security`, `refuter`, `sweep` | State derivation and CI |
| `patch_id` | `git diff -U0 <merge-base>...HEAD -- <product paths> \| git patch-id --stable` | Binds the run to the patch (section 8) |
| `head` | The commit the reviewer saw | The person, and the reset after the run |
| `tier` | The tier at the time | CI: was a `security` run needed |
| `disputes` | A refuter run only: the finding's id | `advance`: which finding the refuter judged |
| `model`, `cost_usd` | From the CLI's JSON, when it gives them | Later measurement |

**A review is complete for a patch** when all three hold. The `reviewing` state and CI use the same test:

1. A `review` run exists with this `patch_id`. On HIGH, a `security` run exists too.
2. No finding is open: the last `finding` event for every id has another outcome (section 3).
3. A blocking finding marked `fixed` counts only once a later run of the same role didn't repeat it. Without this, marking it `fixed` and changing nothing would pass.

## 3. Events: `NN-events.jsonl`

- One JSON object per line. Only the engine appends, and nothing is rewritten.
- The file is committed on the ticket branch and merges with the code.
- **Every line has** `v` (1), `at` (UTC, ISO 8601, to the second), `ticket` and `event`.
- A reader ignores fields and events it doesn't know.
- **Nothing is written between green CI and the merge, except `continued`.** A journal commit moves the head CI just passed. Anything else needed then lives on the forge (labels) or in the local cache (the merge request, announced waits).

| Event | Written when | Fields | Reader |
|---|---|---|---|
| `accepted` | Ticket lint first passes on an auto tier; a person approves with the label or `accept`; an `amend` takes effect | `by` (`engine`, `person`), `via` (`lint`, `label`, `accept`, `amend`), `tier`, `contract`, `note` | The `accepted` state. Ship and CI compare `contract` and `tier` with the ticket: that is the freeze |
| `amended` | `amend NN` | `contract` (the new hash), `changed` (any of `done_contract`, `scope`, `tier`), `added_paths`, `needs_approval` | The PR's Risk section. When `needs_approval` is true, the ticket waits until a later `accepted` |
| `claimed` | A claim or a takeover inside `next` | `session` (`CLAUDE_CODE_SESSION_ID`, or null), `takeover` | The `implementing` state; `next` and the snapshot find this session's ticket |
| `step` | Every step the engine runs (table below) | `step`, `status` (`ran`, `not_run`, `unavailable`), `result` (`pass`, `fail`), `patch_id`, `counted`, `detail`, `duration_ms`, `cost_usd` | The retry budget, the PR's Evidence table, later measurement |
| `shipped` | Every ship step passed for the current patch | `patch_id`, `head`, `tier`, `size` | CI's `not shipped yet` test; the `reviewing` and `in-ci` states |
| `tier_raised` | Ship raises the tier | `from`, `to`, `reason` (`size`, `risk_paths`, `migration_paths`), `detail` | The PR's Risk section |
| `finding` | A run reports a new finding or repeats one; `rail answer`; the refuter or the owner decides one | `id`, `outcome` (`open`, `fixed`, `declined`, `parked`), `by` (`reviewer`, `author`, `refuter`, `owner`), `reason`. The first event for an id also carries `severity`, `claim` and `check` | `advance` and CI: no finding may be open. The sweep reads the `parked` ones and the `check` of fixed ones |
| `consulted` | `consult` ran | `trigger` (`retry_cap`, `request`), `step`, `verdict` (`proceed`, `change`, `stop`), `same_model` | The retry rule below; the limit of three per ticket |
| `continued` | A person continued a wait with `rail:go` or `accept` | `via` (`label`, `accept`), `note` | A fresh retry budget; the agent's next brief |
| `dropped` | `drop`, or `next` sees the PR closed without a merge | `by` (`agent`, `person`), `reason` | The `dropped` state, for as long as the branch exists |

**`contract`** is the first 12 hex characters of the SHA-256 of the Done Contract section and the sorted `scope_paths`, with whitespace normalised. The tier is not in the hash: it is compared by rank, so it may rise and may not fall.

**Step names:**

| `step` | Run at | Fails when |
|---|---|---|
| `setup` | Claim | The command fails |
| `ticket-lint` | Ship, CI | The ticket is malformed, its contract differs from the accepted one, or its tier is below the accepted one |
| `assumptions` | Ship, CI | An ASSUMED row is open |
| `scope` | Ship, CI | A changed product file is outside `scope_paths` |
| `rules` | Ship, CI | A structure rule matches an added line or file |
| `verify` | Ship, CI | The command fails. On a red base the event has `counted: false` |
| `checks` | Ship, CI | A `Check:` line fails; `detail` names it |
| `size` | Ship, CI | Never. A count over the cap writes `tier_raised` |
| `doc-lint` | Ship, CI | A `doc-lint` rule fails |
| `migration` | Ship, CI | A ticket on `migration_paths` lacks `reversibility` or `rollback` |
| `rebase` | Ship, `next` | The rebase onto base conflicts |
| `review`, `security` | `advance` | The run leaves a blocking finding open, or its output is invalid. A run that passes `timeout_secs` also fails, with `detail: "timeout"` and `counted: false` |
| `refuter` | `advance` | The refuter upholds the finding. A pass means it dismissed it |
| `ci` | `next` | A required check is red on the PR head; `detail` names it. Green CI writes nothing |

**The retry budget:**

- A step's attempts are its `step` events with `result: "fail"` and `counted` not false, since that step last passed or since the last `continued`, whichever is later.
- At `retry.budget` attempts, `consult` runs once for that step and the agent gets one more attempt. If that fails too, the ticket waits for a person.
- For `review` and `security`, the count is runs that left a blocking finding open.

**A sample:**

```jsonl
{"v":1,"at":"2026-11-11T13:58:02Z","ticket":"14","event":"accepted","by":"engine","via":"lint","tier":"MEDIUM","contract":"9c1f04e2a7b3"}
{"v":1,"at":"2026-11-11T14:00:10Z","ticket":"14","event":"claimed","session":"0f3a9d1c","takeover":false}
{"v":1,"at":"2026-11-11T14:21:40Z","ticket":"14","event":"step","step":"verify","status":"ran","result":"fail","patch_id":"3f9c6e0d","detail":"exit 1","duration_ms":41200}
{"v":1,"at":"2026-11-11T14:30:02Z","ticket":"14","event":"step","step":"verify","status":"ran","result":"pass","patch_id":"77aa0b12","duration_ms":39800}
{"v":1,"at":"2026-11-11T14:30:05Z","ticket":"14","event":"shipped","patch_id":"77aa0b12","head":"a1b2c3d","tier":"MEDIUM","size":212}
{"v":1,"at":"2026-11-11T14:34:51Z","ticket":"14","event":"step","step":"review","status":"ran","result":"fail","patch_id":"77aa0b12","detail":"run 1: 1 blocking","cost_usd":0.41}
{"v":1,"at":"2026-11-11T14:34:51Z","ticket":"14","event":"finding","id":"F1","outcome":"open","by":"reviewer","severity":"blocking","claim":"A long-lived token is returned without retiring the old one.","check":"A test that refreshes a long-lived token twice."}
{"v":1,"at":"2026-11-11T14:41:13Z","ticket":"14","event":"finding","id":"F1","outcome":"fixed","by":"author","reason":"Both paths now revoke the old token."}
```

## 4. How the states read these

| State (section 7) | Reads |
|---|---|
| `new` | No `accepted` event |
| `accepted` | An `accepted` event and no `claimed` event |
| `implementing` | A `claimed` event, and no `shipped` event for the current patch. Or, from the forge: a red required check on the head, or a conflict with base |
| `reviewing` | A `shipped` event for the current patch, a tier that needs review, and a review that isn't complete (section 2) |
| `in-ci` | A `shipped` event and a complete review for the current patch. From the forge: checks still running |
| `merge-ready` | From the forge: checks green on the head. No finding open |
| `merged` | From git: a squash commit with `Ticket: NN` on base |
| `dropped` | A `dropped` event. Or the PR is closed unmerged. Or the `rail/id/NN` branch exists with no ticket branch and no merge |

**A wait has no event of its own.** Each is derived, so `status`, the `notify` hook and the label all read the same facts:

| The ticket waits for | Derived from |
|---|---|
| Contract approval | `new`, a tier outside `auto_tiers`, and ticket lint passing. Or an `amended` event with `needs_approval` and no later `accepted` |
| A person's merge | `merge-ready` and a tier outside `auto_tiers` |
| The retry cap | A step's budget is used, and so is the attempt after `consult` |
| A finding | A blocking finding is still open when the `review` or `security` budget is used |
| A stuck review | The last two `review` or `security` steps both have `detail: "timeout"` |
| An ASSUMED row | The retry cap on the `assumptions` step |
| A hold | `rail:needs-you` on the PR while none of the waits above applies |
| A failed merge | From the forge: the merge request failed for a reason other than a conflict or a red check |

**The sweep** writes no `finding` events of its own. Its run is stored in its ticket's `NN-review.json` with the role `sweep`, and its summary names the tickets it opened. It reads the `parked` findings, and the `check` of fixed ones, from the journals merged since the last `Sweep:` commit.

## 5. Choices this spec makes

The plan leaves these open, so each is a choice made here:

1. **The engine assigns finding ids,** not the reviewer. A reviewer that numbered its own findings would reuse `F1` on a re-review.
2. **`summary` is a new required field.** Without it, a refuter that dismisses a blocking finding leaves no reason behind.
3. **`parked` is a severity value,** so a finding can't be both blocking and not caused by the change.
4. **`open` is an outcome,** written by the engine. The events file alone then says whether every finding is answered.
5. **The retry budget counts failures since the step last passed.** The plan says "attempts per step" and doesn't say whether a pass resets the count.
6. **Waits are derived, not logged.** The one exception is `continued`, which resets the budget and carries the person's note.
7. **A dropped ticket's journal goes with its branch.** Only the ticket file stays reachable, through the `rail/id/NN` branch.
