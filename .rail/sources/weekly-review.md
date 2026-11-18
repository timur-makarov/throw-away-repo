+++
# The signal: what merged to the base branch in the last seven days, one line each with the files it touched (the
# whole squash messages would fill the brief). rail source sets RAIL_BASE to the base branch's ref ([base_branch],
# on the remote when there is one).
fetch = 'git log --first-parent --since=7.days --stat --format="%h %ad %s" --date=short "$RAIL_BASE"'
max_open = 3
+++

These are the changes that merged in the last seven days. Each was reviewed on its own. Look across them for what a review of one change cannot see:
- the same logic written twice by different tickets;
- code that landed in the wrong area, measured against `## Areas` in ARCHITECTURE.md;
- behaviour that two or more changes added and that no test exercises together;
- a doc that the week's changes made wrong.

Read the files as they are now, not only the list. Report only what you confirmed by reading the code: give the files and lines in the ticket's `## Why`. A ticket is worth filing when you can write a `Check:` line for it that fails today. File at most three tickets, the most valuable first. When nothing meets that bar, file none.

Key: the kind of problem and the main file, such as `duplicate-src/billing/total.py`.
