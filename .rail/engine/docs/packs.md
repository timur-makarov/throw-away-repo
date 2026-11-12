# Packs

A pack is an optional feature in a folder: `.rail/packs/NAME/`, with a `README.md` that names its reader
and a `bin/` of commands.

- `rail NAME ...` runs `.rail/packs/NAME/bin/NAME`.
- Its settings live in a `[NAME]` section of `.rail/config.toml`.
- It may be written in any language.

**Rules:** a pack names its reader. It can only add hints; it never changes ticket state, and it never
writes the journal.

**When to make one:** when a feature has a reader but fails the test for the core: about 80% of projects
would not use it, or a person could set it up once in a few minutes.

**To add one:** make the folder with its `README.md` and `bin/NAME`, make the command executable, and add
its settings section. To remove one, delete the folder.

The `consult` pack is installed by default (`rail docs retries`).
