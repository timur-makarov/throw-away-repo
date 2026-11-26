# Rail in a Claude Code cloud session

A cloud session is Rail's standard place to work: a machine made for the session, with the repository
cloned fresh, that nobody owns. Rail treats it differently from your own computer. `rail doctor` says which
of the two it is on.

| | In a cloud session | On your own machine |
|---|---|---|
| Tools the checks need | Rail installs them: `[commands] provision` runs as root, once per machine | You install them; `rail provision` only shows the command |
| Setting the project up | The agent does it all and opens one pull request; you confirm by merging it | The agent proposes each choice and you confirm it |
| Guard | The rules that protect the rail stay: no force push, no push to the base branch, no merge outside the engine, no journal edits, no `.env` | The same, plus asks before `sudo`, `git reset --hard`, `git clean -f` and `rm -r` outside the worktree, and no download piped into a shell |
| A person's acts | On GitHub: the label `rail:go`, a comment, the merge button | The same, or `rail accept` in the terminal |

## Set up, once

1. **Start a cloud session on the repository** and ask Claude to set Rail up from the framework's
   repository. It runs `rail init`, writes the project's commands, map and `[kinds]`, installs what the
   checks need, and opens one pull request.
2. **Merge that pull request.**
3. **Make three settings on GitHub.** A cloud session can't change a repository's settings, so these are
   yours, and that is also why they are the guard an agent can't get around:
   - Settings > Rules > Rulesets > New ruleset > Import a ruleset: choose `.rail/ruleset.json`. GitHub
     asks for a file from your device, so download it first, from the repository or from the framework
     (`seed/ruleset.json`); it is the same file for every repository. It requires the `rail` check and a pull
     request on the default branch, keeps branches up to date before a merge, allows squash merges only, and
     blocks force pushes and deletion. It also stops a contract pull request being merged by mistake: its
     `rail` check stays red until the work ships.
   - Settings > General > Pull Requests: "Pull request title and description" as the default squash
     message.
   - Settings > General > Pull Requests: turn on "Automatically delete head branches". A cloud session
     can't delete branches, so merged tickets would pile up.
4. **Approve the environment's setup script.** `rail doctor` prints three lines; the agent proposes them for
   the session's cloud environment and you approve once. They run `rail provision` when the environment's
   machine is built: it links `rail` onto `PATH`, writes Rail's hooks into the machine's own Claude Code
   settings, and runs the project's `provision` command. The result is kept as a snapshot, so later sessions
   start with everything in place. Without the script, `rail next` asks the agent to run `rail provision` when
   the project has a `provision` command, since the checks need what it installs. Rail's own hooks reach the
   machine that way only if the session lets the agent change its own settings; an auto mode session may
   refuse that, so the script is the dependable way.

`rail doctor` checks all of it and says what is left.

## Hand work over

- **In a session:** say what you want. The agent writes a ticket and runs `rail add`.
- **From GitHub:** label an issue `rail`. Every `rail next` takes labelled issues in.
- **While you are away:** a scheduled task runs the loop with no session open (below).

## What a session does when it starts

Each cloud session is a new session on a new clone, and `rail next` is all it needs:

- It takes in issues labelled `rail`.
- It moves every shipped ticket, whoever shipped it: it waits for CI, rebases a pull request that fell
  behind, and merges a green one. A claim protects only work in flight.
- It resumes work an ended session left. A ticket another session is implementing or reviewing is left
  alone while it keeps moving; after `[claim] stale_minutes` (30) with no journal event, the next session
  resumes it from the pushed branch. `rail next --ticket NN` takes one over at once.
- Then it takes new work, in ID order.

Work that isn't pushed is lost when a machine goes away. So the work in flight is saved as it goes: hooks
run `rail save` at the end of each turn and at most every ten minutes of work, and `rail advance` commits
and pushes every time. A reclaimed machine, a usage limit or a crash costs minutes, and the next session
starts from the last save.

## Run with no session open

Unattended work runs in the cloud, and only there: a scheduled task starts a runner session, on a schedule
or on a GitHub event. A session on your own machine is for work you drive yourself: free work, grilling a
ticket, `rail next --ticket NN`, `rail adopt`.

Make one scheduled task for the repository, on the environment from step 4, with this prompt:

    You are the Rail runner for this repository. Nobody is here to answer questions.

    Repeat these steps:
    1. Run `rail next --json`.
    2. If `action.kind` is `agent_task`: give the brief to a subagent. Use the subagent already working this
       ticket if there is one and `action.model` has not changed; otherwise start one on `action.model` and
       effort. Give it `action.brief` word for word. Tell it to work in `cwd`, not to run `rail advance`, and
       to reply in one line: done, or what stopped it. When it replies, run `rail advance NN --json`, where
       NN is that ticket's number. If that answer is another `agent_task` for the same ticket, do this step again with it.
    3. If `action.kind` is `script`: run `action.command`.
    4. After any other answer from `rail advance`, go back to step 1.
    5. Stop only when `rail next` itself answers that only a person can act or that there is no work.

    Don't check or change a member's work yourself: `rail advance` does that. End with one message that
    says which tickets wait for a person and what each one needs.

One worker carries a ticket from its assumptions to its last fix, so the repository is read once for each
ticket and not once for each step. A failed attempt that calls for a stronger model goes to a new worker
on that model, with the failure in its brief. The runner decides nothing and keeps a small context, so one
run can move many tickets. A guide's text (`rail docs guides`) is part of the brief, so the worker gets it.
Only `rail next` ends the loop: one ticket that waits for a person does not stop the others.

Give it these triggers. Where a task takes only one GitHub event, make one task for each event, all with
the same prompt:

