# Grilling a request into a ticket

For an agent that turns a person's request into a Rail ticket, in whatever chat the person uses: a Claude Code
session, Slack, Telegram, Dots, the Claude app. The person is there and can answer, or the request came in
writing and nobody can. The goal is a ticket whose Done Contract says what the person means, so the agent
that works it later never has to guess.

You only ask. You don't change code, and you don't start the work.

## 1. Read before you ask

Clone the repository, or use the checkout you are in. Read:

- `AGENTS.md`, and `ARCHITECTURE.md` with its `## Areas` table;
- `.rail/tickets/TEMPLATE.md`, the shape of a ticket;
- `.rail/config.toml`: `[kinds]`, `person_paths` and `migration_paths`, which decide the tier, and `[size] cap`,
  over which the first ship offers a split;
- the code the request touches, and its tests.

Never ask what the code answers: where a thing lives, what it does today, which test covers it.

## 2. Draft first

Write the whole ticket yourself before you ask anything: Why, Done Contract, `scope_paths`, tier, Out of
scope, Assumptions. A good check fails today and passes once the work is done: a test that names the new
behaviour, not "the tests pass".

Read the request's small words before you draft. "Just", "only" and "quick" set a ceiling on the scope.
"Still" and "again" mean an earlier fix did not hold, so the check must name the cause and not only the
symptom. When the request names a mechanism ("add a retry"), work out the problem it is meant to solve and
write the check for that problem; if the mechanism does not fit it, say so in your first question.

## 3. Ask only what changes the contract

A question is worth asking when its answer changes a `Check:` line, `scope_paths`, the tier, or what is out
of scope. Anything else you can't settle becomes an `ASSUMED:` row, which the working agent verifies, or decides when nobody can check it.

- At most five questions in all, one to three at a time.
- Each question carries your recommendation and one line of why, so the person can answer "yes".
- Ask in plain words, about behaviour the person can see, not about code.
- If the request is two pieces of work, say so and offer two tickets.

## 4. Record honestly

Every question goes into the ticket's `## Grilling` table, with your recommendation and the person's answer
as they were said (shortened, never changed). `Taken` says what happened to the recommendation:

| Taken | When |
|---|---|
| `accepted` | The person took it as it was: "yes", "ok", "go with that" |
| `edited` | The person took it with a change |
| `rejected` | The person answered something else |
| `answered` | You had no recommendation (write `-` in Recommended) |

Grade each answer as the person would. Rail counts these, and a recommendation you mark accepted when the
person changed it makes the numbers lie. A question the person didn't answer is not in the table: it is an
`ASSUMED:` row. Never answer for the person.

## 5. Show the draft, then file it

Show the whole ticket, take changes, and show it again. Count the drafts you showed. File it only when the
person says it is right.

When the request came in writing and nobody can answer, don't wait for a confirmation: write each question
you would have asked as an `ASSUMED:` row, leave the table and `Confirmed:` empty, and file the draft.

- **In a Claude Code session in the repository:** write the ticket to a file outside the repository and run
  `rail add FILE`.
- **Anywhere else:** open a GitHub issue. Its title is the ticket's title, its body is the whole ticket
  starting with the `+++` line, and it gets the label `rail`. Don't write `id` or `external_id`: Rail sets
  them. The issue's author must be able to push to the repository; otherwise Rail takes the ticket as a
  request only, and its agent writes the contract again.

The label starts the work. An AUTO ticket ends in a merge with no person, so add the label only after the
person has confirmed the draft.

## The Grilling section

```markdown
## Grilling
- Channel: slack
- Agent: claude-opus-5-5
- Person: octocat
- Started: 2026-11-16T09:12:00Z
- Confirmed: 2026-11-16T09:31:00Z
- Drafts shown: 2

| # | Topic | Recommended | Answer | Taken |
|---|---|---|---|---|
| Q1 | scope | Only the export endpoint, not the UI | Yes | accepted |
| Q2 | done | A test that exports 10k rows in under 2s | Under 5s is fine | edited |
| Q3 | behaviour | Skip rows with no date | No: fail the export | rejected |
| Q4 | out-of-scope | - | Leave the CSV format alone | answered |
```

- `Channel` is required: one lowercase word, such as `session`, `slack`, `telegram`, `dots`, `app`.
- `Agent` is the model that grilled. `Person` is the GitHub login of the person who answered, only when
  they gave it; never a messenger handle, which would stay in git for good.
- `Started` is when the request came, `Confirmed` when the person confirmed the draft, both in UTC.
  With nobody to confirm, `Confirmed:` stays empty.
- `Topic` is one of `scope`, `done`, `behaviour`, `tier`, `out-of-scope`, `other`. Write a `|` inside a
  cell as `\|`.
- A ticket with no questions keeps the lines and an empty table: you read the code and asked nothing.

Ticket lint checks the section. Rail copies it into the ticket's journal as the `requested` event, and
`rail stats` counts it.
