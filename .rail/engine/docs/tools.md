# Tools

A tool is anything the work reaches outside the repository: a service with a key, a CLI that signs in, an MCP
server. A project declares each one in `.rail/config.toml`, so that every agent is told what it may use, and a
missing credential stops a ticket before any work is wasted on it.

```toml
[tools.payments]
use = "The payment service in test mode: create customers and charges in checks"   # what the agents read
env = ["PAY_TEST_KEY"]             # names only, never values; the same name on every machine
probe = 'curl -sf -u "$PAY_TEST_KEY:" https://api.example.com/v1/balance >/dev/null'   # fast, changes nothing
review = false                     # true: the reviewer, the refuter and consult are told of it too
ci = true                          # a test or dev key: a pull request's run may be given it
```

- `use` is needed: one line saying what the tool is for.
- `env` lists the names of the variables the tool needs. A value never goes into the config: an entry that
  is no variable name is refused, and the refusal doesn't repeat it.
- `probe` is a command that exits 0 when the tool can be reached and changes nothing there.
- `ci = true` says the tool's key is one whose leak is undone by rotating it and costs nothing meanwhile: a
  test-mode or dev key. Only such a key may be in a ticket branch's reach (see below). It needs `env`.
- An MCP server stays in `.mcp.json` under the same name; `[tools.NAME]` adds what the engine reads.

`.rail/config.toml` is in `person_paths`, so a ticket that adds or changes a tool is a person's to approve.
Giving a machine a key is a person's act too.

## What the engine does with a declaration

**Briefs list the tools.** The implement brief lists every tool with its `use` line and the names it reads.
The briefs of the review, the security seat, the refuter and consult list only the tools with `review = true`,
and say they are for reading. A value is never in a brief.

**A missing name stops before the claim.** Before a ticket is claimed, each `env` name of every tool must be
set on the machine: in the environment, or with a value in the `.env` at the project's root (the engine reads
that file's names, never its values). While one is missing, `rail next` answers `TOOL_MISSING`, a person's
wait: nothing was tried, so no attempt is counted. It is one wait however many tickets it holds. A ticket
already under way goes on. The brief says where the name is set on that kind of machine: the cloud
environment's variables, the repository's Actions secrets, or the shell and `.env` on a person's own machine.

In a cloud session nobody reads the answer, so the engine opens one issue per tool, labelled
`rail:needs-you`, and closes it when a session finds the name set. No ticket's pull request is labelled for it.

A key that a cloud environment's network proxy adds to requests never shows up as a variable. A tool reached
that way declares no `env` and relies on its probe.

**A probe runs after a failure.** When `verify`, a `Check:` line or a sensor fails at ship, the engine runs
the probe of each tool whose names are set. A failing probe means the step may have failed for the tool's
sake: no attempt is counted, the brief says which tool and to run the ship once more, and a second such
failure in a row waits for a person as `TOOL_DOWN` (`rail docs retries`). So a probe has to be fast and change
nothing: it has 60 seconds.

**`rail doctor` shows each tool:** its names, set or not, where to set a missing one, and the result of its
probe. A probe is not run while a name is missing.

**`rail init` names candidates.** The init task lists the MCP servers in `.mcp.json`, the names in
`.env.example` and the secrets the workflows in `.github/workflows` read, and asks for a declaration of each
one the work uses.

## What a ticket branch can read

A ticket's branch is pushed before any person sees the change, and GitHub runs a branch's own copy of each
workflow. So the branch decides what a run does with whatever that run is given, and a branch can add a
workflow of its own. Three things follow, and no tier, guard or check written in the branch can change them:

1. A run that a pull request starts hands its secrets to the ticket branch.
2. Every repository secret, and every organization secret the repository is given, is in a ticket branch's
   reach, whether or not a workflow reads it today.
3. A secret of a GitHub environment is in reach of every branch that may deploy to that environment.

The worker's own session is in reach in the same way: `.claude/**` hooks in the ticket's worktree run there.

So Rail's rule is: **a secret a ticket branch can reach must be one whose leak is undone by rotating it and
costs nothing meanwhile.** A tool says so with `ci = true`. Every other secret lives in a GitHub environment
that only the base branch may deploy to, and the jobs that need it name that environment.

This limits what a leak costs; it does not prevent one. Nothing detects a key that was read, and rotating a
key is a person's act.

`.github/workflows/rail.yml` passes each `ci = true` key by a line of its own under the `env` of the step that
runs `rail ci`, and never `toJSON(secrets)` or `secrets: inherit`:

```yaml
        env:
          RAIL_BRANCH: ${{ github.head_ref }}
          PAY_TEST_KEY: ${{ secrets.PAY_TEST_KEY }}
```

A check that needs a tool runs in CI only when the tool is `ci = true`. When `rail ci` fails and such a key is
not set in the job, its answer says which. A pull request from a fork or from Dependabot is given no secret.

`rail doctor` checks the rule in three lines:

- **pull request secrets**, from the files: each workflow that a `pull_request` event starts names only keys
  declared `ci = true` and passes no whole set of secrets, and `rail.yml` passes each declared one. The engine
  has no YAML reader: it reads the lines under the workflow's top-level `on` and finds `secrets.NAME` and
  `secrets['NAME']` outside comment lines.
- **repository secrets**, from GitHub: every repository and organization secret is the key of a tool declared
  `ci = true`. When the token may not list secrets, the line says the check did not run.
- **environment NAME**, from GitHub, for each environment that holds a secret no tool declares `ci = true`: its
  deployment branches are the base branch alone, or protected branches only. An environment open to any branch,
  to another branch or pattern, or to a tag fails. A reviewer required on the environment does not pass it: the
  person approving a deployment is not shown the workflow the branch changed.
