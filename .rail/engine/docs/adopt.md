# Adopting a branch

Work sometimes starts outside Rail: a person prototypes in their own session, and a branch with commits and
no ticket is the result. `rail adopt` puts that work on the rail. It then gets what every ticket gets: a
frozen contract, the checks, a fresh reviewer, the merge rules and a journal. Nobody redoes the work.

It takes two steps, both `rail adopt`.

## 1. rail adopt BRANCH

With no branch named, it is the current one. The engine reads the branch against the base branch and creates
nothing. Its brief lists the changed files with their line counts, the size against `[size] cap`, and the
tier the change gets: `PERSON` when a changed file is on `person_paths`, `migration_paths` or `[kinds]`, and `AUTO`
otherwise. A size over the cap leaves it `AUTO`: as for any AUTO ticket, its first ship offers a split, and size
raises no tier (`rail docs loop`). It also writes a ticket draft to a file outside the repository and
names it: `scope_paths` from the changed files, the tier, and the template's sections, empty. A folder becomes
one glob, such as `src/report/**`, only when the branch changes every file in it; otherwise the files are
listed.

The agent then fills the draft in:

- **`## Why` and `## Out of scope`** come from the person. When the commit messages don't say why the work
  was done, the agent asks the person for the intent in one question. When no person is there, it writes what
  the commit messages say and adds an `ASSUMED:` row, which must be verified before ship as any other.
- **One `Check:` line for each behaviour** the branch adds or changes: a command that fails on the base branch
  and passes on this one.

Then it runs `rail adopt BRANCH FILE`.

It refuses a branch that doesn't exist, one with no commits beyond the base branch, the base branch itself, a
ticket's own branch, and a branch another ticket adopted already. When the branch is checked out where the
command runs and that checkout has uncommitted changes, it refuses too: only committed work is adopted.

## 2. rail adopt BRANCH FILE

The ticket goes through ticket lint, as at `rail add`. Then comes the one gate that exists only here. The
engine runs each `Check:` line on the base branch and on the branch's head, each in a throwaway worktree
where `[commands] setup` ran first. Every check must fail on the base and pass on the branch. A check that
passes on the base can't show the work was done, and one that fails on the branch isn't met. A check that
could not run or timed out on the base counts as not failing there: it showed nothing. When any check falls
short, the engine lists each one with its two results and creates nothing.

A ticket written first gets the same test at its claim, but there it is only recorded, because the work
isn't done yet. Here the work is done, so a check that doesn't tell the base from the branch would let the
branch through with a contract that proves nothing.

When the checks hold, the engine:

- files the ticket as `rail add` does. An AUTO ticket is accepted at once. A PERSON ticket waits for a person
  to approve its contract, with the work already on its branch;
- makes the ticket's branch, `NN-slug`, from the adopted branch's head, so it holds the adopted commits with
  the ticket on top. The adopted branch itself is left as it is, and needn't be pushed: with a remote, the
  ticket's branch is pushed;
- writes the check results as the ticket's `base_checks` event, so the claim doesn't run them again, and an
  `adopted` event with the branch and its head commit;
- claims the ticket for this session and makes its worktree, with setup run there.

The answer names the ticket and the next command, `rail advance NN`. From there it is a ticket like any
other: ship, the checks, the review and the merge. A branch that is behind the base branch is rebased at
ship, and a conflict comes back to the agent as at any ship. A changed file outside `scope_paths` fails the
scope check at ship.

`rail stats` counts the merged tickets that came in this way.
