# consult

A different model advises the agent when it is stuck: at the retry cap, or on request with
`rail consult NN "question"`.

- **Reader:** the agent's next brief. The engine records each answer as a `consulted` event and in
  `.rail/journal/NN-advice.md`.
- **Brief:** the ticket, the diff and the raw output of the failing step, plus one question. The
  agent's own story is left out.
- **Answer:** `proceed`, `change` or `stop`, with a few sentences of advice.
- **Rules:** read-only, never a gate, never counted as review, at most three per ticket.
- **Settings:** `[consult] command` in `.rail/config.toml`, run with the brief on stdin. Point it at
  another vendor's CLI when you have one. A consult by the author's own model (`claude`) is
  labelled same-model.
- **Without it:** delete this folder, and a step at its retry cap goes straight to a person.
