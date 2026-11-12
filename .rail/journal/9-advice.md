## 2026-11-12T19:31:41Z: retry_cap at 'refuter', change (same-model)

Question: The step 'refuter' failed 2 times. What is wrong, and should the agent proceed, change its approach, or stop and ask a person?

**What is wrong.** F40 is a real fail-open regression in the framework's new guard, so disputing it again will fail a third time. I did not run it; this comes from reading the diff.

- `_unwrap` now strips shell keywords (`then`, `do`, `{`), so a `cd /tmp && true` behind one looks like a plain `cd DIR &&`.
- `_after_cd` then sets `here` to `/tmp`, and nothing resets it at `fi`, `done` or `}`.
- The later `git push` or `gh pr merge` is placed in a non-project directory and skipped, although the shell may never have run that `cd`.

The agent is probably defending it as upstream code "copied whole". That line is in Look at, not in the Done Contract, and the ticket's Why is to close exactly this kind of hole.

**What to do.** Stop disputing and fix it in `.rail/engine/rail/guard.py`, which is in scope.

1. In `_deny`, believe a `cd`/`pushd` only when it is unconditional. If the command's raw words start with a keyword (`raw[0] in KEYWORDS`, or `raw` is longer than `words` because of a keyword), set `here = None` instead of calling `_after_cd`. That only makes the guard stricter.
2. While there, check `false && cd /tmp && true; git push -f origin x`. `_after_cd` distrusts a `cd` after `||` or `|` but not after `&&`, so this likely passes too. If it does, treat a `cd` whose preceding operator is `&&` and whose previous command was not itself a followed `cd` the same way.
3. Re-run the refuter's five commands and the six Done Contract checks.
4. Answer F40 as `fixed`, not declined.
5. Amend Look at to say the engine is the framework at the `.rail/SOURCE` commit plus this one guard fix, and name the fix so it can go upstream.

`tests/` is not in `scope_paths`, so do not add a test file there without an amend.

