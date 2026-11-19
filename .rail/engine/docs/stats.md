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
Disputes: 1. The refuter dismissed 1.
```

## What each line counts

| Line | Counts |
|---|---|
| `merged` | Merged tickets, by tier |
| `the reviewer read it` | Tickets with at least one `review` run |
| `merged with no review` | The rest: every changed file was in `[review] skip_paths`, or no product file changed. The sweep reads these afterwards |
| `no person acted` | AUTO tickets with no approval by a person, no continued wait, and no finding a person decided |
| `shipped on the first try` | Tickets where no ship step failed before the first ship. A red base doesn't count against a ticket |
| `reverted afterwards` | Tickets whose squash commit a later commit on the base branch reverts: one whose message says `This reverts commit <sha>.` (what `git revert` writes), or `Reverts owner/repo#N` (what GitHub's Revert button writes), where N is the ticket's pull request |
| `median claim to merge` | From the first claim to the squash commit |
| `Every check already green on the base` | Of the tickets with a `base_checks` event, those where every `Check:` line passed on the base before any work (`rail docs loop`) |
| `Adopted from a branch with no ticket` | Tickets with an `adopted` event: work that came in through `rail adopt` (`rail docs adopt`). In JSON, `adopted`. Shown when there is one |
| `Offered a split over [size] cap` | Tickets with a `split_offered` event, then those that shipped AUTO afterwards and those that became PERSON for `size`. In JSON, `split`: `offered`, `auto`, `person`. Shown when there is one |
| `Became PERSON at ship or review` | `tier_raised` events, by reason: `person_paths`, `migration_paths`, `size`, `reviewer`. Such a ticket counts under PERSON |
| `STEPS THAT FAILED` | For each step that failed at least once: its runs, the failed ones, and the ones the shell couldn't start |
| `Consult ran` | `consulted` events |
| `REVIEW` | Runs, cost and time by role. Cost is what the review command reported; a command that reports none counts as $0 |
| `BY MODEL` | Runs and cost by the model that answered, the blocking findings its review and security runs first reported, and how many of those were fixed |
| `Blocking findings` | How each ended: fixed, dismissed by the refuter, declined by a person, parked, or still open |
| `Hit rate` | Blocking findings fixed, divided by the blocking findings that were decided |
| `Advisory findings` | How each ended: fixed, declined, parked |
| `Parked by the reviewer` | Findings the reviewer itself reported as parked |
| `Disputes` | Refuter runs, by what the refuter decided: dismissed, parked or upheld |

## Guides

Once a brief has named a [guide](guides.md), one line says how many merged tickets each situation was named
for: `Guides named: start 12, conflict 2.` In JSON it is `guides.situations`.

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
grilled.

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
- **Many tickets under `Became PERSON at ship or review`** by `size` means tickets are too big: split them at
  add. Read it with the split line: many offers that end PERSON mean the agent can't find a part that stands
  alone, and the tickets are written too wide. By `person_paths`, the scope at add missed a path a person wants to see. By `reviewer`, read the
  sentences in the journal: a kind that repeats belongs in `person_paths` or `REVIEW.md`.
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
