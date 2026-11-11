# Rail: the plan

Date: 2026-11-11. This is the single plan for rebuilding https://github.com/timur-makarov/agentic-framework. It merges [RECOMMENDATIONS.md](RECOMMENDATIONS.md), [VERDICTS-completeness.md](VERDICTS-completeness.md) and the four rounds of [ANSWERS.md](ANSWERS.md). Those files stay as the reasoning and the research trail, and [DECISIONS.md](DECISIONS.md) records what each review round decided. Where they disagree with this file, this file wins.

The CLI is `rail`. A person sets a project up with `rail init` (section 14).

## 0. Status

**Decided by the owner:**

- **Scope:**
  - The lens; not a product.
  - No attacks.
  - The standard setup is clone plus Claude Code.
  - Build for git, GitHub and Claude Code only, for now (2026-11-10). Other popular tools, such as other trackers, forges, CI systems and hosts, must stay possible to add later through the CLI surface (section 19), but none is designed now. The framework stays a railroad a project can change and extend.
  - macOS and Linux only.
  - No license.
  - No support for old versions.
  - No decision is based on a host.
  - The necessity test applies to every item.
  - Token cost is not a concern.
- **Engine and config:** Python 3.11+ with `tomllib` and TOML config.
- **Tiers and size:**
  - LOW is the most common tier and runs automatically to merge.
  - Size caps are LOW 300 and MEDIUM 600.
  - At the retry cap, `consult` runs, then a person takes over.
- **Install and customising:**
  - No `upgrade`, no `uninstall` and no override layer. Projects customise through HIGH tickets or a fork.
  - Craft skills install their own way.
  - No built-in areas.
- **Lessons:** the framework's lessons become checks; the person's lessons are the owner's later pack.
- **Removed:**
  - red-first checks
  - the Stop hook
  - the "cut on purpose" list
  - Windows
- **Next:** the `consult` pack is built in Phase 3.

**The decision history** is in [DECISIONS.md](DECISIONS.md): what each review round decided, and what the owner approved on 2026-11-11. Sections 1 to 25 state the result.

## 1. What this is

**The framework is the rail between craft and orchestration.**

- **Craft** is how to code, design and debug. It lives in the person's own skill libraries.
- **Orchestration** is starting agents, queues, dashboards and fan-out. It belongs to hosts.
- **The rail** is core: what is legal next, what counts as done, and when a person must act.

Every change names its layer first.

**Why:** a machine should program the machine, so people stop fighting it. The rail pays off when code has a future. The goal is that ticket 50 is as easy as ticket 1. With no tomorrow, running without a rail is faster, and the framework doesn't fight that: LOW runs on its own.

**Not a product.** It's built for the owner and anyone interested. "Ready to use" is a direction: small and medium projects, automations and tools.

**Rules for every item:**

- **Necessity test:**
  - Will about 80% of projects use it?
  - If a person or agent can set it up once in a few minutes, leave it to them.
  - Is simplicity really worth giving up for it?
  - Don't design for edge cases.
- **No attacks.** Every engagement is by a person, or checked elsewhere. Guards prevent mistakes; nothing defends against a cheating agent, and there are no attack test suites.
- **The standard setup:**
  - Clone the framework and use Claude Code.
  - macOS and Linux.
  - Compatibility with common orchestrators is welcome, but never at the cost of simplicity.
- **Language-neutral:** any language, and monorepos. A feature is either standard behaviour or a pack; there are no fallbacks tied to one language.
- **Tests and measurement:** tests stay general. Measurement waits; the event log is the only groundwork.
- **Deletion test for every guard, field and step:** it must name the real run it would have saved, or stand in front of an irreversible act. Every config field names its reader.

## 2. Why rebuild

The research compared the framework with 37 studied repos and ran it in throwaway copies. Four of the reports used their repo as a negative control. The idea held up in the other 33 comparisons:

- one first-match table names the next legal move;
- scripts own state;
- tickets carry a frozen contract with runnable checks.

Several larger projects lack this.

What did not hold up:

1. **Packaging.** Copy-in mixes the framework, the framework's history and the project in one tree, which is why the ADRs are hard to delete.
2. **Interface.** Text output and an overloaded exit 1 can't be driven by a program.
3. **Honesty of steps.** A reviewer the agent starts itself can be skipped or faked by accident, and a skipped step can look like a pass.
4. **Runtime.** About 4,100 lines of bash, awk, jq and regex. In a test with 120 tickets, Python parsed the same files in 32 ms against 308 ms for the bash `next`. Treat the numbers as direction only; a second run differed.

**So: keep the workflow and rewrite the runtime.** Phase 1 builds the new core.

## 3. Layout

```text
framework repo (dev)               project after rail init
  bin/rail   the launcher            .rail/
  install    puts rail on PATH         bin/rail      the launcher; on PATH in every session
  engine/    copied by rail init       engine/       the framework and its docs; the project's after init
  seed/      copied once               config.toml   project policy
  packs/     optional features         tickets/      NN.md, one per ticket
  docs/      the framework's ADRs      journal/      per-ticket evidence (NN-*)
  CHANGELOG.md  why each change        SOURCE        framework repo URL and commit it came from
                                     ARCHITECTURE.md   ## Areas (made by the init task)
                                     AGENTS.md       a ~15-line ## Rail section, added by init
                                     CLAUDE.md       imports AGENTS.md, only if the project has one
                                     .claude/        settings.json hook entries, sandbox
                                     .github/workflows/rail.yml
                                     .claude/worktrees/NN   one per claimed ticket (ignored by git)
                                     local cache     in the git common dir, rebuilt from branches
```

**Engine:**

- Python 3.11+ standard library only, vendored into the repo, so every clone and every CI run has the same version.
- `rail init` stops with one line if Python is older; macOS ships 3.9, and `brew install python` fixes it.
- Config is `.rail/config.toml`, and ticket front matter is TOML between `+++` lines, so there is no custom parser.
- Unknown keys fail with a suggestion.

**After `rail init`, every file is the project's,** the engine included.

- A change to `.rail/bin/`, `.rail/engine/`, `.rail/config.toml`, `.claude/` or `.github/workflows/` is in the default HIGH `risk_paths`, so a person sees it at merge.
- **Non-product paths** are `.rail/tickets/**` and `.rail/journal/**`. Every branch touches them, so they are left out of the tier, the scope check, the size count and `patch-id`.
- There is no `upgrade`. To take changes from a newer framework, the person asks the agent to clone the framework and integrate. The agent diffs from the commit in `.rail/SOURCE` and reads `CHANGELOG.md`. That work is an ordinary HIGH ticket.

**State:**

- The local cache is keyed by ticket.
- Everything a resume or budget needs is in the ticket's journal on its branch, so state rebuilds from the pushed branch. A fresh clone or VM loses nothing.

## 4. Config

The whole config surface, with defaults where they exist. Every field lists its reader.

```toml
base_branch = "main"                      # reader: claim, ship, CI, merge
auto_tiers = ["LOW", "MEDIUM"]            # accepted and merged with no person; other tiers get a contract PR and a person's merge
migration_paths = ["**/migrations/**"]    # a HIGH floor, like risk_paths; tickets touching them need reversibility and rollback
                                          # top-level keys come first: in TOML, a key below a [table] header belongs to that table

[commands]
setup  = "pnpm install"                   # after each worktree is made
verify = "pnpm test && pnpm lint && gitleaks git --log-opts=origin/main..HEAD"
                                          # whole project, at ship and in CI; scanners and generators go here too.
                                          # A monorepo makes it affected-aware with its own tools (turbo, nx, make)
timeout_secs = 900                        # per command: setup, verify, each check, each review run

[risk_paths]                              # floors for the tier, matched against scope_paths at add; proposed by the init task
HIGH   = [".rail/bin/**", ".rail/engine/**", ".rail/config.toml", ".claude/**", ".github/workflows/**"]
MEDIUM = []

[size]                                    # changed lines, see section 9
LOW = 300
MEDIUM = 600
exclude = []                              # extra globs; generated files and lockfiles are already excluded

[review]
# runs in the ticket's worktree with the brief on stdin; the engine resets the worktree afterwards
# the command runs through sh; --json-schema takes the schema's text, not a path
command = '''claude -p --safe-mode --system-prompt-file .rail/engine/reviewer.md --tools Read,Grep,Glob,Bash,Edit,Write --allowedTools Bash,Edit,Write --disallowedTools 'Bash(git push *)' --output-format json --json-schema "$(cat .rail/engine/review-v1.json)"'''

[retry]
budget = 2                                # attempts per step; then consult, then a person

[consult]                                 # reader: the consult pack (section 18)
command = "claude -p --safe-mode --tools Read,Grep,Glob"
                                          # read-only, with the brief on stdin. Point it at another vendor's CLI when you
                                          # have one; a consult by the author's own model is labelled same-model

[sweep]
after = 20                                # LOW tickets and ticketless commits since the last sweep

[map]
depth = 1                                 # directory depth that doc-lint expects in ## Areas
ignore = []

[[rules]]                                 # structure rules, section 12
id = "no-new-suppressions"
forbid = ["eslint-disable", "@ts-ignore", "# noqa", ".skip("]
allow = []
fix = "Fix the cause instead of silencing the check."
```

