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
| `requested` | The ticket is made: `rail add`, intake, a sweep, `rail adopt` | `via` (`add`, `intake`, `sweep`, `adopt`, `revert`), `channel` (`session`, `github`, `tracker`, `engine`, or the `## Grilling` record's channel), `grilled`, `assumed` (open ASSUMED rows at the start), `filed_by` (the issue's author), `not_taken` (why an issue's whole ticket became a request), `hidden_removed` (how many HTML comments intake took out of the request, when any), `external_id` (the ticket's, when it has one), and after a failed deploy to dev `opened` (when the smoke check's issue was opened) on the revert and the fix, with `smoke: true` on the fix. When grilled: `agent`, `person`, `started`, `confirmed`, `drafts`, and `questions` with each one's `id`, `topic`, `recommended` and `taken` | `rail stats`. A drop mark on the counter branch keeps a copy, since the journal goes with the branch |
| `accepted` | Ticket lint first passes on an AUTO ticket; a person approves; an amend takes effect | `by` (`engine`, `person`), `via` (`lint`, `label`, `accept`, `amend`, `merge`), `tier`, `contract`, `done`, `scope_paths`, `kinds` (the ids of what the ticket holds that a revert doesn't undo: those its `person_reason` names, in the order written, and those its scope's paths reach; `rail docs kinds`), `wait` (the code of the wait a person's approval answered, such as `APPROVE_CONTRACT`), `note` | The `accepted` state. Ship and CI compare `contract` and `tier` with the ticket: that is the freeze. `via: merge` is a contract pull request that a person merged |
| `amended` | `rail amend NN` | `contract` (the new hash), `changed` (any of `done_contract`, `scope`, `tier`, `after`), `added_paths`, `needs_approval`, `reason` | When `needs_approval` is true, the ticket waits until a later `accepted` |
| `adopted` | `rail adopt BRANCH FILE` filed the ticket with a branch's work on it | `branch` (the adopted branch), `head` (its head commit, 12 characters) | `rail stats` |
| `drafting` | `next`, when it hands a session the brief to write an unfinished ticket's contract | `session` | Other sessions leave that contract alone for `[claim] stale_minutes`; `rail next --ticket NN` takes it over |
| `claimed` | A claim or a takeover inside `next`, or `rail adopt` | `session`, `takeover`, and in a cloud session `session_url` | The `implementing` state. `next` finds this session's ticket by it, and the pull request ends with the last `session_url` |
| `base_checks` | `next`, at a ticket's first claim, once setup has passed, unless `[commands] base_checks` is false. Not for a ticket with no `Check:` line. `rail adopt` writes it from its gate, where every check was red | `base` (the base branch's commit, 12 characters), `checks`: each check's `command` and `result` (`red`: it ran and failed; `green`: it ran and passed; `could_not_run`: exit 127 or 126; `timed_out`: past `timeout_secs`) | `rail stats`; the IMPLEMENT brief and the reviewer's brief, when every check was green. It is no step, no attempt and no state |
| `saved` | `rail save`, the save hooks, `advance` before a long command, and `rail work` while its worker runs | `via` (`save`, `stop`, `pulse`, `advance`, `work`), `files` | Shows the ticket is alive: its `at` is what `[claim] stale_minutes` is measured from |
| `worked` | `rail work NN`, once its worker run ended | `code` (the answer it ran for), `model`, `effort`, `end` (`done`, `turns`, `budget`, `timeout`, `error`), `minutes`, `resumed`, `resume_failed` (a resume failed and it ran fresh), and from the command's JSON result when it gave one: `cost_usd` (none after a timeout), `turns`, `session`. `counts` and `keys`: Bash commands that failed before the first one of the same program passed (`failed`), commands the shell couldn't find (`not_found`), tool calls a rule or the guard denied (`denied`), files read more than twice (`reread`). A key is the program (the first word after `NAME=value` words, a leading `cd DIR &&`, and `uv run`, `npx`, `pnpm exec`, `poetry run`, `bundle exec`), the denied program or tool with the rule, or the path | The next run's `RAIL_SESSION`. While a rebase is open the event waits in the local cache (`rail docs loop`) |
| `step` | Every step the engine runs (below) | `step`, `status` (`ran`, or `could_not_run` when the shell couldn't start the command: exit 127 or 126), `result` (`pass`, `fail`; always `fail` when it couldn't run), `patch_id`, `counted`, `detail`, `duration_ms`, `cost_usd`. A failed step has `signature`: the step's name and 12 hex characters of a hash of its normalised output (below) | The retry budget and cap, and the pull request's Evidence table |
| `shipped` | Every ship step passed for the current patch | `patch_id`, `head`, `tier`, `size` | CI's "not shipped yet" test, and the `reviewing` and `in-ci` states |
| `split_offered` | The first ship of an AUTO ticket whose change is over `[size] cap`, when no file on a kind's paths raised it. Once per ticket | `patch_id`, `size`, `cap` | The `SPLIT` brief; the next ship goes on as AUTO. No step failed, so it spends no attempt. `rail stats` |
| `guided` | `next` or `advance` put a `[guides]` page's text in a brief, the first time for each situation. Not while a rebase is stopped | `situation` (`start`, `stuck`, `findings`, `conflict`, `contract`, `split`), `path` | `start` is given once per ticket. `rail stats` (`rail docs guides`) |
| `tier_raised` | Ship makes an AUTO ticket PERSON, or a review run asks for a person | `from`, `to`, `reason` (`kinds`, `person_paths`, `migration_paths`, `reviewer`; `size` from an older engine), `kind` (the kind's id; for `reviewer`, its first item's), `kinds` (for `reviewer`: each id it listed), `detail` (for `reviewer`: the first item, as `kind: file:line: why`; from an older engine, its `needs_person` sentence; for a path: the files) | The ticket's tier from then on, CI included |
| `finding` | A review run reports or repeats a finding; `rail answer`; a refuter or the owner decides one | `id`, `outcome` (`open`, `fixed`, `declined`, `parked`), `by` (`reviewer`, `author`, `refuter`, `owner`, and `engine` when an upheld finding stands on an AUTO ticket), `reason`, `disputed`. The first event for an id also has `severity`, `claim` and `check` | `advance` and CI: no finding may be open. The sweep reads the parked ones and the `check` of fixed ones |
| `flake` | Ship: `verify` or a `Check:` line failed, the engine ran that one command once more on the same code, and it passed | `step` (`verify`, `checks`), `command`, `patch_id`, `codes` (the two exit codes, `timeout` for a run that timed out) | The worker's brief, the reviewer's brief, the sweep and `rail stats` (`rail docs retries`). The step's own event still says `fail` |
| `consulted` | Consult ran | `trigger` (`retry_cap`, `request`), `step`, `verdict` (`proceed`, `change`, `stop`), `same_model` | The retry rule below, and the limit of three per ticket |
| `continued` | A person continued a wait with `rail:go` or `rail accept` | `via` (`label`, `accept`), `wait` (the code of the wait it continued, such as `MERGE_BY_PERSON`), `note` | A fresh retry budget, and the agent's next brief |
| `dropped` | `rail drop`, or the engine at the retry cap of an AUTO ticket (`STUCK`) | `by` (`agent`, `person`, `engine`), `reason`; from the engine also `step` and `signature`, the step it stopped at and its last failure's | The `dropped` state. Written before the drop's mark, which is written before anything is removed |

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

**Every decision of an agent carries its reason.** `rail answer NN F1 fixed|declined|parked`, `rail amend` of
an accepted contract and `rail drop` refuse an empty reason from an agent, so a `finding`, `amended` or
`dropped` event written by one always says why: the next review run, the sweep and `rail stats` read the
journal, and a decision with no reason tells them only that something happened. A person's act needs none
(`rail answer ... --owner` on `fixed` and `parked`, `rail drop --by person`): approving is itself the
reason. Ticket lint refuses a `VERIFIED: decided, not checked:` row with nothing after it.

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
| `size` | Ship, CI | Never. On an AUTO ticket, a count over `[size] cap` writes `split_offered` at the first ship that meets it and stops there; after that the ship goes on. Size raises no tier |
| `doc-lint` | Ship, CI | `ARCHITECTURE.md` no longer matches the tree |
| `verify` | Ship, CI | The command fails. When it fails on the base branch too, the event has `counted: false` |
| any ship step | Ship | A command that couldn't run has `counted: false`. A failed `verify`, `checks` or `sensors` with a declared tool out of reach has `counted: false` and `tools_down` (each tool and what its probe said): `rail docs retries` |
| `checks` | Ship, CI | A `Check:` line fails; `detail` names it |
| `sensors` | Ship, CI, last, when the change touches a sensor's `paths` | A sensor reports a violation on a line the change adds; `detail` counts them and names the sensors. `could_not_run` when a sensor ends with an exit it doesn't declare (`rail docs sensors`) |
| `review`, `security` | `advance` | The run leaves a blocking finding open. A run past `timeout_secs` fails with `detail: "timeout"`, and a run whose output is invalid with `detail: "invalid output: ..."`, both with `counted: false`. No run and no step when the change needs no review |
| `refuter` | `advance`; `rail answer` | The refuter upholds the finding. A pass means it dismissed it. On an AUTO ticket, `rail answer` writes a failed `refuter` step, with no run, when the author disputes a finding a refuter already upheld: the verdict stands, and the dispute counts toward the retry cap |
| `sweep` | `rail sweep` | Never |
| `harvest` | `rail sweep`, when nothing merged without a review: no review run | Never. `detail: "nothing to file"` when the sweep found nothing, and its ticket then merges with no task |
| `merge` | `advance`, with no remote | The base branch moved during the merge |

**The retry budget.** A step's attempts are its `step` events with `result: "fail"` and `counted` not false
(a ship step that couldn't run, or that failed with a declared tool out of reach, is none),
since that step last passed or since a person's `continued` or approval, whichever is later. Two attempts in a
row are the same failure when their `signature`s are equal, or when either has none (an older engine wrote
it). At `[retry] budget` same failures in a row consult runs once for that step and the agent gets one more
attempt; if that fails too, the ticket is stuck. At `[retry] cap` attempts, whatever their signatures, the
ticket is stuck. A stuck AUTO ticket is dropped with a record; a stuck PERSON ticket waits for a person
(`rail docs retries`).

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
| `kinds` | A `review` or `security` run that listed any: its `kinds` items. A run from an older engine may hold `needs_person`, a sentence, instead | The pull request's Risk section and the wait for a person |
| `model`, `cost_usd` | From the command's JSON, when it gives them. `model` is the one that did the work | The Evidence table |

**A review is complete for a patch** when all three hold. The `reviewing` state and CI use the same test:

1. A `review` run exists with this `patch_id`. On a PERSON ticket, a `security` run exists too. An AUTO
   ticket whose every changed product file is in `[review] skip_paths`, or that changes no product file,
   needs no run.
2. No blocking finding is open: the last `finding` event for every blocking id has another outcome. An
   advisory finding may stay open.
3. A blocking finding marked `fixed` counts only once a later run of the same role didn't repeat it. Marking
   it fixed and changing nothing doesn't pass.

## What a reviewer returns: `review/v1`

Every run of `[review] command` returns this shape: the review, the security seat, the refuter and the
sweep. The schema is `.rail/engine/review-v1.json`; the default command passes the base branch's copy of
its text (`RAIL_REVIEW_SCHEMA`, `rail docs review`) to `claude -p --json-schema`.

| Field | Holds | Read by |
|---|---|---|
| `summary` | One or two sentences: what was checked and how. In a refuter run: why the finding holds or doesn't | The pull request's Evidence row; the reason on a finding the refuter dismisses |
| `findings[].severity` | `blocking` (must not merge as it is), `advisory` (worth fixing, safe to merge), `parked` (a real problem this change didn't cause) | `advance`: a blocking finding holds the ticket; an advisory one may stay open, and the sweep gathers it; a parked one needs no answer |
| `findings[].file`, `line` | A path from the repository root, and a line in the file as it is after the change | The author's next brief |
| `findings[].claim` | What is wrong, and the input or sequence that shows it | The author, the refuter and the person |
| `findings[].check` | A deterministic check that would catch this kind of mistake, when one exists | The sweep, which turns repeated kinds into checks |
| `findings[].evidence` | `command` and `output`: what the reviewer ran | The refuter, which runs it again |
| `findings[].evidence.rerun` | Added by the engine: the engine's own run of `command` at the reviewed commit, before the clean-up: `exit` (null when it passed `timeout_secs`) and `output_tail` | The person; `rail stats` |
| `findings[].evidence.reproduced` | Added by the engine: true when every non-empty line of `output`, normalised as failure signatures are (numbers, hashes, paths and spacing left out), is in the re-run's output. Nothing is decided from it | `rail stats` |
| `findings[].evidence.scripts` | Added by the engine: `{path: text}` of each untracked file the command names (at most 3, each cut at 8,000 characters), which the clean-up removes | The author's brief, with the finding |
| `findings[].repeats` | On a re-review: the id of the earlier finding this one repeats | The engine: the finding keeps its id and is open again |
| `kinds` | Optional: each thing in the change a revert doesn't undo, as `kind` (an id from `rail docs kinds`; an unknown one makes the output invalid), `file`, `line` and `why` | `advance`: from a `review` or `security` run, an AUTO ticket becomes PERSON; on a PERSON ticket they are only recorded. A refuter's or a sweep's are ignored |

After the schema, the engine checks what only it can: `file` is a tracked path at the reviewed commit and
`line` is inside it (within two lines, because reviewers are sometimes off by one or two); `repeats` names
an earlier finding of this ticket; a refuter returns at most one finding, and it repeats the disputed id. A
run that fails one of these has invalid output, and its step fails without counting against the author
(`rail docs retries`). The engine trims `evidence.output` to 2,000 characters.

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
  itself stay in the counter branch, so a dropped ticket stays dropped when its branch is deleted. The drop's
  mark is a `rail drop NN` commit whose message keeps the `requested` event with one more key, `dropped`: `by`,
  `reason`, `at`, `cost_usd` (what the ticket's worker and review runs reported, when they reported any), and
  from the engine `step` and `signature`. The mark is written before the worktree and branches
  are removed and before the pull request is closed. When it can't be (offline, or a push refused other than by
  another clone's push), nothing is removed and the ticket rests as `DROP_PENDING` until a later `rail next`
  writes it and finishes the drop.
- **The local cache** in the git directory (`rail/cache/`): a requested merge, the waits already announced,
  when the save hook last ran, each `rail work` run's log (`work/NN`: one line per tool call, cut at 200
  characters a line and 500 lines a run), and a `worked` event a rebase holds back (`worked/NN`). Nothing
  else needs it, and a fresh clone works without it.
