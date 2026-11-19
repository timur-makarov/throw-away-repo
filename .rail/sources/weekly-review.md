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

Read the files as they are now, not only the list. File a ticket only for a problem that is in the code now and is one of the four kinds above. Give its files and lines in the ticket's `## Why`, and write a `Check:` line that fails today because of that problem. A check that fails only because the test it names is not written yet shows nothing, so write the check to run against the code as it is. Run each check before you file its ticket, and drop the ticket when the check passes. A feature the product does not have is not a problem of these kinds: this source files none. File at most three tickets, the most valuable first. When nothing meets that bar, file none.

Key: the kind of problem and the main file, such as `duplicate-src/billing/total.py`.