## 5. The ticket

```markdown
+++
id = "14"
title = "Rotate refresh tokens on use"
tier = "MEDIUM"                    # the author's choice; the engine may only raise it
scope_paths = ["auth/**", "tests/auth/**"]
after = ["12"]                     # waits for 12 to merge
caused_by = ""                     # set on fix tickets, for history and learning
external_id = "github#123"         # or "PROJ-123"; makes intake idempotent
+++

## Request
(optional: the words the work came in with, verbatim from the person or the issue)

## Why
Refresh tokens can be replayed after use.

## Done Contract
- Check: `pytest tests/auth/test_refresh.py`

## Out of scope
- Session storage changes.

## Assumptions
- ASSUMED: sessions are stored server-side.
  (after the claim, the agent verifies each one or asks; an open one blocks ship)

## Look at
(written by the agent before the PR: what a reader should check; it becomes "Look at" in the PR)

## Split
(optional work breakdown)
```

**Tickets that touch `migration_paths`** are HIGH and must set `reversibility` (for example `expand-contract`) and `rollback` in the front matter. That is the migration gate, with no SQL parsing.
- `next` prints a short migration brief when the gate applies: expand then contract, write the down step, test the rollback.
- Both fields appear in the PR's Risk section, which is what the person merging reads.

**Dropped sections:**

- Blast Radius and `blocked-on-alignment`: an unclear decision is an ASSUMED row the agent can't verify, which makes it a wait.
- Open questions and `blocked-on-answers`: these go into Assumptions too.
- Resolution: the PR description and the journal hold it.

**A ticket exists as its branch.**

- `add` takes the next ID and creates branch `NN-slug` (with the external id in it when there is one). It commits the ticket file there without touching the current worktree, and pushes when there is a remote.
- **The next ID** is one more than the highest ticket ID found in `rail/id/NN` branches, on base and in ticket branches.
- This works the same when tickets are created in the middle of other work: by the sweep, by `intake`, or from a failed dev deploy reported as an issue.
- **IDs and claims are taken on the remote,** so two clones never take the same one: a laptop and a cloud session, or two cloud runs. Git refuses each push below when someone else got there first.
  - `add` takes ID NN by pushing the branch `rail/id/NN` at the ticket's first commit. If the push is refused, the ID is taken, and `add` tries the next ID. The ID branch is never deleted, so a dropped ticket's ID is never reused and its ticket file stays reachable. It is a branch, not a tag, because the cloud proxy refuses tag pushes (section 25). A branch would accept a fast-forward, but no other ticket's first commit descends from this one.
  - A claim is a commit with the `claimed` event, pushed to the ticket branch. If the push is refused, the branch moved: the engine fetches, and if the branch now holds a claim, it takes another ticket.
  - With no remote, a `mkdir` in the git common dir does the same within one clone.

**State is derived, never written by hand.** It comes from git, the journal and the forge (section 7).

**The tier** is the highest of three:

- the author's choice;
- the `risk_paths` and `migration_paths` floors, matched against `scope_paths` at `add`;
- the size cap at ship (section 9).

It freezes at acceptance and can only go up after that. A raise at ship needs no new contract approval: if it leaves `auto_tiers`, the person sees it at merge.

**The contract** is the Done Contract, scope and tier. It freezes at acceptance. `amend NN` changes it, with the tier's acceptance again; outside `auto_tiers`, that means the label again. An amend that only widens scope needs no new approval: the added paths are listed under Risk in the PR, so the person sees them at merge, as with a tier raise at ship. Changing the Done Contract still needs the label.

**The journal**, per ticket, lives under `.rail/journal/` and merges with the code:

| File | Holds |
|---|---|
| `NN-events.jsonl` | Script-written events: step, outcome, tokens if known, and how each finding ended (`fixed`, `declined` or `parked`, with the reason). The sweep reads the `parked` ones from every ticket |
| `NN-review.json` | Reviewer output, bound to the patch by `git patch-id` |
| `NN-advice.md` | `consult` output |
| `NN-summary.md` | The sweep's one-page summary, on a sweep ticket only (section 12) |

The fields of the review file and the list of events are in [SPEC.md](SPEC.md).

**Checks:**

- `Check:` lines must pass at ship and in CI.
- The vacuous-check lint rejects checks like `true` or `echo ok`.
- There is no red-first rule. Test order is craft, and a new test file fails on base for a trivial reason.

## 6. The loop

```text
next --json -> do action.brief -> advance --json -> repeat
when owner is not "agent": tell whoever is listening and take the next ticket, or stop
```

**Every verb accepts `--json`** and answers in the same shape:

```json
{"schema_version": 1, "ok": true, "ticket": "14", "state": "implementing",
 "owner": "agent", "cwd": ".claude/worktrees/14",
 "action": {"kind": "agent_task", "brief": "Implement the Done Contract in .rail/tickets/14.md"},
 "reason": {"code": "CLAIMED"},
 "steps": [{"step": "verify", "status": "ran", "result": "pass"}]}
```

| Field | Values |
|---|---|
| `owner` | `agent`, `human`, `none` |
| `action.kind` | `script`, `agent_task`, `human_wait` (what is needed, the link, the options), `rest` |
| `steps[].status` | `ran`, `not_run`, `unavailable`. A skipped step never looks like a pass |

- "No ticket" is not an error: `next` returns `rest`.
- **Exit codes:** 0 when the command worked (read `owner`), 2 for a usage error, 3 when a step failed.
- **Verbs:** `init`, `add`, `accept`, `amend`, `answer`, `next`, `advance`, `status`, `context`, `intake`, `drop`, `docs`, `doctor`, `sweep`, `ci`. `init` sets a project up (section 14). Packs add verbs such as `consult`. `forge` is the engine's internal module for `gh`, not a verb.
- **Follow-up work after a merge** is a new ticket with `caused_by`; a merged ticket never reopens.
- **`intake` has two forms:** `rail intake github` pulls issues labelled `rail`, and `rail intake --external-id KEY --title T --brief FILE` covers anything else. Both are idempotent by `external_id`. `intake` writes the request and leaves the tier and Done Contract empty. `next` then returns the agent task "write the Done Contract and set the tier", and the ticket gets its `accepted` event (auto tiers) or its contract PR (other tiers) only once ticket lint passes.
- **Finding the ticket:** `--ticket <id or external id>`, then `RAIL_TICKET`, then the worktree it runs in. IDs are strings.
- **Offline:** `next`, `advance` and `context` work offline, and network steps report `unavailable`. With no remote, `advance` merges locally with the same squash format.
- **Procedures are printed by `next`** as the brief: how to implement, how to answer findings, how to ship. They cost nothing until needed, and they never collide with a craft skill's name.
- **The `AGENTS.md` section,** about 15 lines under the heading `## Rail`, names the loop and points to `rail docs`. The heading lets the engine leave this section out of the reviewer's brief (section 8). Claude Code reads `AGENTS.md` on its own. A `CLAUDE.md` stops that, so if the project has one, `rail init` adds `@AGENTS.md` to it. The framework never creates `CLAUDE.md`. A `CLAUDE.local.md` or a `CLAUDE.md` in a parent folder stops it too, and `doctor` warns when it finds one.
- **The SessionStart hook** prints a snapshot after a start or a compaction: ticket, state, Done Contract and scope. A crash or compaction needs no handoff written by the agent. The hook also puts `.rail/bin` on `PATH` (section 14).
- **Each claim records `CLAUDE_CODE_SESSION_ID`,** so the snapshot shows the ticket this session is on, even when several sessions share the machine.
- **A claim is held by its worktree, not by a session.** `next` prefers the ticket claimed with this session's id. Other claimed tickets are listed as resumable, and `next --ticket NN` takes one over after a crash and records the new session id. A takeover is a pushed commit, like a claim, so two takeovers started at once can't both succeed. In a clone without the ticket's worktree, such as a fresh cloud run, the takeover makes it again from the pushed branch. Two live sessions on one ticket is a person's mistake, which the engine doesn't try to prevent.

## 7. Lifecycle

```text
new ─► accepted ─► implementing ─► reviewing ─► in-ci ─► merge-ready ─► merged
       (outside auto_tiers:        (MEDIUM,     (auto tiers: the engine merges
        rail:go on the           HIGH)        here; otherwise a person merges)
        contract PR)
   ◄── a red required check (CI, or a bot the project requires), a rebase conflict or a person's push returns the ticket to implementing, on the same PR
any state can also be waiting on a person (owner: human); drop ends a ticket
```

**How each state is derived:**

