# GitHub

Rail talks to GitHub only through `gh api` REST calls, so the same engine runs on a laptop and in a Claude
Code cloud session, where `gh pr` and `gh issue` (GraphQL) don't work.

## One-time setup

`rail init` creates the labels `rail`, `rail:go`, `rail:needs-you`, `rail:hold`, `rail:stop`, `rail:revert` and `rail:look`, and writes
`.rail/ruleset.json`.
The rest is yours, in the repository's settings; a cloud session can't change them:

- **Settings > Rules > Rulesets > New ruleset > Import a ruleset:** choose `.rail/ruleset.json`, downloaded
  to your device first (the framework's `seed/ruleset.json` is the same file). It makes
  `rail` a required check on the base branch, requires a pull request and an up-to-date branch, allows
  squash merges only, and blocks force pushes and deletion. To make it by hand: a branch ruleset, active,
  on the default branch, with "Require a pull request before merging" (0 approvals, squash only) and
  "Require status checks to pass" (`rail`, with "Require branches to be up to date").
- **Settings > General > Pull Requests:** "Pull request title and description" as the default squash
  message, so a person's merge puts the same `Ticket:` trailer on the base branch as the engine's. The
  ruleset already allows squash merges only on the base branch.
- **The same page:** turn on "Automatically delete head branches".
- Turn on Dependabot or Renovate.

`rail doctor` checks the required check, the squash setting, branch deletion and the labels, with a link to
each page.

## How tickets use pull requests

- A PERSON ticket opens a contract pull request at `add`, titled `NN: [contract] ...`. Approve
  it with the label `rail:go`, change it by commenting, reject it by closing it. Don't merge it: it holds
  only the contract, and with the ruleset GitHub refuses, because its `rail` check is red. Without the
  ruleset a merge goes through, and Rail takes it as the approval: the work gets a new pull request. Only
  the merge of the ticket's own pull request counts. A ticket file that reaches the base branch any other
  way, such as inside another ticket's merge, approves nothing.
- An AUTO ticket opens its pull request at claim.
- No pull request is a draft. The `rail` check stays red with `not shipped yet` until the ticket ships, so
  nothing merges early by mistake.
- At ship the engine writes the title and description: Read these (below), Why, Look at, Evidence, Risk, and the trailers
  `Ticket:`, `Tier:` and `Review:` (`reviewer`, `reviewer, security seat`, or `none` when the change needed no
  review). The squash commit carries the same text.
- A red required check, or a conflict with the base, returns the ticket to the agent. A pull request that is
  behind its base, when the base requires up-to-date branches, is rebased with no agent work.
- An AUTO ticket merges through the async merge endpoint once the required checks are green. A person
  merges a PERSON ticket by pressing the button.

## Testing every merge on the latest base

Turn on "Require branches to be up to date before merging": the engine rebases a shipped pull request that
falls behind, and CI runs again. A merge queue is for organisations with many merges a day; a project that
turns one on adds the `merge_group` trigger to `.github/workflows/rail.yml` and tests it.

## Many pull requests, and GitHub's limits

- The engine reads the 100 newest pull requests once per command. A ticket whose pull request is older than
  those is asked for by its branch, one call for each such ticket, and only when the ticket should have one:
  it is claimed, or it is a PERSON ticket with a contract to approve.
- Issues labelled `rail` are read to the last page, so intake misses none.
- When GitHub refuses a call because a rate limit is used up (a `403` or `429` with `retry-after`, or with
  nothing left until `x-ratelimit-reset`), the command stops there and answers `GITHUB_LIMIT`. Under five
  minutes the answer is the script `sleep N; rail next`; a longer wait is a `rest` that names the time to come
  back. Nothing is counted as an attempt, and what the command had already done stays done: the next
  `rail next` goes on from the journal. A ship whose pull request could not be written has its title and
  description written by the next `rail next`.
- Two writes to GitHub in one command are at least one second apart, as GitHub's guide to its REST API asks.

## Read these

A pull request's description opens with `## Read these`: the lines of the change that need a person's eye, and
why. The engine builds the list from facts. It stands before `## Look at`, which the worker wrote: an author
frames a change as its author sees it, and this list has no author.

| An item is | Its lines | Named as |
|---|---|---|
| What the reviewer found that a revert doesn't undo | Where the reviewer saw it | the reviewer |
| A changed file on the paths of a kind (`[kinds]`, `person_paths`, `migration_paths`) | The lines the change adds there | the tier |
| A PERSON ticket whose `person_reason` names no changed path | The ticket | the tier |
| An advisory finding the author declined, or a blocking finding the refuter dismissed | The finding's place | the review |
| A Done Contract amended on an AUTO ticket, which no person approved | The ticket, with the amend's reason | an amend |
| An added `SHORTCUT(NN)`, `SENSOR(NN)`, `TODO(NN)` or `FIXME(NN)` | Its line | a marker |
| An added line that matches a flag rule (`rail docs rules`) | Its line | a flag rule |
| A changed manifest, lockfile or `.gitattributes` | The file | the change |

The section ends with a count of the rest: "12 other changed lines: checked by verify, 2 checks and the
reviewer." With no item it says "Nothing needs a person's eye." It is rebuilt whenever the description is: at
ship, and after the review.

- **Each item is also a comment on its line.** When a PERSON ticket reaches its person's merge, and when an AUTO
  ticket is about to merge, the engine posts one review that comments on each item's first line, where that
  line is one the change adds. Each comment carries the engine's mark, so it is posted once per patch and is
  never read as a person's word.
- **A person's answer on a line is heard.** A comment a person leaves on a line of the diff reaches the agent
  as the person's note, like a comment on the conversation, with the same filter: only someone who can push
  to the repository speaks for it.
- **After the fact.** An AUTO ticket merges with nobody reading it. When its list is not empty, the engine sets
  the label `rail:look` as it asks for the merge. The search `is:pr is:merged label:rail:look` is what to read
  afterwards; take the label off when you have. What you find wrong, take out with `rail:revert`, or file a
  ticket for. A PERSON ticket gets no such label: its person reads the list before merging.
- **Generated files fold.** `rail init` writes each `[size] exclude` glob into `.gitattributes` as
  `linguist-generated`, which GitHub folds in a diff. Lockfiles stay in sight. A ticket that changes
  `.gitattributes` is on its own list, because marking a file generated hides it from the diff and from the
  size count.
