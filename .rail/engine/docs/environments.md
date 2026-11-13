# Environments

Environments belong to the project. Rail touches each at one named point.

| Environment | What Rail does |
|---|---|
| The machine | In a cloud session and on a CI runner, `provision` installs what the checks need, once per machine, as root. On your own computer Rail installs nothing: `rail provision` shows the command |
| Local | `setup` runs in each ticket's worktree with `RAIL_TICKET` set, so parallel tickets can name their own databases and ports. `verify` and the checks run at ship |
| Dev | Nothing at runtime: a ticket ends at its merge, and the project's CD deploys the base branch. Add one step to that CD: after a deploy, run the smoke check, and when it fails, open an issue labelled `rail` whose body starts with `Commit: <sha>`. `rail intake github` turns it into a fix ticket whose `caused_by` is the ticket that commit merged |
| Prod | Nothing. Releasing is a person's act, through the project's CD gate |

- The machine the agent runs on holds local and dev secrets only.
- Risky paths are HIGH, so a person sees them before they reach dev.
- People keep four acts: merging HIGH, deleting data, handling credentials, and releasing to prod.