| State | Derived from |
|---|---|
| `new` | The ticket branch exists and there is no `accepted` event. Outside `auto_tiers` it waits for a person. Inside, it waits for the agent to make ticket lint pass, as with an `intake` stub |
| `accepted` | An `accepted` event in the journal, with no `claimed` event. `auto_tiers` get it when ticket lint first passes, normally at `add`. Other tiers get it from `accept`, or when `next` sees `rail:go` on the PR |
| `implementing` | A `claimed` event, and one of: the current product patch has not passed the ship steps; a required check failed on the PR head; the PR conflicts with base (`mergeable_state: dirty`) |
| `reviewing` | The ship steps passed for this patch, the tier needs review, and no complete review exists for this `patch-id` |
| `in-ci` | The ship steps (and the review, where the tier needs one) passed for this patch, and CI hasn't finished on the PR head |
| `merge-ready` | CI is green on the head, and every finding is answered |
| `merged` | A squash commit with `Ticket: NN` is on base |
| `dropped` | A `dropped` event, or the PR was closed without a merge |

**The PR exists from the start.**

- For a tier outside `auto_tiers`, the contract PR opens at `add`.
- For a tier in `auto_tiers`, the PR opens at claim.
- No PR is a draft: REST can't mark one ready, and GitHub counts a required check skipped on a draft as passed. Instead, until the ticket ships its current patch, the `rail` check fails with `not shipped yet`, so no PR can be merged early by mistake.
- So every wait after `add` has a PR to label.
- With no remote, the same states come from the journal and local merges.

| Step | What happens |
|---|---|
| `add` | The agent or a person writes the ticket; `intake` makes one from an issue. Section 5 covers the branch and ID |
| Accept | Automatic for `auto_tiers`. Otherwise, the person adds `rail:go` to the contract PR or says "accept 14". The contract and tier freeze |
| Claim | Inside `next`. Refused while an `after:` ticket is unmerged, or while scope overlaps an `implementing` ticket. It makes `.claude/worktrees/NN` on the ticket branch, copies the files listed in `.worktreeinclude` (such as `.env`), and runs `setup` there. While an ASSUMED row is open, the brief is "verify it or ask" in place of "implement", and a row the agent can't verify becomes a wait on the PR (section 10) |
| Implement | `next` shows the size count (`size 240/300`), and at 80% suggests splitting the rest into a new ticket. `advance` commits in-scope changes with the `NN:` prefix and pushes the branch, so any clone can resume from it; changes outside scope fail |
| Ship (`advance`) | Runs `verify`, ticket `Check:` lines, structure rules on added lines, the scope check, the size cap, `doc-lint`, the migration gate and ASSUMED rows. A failing step returns an `agent_task` with the output |
| Review | MEDIUM and HIGH only (section 8) |
| PR | The engine pushes and writes the title and description (section 9) |
| CI | The `rail` job repeats the ship checks (section 11). A red required check sends the ticket back to `implementing`, and the brief includes the check's output and that check's review comments |
| Merge | `auto_tiers`: once CI is green, `next` returns `rail advance NN`, which merges through the async merge endpoint, `PUT /repos/{owner}/{repo}/pulls/{n}/merge-async` (REST): squash, the head commit pinned with `sha`, the generated subject and body. The engine notes the request in the local cache, not the journal, because a journal commit would move the head CI just passed. The ticket is `merged` once its squash commit is on base, so nothing polls. A clone without the note sees a green, unmerged PR and asks again. GitHub's docs say the same call adds the PR to a merge queue when the ruleset requires one; a queue is the project's to set up and test (section 11). If the request failed, the next `next` reads why: a conflict or a red check returns the ticket to `implementing`, and anything else waits for a person. Your own token makes the merge, so workflows on push to main run. Others: the person merges, and the repo's squash setting (section 11) puts the same trailers on main. Open branches rebase onto the new base at their next ship, or as soon as `next` sees their PR conflicts: GitHub runs no workflow on a conflicted PR, so nothing else would notice |
| `drop` | Closes the PR, deletes the branch and worktree, and logs the event. For a ticket from an issue, it removes the `rail` label from the issue and comments with the PR link, so `intake` doesn't make the ticket again; labelling the issue again is how to retry. Safe to rerun. A PR closed by hand counts as dropped and gets the same cleanup, through leftovers (below) |

**What `next` returns when tickets wait:**

- It takes any ticket the agent can act on first.
- If only CI waits remain, it returns `script: gh run watch <run> --exit-status`, then `rail next`. `gh` does the waiting through REST, so the engine never polls, and a green result merges, or a red one is fixed, in the same session. If the session ends first, the PR waits, and the next session's `next` merges it or returns the red result.
- If only human waits remain, it returns `owner: human` with the list, and the session can stop.

**Retries:**

- The retry budget counts attempts per step: 2 by default. Changing error text can't reset it.
- When the budget is used up, `consult` runs, then one more attempt, then `owner: human`.
- `consult` is installed by default. Without it, the cap goes straight to `owner: human`.
- **A red base spends no budget.** Two tickets that each pass can break main together, because branches needn't be up to date by default. A project that requires up-to-date branches (section 11) doesn't hit this. When `verify` fails at ship, the engine runs it once more on base in a scratch worktree. If base fails too, the attempt doesn't count, and `next` opens one fix ticket for base; other tickets' ships wait until it merges.

**`status`** lists every ticket from git and the journal, with no new state:

```text
$ rail status
TICKET  STATE         OWNER  LAST EVENT  NOTE
12      in-ci         agent  4m          PR #57
14      new           human  1d          waiting: approve contract, PR #61
15      implementing  agent  3d          STALE: no event for 3 days
16      implementing  agent  6d          STALE: no worktree found
leftovers: worktree .claude/worktrees/09 (ticket 09 merged)
           remote branch 07-old-auth (ticket 07 dropped; deletion refused here)
           branch 11-old (no ticket; left for you)
```

**Leftovers stay listed until they're gone.**

- Each `next` removes what it can: the worktree and the local and remote branch of every merged or dropped ticket.
- What it can't remove stays under `leftovers` with the reason, and a later `next` tries again. A cloud session's proxy refuses branch deletion, so a remote branch waits for a local session, or for GitHub's "Automatically delete head branches" setting, which covers merged tickets.
- It never removes a worktree with uncommitted changes, or a branch that belongs to no ticket. Those stay listed for the person.

## 8. Review

There is one review, run the same way every time.

1. **The gate launches it.** `advance` runs `review.command` in the ticket's own worktree. Dependencies are installed there, and the tree is clean, because `advance` has just committed everything.
   - By default the command is `claude -p --safe-mode` with the prompt below, the tools Read, Grep, Glob, Bash, Edit and Write, `git push` denied, and `--json-schema`, which takes the schema's text. The brief goes in on stdin.
   - `--safe-mode` loads no `CLAUDE.md`, `AGENTS.md`, hooks or custom agents, while login and permission rules work as usual. So the reviewer never sees the loop's instructions, and project hooks don't run for it. The brief then gives it the project's own part of `AGENTS.md`, everything except the `## Rail` section, so it judges the change by the project's conventions.
   - The reviewer may run commands and write scratch files to test a hypothesis: run a test, write a failing one, start the program.
   - Afterwards the engine resets the worktree to the reviewed commit and deletes untracked files, so whatever the reviewer changed is thrown away. The security seat and the refuter run the same command, one after another, with a reset between. Each run has one job, which its brief sets (below).
   - The engine reads `structured_output` directly, so the agent can't forget the step or fill the gap itself.
   - Running `claude -p` from inside a Claude Code session works in current versions.
   - `rail init` raises the Bash tool timeout (`BASH_DEFAULT_TIMEOUT_MS` and `BASH_MAX_TIMEOUT_MS`), because a review can run longer than the 10-minute default maximum.
   - Each run has the `timeout_secs` limit, because a reviewer can start a command that never ends. In the test below, 2 of 39 runs hung on a command that read from stdin. A run that times out is started once more, and a second timeout waits for a person. Neither spends the retry budget.
2. **Output:**
   - It must match the `review/v1` schema, which is in [SPEC.md](SPEC.md).
   - It is bound by `git diff -U0 <merge-base>...HEAD -- <product paths> | git patch-id --stable`. With no context lines, a clean rebase keeps the same id: the checks rerun, the review doesn't.
   - Invalid or missing output fails the step.
3. **The brief:**
   - the diff and the contract;
   - the matching `## Areas` rows and directory digest from `context`;
   - the project's part of `AGENTS.md`;
   - what to look for in this run (below);
   - the do-not-report list;
   - on a re-review, the earlier findings with the author's answers.
4. **What it reports:** the reviewer may read anywhere, and reports what the change touches.
   - A finding has an id, a severity, a location and a claim.
   - The optional `check` field names what would catch this kind of mistake.
   - The optional `evidence` field holds a command the reviewer ran and its trimmed output, when running something could show the problem.
   - A problem the change didn't cause becomes `parked`.
