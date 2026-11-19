# Structure rules

A structure rule stops a bad shape from entering the code. It is a text match on added lines and added
files, so old code never fails and a new rule works from day one.

```toml
[[rules]]
id = "web-no-db"
files = "apps/web/**"          # the files the rule applies to; all files when left out
forbid = ["@acme/db"]          # text an added line in those files may not contain
fix = "Call the API client in apps/web/lib/api."
why = "ticket 41"

[[rules]]
id = "migrations-home"
files = "**/*.sql"
only_in = "db/migrations/**"   # each added file that matches must sit under this glob
fix = "Create migrations with make migration."
```

- `fix` is printed to the agent when the rule breaks.
- `why` is a note for whoever reads the config, such as the ticket that added the rule. The engine prints it nowhere.
- `allow` lists paths the rule skips.
- A rule prevents mistakes; real dependency analysis belongs in `verify`, with any checker the project likes.
- A finding a rule already covers is not a review finding.
- The seed ships two rules: no new suppressions or skipped tests, and a `SHORTCUT` marker must carry its
  ticket's number. The marker is how an agent says "I cut this corner on purpose": `SHORTCUT(41): linear
  scan, fine under 1,000 rows; index it past that`. A rule is a text match, so it refuses the marker without
  a number; it can't find a shortcut nobody marked.
