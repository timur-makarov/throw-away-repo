# Tickets from chat bots

People ask for work where they already talk: Slack, Telegram, Dots, the Claude app, a personal agent. Any
bot that can clone the repository and open a GitHub issue can turn such a request into a Rail ticket. Rail
needs no integration with the chat: the GitHub issue is the one way in.

```text
person <-> bot: the bot reads the repository and grills the person (rail docs grill)
bot -> GitHub: an issue whose body is the whole ticket, labelled rail
Rail: the next rail next takes the issue in as the ticket, as it is
```

## Set a bot up

1. **Give it read access to the repository**, to clone it and read the code before it asks anything.
2. **Give it a GitHub account that can push to the repository** (owner, member or collaborator), with a
   token that can open issues and add labels. Rail takes a whole ticket from an issue only when its author
   can push: a ticket's checks run on the machine, so a stranger's ticket is only ever a request. A bot
   whose issues come in as requests shows it in the ticket's first brief, with the reason.
3. **Give it the instructions.** Point it at `.rail/engine/docs/grill.md` in the clone: "Read that file and
   follow it for every request for work in this repository." In a Claude Code session the `rail-grill`
   skill, which `rail init` installs, says the same.

For Claude in Slack, a thread can start a Claude Code cloud session on the repository with the request; the
session grills in the thread and runs `rail add` itself, with no issue.

## Who can start work

The label `rail` starts work, and an AUTO ticket ends in a merge with no person. So whoever can talk to the
bot can start work that merges. Give the bot to the people you would give triage access to on the
repository, and have it add the label only after the person confirms the draft.

## What Rail keeps

The ticket keeps the `## Grilling` record: the channel, the model, each question with the recommendation and
the answer. Its journal starts with a `requested` event that holds the same, plus who filed the issue.
`rail stats` compares grilled tickets with the rest: how often the recommendations were taken, and how often
a contract changed after it was accepted, a ticket was dropped, or a fix ticket followed.

## An issue a person files by hand

An issue with a plain request, and any issue from someone who can't push, becomes a ticket with the request
and an empty contract. The agent that works it writes the contract from the request alone, with nobody to
ask. Grilling first is the better way in.