5. **Every finding ends `fixed`, `declined` with a reason, or `parked`.** The agent records each with `rail answer NN F2 parked "reason"`, which writes an event, and `advance` checks that none are missing.
   - The author cannot decline a blocking finding. If the author disputes one, a fresh refuter decides. It sees the location, the claim and the evidence, not the author's argument, and reruns the evidence when there is some.
   - If the refuter upholds it and the agent still can't fix it, `owner: human`.
6. **Re-review** reads the whole diff again, with the previous findings and responses, up to the retry budget. If the budget runs out before the final patch has a clean review, `owner: human`.
7. **HIGH adds a separate security seat:** a second run of the same command whose brief asks only about security, with a refuter for each blocking finding. On HIGH the main review leaves security to it. A person merges HIGH, but isn't necessarily a security reviewer.
8. **Outside reviewers** (Bugbot, CodeRabbit, people) are not a findings ledger, because the merge doesn't wait for comments, and there is no point at which all comments are in.
   - A bot the project wants obeyed is made a required check. The merge then waits for it, and a red result returns the ticket to `implementing` with that bot's comments in the brief.
   - A person's comments during a wait go into the next brief (section 10).
   - Everything else is advisory. To stop a merge, a person adds `rail:needs-you` to the PR (section 10).
9. **Findings become checks.** The `check` field of every fixed finding is kept in the journal. The sweep groups them, and opens one LOW ticket, "make it a check: ...", for each kind it sees, with `caused_by` set. One ticket per finding would flood the backlog.

**The reviewer prompt**, `.rail/engine/reviewer.md`:

```text
You review one change to this repository. You don't claim or ship tickets, and you don't push.

The brief gives you the ticket (why, Done Contract, scope, risk), the diff, the matching
## Areas rows, the project's conventions from AGENTS.md, what to look for in this run, and
on a re-review the earlier findings with the author's answers. Read any file you need.
You may run commands and write scratch files to test a hypothesis; everything you change
is thrown away after the review.

Report only what the brief asks you to look for, and only problems this change causes or
exposes. Each finding names a concrete input or sequence that goes wrong.
A problem the change didn't cause is parked. Style is not a finding unless a rule says so,
and neither is a choice the project's conventions make.

Each finding has a location (file:line), a claim in one or two sentences, a severity, and,
when a deterministic check could catch this kind of mistake, a `check` saying what it
would be. The severity is blocking, advisory or parked. Blocking means the change must not
merge as it is: a wrong result, a crash, lost data, a security hole, or a Done Contract
item that isn't met. Advisory means worth fixing but safe to merge. When you can show the
problem by running something, put the command and its output in `evidence`.

On a re-review, review the whole change again. When an earlier finding still stands,
report it with its id in `repeats` and keep its severity.

Return only JSON matching the schema. `summary` says what you checked and how. An empty
list is a valid review.
```

**This wording was tested on 2026-11-11.** The test was 39 real runs on a small fixture repo, with Claude Code 2.1.292 and `claude-opus-5-5`; 15 of them used this wording:

- On a first review it found all 7 planted problems in 3 of 3 runs, and reported none of the 3 decoys.
- On a clean change it raised no blocking finding.
- On 9 re-reviews it repeated the unfixed finding with its id every time, kept each severity, and caught a new bug in 7.
- A longer rewrite caught that new bug in only 1 of 3 re-reviews. So change this prompt only with a test of the same kind.

**What to look for** is the part of the brief that changes between runs, so each run has one job:

- **Review (MEDIUM and HIGH):**
  - a Done Contract item the diff doesn't meet;
  - a bug: a wrong result, a crash, data loss, a race;
  - missing or weak checks for behaviour the diff adds;
  - code in the wrong area, or a doc the change makes wrong;
  - what generated code gets wrong: a check weakened, skipped or deleted so that it passes; a call to a function, flag or API that doesn't exist; state that is set but never cleared, or cleared on only one path; debug output or temporary code left in;
  - on MEDIUM only, the security section (below). On HIGH the security seat owns security.
- **Security seat (HIGH):** only trust boundaries, input handling, auth, secrets and data exposure, including unchanged code the diff now reaches. It reads `THREAT_MODEL.md` if it exists.
- **Refuter (a disputed blocking finding):** whether that one finding holds. It returns the finding if it does, and an empty list if not.
- **Sweep (section 12):** the sweep brief.

**The security section** is ten one-line prompts. It is the last item of "what to look for" on MEDIUM, and the security seat's checklist on HIGH:

```text
Security. This list is a checklist, not a ceiling. Report only what someone could exploit in this application:
1. authorization: checked at object level and on every path;
2. authentication and sessions;
3. injection into SQL, shell, templates, paths or deserialisers;
4. outbound requests, webhooks and redirects;
5. secrets and personal data in code, logs or URLs;
6. business logic: invariants, replay, check-then-act;
7. fail-open defaults and error paths;
8. crypto misuse;
9. supply chain and CI;
10. model output reaching a sink, or untrusted text reaching a tool.
```

**The do-not-report list** goes into every brief:

```text
Do not report:
- Denial of service, resource exhaustion, or a race that stays inside one trust boundary.
- A missing hardening header or rate limit.
- A missing check in client-side code.
- Behaviour the ticket or the project's conventions describe as intended.
- What the ticket lists as out of scope.
- Anything a structure rule or the project's checks already report.
- Style, naming and formatting.
```

The ten prompts and the first four exclusions come from `discovery/discovery-G-security.md`. The last three follow from this plan: the ticket's `## Out of scope` section, the structure rules and `verify`, and the prompt's rule on style. Both lists were in the brief for the test above, in this wording.

LOW has no reviewer. Its safety is `risk_paths`, the size cap, the checks and the sweep.

## 9. PR shape and size

**One ticket, one branch, one PR, one squash commit on main.**

**Size caps:** LOW 300 changed lines, MEDIUM 600, HIGH none.

- **Counting:** `git diff --numstat -M <merge-base>...HEAD`, added plus deleted lines.
  - Renames count only their edits, and binary files count zero but are listed.
  - Files marked `linguist-generated` or `-diff` in `.gitattributes` are excluded, along with a short default list of lockfile names and `[size] exclude`.
- **Enforcement:**
  - `next` shows the count and warns at 80%.
  - At ship, a LOW over 300 becomes MEDIUM and gets a reviewer; a MEDIUM over 600 becomes HIGH and goes to the person. Tiers only go up, and the raise is recorded in the journal.
  - CI recomputes the count.
- **Raise the tier, don't force a split.** Untangling a finished branch is slow and error-prone. Splitting is advice at 80%, where it's cheap.
- A ticket that mixes a refactor with a feature is split at contract time.

**The engine writes the description from the ticket:**

```markdown
## Why
Refresh tokens can be replayed after use. (ticket 14)

## Look at
The revoke check in auth/refresh.py: is the cache key right?

## Evidence
| Step | Status |
| verify | ran, pass |
| check: pytest tests/auth/test_refresh.py | ran, pass |
| review | ran, 3 findings, all answered |

## Risk
MEDIUM. Touches auth/**. No migrations. Changed lockfiles: none. Revert is safe.

Ticket: 14
Tier: MEDIUM
Assisted-by: claude-opus-5-5
```

- "Look at" says what feedback is wanted, the element most linked with acceptance in a study of 80,000 PRs.
- **On HIGH,** `## Look at` separates the core of the change from the wiring, and `## Risk` says whether the merge can be undone: a migration, a public API change or deleted data can't be.
- **The squash subject is `14: rotate refresh tokens on use (#61)`,** and the body is the description, so the trailers land on main.
- **Issue links:** `Closes #123` for GitHub issues. Any `external_id` also goes into the branch name and PR title, which is how most other trackers link a PR when one is added later.
- **Dependent tickets wait for the earlier merge.** GitHub's native stacked PRs aren't used: the gain is only for chains behind a HIGH merge, and the agent takes other tickets meanwhile. If the event log shows claims often refused behind a HIGH merge, revisit it; the async merge endpoint already supports stacks.
- **Learning hooks, from git alone:**
  - the `Ticket:` trailer is the join key;
  - `caused_by` and detected reverts are outcome labels;
  - the journals record what was believed at the time.

## 10. Approvals and waiting

**The framework never waits. A wait is a state on a ticket.**

- `next` returns `owner: human` with what is needed and a link, and the agent takes the next ticket it can act on.
- When the person acts, any later `next` sees it.
- Nothing polls.

**The ticket's PR is where a person acts:**

- **The contract (tiers outside `auto_tiers`):** at `add`, a PR, `14: [contract] ...`, holds only the ticket file. At ship the engine drops `[contract]` from the title. Its check stays red with `not shipped yet` until the ticket ships, so it can't be merged by mistake.
  - To approve it, add the label `rail:go`. In chat, "accept 14" runs `rail accept 14`, which sets the same label.
  - To change it, comment on the PR. The agent amends the contract and asks again.
  - To reject it, close the PR, and the ticket is dropped.
