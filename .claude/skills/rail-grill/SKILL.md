---
name: rail-grill
description: Turn a request for new work into a Rail ticket by questioning the person who asked, before rail add. Use when someone asks for a feature, a fix or a change in a project that runs on Rail.
---

Read `.rail/engine/docs/grill.md` (or run `rail docs grill`) and follow it. In this session, file the confirmed
ticket with `rail add FILE`, from a file outside the repository, with `Channel: session` in its `## Grilling`
section.

When the request is about data, look at the real data too before you ask (the stored records, a sample of the
input, the output the code makes today), so you don't ask the person what you can see there and your checks fit
the data as it really is.

Two other skills can come before this one. Each is optional: `rail-blast-radius` for the scope and tier of
a change to existing code, and `rail-slice` when the work is more than one ticket.
