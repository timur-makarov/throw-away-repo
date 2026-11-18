# Guides and skills

Rail says what is legal next and what counts as done. How to do the work is the agent's craft. A guide is a
short page of craft that the engine names in the brief at the moment it applies. It is a hint: nothing
fails when an agent ignores it. The checks stay the enforcement.

## When the engine names a guide

`[guides]` in `.rail/config.toml` maps a situation to a page, as a path from the repository root.
`rail next` and `rail advance` add one line to the brief, such as
`Guide: read .claude/skills/rail-debug/SKILL.md and follow it.`, and the answer's `guide` field names the
situation and the path.

| Situation | When | Default guide |
|---|---|---|
| `start` | The first `IMPLEMENT` brief of a claimed ticket, once per ticket | `rail-build`, which ends with `rail-self-check` |
| `stuck` | A step failed the same way twice in a row (the same `signature`) | `rail-debug` |
| `findings` | A review left findings to answer | `rail-findings` |
| `conflict` | A rebase stopped on a conflict in the ticket's worktree (`REBASING`) | `rail-conflict` |
| `contract` | A ticket came in as a request and needs its contract | `rail-blast-radius` |
| `split` | Ship offered a split: an AUTO change is over `[size] cap` | `rail-slice` |
| `setup` | The init task | `rail-verify` |

- To give no guide in a situation, delete its line. To use your own page, point the line at it.
- The seed config that `rail init` copies has the table above. A config with no `[guides]` table names no
  guide.
- A page that isn't there, in the ticket's worktree or at the root, names nothing; `rail doctor` lists it.
- The engine records the first time it names each guide for a ticket as a `guided` event in the ticket's
  journal. While a rebase is stopped it writes nothing, so `conflict` has no event, and the init task has no
  ticket. `rail stats` counts failed steps and review runs for tickets with and without the `start` guide.
  That is how you tell whether a guide earns its place.

## Skills a person starts

The pages are Claude Code skills in `.claude/skills/`, so a session with no ticket can use them too. Four
are for the time before a ticket exists, with a person present. Each is optional, and stopping after any of
them is a complete outcome.

| Skill | Use it when | It produces |
|---|---|---|
| `rail-clarity` | The person is not sure what to ask for | The real goal, in a few lines |
| `rail-deepen` | The request is clear but shallow | A rewritten request and candidate checks |
| `rail-blast-radius` | The change touches existing code | Scope, tier and expected size |
| `rail-grill` | The request should become a ticket | The ticket, filed (`rail docs grill`) |
| `rail-slice` | The work is more than one ticket | Several tickets with their order |

## Writing or changing a guide

After `rail init` every page is the project's own. These rules keep a page useful:

- **Open with three lines:** what the page assumes, what it produces, and what done means.
- **One word for one thing.** A *ticket* has a *contract*. A *worker* is the agent doing a ticket; the
  *reviewer* is the fresh agent the engine starts; a *person* is a human. Don't swap in synonyms.
- **A strong word names its limit.** Write "never", "always" or "must" only with what it covers and why. A
  rule that a command can enforce belongs in a check, a structure rule or a hook, and then leaves the page.
- **"Ask" says whom.** In an unattended session nobody answers. Say what the agent does instead: record an
  `ASSUMED:` row and go on, or amend the contract.
- **Say what to do.** A page that lists what to avoid brings those things to mind. Describe the method, and
  give the reason once.
- **Name methods, not roles.** "Check it the way a security auditor would" changes the wording of the
  answer. "Trace each input from the request to the query" changes the work.
- **Mark what was seen.** A claim is *confirmed*, with a `file:line` or a command and its output, or
  *inferred*, with the reason. "Not tested: X, because Y" is information; silence looks like a pass.
- **Keep it short.** About a hundred lines. Teach what the model does not already do; cut the rest.
- **Change it on evidence.** Run a few real tickets with the old page and the new one, and keep the change
  only when `rail stats` shows fewer failed steps or review runs.