- **HIGH merge:** the agent implements on the same PR, and the person merges it.
- **Inbox:** the engine adds `rail:needs-you` to the PR whenever a ticket waits for a person. Every ticket has a PR from `add` or from its claim (section 7), so one saved search lists everything: `is:open label:rail:needs-you`. It works on GitHub, on a phone, or from any host. GitHub doesn't notify you about PRs made with your own token, so the search is the inbox, and the `notify` hook (section 15) pings the desk. A ticket waits for:
  - contract approval;
  - a HIGH merge;
  - the retry cap after `consult`;
  - a blocking finding the refuter upheld that the agent can't fix, a used-up review budget, or a review run that timed out twice;
  - an ASSUMED row the agent can't verify. Verifying ASSUMED rows is agent work first, right after the claim;
  - a hold: a person added `rail:needs-you` by hand.
- **One act continues any wait:** `rail:go` on the PR, or `accept NN "note"` in chat.
  - When `next` sees it, it logs the event, removes both labels, and gives the agent a fresh retry budget.
  - The note and any PR comments the person wrote during the wait go into the agent's next brief.
  - The person may decline a blocking finding there; it is recorded as declined by the owner.
  - If the note, an answer or a declined finding holds beyond this ticket, the brief asks the agent to open a ticket that writes it into the project's part of `AGENTS.md`, or into a rule, so nobody has to say it twice.
  - A HIGH merge needs no label: merging is the act.
- **A person can hold any ticket** by adding `rail:needs-you` to its PR. The engine doesn't merge it, and `rail:go` continues it with the PR comments in the brief. The PR is made with the person's own token, so GitHub won't let them request changes on it; the label is the brake.
- **The labels** `rail`, `rail:go` and `rail:needs-you` are created by `rail init` when the project has a GitHub remote, so a person can pick them from the first ticket. `doctor` reports a missing one.
- **Another tool with its own approval step,** added later, runs `rail accept` when its approval resolves.
- **With no remote,** `accept` writes the approval to the journal.
- **Notify:** the `notify` hook (section 15) announces each new wait on the desktop. To reach a phone, the project adds one line to it, for example a `curl` to ntfy; the docs show it.

**Other tickets go on while one waits:**

- Each ticket has its own worktree.
- Claims stop two sessions from taking the same ticket.
- Scope overlap and `after:` keep parallel work apart.
- When a ticket merges, open branches rebase onto it at their ship step, or when `next` sees their PR conflicts, and rerun their checks. Resolving a conflict is agent work. A clean rebase keeps the `patch-id` and the review; a conflict fix that changes product lines needs a new review on MEDIUM and HIGH.
- One session works one ticket at a time. More at once means more sessions, which a person or a host starts.

**Situations** (walked through in ANSWERS H4):

| Situation | How work starts | Where the person acts | What wakes the agent |
|---|---|---|---|
| Claude Code at the desk | "Work through the backlog" | Chat or the PR | The person, in the same session |
| Away from the desk | The same session under `/loop` or `/goal`, in `--permission-mode auto` | The GitHub app, or chat through Remote Control | `/loop` reruns `next` on an interval. If the session ended: a desktop or cloud scheduled task, or `github-runner` |
| GitHub Issues | Label `rail`; `rail intake github` pulls labelled issues | The PR | Local session, or `github-runner` |
| A team | Any of the above | GitHub's own rules: required reviewers, CODEOWNERS | Same as above |

**GitHub Issues need no extra code:** `intake` reads them, and `Closes #N` closes them on merge.

**Other trackers and hosts aren't designed now.** The surface in section 19 keeps them possible later; ANSWERS H4 sketches how Linear, Jira and Paperclip could fit.

**Away from the desk** needs no framework code either. A docs page shows what Claude Code ships (checked 2026-11-11):
- **The loop prompt:** `rail intake github`; then `rail next --ticket NN` for each ticket listed as resumable, which finishes what an ended session left; then `rail next` until it returns `rest` or only waits on a person. A project that writes it into `.claude/loop.md` gets it from a bare `/loop`. The resume step is for setups where one runner works at a time: with several live sessions, a resumable ticket may be another session's current work.
- **`/loop`** reruns it in one session: every 5 minutes with `/loop 5m`, or at an interval Claude picks between 1 minute and 1 hour. The machine must stay on, and a loop expires after 7 days.
- **A desktop scheduled task** survives restarts and starts a fresh session in the same clone each run.
- **A cloud scheduled task** runs with the machine off, at most hourly, or on a GitHub event such as an issue labelled `rail`. Each run is a fresh clone. Section 5 keeps two runs from taking the same ticket, and `advance` pushes every commit, so a run resumes from the branch what the last one left.
- **`/goal`** works a labelled backlog until it is empty.
- **Remote Control** lets the person answer from another device. `ask` rules still prompt in auto mode, so `sudo` or `git reset --hard` pauses the loop until someone answers.

**What others do (checked 2026-11-09):**

- Merge approval is always a PR review.
- Plan approval, where it exists, sits next to the ticket or task, in the tool where the work started.
- Waiting is a parked state that an event wakes.
- No tool moves one agent on to other work while a task waits; they run more sessions.
- Using a label as a plan approval is this framework's own choice.

## 11. CI

One installed workflow, `.github/workflows/rail.yml`, with actions pinned by SHA and minimal permissions.

| Job | Trigger | Runs |
|---|---|---|
| `rail` | `pull_request`, default types; checks out the PR head with full history (`ref: head.sha`, `fetch-depth: 0`) | `rail ci`, the same checks as ship: ticket lint (including open ASSUMED rows and the migration fields), scope, tier against `risk_paths` and size, structure rules on added lines, `verify`, ticket `Check:` lines, `doc-lint`. It also checks that the journal has a `shipped` event for this patch, failing with `not shipped yet` before ship, and that a review bound to this patch exists, with every finding answered, whenever the computed tier needs one. One receipt table per step: `ran`, `not_run` or `unavailable` |

- **A PR with no ticket** gets `verify` and the rules: the `rail init` PR, Dependabot, or a person's own PR. The receipt prints the tier its paths would have, so a person merging it knows what it touches.
- **Before ship** the check is red with `not shipped yet`, contract PRs included. `rail ci` looks for the `shipped` event first and stops there, so a push before ship costs seconds. The engine reads CI only once the ticket has shipped the head's patch. Ticket lint also runs locally at `add`, where an open ASSUMED row passes; such a row fails only at ship and in CI.
- **A `verify` or `Check:` line that can't run fails CI.** Whether a missing scanner counts as an error is up to `verify` itself.

- **The repo's own engine runs in CI.** No secrets are needed, because CI runs no model.
- **One-time setup, in the setup docs:**
  - Make `rail` a required check on main.
  - Allow squash merging only, with "Pull request title and description" as the default message, so a person's merge puts the same `Ticket:` trailer on main as the engine's.
  - Turn on "Automatically delete head branches", so merged ticket branches go even when only cloud sessions run.
  - Leave "Require branches to be up to date before merging" off by default; with it on, each merge puts every other open PR behind. A project that wants every merge tested on the latest base turns it on (below).
  - Turn on Dependabot or Renovate for dependency updates.
  - `doctor` checks the first two settings.
- CI never runs the agent, edits tickets or merges.
- **Testing every merge on the latest base** is optional. There are two ways:
  - **Require up-to-date branches.** In the repo's branch protection rule or ruleset, turn on "Require branches to be up to date before merging". A PR that is behind base must then be rebased before it merges, and the rebase push runs the ordinary `pull_request` workflow, so `rail.yml` needs no `merge_group` trigger. It works in any repo. When `next` sees a shipped PR is behind (`mergeable_state: behind`), the engine rebases and pushes it with no agent work, and the ticket is `in-ci` again; a clean rebase keeps the `patch-id` and the review. The cost is one more CI run for a ticket each time another merges ahead of it.
  - **A merge queue.** GitHub offers queues only to organisations, and they suit branches with many merges a day, so a queue fails the 80% test, and the framework doesn't test one. Its required checks run on `merge_group` events, on a branch the queue makes, so the project adds that trigger to `rail.yml` and checks that `rail ci` finds the ticket there. The queue's squash takes the repo's default message, the PR title and description, so the trailers still land on main.
- **`forge`** talks to GitHub only through `gh api` REST calls: open and close PRs, labels, comments, check runs and the merge. `gh pr` and `gh issue` use GraphQL, which Claude Code cloud sessions block, so the engine doesn't use them, and the same code runs locally and in the cloud. Where the cloud proxy refuses a branch deletion, the branch stays listed as a leftover (section 7).
- **Other CI systems and forges** aren't designed now. `rail ci` uses only git and Python, and all forge calls go through the one `forge` module, so adding another later means a job template and a second `forge` adapter.

## 12. Keeping the code in shape

