# Languages

Rail serves Python, TypeScript, Rust and Go first. Each has a profile: data in the framework's `profiles/`
folder that `rail init` reads when it finds the language. Any other language is unsupported: Rail still runs,
because the engine reads commands, not languages, but init writes nothing language-specific for it.

## How init finds a language

Init reads the repository's tracked files (`git ls-files`) and looks for each profile's manifests. A manifest
inside `node_modules`, `vendor`, `target`, `.venv` or `dist` is vendored, installed or built code and counts
for nothing.

| Profile | Manifests |
|---|---|
| `python` | `pyproject.toml`, `setup.cfg`, `requirements*.txt` |
| `typescript` | `package.json`; type checking is on only where a `tsconfig.json` is tracked too |
| `rust` | `Cargo.toml` |
| `go` | `go.mod` |

A manifest at the root gives the profile `paths = "**"`. Manifests only below the root give the top-most
folders that hold one: `web/**` for one folder, `{api,worker}/**` for two. A repository with a Go service in
`api/` and a web app in `web/` gets two profiles. Init's receipts list what it found.

## What init writes

Into a new `.rail/config.toml`, for each profile found:

- a `[[profiles]]` entry with its `name` and `paths`;
- a `[[rules]]` entry that forbids the language's suppression markers in added lines of its own files
  (`rail docs rules`);
- its migration folders in `migration_paths`, its generated files in `[size] exclude`, and its test files in
  `[tests] paths`;
- its default `setup` and `verify` in `[commands]` (below).

| Profile | Suppression markers, in these files | Migration paths | Generated files |
|---|---|---|---|
| `python` | `# type: ignore`, `# pyright: ignore`, `@pytest.mark.skip`, `@pytest.mark.xfail` in `**/*.py` | `**/alembic/versions/**` | `**/*_pb2.py`, `**/*_pb2_grpc.py` |
| `typescript` | `@ts-expect-error`, `@ts-nocheck`, `oxlint-disable`, `biome-ignore`, `.only(` in `**/*.{ts,tsx,mts,cts,js,jsx,mjs,cjs}` | `**/drizzle/**` | none |
| `rust` | `#[allow(`, `#![allow(`, `#[ignore` in `**/*.rs` | none | none |
| `go` | `//nolint`, `t.Skip(` in `**/*.go` | none | `**/*.pb.go` |

The seed's own `no-new-suppressions` rule stays, on every file. An existing `.rail/config.toml` is never
touched: init lists what it found and writes nothing to it.

## A language added later

A service in another language, or a second folder in a language the project has, arrives after the config
exists, so init writes none of the above for it. Three places say so:

- `rail doctor` has a line `languages`. It fails when a tracked manifest of the four languages is covered by no
  `[[profiles]]` entry of its language, and names the top-most folder's manifest.
- `rail init`, run again with the `rail` that `install` put on `PATH`, prints what the config lacks: the
  `[[profiles]]` entry and the language's rules to add at the end of the file, what `migration_paths`,
  `[size] exclude` and `[tests] paths` gain, and what `setup` and `verify` gain for each new folder. For a new
  folder of a language the config has, it prints the entry's new `paths` and the commands. It writes nothing to
  the config: `.rail/config.toml` is a person's to approve, so the text goes into a ticket.
- The sweep's free part names the same manifests on the base branch, so a project where nobody runs doctor
  still hears of it.

A manifest that marks no code of the project's own, such as a `package.json` kept for a formatter, goes under
`[init] other_manifests`, a list of globs. Vendored, installed and built folders are skipped as at init.

## The commands init writes

Into the new config's `[commands]`, init also writes a default `setup` and `verify` for each profile found.
The package manager is the one whose lockfile is tracked beside the manifest; with no lockfile, the first
in the row.

