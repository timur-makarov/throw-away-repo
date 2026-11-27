# Stats

`rail stats` counts over the journals of merged tickets: how the tickets went, which steps failed, and what
the reviewer cost and found. It also reads the base branch's history for reverts. It only reads. Nothing is stored, so every number can be checked against the
events and review runs it comes from (`rail docs journal`).

```text
rail stats                      every merged ticket
rail stats --since 2026-01-01   tickets merged on or after that day (UTC)
rail stats --json               the same numbers, under "stats"
```

A ticket counts once its squash commit is on the base branch. It counts under the tier it merged with, so
a ticket that became PERSON at ship is a PERSON ticket. A revert takes a ticket's journal off the base branch
with its code, so for a reverted ticket the journal is read from its squash commit.

```text
Rail stats: 3 merged tickets. Not counted: 1 not merged.

OUTCOMES                                     AUTO  PERSON
merged                                          2       1
reverted afterwards                             0       0
caused a fix ticket                             0       0
held, of those merged 14 days ago or more  2 of 2  1 of 1
cost for each merged ticket                 $0.62   $0.50
a person's acts, median for a ticket            0       2
tickets with no act of a person                 2       0
Merged tickets that name the ticket that caused them (caused_by): 0 of 3.

TICKETS                   AUTO  PERSON
merged                       2       1
the reviewer read it         1       1
merged with no review        1       0
no person acted              2       0
shipped on the first try     1       1
reverted afterwards          0       0
median claim to merge      41m   3h10m
Every check already green on the base: 1 of 3 tickets whose checks ran there before the work.

STEPS THAT FAILED  runs  failed  could not run
checks                5       1              0
review                3       1              0

WHERE THE TIME GOES                                   times  median  for each ticket  share
first ship to merge                                       3     12m              31m    45%
waiting for a person, MERGE_BY_PERSON                     1   1h02m              21m    30%
worker run (rail work), each run                          4     14m              19m    27%
waiting for a person, APPROVE_CONTRACT                    1     25m               8m    12%
step review, each run                                     3      3m               3m     4%
step checks, each run                                     5     40s               1m     2%
accepted to claimed, with no overlapping ticket open      3      1m               1m     1%
Share: of the time from request to merge, median 58m over 3 tickets. The lines overlap, so the shares don't add up to 100%.

REVIEW    runs   cost  time
review       3  $1.23    9m
security     1  $0.38    3m
refuter      1  $0.12    1m
total        5  $1.73   13m
$0.87 for each ticket the reviewer read.

BY MODEL         runs   cost  blocking  fixed
claude-opus-5-5     5  $1.73         2      1

Blocking findings: 2. Fixed 1, dismissed by the refuter 1.
Hit rate: 50% of the decided ones ended in a fix. A finding the author fixed without disputing it counts as a hit, so read this as an upper bound.
Advisory findings: 1. Declined 1.
Disputes: 1. The refuter dismissed 1. Refuter overturns: 100%.
Rounds to pass: median 1.5 review runs for each ticket the reviewer read; 50% merged after one run.
Evidence reproduced: 1 of 2 blocking findings whose evidence the engine ran again (50%).
PERSON tickets where the person changed nothing, by why they were PERSON: access 1 of 1.
```

## What each line counts