| When | What holds the shape |
|---|---|
| Before code | HIGH contracts accepted by a person; `risk_paths` set the tier; `## Areas` says where things go |
| While coding | Scope paths, structure rules on added lines, size caps |
| At ship | `verify`, checks, `doc-lint`, review on MEDIUM and HIGH, security seat on HIGH |
| After merge | The project's dev smoke check, the sweep, Dependabot or Renovate, the security audit pack on its triggers |
| Over time | Findings become checks; repeated sweep findings become rules |

**Structure rules** stop a bad shape from entering the code:

```toml
[[rules]]
id = "web-no-db"
files = "apps/web/**"
forbid = ["@acme/db"]
fix = "Call the API client in apps/web/lib/api."
why = "ticket 41"

[[rules]]
id = "migrations-home"
files = "**/*.sql"
only_in = "db/migrations/**"
fix = "Create migrations with make migration."
```

- `files` is the glob a rule applies to. `forbid` checks added lines in those files; `only_in` requires each added file that matches to sit under the given glob. Old code never fails, and a new rule works from day one.
- `fix` is printed to the agent.
- `allow` lists paths a rule skips.
- A rule is a text match, which is mistake prevention. Real dependency analysis goes in `verify`, with any checker the project likes.
- A finding a rule already covers is not a review finding.
- **The seed ships one default rule set:** no new suppressions or skipped tests.

**The sweep** reviews what shipped without review.

- **When:** after `sweep.after` (20) LOW tickets and ticketless commits since the last sweep. Time alone is not a trigger: with no new unreviewed work there is nothing to sweep. `next` offers it as an `agent_task` when no ticket work is waiting, so it runs wherever agents run. A person can run `rail sweep` at any time.
- **A sweep is itself a ticket.** It is LOW, and it changes only its journal summary, so it merges on its own. Its squash commit carries a `Sweep:` trailer, which marks where the next sweep starts. Any clone and CI can see that marker.
- **Scope:** the combined diff since the last `Sweep:` commit on base, limited to `Tier: LOW` commits and commits with no ticket.
- **Free part:** `doc-lint`, structure rules counted over the whole tree, and directories missing from `## Areas`.
- **Review part:** one pass of the normal reviewer with a sweep brief. It looks for:
  - duplication across tickets;
  - logic in the wrong area;
  - weak checks;
  - security;
  - stale docs.
  - It also reads every `parked` finding event and the `check` fields of fixed findings.
- **Output:** tickets, never edits, plus a one-page summary in the journal.
  - It removes duplicate parked findings and turns real ones into tickets.
  - A finding of its own that it keeps seeing, with no check yet, becomes a ticket for one. The `check` fields of fixed review findings are grouped by kind, with one ticket each (section 8).
- **It never blocks a merge.**

**Security:**

| When | Runs |
|---|---|
| Every PR | Secret scan on the range, and a dependency scan when a lockfile changed, both inside `verify` |
| MEDIUM | The review brief's security section: ten one-line prompts and the do-not-report list (section 8), with the `review/v1` finding fields |
| HIGH | A separate security seat, with a refuter for each blocking finding |
| Continuously | Dependabot or Renovate, plus GitHub push protection for secrets; both are one-time settings |
| On demand | The `security-audit` pack: first release, new auth or tenancy, monthly at most |

- `THREAT_MODEL.md` is optional, about 30 lines, read by the reviewers and listed in `risk_paths`.
- No scanner is vendored or named in the docs. The init task proposes a secret scan and a dependency scan for the stack in `verify`.

## 13. Knowledge

**Repo map, `ARCHITECTURE.md`.** The init task drafts it and the person confirms it; `doc-lint` skips it until it exists. The agent updates it on the ticket, and it is capped at about 150 lines.

```markdown
## Areas
| Area | Paths | Holds |
|---|---|---|
| api | services/api/** | public HTTP handlers, rate limits |
```

- **No areas ship with the framework.** The init task proposes rows from this repo's own directories, and the person confirms them.
- **`Paths`** are globs.
- **`Holds`** uses a bug reporter's words.
- **There is no `Check` column.** Test commands live in one place, `verify`, so `ARCHITECTURE.md` stays documentation.
- **`context NN`** returns the rows that match the ticket's scope, plus a directory digest of about 40 lines, rebuilt each time from `git ls-files` and never stored.
- **`doc-lint` rules:**
  - every glob matches a tracked file;
  - every directory at `map.depth` is in an area or in `map.ignore`;
  - the file stays under its cap, and paths and headings in docs resolve;
  - a diff that adds or removes a directory at `map.depth` updates this file.
- **Search stays the default way to find code.** The framework owns no index.

**ADRs.** Write one only when a decision is hard to reverse, surprising, and a real trade-off. The seed holds none. A glossary is the project's own choice; it isn't core.

**Lessons.**

- **The framework's lessons are checks.** A mistake that could happen again ends as a test, a rule, a gate or a lint, so nobody has to remember it. The paths there:
  - review findings with a `check` field (section 8);
  - escaped defects: a red main, a failed dev deploy reported as an `rail` issue, or a revert. Each opens a fix ticket with `caused_by` set, and its brief asks for the check that would have caught the defect;
  - the sweep's repeated findings.
- **Knowledge that can't be a check** goes into `ARCHITECTURE.md` or an ADR.
- **No lesson files exist.**
- **The person's lessons** are what someone needs to understand to prompt well tomorrow. They belong to the owner's learning pack, which isn't built now. The core keeps the raw material in git, joined by ticket id: tickets, PR descriptions, findings and their outcomes, `caused_by` links, reverts and sweep summaries.

**Correction ladder.** Any correction goes to the strongest layer that fits: the code or architecture, then a check or rule, then a skill, then a doc.

**Framework docs.** They ship inside the engine and are read with `rail docs [topic]`. Config and CLI reference pages are generated from the engine's schema.

**Not built:**

- generated summaries in always-loaded files
- an index or embeddings
- `llms.txt`
- wikis
- committed generated diagrams

## 14. Install

```bash
git clone <framework> ~/rail && ~/rail/install
```

```bash
cd /path/to/project && rail init
```

**`install` only puts `rail` on `PATH`:** a link in `~/.local/bin` to the framework's launcher, and the line to add when that folder isn't on `PATH`. There is no package and no package manager.

**`rail` runs the project's own engine:**

- Inside a project, the launcher hands over to `.rail/bin/rail`, so the project's changes to its engine take effect. Outside a project it offers only `init`.
- Cloud sessions start from a fresh clone with no `~/rail`. The SessionStart hook adds `.rail/bin` to `PATH` through `CLAUDE_ENV_FILE`, so `rail` works in every session, local or cloud.
- CI runs `.rail/bin/rail ci`.

**`rail init` checks Python 3.11+ and then:**

- copies `engine/` and `seed/`, and writes `.rail/bin/rail` and `.rail/SOURCE`;
- appends its `## Rail` section to `AGENTS.md`, and adds `@AGENTS.md` to `CLAUDE.md` if the project has one;
- merges into `.claude/`:
  - its permission rules, hook entries and sandbox settings;
  - the Bash timeout values;
- adds the workflow file and `.gitignore` lines;
- creates the labels `rail`, `rail:go` and `rail:needs-you` when the project has a GitHub remote.

It never overwrites a file of the project's.

**The first `rail next` returns the init task to Claude.** The agent proposes the following, and the person confirms:

- `setup` and `verify`
- `## Areas`
- `risk_paths`
- the default rules
- `.worktreeinclude` entries for local files a worktree needs, such as `.env`

Detecting the stack is judgment, which the agent does well. A script would need a list per language.

**`doctor`** checks and prints what's missing:
- Python, git, and `gh` auth when there is a remote;
- the `claude` CLI and the hook wiring;
- a `CLAUDE.local.md`, or a `CLAUDE.md` in a parent folder, that would stop `AGENTS.md` loading;
- that the config is valid;
- that `rail` is a required check, and that merging is squash-only with the PR title and description as the default message;
- that the three labels exist.

**Dropped:**

- dry run
- the non-interactive flag
- stack detection
- `upgrade`, `uninstall`, the manifest and managed-block markers

## 15. Guards

Guards prevent mistakes; they are not a boundary.

**Claude Code hooks:**

- **Permission rules first.** The guard table is written as `permissions.deny` and `ask` rules in `.claude/settings.json` wherever a rule fits. Deny rules hold in every permission mode. Bash rules match the start of a command, so they fit paths and whole commands, such as `Read(./.env)` and `Bash(sudo *)`.
- **`guard`** (PreToolUse) is a small hook for what depends on a flag or a pipe anywhere in the command: force push (`-f`, `--force`, `+ref`), push to `base_branch`, `--no-verify`, merges outside the engine, `git reset --hard`, `git clean -f`, `rm -r` outside the worktree and `curl | sh`. Together, rules and hook cover this table:
  - **Deny:**
    - force push or direct push to `base_branch`;
    - a merge outside the engine;
    - `--no-verify`;
    - reading or writing secret files (`.env.example` is fine);
    - editing the journal (`Edit` and `Write` on `.rail/journal/**`), which only the engine writes. A review file written by hand would be today's bug 1 (section 20);
    - `curl | sh`;
    - disk-wiping commands.
  - **Ask the person:**
    - `sudo`;
    - `git reset --hard`;
    - `git clean -f`;
    - `rm -r` outside the worktree.
