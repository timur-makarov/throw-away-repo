# The contract

The contract is a ticket's Done Contract, `scope_paths` and tier. It freezes at acceptance: from then on,
ship and CI fail when the ticket's contract differs from the accepted one, or its tier is lower.

To change it, edit the ticket in its worktree and run:

```text
rail amend NN
```

- A wider or narrower scope, or a higher tier, is accepted again at once. The added paths are recorded.
- A changed Done Contract is accepted at once on a tier in `auto_tiers`. On other tiers the ticket waits
  until a person runs `rail accept NN`.
- A tier never goes down.
