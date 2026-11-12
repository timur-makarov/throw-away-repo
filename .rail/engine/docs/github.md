# GitHub

Rail talks to GitHub only through `gh api` REST calls, so the same engine runs on a laptop and in a Claude
Code cloud session, where `gh pr` and `gh issue` (GraphQL) don't work.

## One-time setup

`rail init` creates the labels `rail`, `rail:go` and `rail:needs-you`. Then, in the repository's settings:

- Make `rail` a required check on the base branch (a ruleset or branch protection).
- Allow squash merging only, with "Pull request title and description" as the default message, so a
  person's merge puts the same `Ticket:` trailer on the base branch as the engine's.
- Turn on "Automatically delete head branches".
- Turn on Dependabot or Renovate.

`rail doctor` checks the required check, the squash setting and the labels.

## How tickets use pull requests

- A ticket outside `auto_tiers` opens a contract pull request at `add`, titled `NN: [contract] ...`. Approve
  it with the label `rail:go`, change it by commenting, reject it by closing it.
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