- **An issue labelled.** New work: the label `rail` starts it. "Issue opened" misses an issue that gets the
  label later.
- **A pull request labelled,** with the filter "Labels contains `rail:go`". Your approval. Without the
  filter the engine's own `rail:needs-you` starts a run too.
- **A pull request closed,** with the filter "Is merged". A merge unblocks the next ticket, and it is what
  puts another open pull request behind its base.
- **A schedule,** hourly or nightly, as a net for anything an event missed.

Don't use "edited" or "synchronized": the engine writes each pull request's title, body and branch, so its
own work would start run after run.

**One runner for a repository.** A scheduled task belongs to one person's Claude account: its runs are that
person's usage, and its commits and pull requests carry that person's GitHub login. When two people each
make these tasks for the same repository, every event starts a run for each of them. Claims keep the two
off the same ticket, but each event costs twice, and nothing decides whose name a ticket's work carries.
Until Rail has a way to share the work out (`proposals/team.md`), one person owns the runner, and the
others hand work over and answer waits on GitHub.

Each run is a fresh session, and the section above is why that is enough. For more work at once, start
more sessions: claims are taken on the remote, so two never take the same ticket. `rail status --json`
lists the tickets whose owner is `agent`.

A scheduled task starts in auto mode. The loop's own commands are allowed by rule, so auto mode doesn't
review them (`rail docs guards`), and in a cloud session the guard asks nothing, so no run stops for an
answer. To run from GitHub Actions instead, see `rail docs github-runner`.

## Run a source on a schedule

A [source](sources.md) turns a signal, such as failed CI runs, into tickets. Make one scheduled task for
each source, on the same environment, with this prompt:

    Run `rail source NAME --json` and do its brief.

The source only files tickets. The runner above picks them up on its own schedule, as any other ticket.

## Where your acts go

- **Your inbox** is one saved search: `is:open label:rail:needs-you`. Every wait gets the label as soon as
  any session sees it. GitHub doesn't notify you about pull requests made with your own token, so the search
  is how you find every wait.
- **Waits are named.** A runner ends its turn by saying which tickets wait for a person, and
  the Claude app notifies you. In a session on your own machine, the `notify` hook pings the desktop once
  for each new wait while Claude sits idle.
- **Answer from any device.** Every act below is on GitHub, so the GitHub app or a browser is enough.
- **Approve or continue:** add the label `rail:go` to the pull request. A comment you leave there reaches
  the agent as your note. Don't merge a contract pull request: it holds only the contract. If you do, Rail
  takes it as your approval and opens a new pull request for the work.
- **Change a contract:** comment on its pull request. **Reject it:** close the pull request.
- **Stop a ticket:** add the label `rail:hold` to its pull request. Nothing moves it until you add `rail:go`.
  `rail:needs-you` is the engine's own label: adding or removing it by hand changes nothing.
- **Revert a merged ticket:** add the label `rail:revert` to its merged pull request. The next run files a
  ticket that takes the change out again, comments with its number, and removes the label; the revert ships,
  is reviewed and merges like any ticket (`rail docs tickets`).
- **Read what merged with no person:** the search `is:pr is:merged label:rail:look` lists the AUTO tickets whose
  "Read these" list was not empty. Take the label off when you have read one (`rail docs github`).
- **Stop everything:** open an issue and give it the label `rail:stop`. While it is open, `rail next`,
  `rail advance` and `rail work` answer `STOPPED` and do nothing, in every session, at their next call: no
  ticket is claimed, shipped, reviewed or merged, and no worker starts. A run already going ends its command
  first, and a merge GitHub had already accepted may still land. To stop only part of the repository, put a
  line `paths: src/billing/**, db/**` in the issue's body: then only the tickets whose `scope_paths` reach
  those paths stop. Close the issue, or take the label off, and the next run goes on; closing starts no run
  by itself, so the schedule or your next message does. A revert ticket goes on under a brake, so a brake can't block its own way out. Issues still come in as tickets under a brake, since
  taking one in changes no code, and what a worker already changed stays saved in its worktree. Only someone
  who may triage the repository can set a label, so a stranger's issue stops nothing. With no remote there
  is no brake.
  The engine sets one brake itself: on the scope of a ticket whose deploy to dev failed, until its revert has
  merged (`rail docs environments`).
- **Merge a PERSON ticket:** the merge button.
- Each pull request ends with `Claude-Session:` and a link to the session that worked the ticket.

## Session shapes

Claude Code loads a repository's hooks and permission rules only in a session that starts with that one
repository. A session with several repositories, and a thread in a project, load neither. So
`rail provision` also writes the hooks into the machine's own settings, which every session loads:

- the guard finds the project a command runs in (`cd repo && git push origin main` is still denied), also
  further down when the command names its folder; the saves and the session's snapshot cover every Rail
  repository directly below the session's folder;
- where the repository's own hooks did load, the machine's step aside, so nothing runs twice;
- `rail` works everywhere, because provision linked it onto `PATH`;
- the link and the hooks call the engine in the project's own checkout, so a ticket's copy of a newer
  engine leaves them alone, and provision sets them up once that engine is merged;
- the allow rules are a repository's and don't load there, so auto mode reviews `rail` commands itself;
- the ruleset on GitHub stays the guard nothing can get around, and `rail ci` repeats every ship check.

`rail doctor` says which hooks ran in the session.

## What the cloud refuses

Branch deletion, tag pushes, GraphQL (so `gh pr` and `gh issue`), and writes to repository settings and
rulesets. Rail needs none of them: it talks to GitHub through `gh api` REST calls, takes ticket IDs from
one counter branch (`rail/ids`), and leaves settings to you.