- **`session-start`** (SessionStart): the snapshot from section 6, and `.rail/bin` on `PATH` through `CLAUDE_ENV_FILE` (section 14).
- **`notify`** (Notification, matcher `idle_prompt`) fires when Claude finished responding about a minute ago and the person hasn't typed since.
  - It asks the engine which tickets wait for a person and announces the ones not yet announced, for example "14: approve the contract · 17: merge", with the first PR link.
  - It returns the message as a `terminalSequence`, which Claude Code turns into a desktop notification in terminals that support one: OSC 9 in iTerm2 and WezTerm, OSC 777 in Ghostty and Warp, OSC 99 in Kitty. It picks the sequence from `TERM_PROGRAM` and falls back to a bell.
  - It stays silent when no ticket waits, so an ordinary pause in chat doesn't ping.
  - It remembers announced waits in the git common dir, so each wait pings once.
  - Outside an interactive terminal, such as under `-p`, Claude Code ignores the sequence; the saved search still lists every wait.
- **The hook scripts stay tool-neutral,** so another tool's wiring can be added later. Only Claude Code is wired now.

**No git hooks are installed.** They would collide with a project's own hook manager (husky, lefthook, pre-commit), and CI repeats the checks. The squash subject carries `NN:`, so intermediate commit messages don't matter. A project's own hooks keep working, and the guard denies `--no-verify`.

**The sandbox** is turned on in `.claude/settings.json` with `"sandbox": {"enabled": true}`. That is all the current framework sets.

## 16. Environments

**Environments belong to the project.** The framework touches each at one named point.

| Environment | What the framework does |
|---|---|
| Local | `setup` in each ticket's worktree, with `RAIL_TICKET` set so parallel tickets can name databases and ports. `verify` and the checks at ship |
| Dev | Nothing at runtime. A ticket ends at merge, and the project's CD deploys main to dev. The docs show one step to add to that CD: after deploy, run the smoke check, and on failure open an issue labelled `rail` whose body starts with `Commit: <sha>`. `intake` turns it into a fix ticket, with `caused_by` set from the commit's `Ticket:` trailer |
| Prod | Nothing. Release is a person's act, through the project's CD gate (an environment reviewer, a release tag, or a manual job) |

- The machine the agent runs on holds local and dev secrets only. That is one line in the setup docs.
- Risky paths are HIGH, so a person sees them before they reach dev.
- The migration brief covers the basics (section 5); deeper migration craft comes from the person's own skills.

**People keep four acts:**

- merging HIGH;
- deleting data;
- handling credentials;
- releasing to prod.

## 17. Skills

**The framework ships no skills.** Each job today's skills do moves here:

| Today's skill | Becomes |
|---|---|
| route, status | `next` and `status` |
| handoff | The SessionStart snapshot |
| implement, PR, task, init | Procedures printed by `next`, `add` and the init task |
| critic, and the evaluator agent | The reviewer prompt, `.rail/engine/reviewer.md`, and the briefs |
| security | The review brief's security section and the HIGH security seat |
| archive | Removed: no lesson files |
| postmortem | The `caused_by` fix-ticket brief: reproduce, fix, add the check that would have caught it |
| audit | The sweep, plus the `security-audit` pack |
| grill, interview, idea, debug, API, migrate | Removed: craft comes from the person's own skills (below) |
| The judgment and done-definition references, and "How to work" in `AGENTS.md` | Folded into the review brief and the procedures `next` prints |
| Templates (ticket, report, lessons, handoff, PR, ADR) | The ticket template stays in the seed. The PR body is generated. The ADR format is in `rail docs adr`. The rest are removed |
| The debt lint and its markers | Removed. A project that wants them adds a rule |

**Craft skills** come from the person's own libraries (pstack, gstack, superpowers and others), installed the way their authors ship them. The framework ships none, so none competes with the person's own. `next` says what to do; a skill says how. To insist on one, a project adds a line to its own part of `AGENTS.md`. Skills in `~/.claude` don't reach cloud sessions, which start from a fresh clone; a project that wants one there commits it or enables its plugin in `.claude/settings.json`.

## 18. Packs

**A pack is a folder:** `.rail/packs/NAME/`, with a `README.md` naming its reader and a `bin/` of commands.
- `rail NAME ...` runs `bin/NAME`.
- Its settings live in a `[NAME]` section of `config.toml`.
- A manifest with event subscriptions waits until a second pack needs events.

**Rules:**

- A pack names its reader.
- It can only add hints; it never changes ticket state.
- The seed holds no pack data, apart from `consult`, which is installed by default.
- Packs may be written in any language.

**The docs describe packs in general.** `rail docs packs` covers what a pack is, the rules above, when one is worth making (it fails the 80% test for core but has a reader), and how to add one. It names no tools. The table below is this plan's backlog, not a catalogue.

| Pack | What it does | When |
|---|---|---|
| `consult` | A different model advises when the agent is stuck: at the retry cap or on request. The brief is the ticket, the diff and raw check output plus one question; the agent's own story is left out. It returns `proceed`, `change` or `stop` in `NN-advice.md`. At most three per ticket. Read-only, never a gate, never counted as review. Its command is `[consult] command` (section 4), and a same-model consult is labelled | Phase 3 |
| `github-runner` | A docs page, not code: run claude-code-action with its own app token and `label_trigger` on issue labels, `rail:go` and PR comments, or use Claude Code scheduled tasks. Events made with `GITHUB_TOKEN` start no workflows, so that token can't drive it | Phase 5 |
| `security-audit` | Wraps a pinned `cloudflare/security-audit-skill`; output becomes tickets | As needed |
| `drive` | A project-local way to drive the software, plus `docs/features/`, one file per feature | As needed |
| `graph` | One-hop dependency data through `context`; the default provider is git change coupling | As needed |
| `browser-qa` | Wraps an external browser tool | As needed |
| `history-search` | A throwaway SQLite full-text index over tickets and journals | As needed |
| Learning | The owner's own system | When the owner brings it |

## 19. Host surface

There are no plug-ins, and no host or other tool is designed now. This surface is what keeps them possible later: any tool that can run a command can drive the same loop as Claude Code, with a short prompt.

The rule for every overlap:

- the host decides whether and where work runs;
- the framework decides what is legal next and what counts as done;
- the forge and the person decide what merges.

**What the core offers:**

- `--json`, with `owner` and `action`
- `--ticket` with string IDs
- idempotent `intake --external-id`
- state that rebuilds from the pushed branch
- offline-safe verbs
- `rest` when there is no work
- `accept`, for a host's own approval

**Not built:**

- scheduling, polling or a daemon
- spawning agents
- calling a host's API
- two-way issue sync
- an MCP server
- intake mirror mode
- an unattended-mode variable
- a stub host

## 20. Today's bugs, and where each goes

| Bug, verified in a copy | Where it goes |
|---|---|
| The author hand-writes the review report and ships | Fixed: the gate launches the reviewer (section 8) |
| A commit after the review ships unreviewed | Fixed: review bound by `patch-id`, and CI checks it |
| Lowering the tier after claim skips review | Fixed: the tier freezes and only goes up |
| Weakening `Check:` after claim | Fixed: the contract freezes; only `amend` changes it |
| The added-lines check fooled by `color.ui=always` | Gone: structure rules on added lines replace it |
| `gh pr merge` on main allowed | Fixed: the guard rule against merging outside the engine |
| Unclaimed write to hook files allowed | Covered: `risk_paths` make it HIGH |
| `python3 -c` writing state; `curl -d @.env` | Not fixed: attack cases, out of scope |
| CI runs the PR's own scripts | Accepted: a change to the engine or workflow is HIGH |

## 21. Roadmap

