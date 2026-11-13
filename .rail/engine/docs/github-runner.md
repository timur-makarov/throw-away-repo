# Running from GitHub events

Rail starts no agents; a host does. To run the loop from GitHub instead of a session you keep open:

- **Claude Code scheduled tasks:** a cloud scheduled task runs the loop prompt on a schedule, or on a GitHub
  event such as an issue labelled `rail`. Each run is a fresh session on a fresh clone, and a bare
  `rail next` picks up everything earlier runs left. `rail docs cloud` has the prompt and the triggers.
- **claude-code-action:** a workflow that runs Claude Code with the loop prompt, triggered by the labels
  `rail` and `rail:go` and by pull request comments. Give it its own GitHub App token. Events made with the
  workflow's `GITHUB_TOKEN` start no workflows, so pushes and merges made with that token would never run
  the `rail` check.

Either way the engine is the same: the host decides whether and where work runs, Rail decides what is legal
next and what counts as done, and GitHub and the person decide what merges.
