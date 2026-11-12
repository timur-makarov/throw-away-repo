# Away from the desk

Rail never waits: a wait is a state on a ticket, and the agent takes other work meanwhile. To keep work
moving while you are away, use what Claude Code ships.

**The loop prompt:** run `rail intake github` to take in issues labelled `rail`; then, for each ticket
`rail next` lists as resumable, run `rail next --ticket NN`, which
finishes what an ended session left; then run `rail next` until it returns `rest` or only waits on a
person. Write it into `.claude/loop.md` to get it from a bare `/loop`. The resume step is for setups where
one runner works at a time.

- **`/loop`** reruns the prompt in one session, on an interval you give or one Claude picks. The machine
  must stay on.
- **A desktop scheduled task** survives restarts and starts a fresh session in the same clone each run.
- **A cloud scheduled task** runs with your machine off. Each run is a fresh clone; IDs and claims are
  taken on the remote, so two runs never take the same ticket, and a run resumes from the pushed branch.
- **`/goal`** works a backlog until it is empty.
- **Remote Control** lets you answer from another device.

**Your inbox** is one saved search on GitHub: `is:open label:rail:needs-you`. GitHub doesn't notify you
about pull requests made with your own token, so the search lists every wait, and the `notify` hook pings
your desktop once for each new one while Claude is idle. To reach a phone, add a line to that hook, such as
a `curl` to ntfy.

To run from GitHub events instead, see `rail docs github-runner`.

Run unattended sessions with `--permission-mode auto`. `ask` rules still prompt there, so `sudo` or
`git reset --hard` pauses the loop until someone answers.