| Line | Counts |
|---|---|
| `OUTCOMES` | What became of the merged tickets, by tier. It comes first: the rest says how the work went, this says whether it lasted. In JSON, `outcomes.tiers` |
| `caused a fix ticket` | Merged tickets a later ticket names in `caused_by` (`rail docs tickets`). In JSON, `caused_fix` |
| `held, of those merged N days ago or more` | Of the tickets merged at least `[stats] held_days` ago (14 unless the config says otherwise), those not reverted and named in no `caused_by`. A ticket merged yesterday has had no time to fail, so it is in neither number. In JSON, `held` and `old_enough` |
| `cost for each merged ticket` | What the review commands reported (`cost_usd` on the `review`, `security`, `refuter` and `sweep` step events) and what the worker runs reported (`cost_usd` on the `worked` events), summed and divided by the merged tickets. A command that reports no cost counts as $0, and a session a person drives records none. In JSON, `review_usd`, `worker_usd` and `cost_per_ticket` |
| `a person's acts, median for a ticket` | The acts the journal records for a ticket: each approval of a contract, an amend or a merge and each continued wait (`accepted` by a person, `continued`), and each finding a person decided (`rail answer --owner`). In JSON, `acts`: `total`, `median`, `none` |
| `tickets with no act of a person` | Merged tickets with none of those acts |
| `Merged tickets that name the ticket that caused them` | Merged tickets with `caused_by` set. Read it beside `caused a fix ticket`: a fix that names no cause leaves the ticket that caused it counted as held. In JSON, `outcomes.names_cause` |
| `Failed dev deploys reverted` | The merged revert tickets the intake filed after a failed smoke check, and the median minutes from the issue's opening (`opened` on the `requested` event) to the revert's merge: how long dev stayed broken. Shown when there is one. In JSON, `dev_broken`: `reverts`, `median_minutes` |
| `BY WORKER`, `BY LANGUAGE` | The outcome counts by the model and effort of the ticket's last worker run (`worked` events; `(no worker run)` when a session did the work), and by each `[[profiles]]` entry whose paths the ticket's scope reaches (`rail docs languages`). A group of fewer than five merged tickets is summed into `other`, and a split with no group of five isn't shown. In JSON, `outcomes.by_worker` and `outcomes.by_profile` |
| `merged` | Merged tickets, by tier |
| `the reviewer read it` | Tickets with at least one `review` run |
| `merged with no review` | The rest: every changed file was in `[review] skip_paths`, or no product file changed. The sweep reads these afterwards |
| `no person acted` | AUTO tickets with no approval by a person, no continued wait, and no finding a person decided |
| `shipped on the first try` | Tickets where no ship step failed before the first ship. A red base doesn't count against a ticket |
| `reverted afterwards` | Tickets whose squash commit a later commit on the base branch reverts: one whose message says `This reverts commit <sha>.` (what `git revert` writes), `Reverts owner/repo#N` (what GitHub's Revert button writes), where N is the ticket's pull request, or the trailer `Reverts: <sha>` (what a revert ticket's squash carries, `rail docs tickets`) |
| `median claim to merge` | From the first claim to the squash commit |
| `Every check already green on the base` | Of the tickets with a `base_checks` event, those where every `Check:` line passed on the base before any work (`rail docs loop`) |
| `Adopted from a branch with no ticket` | Tickets with an `adopted` event: work that came in through `rail adopt` (`rail docs adopt`). In JSON, `adopted`. Shown when there is one |
| `Offered a split over [size] cap` | Tickets with a `split_offered` event, then those that shipped AUTO afterwards (and those an older engine made PERSON for `size`, when there are any). In JSON, `split`: `offered`, `auto`, `person`. Shown when there is one |
| `AUTO tickets over [size] cap` | Merged AUTO tickets whose last `shipped` size is over the cap the config sets now, and how many were reverted afterwards or named in a later ticket's `caused_by`; then the same two numbers for those under it. Size raises no tier, so this is what a large AUTO change costs. In JSON, `size`: `cap`, `over` and `under`, each with `merged` and `reverted_or_fixed`. Shown when one merged over the cap |
| `AUTO tickets that held a kind` | Merged AUTO tickets that a later PERSON ticket names in `caused_by`, by the kinds that later ticket holds. Such a ticket did something a revert doesn't undo and nobody was asked: it is the opposite mistake to a PERSON ticket where the person changed nothing. In JSON, `auto_held_a_kind`: `tickets`, `kinds`. Shown when there is one |
| `Dropped` | Dropped tickets (those requested on or after `--since`), by who dropped them: the engine at the retry cap (`rail docs retries`), an agent, or a person; and for the engine's drops the step that kept failing. Read from the drop marks, which outlive the tickets' branches and keep what each ticket's runs reported they cost. In JSON, `drops`: `total`, `by`, `stuck_steps`, `cost_usd`. Shown when there is one |
| `Became PERSON at ship or review` | `tier_raised` events, by reason: `kinds`, `person_paths`, `migration_paths`, `reviewer` (`size` from an older engine). Such a ticket counts under PERSON |
| `STEPS THAT FAILED` | For each step that failed at least once: its runs, the failed ones, and the ones the shell couldn't start |
| `Consult ran` | `consulted` events |
| `FLAKES` | For each command that was flaky on a merged ticket (`flake` events, and a pass and a failure on one patch; `rail docs retries`): the tickets it was flaky on, its flakes, how often ship ran it on those tickets, and flakes divided by runs. In JSON, `flakes`, by command: `tickets`, `flakes`, `runs`, `share`. Shown when there is one |
| `WORKER` | The `rail work` runs of the merged tickets (`worked` events), by model and effort: runs, the cost and time they reported, how many ended at the CLI's turn limit, at its budget, at `[worker] timeout_minutes` or in an error, and how many resumed the last run's session. Then the runs that could not resume and started fresh, and what the merged tickets a person acted on cost. In JSON, `worker.runs` and `worker.person_acted`. Shown once `rail work` ran |
| `WHERE THE TIME GOES` | What the merged tickets' time went on, the largest share first. Every line is read from events that already exist, so nothing is timed for it. `times` is how often it happened, `median` its median length, `for each ticket` its total divided by the merged tickets, and `share` its total divided by the tickets' time from request to merge. In JSON, `time`: `tickets`, `request_to_merge_secs` (the median), `rebases_after_ship`, and `lines`, each with `key`, `label`, `count`, `median_secs`, `per_ticket_secs` and `share` |
| `accepted to claimed` | From a ticket's first `accepted` event to its first claim. `behind a ticket with an overlapping scope` when another ticket whose scope overlaps was claimed before this one and had neither merged nor been dropped when this one was accepted (the `SCOPE_OVERLAP` rest); `with no overlapping ticket open` otherwise: that time is the wait for a free session. Keys `claim_behind_overlap` and `claim` |
| `step NAME, each run` | `duration_ms` of each step event with that name. Key `step:NAME` |
| `worker run (rail work), each run` | `minutes` of each `worked` event. Key `worker` |
| `first ship to merge` | From the first `shipped` event to the squash commit: review, CI, rebases behind other merges and a person's merge. Key `shipped_to_merged`. `Rebases after the first ship` counts the `rebase` steps in that time, for each merged ticket |
| `waiting for a person, CODE` | From the event before a person's act to the act (`accepted` by a person, `continued`), by the code of the wait the act answered, which the act records in `wait`. A step the engine ran in the middle of the wait, such as a rebase, starts the count again, so read it as a lower bound. For an act an older engine wrote with no `wait`: `APPROVE_CONTRACT` for a ticket's first approval, `APPROVE_AMEND` for a later one, `(not recorded)` for a continue. Key `person:CODE` |
| `REVIEW` | Runs, cost and time by role. Cost is what the review command reported; a command that reports none counts as $0 |
| `BY MODEL` | Runs and cost by the model that answered, the blocking findings its review and security runs first reported, and how many of those were fixed |
| `Blocking findings` | How each ended: fixed, dismissed by the refuter, declined by a person, parked, or still open |
| `Hit rate` | Blocking findings fixed, divided by the blocking findings that were decided |
| `Advisory findings` | How each ended: fixed, declined, parked, or still open (an open one holds nothing; the sweep gathers it) |
| `Parked by the reviewer` | Findings the reviewer itself reported as parked |
| `Disputes` | Refuter runs, by what the refuter decided: dismissed, parked or upheld |
| `Refuter overturns` | Disputes the refuter dismissed or parked, divided by all disputes. In JSON, `review.refuter_overturns` |
| `Rounds to pass` | `review` runs stored in the journal (runs with a verdict; a timeout or invalid output is not one) for each merged ticket the reviewer read: the median, and the share of those tickets merged after one run. In JSON, `review.rounds`: `tickets`, `median`, `one_run` |
| `Evidence reproduced` | Blocking findings (review and security) whose evidence, as the run that first reported them gave it, the engine ran again after the review (`evidence.reproduced` in the journal, `rail docs journal`), and how many of those re-runs showed every line the reviewer quoted. Findings from before the engine ran evidence again are left out. In JSON, `review.evidence`: `rerun`, `reproduced`, `share` |
| `PERSON tickets where the person changed nothing` | For each kind a merged PERSON ticket held (`rail docs kinds`): the `kinds` of its first acceptance when that was already PERSON, and the kind of each `tier_raised` event; a ticket counts under each of its kinds. A journal of an older engine names no kind, and counts under `at add` or the event's reason: its tickets, and those where the person changed nothing. That is: no `accept` or `rail:go` with a note, no finding the person decided, no amend after the person's first act, and no new patch shipped after the person's first act once the work had shipped. A contract approval before the work is not that act, since every commit follows it. In JSON, `person_changed_nothing` |

## When a line says to remove something

Four lines measure parts of the review that are kept only while they pay. Each says when to take the part
out; read them over the stated number of tickets, not fewer.

| Line | Remove when |
|---|---|
| `Evidence reproduced` | Under 5% over 50 or more blocking findings with re-run evidence: the engine's re-run of the evidence buys nothing |
| `Refuter overturns` | 0% over 50 or more disputes: the refuter always upholds, so it only costs a run |
| `PERSON tickets where the person changed nothing` | 95% or more over 20 or more tickets of one kind, and none of them reverted or named in a later ticket's `caused_by`: the paths that mark that kind reach changes that don't hold it, so they may be narrowed. It is policy, so the owner decides |
| `Rounds to pass` | No removal test: it reads as convergence, and a rise after a change to the reviewer or the worker shows the change cost rounds |

## Guides

Once a brief has carried a [guide](guides.md), one line says how many merged tickets each situation was
given for: `Guides named: start 12, conflict 2.` In JSON it is `guides.situations`.

## Grilling

Every ticket's journal starts with a `requested` event: where it came from, and the `## Grilling` record when
someone questioned the person who asked (`rail docs grill`). The GRILLING table counts every ticket requested
in the period, whatever became of it, with grilled tickets beside the rest:

| Line | Counts |
|---|---|
| `questions asked` | Rows in the Grilling tables |
| `recommendation accepted`, `edited`, `rejected` | How the person took the agent's recommendation |
| `acceptance rate` | Accepted, divided by accepted, edited and rejected. A question asked with no recommendation isn't in it |
| `merged`, `dropped`, `still open` | What became of the tickets. A dropped ticket counts through its drop mark |
| `contract amended after acceptance` | The Done Contract or the scope changed after the ticket was accepted |
| `caused a fix ticket` | A later ticket names it in `caused_by` |
| `median request to merge` | From the `requested` event to the squash commit |

`BY CHANNEL` and `GRILLED BY` split the same counts by where the request came from and by the model that
grilled. A last line names, by channel, the tickets whose request had hidden text removed at intake
(`hidden` in the JSON; `rail docs tickets`): any at all means someone put text in an issue that its reader
couldn't see.

**Read the acceptance rate with the amends.** Many acceptances with many amends mean people said yes without
deciding, and the recommendations steered them. Many acceptances with few amends mean the agent recommends
well. A low rate means it doesn't know the project or the person yet. The grilling agent grades the answers
itself; the ticket keeps the recommendation and the answer word for word, so the grade can be checked.

## Sources

The SOURCES table has one row for each [source](sources.md) with a ticket requested in the period: how many
it filed, and how many of those merged, were reverted afterwards, were dropped, and are still open. In JSON
it is under `sources`. A source whose tickets are mostly dropped files what isn't worth a ticket: tighten its
prompt. One whose tickets are reverted files what is wrong.

## What to read from it

- **A low hit rate with many dismissals** means the reviewer reports what isn't wrong. Try another
  `[review] model`, and compare the two in `BY MODEL` after a few weeks.
- **A hit rate near 100%** is weaker evidence than it looks: an author who fixes a finding without disputing
  it counts as a hit, whether or not the finding was right. The disputes line shows how often the author
  pushes back at all.
- **AUTO tickets over the cap reverted or fixed more often than those under it** means large changes get
  through review with faults: lower `[size] cap` so more are offered a split, or write narrower tickets.
- **Many tickets under `Became PERSON at ship or review`** by `kinds`, `person_paths` or `migration_paths` means
  the scope at add missed a path of a kind. By `reviewer`, read the sentences in the journal: a kind of change
  that repeats belongs in `[kinds]` or `REVIEW.md`.
- **A step with many failures** is where retries go. A `could not run` count means a tool is missing on the
  machine: `[commands] provision` or `setup` should install it. `rail stats` doesn't read the failures'
  `signature`s; to see whether a step failed the same way again and again or differently each time, compare
  them in the ticket's journal (`rail docs journal`).
- **`reverted afterwards`** is the guardrail on merging with nobody. When it rises on AUTO tickets, the time a
  person saved at the merge was spent later, on the revert.
- **Every check already green on the base** means those checks couldn't show that the work was done: the
  ticket would have passed them with no change. Write checks that fail first.
- **`no person acted`** against `merged` is how much of the AUTO work ran with nobody. `merged with no review`
  is what `[review] skip_paths` let through.
