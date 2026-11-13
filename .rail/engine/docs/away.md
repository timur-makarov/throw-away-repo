# Away from the desk

Rail never waits: a wait is a state on a ticket, and the agent takes other work meanwhile. To keep work
moving while you are away, use what Claude Code ships.

**The loop prompt:** run `rail next` and do what it says, then `rail advance`, until `rail next` returns
`rest` or only waits on a person. `next` itself takes in issues labelled `rail`, moves shipped tickets, and
resumes work an ended session left. Write the prompt into `.claude/loop.md` to get it from a bare `/loop`.

- **A cloud scheduled task** runs with your machine off, on a schedule or on a GitHub event. It is Rail's
  standard way to work unattended: `rail docs cloud` has the prompt and the triggers.
- **`/loop`** reruns the prompt in one session, on an interval you give or one Claude picks. The machine
  must stay on.
- **A desktop scheduled task** survives restarts and starts a fresh session in the same clone each run.
- **`/goal`** works a backlog until it is empty.
- **Remote Control** lets you answer from another device.

**Your inbox** is one saved search on GitHub: `is:open label:rail:needs-you`. GitHub doesn't notify you
about pull requests made with your own token, so the search lists every wait. A cloud session ends its turn
by naming the waits, and the Claude app notifies you. On your own machine the `notify` hook pings the
desktop once for each new wait while Claude is idle.

To run from GitHub events instead, see `rail docs github-runner`.

Run unattended sessions with `--permission-mode auto`; a cloud session picks Auto from the mode menu, and a
scheduled task starts in it. The loop's own commands are allowed by rule, so auto mode doesn't review them
(`rail docs guards`). On your own machine the guard still asks before `sudo` or `git reset --hard`, which
pauses a loop until someone answers; in a cloud session it doesn't ask.
