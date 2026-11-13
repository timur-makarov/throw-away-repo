# GitHub

Rail talks to GitHub only through `gh api` REST calls, so the same engine runs on a laptop and in a Claude
Code cloud session, where `gh pr` and `gh issue` (GraphQL) don't work.

## One-time setup

`rail init` creates the labels `rail`, `rail:go` and `rail:needs-you`, and writes `.rail/ruleset.json`.
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

- A ticket outside `auto_tiers` opens a contract pull request at `add`, titled `NN: [contract] ...`. Approve
  it with the label `rail:go`, change it by commenting, reject it by closing it. Don't merge it: it holds
  only the contract, and with the ruleset GitHub refuses, because its `rail` check is red. Without the
  ruleset a merge goes through, and Rail takes it as the approval: the work gets a new pull request. Only
  the merge of the ticket's own pull request counts. A ticket file that reaches the base branch any other
  way, such as inside another ticket's merge, approves nothing.
- A ticket in `auto_tiers` opens its pull request at claim.
- No pull request is a draft. The `rail` check stays red with `not shipped yet` until the ticket ships, so
  nothing merges early by mistake.
- At ship the engine writes the title and description: Why, Look at, Evidence, Risk, and the trailers.
- A red required check, or a conflict with the base, returns the ticket to the agent. A pull request that is
  behind its base, when the base requires up-to-date branches, is rebased with no agent work.
- `auto_tiers` merge through the async merge endpoint once the required checks are green. A person merges
  HIGH by pressing the button.

## Testing every merge on the latest base

Turn on "Require branches to be up to date before merging": the engine rebases a shipped pull request that
falls behind, and CI runs again. A merge queue is for organisations with many merges a day; a project that
turns one on adds the `merge_group` trigger to `.github/workflows/rail.yml` and tests it.