| Profile | Manager, by lockfile | `setup` | `verify`, in order |
|---|---|---|---|
| `python` | `uv` (`uv.lock`), `poetry` (`poetry.lock`), `pip` (`requirements.txt`) | `uv sync --locked` | format `uv run ruff format --check --extend-exclude .rail --extend-exclude .claude .`; lint `uv run ruff check --extend-exclude .rail --extend-exclude .claude .`; types `uv run basedpyright`; tests `uv run pytest -q`; audit `uv export --locked --no-emit-project --format requirements-txt \| pip-audit --disable-pip -r /dev/stdin` |
| `typescript` | `pnpm` (`pnpm-lock.yaml`), `npm` (`package-lock.json`), `yarn` (`yarn.lock`), `bun` (`bun.lock`) | `pnpm install --frozen-lockfile --ignore-scripts` | lint `pnpm exec oxlint`; types `pnpm exec tsc --noEmit`; tests `pnpm test`; audit `pnpm audit` |
| `rust` | `cargo` (`Cargo.lock`) | `cargo fetch --locked` | format `cargo fmt --check`; lint `cargo clippy --all-targets --locked -- -D warnings`; tests `cargo test --locked` (a workspace's root runs every member); audit `cargo deny check advisories` |
| `go` | `go` (`go.sum`) | `go mod download` | format `test -z "$(gofmt -l .)"`; lint `go vet ./...` and `golangci-lint run`; tests `go test -race ./...` (the race detector needs cgo and a C compiler); audit `govulncheck ./...` |

The other managers of a profile run the same parts through their own runner. How init puts the parts
together:

- The parts are joined with `&&`, each language after the one before, so the first failure ends `verify`.
- A profile below the root runs each command in its folder, as `(cd web && pnpm test)`. A language in two
  folders runs every part in both.
- `types` is left out where type checking is off: a `package.json` with no `tsconfig.json`.
- An audit runs only on a change that touches the lockfile:
  `{ git diff --quiet "$RAIL_BASE"...HEAD -- uv.lock || AUDIT; }`. A new advisory on an old dependency
  then doesn't fail a ticket that has nothing to do with it.
- One secret scan over the branch's commits ends `verify`, whatever the languages:
  `gitleaks git --no-banner --log-opts="$RAIL_BASE..HEAD"`.
- ruff leaves out `.rail` and `.claude`: Rail's engine and the agent's files are tracked in the project,
  and they are not its code.
- An install runs no dependency's lifecycle scripts where the manager can turn them off (`--ignore-scripts`).
  Cargo can't: a build always runs the dependencies' build scripts and procedural macros.

The defaults are a start. The init task tells the agent that the repository's own commands win: where a
Makefile target, a `package.json` script or a CI step already runs a part, that goes in the default's place,
because it holds what the project knows. Every tool `verify` names has to be on the machine that runs it:
a command the shell can't find is recorded as could not run (`rail docs retries`).

Rail's own tests run each profile on a small real project of that language, from `rail init` to a merged
ticket: `setup` and `verify` pass, and one planted mistake for each part fails it. Which lines that covers:

| Profile | Run by Rail's tests | Not yet run by them |
|---|---|---|
| `python` | uv's setup, format, lint, tests | types (basedpyright), audit (pip-audit); every Poetry and pip line |
| `typescript` | pnpm's setup, types, tests | lint (oxlint), audit; every npm, Yarn and Bun line |
| `rust` | setup, format, lint, tests | audit (cargo-deny) |
| `go` | setup, format, both lints, tests | audit (govulncheck) |

The secret scan is not yet run by them either. Plant a mistake for each part on your own project before
you rely on it, as the init task asks.

## Generated Go files

A Go file whose generator marked it is left out of the size count wherever it lives: a line that reads
`// Code generated ... DO NOT EDIT.` on its own, anywhere before the `package` line, which is the mark Go's
own tools read. The same words after `package`, or at the end of another line, mark nothing.

Into `.claude/settings.json`, whether the config is new or not: each profile's package registry in
`sandbox.network.allowedDomains`, so the agent's own installs reach it with the sandbox on. Python:
`pypi.org`, `files.pythonhosted.org`. TypeScript: `registry.npmjs.org`, `registry.yarnpkg.com`. Rust:
`index.crates.io`, `static.crates.io`. Go: `proxy.golang.org`, `sum.golang.org`. A mirror, a private
registry or a Git dependency is the project's to add.

After init every file is the project's, as with the rest of the seed: change or delete what doesn't fit.
