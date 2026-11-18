---
name: rail-deepen
description: Rewrite a clear request so it asks for what a leading practitioner would do and names how the result is proven, before it becomes a ticket. Use when a request is clear but shallow, or when the person asks to aim higher.
---

# Deepen the request

- **Assumes:** the goal is clear. A person is present, or the request came in writing and you prepare a
  ticket from it alone.
- **Produces:** a rewritten request, a list of candidate `Check:` lines, and a list of what is missing
  (data, access, tools) with how to provide each.
- **Done means:** the rewritten request answers the four questions below. When a person is present, they
  have seen it and agreed.

This makes a request deeper, not larger. A deeper request still fits a ticket, or splits into several
(`rail-slice`).

## 1. Task or outcome

Ask what should be true after this, and after that. "Fix this crash" is a task. "The app stays free of
crashes" is an outcome: it needs a signal that is read again and again, and it produces tickets over time.
Say which one this is. For an outcome, say what would have to exist for it to run with no person handing
over tasks: the data, the access, the machines.

## 2. Four questions

Answer them yourself from the repository and the field. Ask the person only what you can't find out.

1. **What would a leading practitioner in this field do here that the request doesn't ask for?**
2. **What is the rawest material to start from?** The logs, the data, the source, and not a summary
   someone made of them.
3. **Which methods and tools does the field really use for this?** Name them. Asking an agent to "act like
   an expert" changes how it writes, not what it does.
4. **What, other than you or the person, would show that the result is right?** A test, a measurement, a
   comparison against known data.

The answer to the fourth question becomes the candidate `Check:` lines.

## 3. Test what the request takes for granted

List the beliefs inside the request ("the slowness is in the database"). For each, say how the raw material
could show it wrong. A belief you can check now, check. The others become `ASSUMED:` rows in the ticket.

## 4. Name what is missing

When a deeper version needs something that isn't there (an export, a connector, access, a machine where
software can be installed), say exactly what to provide. Don't drop the idea silently.

## Close

Show the rewritten request and what changed from the original. Then recommend `rail-blast-radius` when the
change touches existing code, or `rail-grill` to draft the ticket.
