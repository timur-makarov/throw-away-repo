# Guides and skills

Rail says what is legal next and what counts as done. How to do the work is the agent's craft. A guide is a
short page of craft whose text the engine puts in the brief at the moment it applies. Whatever Rail wants an
agent to read is in the brief itself: an agent seldom opens a page a brief only names. It is still a hint:
nothing fails when an agent ignores it. The checks stay the enforcement.

## When a brief carries a guide

`[guides]` in `.rail/config.toml` maps a situation to a page, as a path from the repository root. `rail next`
and `rail advance` add the page's text to the end of the brief, and the answer's `guide` field names the
situation and the path. A skill's front matter is left out.

To take only part of a page, name its sections after the path, each as `#Heading`:
`".claude/skills/rail-slice/SKILL.md#2. Three tests for each draft#When the engine offered the split"`. A
section runs from its heading line to the next heading of any level; a `#` inside a fenced block is no
heading. The brief gets the sections in the order named.

| Situation | When | Default page |
|---|---|---|
| `start` | The first `IMPLEMENT` brief of a claimed ticket, once per ticket | `.rail/engine/guides/build.md` |
| `stuck` | A step failed the same way twice in a row (the same `signature`) | the `rail-debug` skill |
| `findings` | A review left findings to answer | `.rail/engine/guides/findings.md` |
| `conflict` | A ship failed at `rebase`, or a rebase is stopped on a conflict in the ticket's worktree (`REBASING`) | `.rail/engine/guides/conflict.md` |
| `contract` | A ticket came in as a request and needs its contract | the `rail-blast-radius` skill |
| `split` | Ship offered a split: an AUTO change is over `[size] cap` | two sections of the `rail-slice` skill |
| `setup` | The init task | the `rail-verify` skill |

- To give no guide in a situation, delete its line. To use your own page, point the line at it.
- The seed config that `rail init` copies has the table above. A config with no `[guides]` table gives no
  guide.
- A page or section that isn't there, in the ticket's worktree or at the root, adds nothing; `rail doctor`
  lists it.
- The engine records the first time a brief carries each guide for a ticket as a `guided` event in the
  ticket's journal. While a rebase is stopped it writes nothing, so `conflict` has no event, and the init task
  has no ticket. `rail stats` says how many merged tickets each guide was given for.

## Pages and skills

A page that only applies at a step the engine knows lives with the engine, in `.rail/engine/guides/`:
`build.md`, `findings.md` and `conflict.md`. They are not skills, because nothing but the brief needs them.

The pages in `.claude/skills/` are Claude Code skills, so a session with no ticket can use them too. Three
are for the time before a ticket exists, with a person present. Each is optional, and stopping after any of
them is a complete outcome. `rail-debug` serves any failure whose cause isn't known yet, and `rail-verify` a
ticket that improves how the project is verified; the engine gives each in the brief only at its own step.

| Skill | Use it when | It produces |
|---|---|---|
| `rail-blast-radius` | The change touches existing code | Scope, tier and expected size |
| `rail-grill` | The request should become a ticket | The ticket, filed (`rail docs grill`) |
| `rail-slice` | The work is more than one ticket | Several tickets with their order |

**Where the skills are written.** `SKILL.md` is a format several agents read, each from a folder of its own.
`[init] skill_dirs` lists the folders `rail init` writes the skills to, `.claude/skills` by default. For a
worker or reviewer command that is another agent's CLI, add that agent's folder and run `rail init` again: it
writes what is missing and leaves the rest. `rail init --skills DIR` (repeat it for several) sets the folders
of a new project, and the `[guides]` lines that name a skill then read it from the first.

A seed skill can carry a docs page instead of naming it: a line `<!-- include engine/docs/grill.md -->` in
the seed is replaced by that page's text when `rail init` installs the skill. To take only some sections, put
each heading after a `#`, as it stands, spaces and all, such as
`<!-- include engine/docs/guides.md#Writing or changing a guide -->`. `rail-grill` carries `grill.md` this way.

## Writing or changing a guide

After `rail init` every skill is the project's own; the pages in `.rail/engine/guides/` come with the
engine. These rules keep a page useful:

- **Open with three lines:** what the page assumes, what it produces, and what done means.
- **One word for one thing.** A *ticket* has a *contract*. A *worker* is the agent doing a ticket; the
  *reviewer* is the fresh agent the engine starts; a *person* is whoever answers for the repository. Don't swap
  in synonyms.
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
  only when the new one does better: fewer failed steps, fewer review runs, the right result more often.
