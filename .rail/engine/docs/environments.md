# Environments

Environments belong to the project. Rail touches each at one named point.

| Environment | What Rail does |
|---|---|
| The machine | In a cloud session and on a CI runner, `provision` installs what the checks need, once per machine, as root. On your own computer Rail installs nothing: `rail provision` shows the command |
| Local | `setup` runs in each ticket's worktree with `RAIL_TICKET` set, so parallel tickets can name their own databases and ports. `verify` and the checks run at ship |
| Dev | Nothing at runtime: a ticket ends at its merge, and the project's CD deploys the base branch. Add one step to that CD: after a deploy, run the smoke check, and when it fails, open an issue labelled `rail` whose body starts with `Commit: <sha>`. The intake reverts first, then fixes (below) |
| Prod | Nothing. A release goes through the project's CD gate; Rail has no part in it |

- The machine the agent runs on holds local and dev secrets only.
- A change to `person_paths` or `migration_paths`, or a change of a kind in `rail docs kinds`, is a PERSON
  ticket, so a person sees it before it reaches dev.
- A person is asked only about what a revert doesn't undo (`rail docs kinds`): a PERSON ticket's contract
  and its merge. Credentials stay with people: the machine never holds a prod secret.

## A failed deploy to dev reverts first

An open issue labelled `rail` whose body starts with `Commit: <sha>` says the smoke check failed on a deploy
of that commit. The ticket the commit merged is the cause. The next `rail next` (or `rail intake github`)
then does three things, once for an issue:

1. **A revert ticket** for the cause (`rail docs tickets`), with `external_id` `smoke#` and the issue's
   number. It is AUTO unless its paths hold a kind, and its pull request says `Part of #N`, so merging it
   leaves the issue open.
2. **A brake on the cause's scope**: an issue labelled `rail:stop` with a `paths:` line of the cause's
   `scope_paths`, so that no other ticket builds on the change that failed. The revert goes on under it. The
   engine closes it when the revert has merged or was dropped; closing it yourself lifts it at once.
3. **The fix ticket**, from the issue as before, with `after` set to the revert and `caused_by` to the cause:
   it does the cause's work again so that the smoke check passes, and its merge closes the issue.

Dev works again as soon as the revert merges, however long the fix takes. `rail stats` gives the time from
the issue to the revert's merge.

**A chain ends.** When the cause was itself the fix after a failed deploy, the same work has failed on dev
twice: the engine files the revert and no further fix. When the cause is a revert, it files neither, since
reversing a revert puts the failed change back. In both cases it comments on the issue, labels it
`rail:needs-you` and takes `rail` off; a person who labels it `rail` again gets one more fix ticket.

When the commit merged no ticket, or the ticket changed none of the project's own files, the issue becomes
a fix ticket and nothing else.
