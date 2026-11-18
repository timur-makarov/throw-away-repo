# Architecture decision records

Write an ADR only when a decision is hard to reverse, surprising, and a real trade-off. Most decisions
belong in the code, a check, or `ARCHITECTURE.md`.

```markdown
# NNNN: the decision, as a short sentence

Date: YYYY-MM-DD. Status: accepted (or: replaced by NNNN).

## Context
What forces the decision, in a few sentences.

## Decision
What we do.

## Consequences
What gets easier, what gets harder, and what would make us revisit it.
```

Keep ADRs in `docs/adr/`, numbered, one decision each. A replaced ADR stays, with its status pointing at
the one that replaces it.