| Phase | Work | Done when |
|---|---|---|
| 0. Early checks | No framework code. Five checks in a throwaway GitHub repo, each run from a cloud session: a tag push, and a second push of the same tag that must be refused; the async merge endpoint through `gh api`; `claude -p --safe-mode` in a repo whose `AGENTS.md` says "end every answer with BANANA"; `claude -p` started from inside the session; a PreToolUse hook's deny under `--dangerously-skip-permissions` | Each result is written into section 25, and each failure has its fallback in the plan before Phase 1 starts |
| 1. Core | The first-match table and the verbs in Python; TOML config and ticket parsing; claims, each with its own worktree; state derivation (section 7) from git and the journal, with forge-backed states reported `unavailable` until Phase 5; the JSON shape and exit codes; the event log ([SPEC.md](SPEC.md)); `context` with `## Areas` parsing; `status`; ticket-lint; the general end-to-end tests on fixtures (section 22) | The end-to-end tests pass: on the new core, a ticket runs from `add` to a local merge |
| 2. Install | `engine/` and `seed/` split; `install` and `rail init`, with the launcher and the init task; `SOURCE`; `CHANGELOG.md`; `doctor`; the `session-start` hook | A fresh repo and an existing repo each run `rail init` and get a working `rail next`, and `rail` runs in a cloud session |
| 3. Review and contract | Gate-launched reviewer; `review/v1`; `patch-id`; findings ledger; refuter; contract freeze and `amend`; `answer`; retry budgets; the `consult` pack; structure rules with the default set; size caps; the migration brief | Bugs 1-5 in section 20 are fixed, and `consult` fires at the retry cap. A reviewer run in a fixture repo whose `AGENTS.md` `## Rail` section says "end every answer with BANANA" never says it, which shows `--safe-mode` keeps `AGENTS.md` from loading and the brief leaves that section out. A reviewer run started by `advance` inside a cloud session returns a valid review |
| 4. Guards | Permission rules and the small guard hook | The guard rules in section 15 hold under Claude Code |
| 5. Autonomy | `forge`; PR lifecycle to merge, including the engine's merge and the rebase of a PR that is behind; the contract PR and labels; per-ticket waits; the red-base check; the `notify` hook; `intake`; the sweep, which must land with LOW merging; the docs pages for away-from-desk and `github-runner` | A backlog with LOW, MEDIUM and HIGH tickets runs from one session, with HIGH waiting on the PR while the others merge. Two cloud runs started at once never take the same ID or claim, and a later run resumes a ticket an earlier one left half done |
| 6. Standard features | `ARCHITECTURE.md` drafting and `doc-lint`; findings becoming checks; `rail docs` | **Ready to use:** a fresh repo and an existing repo each reach a merged MEDIUM ticket by following the docs alone |
| 7. Packs | From section 18, as needed | Each has a named reader |

- **The framework is written from scratch,** in a cloud environment. The current framework is a reference to read, not a base to change.
- Phases 1 and 2 can overlap.
- **Checkpoint after Phase 3:** run ten real tickets. If the rail stopped nothing a person would have missed, change the plan before building more.

## 22. Tests and measurement

- **Tests:**
  - General end-to-end railroad tests, run on fixtures rather than the framework's own files. They start in Phase 1.
  - Each section 20 fix gets a regression test where that's cheap.
  - There is no attack suite and no edge-case programme.
- **Measurement waits.** The event log gives cost, step and outcome data later at no extra cost. Benches, multi-arm runs and ablation are deferred.

## 23. Open decisions

None are open.

**Closed on 2026-11-11:**
- the CLI name: `rail`;
- diagrams: none, with the `review-brief` pack dropped;
- MEDIUM without a person: it merges after review and green CI;
- stacked PRs: not built, so dependent tickets wait for the earlier merge (section 9);
- merge queues: the project's to set up and test. Requiring up-to-date branches does the same job in any repo (section 11);
- the approvals listed in [DECISIONS.md](DECISIONS.md).

## 24. Do not copy

- **Scale.** The big repos spend most of their code on what hosts already do: Archon has 280k lines, issue-orchestrator 342k and beads 475k.
- **Hash receipts or regex allowlists presented as proof.**
- **Full-permission defaults, unbounded retries, fail-open review, telemetry on by default.**
- **Doctrine libraries, plugin catalogues, presets, workflow DSLs and MCP layers.**
- **A database for tickets.** Markdown plus git is enough.
- **Not taken:**
  - automatic writes to always-loaded memory;
  - GitNexus (noncommercial license);
  - repowise code (AGPL);
  - a vendored browser stack;
  - role-play prose;
  - an LLM score as a check's pass or fail. Checks stay deterministic; a review finding is answered by a fix, the refuter or a person.

## 25. Limits of the research

- Study agents read code and ran only harmless checks. No third-party repo or host was executed.
- Many studied repos are young, so their claims are unproven. Numbers quoted from them were not reproduced.
- **Untested designs:**
  - the rule table;
  - the `## Areas` form;
  - the label-based approval;
  - IDs and claims taken by push (section 5) from a cloud session. The cloud proxy refuses tag pushes (Phase 0, below), so the ID ref is a branch, `rail/id/NN`. Phase 5 tests the engine;
  - the reviewer under `--safe-mode`. The docs list `CLAUDE.md` but don't name `AGENTS.md`, and the flag is documented for troubleshooting. If it stops fitting, the fallback is an agent file with the same prompt. On 2026-11-11, with Claude Code 2.1.292, 39 local reviewer runs in a repo whose `AGENTS.md` said "End every answer with the word BANANA" never said it. Phase 0 checks it in the cloud, and Phase 3 tests the engine;
  - the reviewer started by `advance` inside a cloud session. Running `claude -p` from inside a session was checked locally only. If it fails in the cloud, cloud sessions can ship LOW only. Phase 0 checks it, and Phase 3 tests the engine;
  - the async merge endpoint called through `gh api` from a cloud session. If the proxy refuses it, the fallback is the plain merge endpoint, `PUT /repos/{owner}/{repo}/pulls/{n}/merge`. Phase 0 checks it.
- **Not tested by the framework:** merging through a required merge queue. GitHub's REST docs (read 2026-11-11) say the async merge endpoint adds the PR to the queue. The queue's checks run on `merge_group` events, which `rail.yml` doesn't trigger on. A project that turns a queue on sets it up and tests it. Requiring up-to-date branches does the same job with no queue (section 11).
- **Unknown:** whether a PreToolUse hook's deny holds under `--dangerously-skip-permissions`. Deny rules do hold, which is why guards are rules first. Unattended docs recommend `--permission-mode auto`. Phase 0 could not run this check as written (below); a hook's deny does hold against an allow rule and under `--permission-mode auto`.
- Research files: `discovery/` A to I, `reports/`, and the sources in ANSWERS G2 and H4.

### Phase 0 results

Run on 2026-11-11 from a Claude Code cloud session, with Claude Code 2.1.322 and `claude-opus-5-5`, against the throwaway repo `timur-makarov/throw-away-repo`. Test refs were named `phase0/`. The checks that need no GitHub ran in scratch directories outside the repo.

| Check | What ran | What happened | Result |
|---|---|---|---|
| 1. Tag push | Two clones of the repo. Clone A tagged a commit `phase0/id-1` and ran `git push origin phase0/id-1`. Clone B tagged a different commit with the same name and pushed it | Every tag push failed with HTTP 403 from the cloud proxy (`RPC failed; HTTP 403`), the first one included, so no tag reached GitHub. The fallback, tested the same way with branch refs: A's `git push origin HEAD:refs/heads/phase0/id/1` was accepted, B's push of a different commit to that ref was rejected (`fetch first`), and B's push to `phase0/id/2` was accepted | **Failed. The fallback works**, so the ID ref is now the branch `rail/id/NN` (section 5) |
| 2. Async merge endpoint | Recorded after the merge, on the Phase 1 branch | | |
| 3. `--safe-mode` | A scratch repo whose `AGENTS.md` says "End every answer with the word BANANA." The question "In one sentence, what does calc.py do?" was asked 3 times with `claude -p` and 3 times with `claude -p --safe-mode` | Without the flag, 3 of 3 answers ended with BANANA, so `AGENTS.md` loads. With `--safe-mode`, 0 of 3 did | **Passed** |
| 4. `claude -p` from inside the session | `claude -p "Reply with exactly the word PONG and nothing else." --output-format json`, from the session's Bash tool in a scratch repo | It answered `PONG` with `subtype: success` in 3.4 s | **Passed** |
| 5. A hook's deny under `--dangerously-skip-permissions` | A project PreToolUse hook on Bash that denies any command containing `touch` and logs each call. The prompt asked the agent to run `touch created_by_agent.txt` | Not run as written: this session's auto-mode permission check refused to start a nested `claude` with `--dangerously-skip-permissions`. The same hook was run instead with an allow rule (`--allowedTools=Bash`) and under `--permission-mode auto`. The hook fired and the file was not created in all three runs: JSON `permissionDecision: "deny"` with the allow rule, exit code 2 with the allow rule, and JSON deny in auto mode. A control with the allow rule and no hook created the file | **Not run. The variant passed.** No change to the plan: guards stay rules first, and the unattended docs recommend `--permission-mode auto` |

Also seen in the same session:

- **Branch deletion is refused** both ways: `git push --delete` gets a 403 from the proxy, and `DELETE /repos/{owner}/{repo}/git/refs/heads/...` returns "Write access to this GitHub API path is not permitted through this proxy". This matches the leftovers rule (section 7). The `phase0/` branches stay for the owner to delete.
- **The proxy allows REST writes only on some paths.** Which ones `forge` needs beyond the merge (labels, comments, check runs, closing PRs) is for Phase 5 to find.
- **GraphQL is refused** with a 403, as section 11 expects, and REST reads work. `gh auth status` reports the token as invalid even though REST calls work, because the proxy adds the credentials. So `doctor` (section 14) should test `gh` auth with a REST call, not with `gh auth status`.
