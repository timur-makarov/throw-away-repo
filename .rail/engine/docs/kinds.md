# Kinds: what a revert doesn't undo

A person bears responsibility for what can't be undone, and for nothing else. A ticket is PERSON when its change
does something of a kind below; every other change is AUTO: the engine accepts its contract, the reviewer reviews
it, and the engine merges it. A person may still hold any ticket with `rail:hold`.

Each kind has an id. The engine holds the ids as one list, and `[kinds]`, `person_reason` and the journal use them.

| Id | Kind | Why a revert doesn't undo it | Takes effect |
|---|---|---|---|
| `data-loss` | Deleting data; a migration | The data may be gone. A migration's `rollback` is a claim nobody has run | merge (dev data), release (prod data) |
| `data-shape` | A stored or shared data shape: a database schema, a file or wire format, the keys of stored data, a new storage service | Data written in the new shape meanwhile stays after a revert, and old code may not read it; other programs may already depend on the shape | merge, release |
| `data-exposure` | Data copied out of where it lives: production data into a preview, a log, a test fixture, a third party | The copy exists; a revert stops the next copy, not this one | merge, release; at push when a check copies it |
| `external-effect` | An effect outside the system: a message to a real person, a payment, charge or refund, a call that changes a third party's state, text published outside the repository | It happened | release; at merge when dev is wired to real recipients or real money |
| `access` | Credentials, secrets, authentication and permissions | Access granted meanwhile was usable; a leaked secret stays leaked | merge, release |
| `runs-with-secrets` | Code that runs where secrets are: CI workflows, agent settings and hooks, a dependency's install and build scripts | A secret it read is out, and the revert doesn't take it back | push, for what a ticket branch reaches (below); release, for the prod build and deploy |
| `controls` | Rail's own gates, and the files that set an agent's permissions, tools or spend limits | A weakened gate lets later changes through before anyone looks | merge |
| `infrastructure` | Infrastructure a change can delete or replace | The resource and its data are gone | merge or release, by where it is applied |
| `money` | Money committed: a new paid service or plan, a higher tier of one, spend past the caps | The money is spent and the contract signed | merge |
| `licence` | Licence terms the project takes on: a new dependency, copied code | The terms bind what was shipped under them | merge |
| `public-release` | A release that can't be pulled back: a published library version, an app store build, a public API others call | Others already have it | release |

Not on the list, so AUTO: size; the first of something other code will copy; a change to `REVIEW.md` or tests; a
refactor of any size; a change to what users see in the product, when it sends nothing outside the system. Over
`[size] cap`, the first ship offers a split, because a reviewer checks a small change better; the cap raises no
tier (`rail docs loop`).

## How a ticket's kinds are found

- **Paths.** `[kinds]` in `.rail/config.toml` maps kind ids to globs. `person_paths` means `controls` and
  `migration_paths` means `data-loss`, so a config with only those two works as before. A ticket whose
  `scope_paths` reach one is PERSON at `rail add` and at `rail amend`: the engine raises the tier in the ticket
  and, when the ticket has no `person_reason`, writes one naming every kind reached, each with the first path that
  reaches it: `person_reason = "<kind>: <path>; <kind>: <path>"`. A changed file on one raises the tier at
  ship, with a `tier_raised` event naming the `kind`. `rail init` asks for the paths of each kind in the project.

  ```toml
  [kinds]
  runs-with-secrets = [".github/workflows/**", ".claude/**"]
  access = ["src/auth/**"]
  data-shape = ["db/schema/**"]
  ```

- **The author.** A ticket written `PERSON` names its kind in `person_reason`: the id, a colon, and where, such
  as `person_reason = "access: src/auth/session.py"`. Separate several with `"; "`, such as
  `"external-effect: emails each customer; data-shape: db/schema/orders.sql"`. Ticket lint fails a PERSON
  ticket without one, or with a part whose id is not in the list. A change with none of these kinds is AUTO,
  however large or new.
- **The reviewer.** It lists each kind it sees in the change in `kinds`, on every ticket; on an AUTO ticket one
  makes it PERSON (`rail docs review`).

The `accepted` event records the ticket's kinds: its `person_reason`'s, in the order written, and those its
scope's paths reach (`rail docs journal`).

## `runs-with-secrets` at push

Rail's CI workflow runs the ticket branch's own Rail, config and workflow file, and `.claude/**` hooks run in the
ticket's worktree on the worker's machine. So a ticket branch controls what CI and the worker's session do with
any secret they hold, at push, before any PERSON gate: a PERSON contract is approved before the code exists, and
its merge comes after the push. No tier can stop that.

What bounds it is which secrets are in reach at all: only the key of a tool declared `ci = true`, a test or dev
key, with every other secret in a GitHub environment that only the base branch may deploy to. `rail doctor`
checks both (`rail docs tools`). A leak of such a key is still possible, and nothing detects one.
