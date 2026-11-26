# Sensors

A sensor is a ship step backed by a tool: a duplication finder, a complexity counter, a linter with rules
stricter than `verify` asks of old code. A violation is one line of the tool's output. Only a violation on a
line the change adds fails the ship, so a sensor works from day one on a codebase that is already full of
what it looks for. No sensor is on until the project writes one.

```toml
[[sensors]]
id = "duplication"
paths = ["src/**"]                 # runs only when the change touches these; every change when left out
command = 'jscpd --config "$RAIL_SENSORS/jscpd.json" --reporters xcode .'
ok_exit = [0]                      # no violations; [0] when left out
violations_exit = [1]              # violations printed; [1] when left out
fix = "Call the code that already does this, or move both copies into one function."
```

**One step, last.** `sensors` runs after `checks`, at ship and in CI, so `verify` and the Done Contract speak
first. Each sensor whose `paths` the change touches runs in the ticket's worktree, through the same shell and
within the same `timeout_secs` as a check. A failure counts toward the retry budget like any step
(`rail docs retries`). With no sensor due, the step is not run, and a project with no sensor has no such step.

**What a violation is.** A line of the output of the form `path:line: message`. A range (`path:12-18:`) and a
column (`path:12:5:`) are read too, colour codes are stripped, and a path may be absolute or start with `./`.
Any other line is ignored. Set the tool to print one violation a line, and turn off any cap it puts on
repeated findings, or a new violation can hide behind old ones.

**Only new code fails.** The engine keeps a violation when one of its lines is a line the change adds to the
base branch, and drops it when:

- the line is old, or the file is untouched: the sensor still printed it, and it fails nothing;
- git shows the line as part of a block that moved (the same block is removed elsewhere in the change). A
  block that was copied is new;
- the file is a lockfile or matches `[size] exclude`, as for the size count;
- a marker answers it (below).

**The tool reads the base branch's files.** The command gets two variables: `RAIL_SENSORS`, a folder holding
the base branch's copy of `.rail/sensors/`, and `RAIL_MAP`, the base branch's `ARCHITECTURE.md`. Keep a
sensor's config and scripts in `.rail/sensors/` and name them through `RAIL_SENSORS`: a ticket that edits them
changes nothing for its own ship. `.rail/sensors/**` is in `person_paths`, as `.rail/config.toml` is, so a
ticket that changes a sensor is a person's to approve. `RAIL_BASE` and `RAIL_TICKET` are set as for a check.

**A sensor that is wrong about a line.** A comment `SENSOR(NN): why`, with the ticket's number, on the line
or on the line above it, makes the engine drop that line's violations:

```python
# SENSOR(41): the two parsers must stay apart, one reads untrusted input
```

No suppression of the tool itself is needed, so `no-new-suppressions` stays as it is. The seed's rule
`sensor-marker-names-its-ticket` refuses the marker without a number. The briefs of the review and of the
security seat list each marker a change adds, and ask for the reason to be judged: a marker with no reason
that holds is a finding.

**Exit codes.** An exit in `ok_exit` passes. An exit in `violations_exit` has its output read. Any other exit
is `could_not_run`: nothing was checked, and it counts as an attempt. The brief then tells two cases apart.
For exit 127 or 126 the tool is missing, and the brief says to install it. For any other exit the tool
crashed, or its command or config is wrong, and the brief says so: a change that broke what the tool reads is
the agent's to fix, and the sensor itself is a person's. `rail doctor` lists each sensor whose tool is not on
the machine, before a ship finds out.

**Choosing a sensor.** A good one is fast, reads source text without a build, and reports a kind of mistake
that agents make and reviewers tire of: a second copy of code that exists, a function that grew past what one
reader holds. What must hold for the whole program belongs in `verify`; a sensor is for what should stop
getting worse.
