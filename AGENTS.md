## Rail

This repository runs on Rail: the engine owns ticket state, and you write the code.

- The loop: `rail next --json`, do what `action.brief` says, then `rail advance --json`. Repeat.
- When `owner` is not `agent`, tell the person what is needed, then take the next ticket or stop.
- New work is a ticket: write it like `.rail/tickets/TEMPLATE.md`, then run `rail add <file>`.
- Work in the ticket's worktree (`cwd` in the answer), and change only paths in its `scope_paths`.
- Only the engine writes `.rail/journal/`. Answer each review finding with `rail answer NN F1 fixed|declined|parked "why"`.
- To change a frozen contract (Done Contract, scope, tier), edit the ticket in the worktree and run `rail amend NN`.
- `rail status` lists every ticket. `rail context NN` shows the areas a ticket touches.
- How to code, test and debug is your craft and your skills. Rail says only what is legal next and what counts as done.
- Everything else: `rail docs`.
