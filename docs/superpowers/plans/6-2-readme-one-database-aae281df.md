# 6.2 README: one database, migration, relink, export/import

Card: aae281df (subtask of story 6bfad168 "Document the new surface"; blocked by
84795ab7, 6.1 `--help` and `brd prompt`, already landed on this branch).
Parent design: `docs/superpowers/specs/2026-10-06-single-db-cross-project-blocking-design.md`
in the main checkout (not present in this worktree's `docs/`), cited below as **[P]**
with line numbers.

## Goal

A person upgrading brd, or setting it up on a second machine, reads `README.md`. It
already explains that every board lives in one `brd.db`, how the current project is
found, `brd init --relink`, `brd forget --project` and export/import. It does **not**
say that the first run of a new brd moves the old per-project files into `brd.db`,
what that leaves behind, or that every installed copy has to be upgraded together.
Its import paragraph is a single 900-character line that is hard to read.

This card makes `README.md` tell that whole story, worded from the code as built, so
a reader can upgrade, move a repo, forget a project and move boards between machines
without reading the source.

This is a documentation-only change: one file, `README.md`. No code, help text, JSON
shape, message or exit code changes.

## Inherited constraints

- [P] D2 (line 32): one database, `$XDG_DATA_HOME/brd/brd.db`; `master.db` and
  `projects/<hash>.db` go away.
- [P] D5 (line 35) and §2 lines 100-107: no `.brd` marker; the current project is the
  deepest registered root at or above the cwd; `brd init` writes nothing into the
  repo; `brd init --relink <old-root-or-project-id>`; nested projects allowed.
- [P] §2 lines 122-123: `brd forget` takes the cwd project, or `--project <id>` for a
  project whose directory no longer exists.
- [P] D8 (line 38): `brd forget` and import's replacement keep incoming edges from
  other projects as not-found; they reconnect when the ids return.
- [P] §3 lines 127-147: migration runs once, from any command; all projects in one
  transaction; a shared id aborts it with nothing renamed; old files renamed with
  `.migrated`, never deleted; stderr notice; unregistered `projects/*.db` skipped and
  reported. Lines 144-147 are the release-notes text this card turns into README
  prose: "Existing `.brd` files and `.gitignore` lines are left alone and ignored.
  … boards in those very old formats must be opened once with the last per-project
  release first; upgrade every installed copy of brd together."
- [P] D9-D11 (lines 39-41) and §5 lines 208-237: export is a list of projects;
  `--all` exports every project; import placement, replacement after confirmation,
  `--yes`, refusal without a TTY; the cross-machine round trip.
- [P] "Implementation order" (lines 271-284) and story 6bfad168: this story owns
  `README.md`; sibling 6.1 owned `src/brd/cli/_app.py` help text and
  `src/brd/prompt.py`.

## Behaviour as built (the facts the README must state)

Read from the code at this branch's HEAD. The README must not promise more than
this, and where the code differs from [P], the code wins.

| Fact | Source |
|------|--------|
| Data lives in `$XDG_DATA_HOME/brd/`, else `~/.local/share/brd/`: `brd.db`, and document backups in `docs/<doc-id>.md`. | `src/brd/paths.py:6-23` |
| Every data command connects through `master.connect()`. When `brd.db` is not yet at schema 4 and `master.db` exists, that call migrates first, even for a command run outside any project. With no `master.db` it creates an empty `brd.db` with no notice. `brd --help`, `brd prompt` and `brd purge` do not migrate. | `src/brd/master.py:27-67`; `src/brd/cli/_app.py:74-77`; `src/brd/cli/project.py:96-97`; `tests/test_single_db_migration.py:674,692` |
| The migration copies every project registered in `master.db`, together with its board `projects/<sha256(root)>.db` and its backups `projects/<hash>.docs/`, into `brd.db` in one transaction. It keeps every project id, card/issue/document/comment id and timestamp. (Here the code differs from [P] line 133, which planned new project UUIDs. The ids already registered in `master.db` are kept.) A registered project with no board file is registered empty. | `src/brd/consolidate.py:1-6,114-129,167-207` |
| Boards at any schema version that `master.db` registered (v0-v4) are upgraded on the way. Even very old `master.db` registries that have no project ids are upgraded. | `src/brd/consolidate.py:66-84`; `src/brd/db.py:417-442`; `tests/test_single_db_migration.py:120,245` |
| After the commit, `master.db` and each migrated board and `.docs` directory are renamed with a `.migrated` suffix, with their `-wal`/`-shm` sidecars. Nothing is deleted. A rename that fails leaves the old file in place and does not re-run the migration. | `src/brd/consolidate.py:19,210-229` |
| A notice goes to stderr, not stdout: `brd: migrated N projects into brd.db (old files kept as *.migrated)`. When unregistered board files exist, a second line follows: `brd: skipped K unregistered board files: projects/<hash>.db, …`. Those files are left untouched. | `src/brd/consolidate.py:28-38,150-157`; `tests/test_single_db_migration.py:169,601,634` |
| If two boards share an id, or a board is unreadable or records another project, the command fails with `MigrationError`, which names the projects and ids or files. Nothing is renamed, and the next brd command tries again. `brd purge` still works in that state. | `src/brd/consolidate.py:66-112,190-195`; `src/brd/master.py:221-237`; `tests/test_single_db_migration.py:347,577,719` |
| Very old formats that `master.db` never registered, namely an in-repo `.brd/` directory board or a UUID `.brd` marker, are not found by the migration. Old `.brd` marker files and `.gitignore` lines are ignored, never edited. | [P] lines 144-147; `src/brd/master.py:89-97` (resolution ignores markers); `tests/test_master.py:469` |
| An old brd still installed elsewhere (another venv, pipx, an older `uv tool`) reads `master.db` and `projects/`. After the migration renames those files, an old brd no longer sees the boards, and nothing it writes appears in `brd.db`. No code guards this; it follows from the rename. | `src/brd/consolidate.py:210-229`; `src/brd/master.py:31-33` (only `brd.db`'s version decides) |
| A command in a directory with no registered project at or above it fails with `ProjectNotFoundError`: `no registered project at or above <dir>; run \`brd init\` there`. | `src/brd/master.py:89-97`; `tests/test_cli_app.py:108` |
| `brd init` in an already-registered root keeps its id and created_at and only updates the name. | `src/brd/master.py:70-86` |
| `brd init --relink <old-path-or-id>` points the existing project at the cwd. It matches by project id first, else by old root path: a relative path is taken relative to the cwd, without following symlinks. The project keeps its id, created_at and board; `--name` renames it at the same time. An unknown ref fails with `no project with id or root path <ref>; see \`brd projects\``. Relinking onto another project's root is refused. | `src/brd/master.py:100-133`; `src/brd/cli/project.py:17-39`; `tests/test_cli.py:123-166` |
| `brd forget` with no argument forgets the project the cwd belongs to (deepest root). With a path it forgets the project registered exactly at that path. With `--project <id>` it forgets that project from anywhere, even when its directory is gone. Giving both a path and `--project` is a `UsageError`. It deletes the project's board and its document backups, not the repo's files. Edges from other projects into it stay, as not-found. | `src/brd/cli/project.py:53-87`; `src/brd/master.py:144-197`; `tests/test_cli.py:210-294,1128` |
| `brd export` writes the current project (needs one). `brd export --all` writes every registered project from any directory. | `src/brd/cli/snapshot.py:96-115` |
| `brd import <file> [--yes]`: placement, replacement, confirmation, refusals and not-found edges are as the current README paragraph (line 73) already states. Before asking, import prints one stderr line per replaced project: `brd: replacing <name> (<root>): -N cards, … / +N cards, …`. The y/N question defaults to no. `--pretty` prints one line per project, marked `[registered]` or `[replaced]`, plus `not-found edge targets: N`. | `src/brd/cli/snapshot.py:41-93,118-145`; `src/brd/snapshot.py:276-360` |

## Required behaviour

Each requirement is an observable property of `README.md` after the change.

### R1. `## Storage` is split into short subsections

`## Storage` keeps its heading and gains four `###` subsections, in this order:

1. `### One database`
2. `### Upgrading from per-project databases`
3. `### Finding the project, moving a repo`
4. `### Moving boards between machines`

The other top-level sections (`Install`, `Usage`, `Documents`, `For agents`) keep
their headings and order. Every fact the current `## Storage` states (README
lines 38-73) is kept, under one of the four subsections. Nothing it says now is
dropped, and the current wording is reused where it is already accurate.

### R2. One database

States:

- every project's board lives in one file, `~/.local/share/brd/brd.db`, or
  `$XDG_DATA_HOME/brd/brd.db` when that is set;
- document backups sit next to it, in `docs/`;
- `brd init` writes nothing into the repo, and nothing project-specific is committed
  to git, so a board does not travel with a clone. Point to "Moving boards between
  machines".

### R3. Upgrading from per-project databases (new content)

States, in plain words:

- older versions kept a registry, `master.db`, and one board file per project under
  `projects/`;
- the first brd command that reads data moves every registered project, with its
  cards, issues, documents, comments, ids and timestamps, and its document backups,
  into `brd.db`, all at once. Any data command does this, even one run outside a
  project; `brd --help` and `brd prompt` do not;
- the old files are renamed with a `.migrated` suffix and never deleted. Once the
  boards look right, they can be deleted by hand;
- the stderr notice, quoted exactly:
  `brd: migrated N projects into brd.db (old files kept as *.migrated)`.
  Board files under `projects/` that `master.db` did not register are left alone and
  listed in a second `brd: skipped …` line;
- if the migration cannot finish (for example, two boards share an id), the command
  fails, names what clashed, renames nothing, and the next command retries once the
  cause is fixed. `brd purge` still works in that state;
- **upgrade every installed copy together**: an older brd (another virtualenv,
  `pipx`, `uv tool`) still reads `master.db` and `projects/`. After the migration it
  no longer finds those boards, and anything it records never reaches `brd.db`;
- `.brd` marker files and `.brd` lines in `.gitignore` written by older versions are
  ignored, and can be deleted by hand (this keeps the current README's lines 54-55);
- boards in the **very old** formats that `master.db` never registered (an in-repo
  `.brd/` directory, or a UUID `.brd` marker) are not migrated. Open each of them
  once with the last release that used per-project databases, so that it gets
  registered, before upgrading. Without that step, the upgrade cannot find them.
  This replaces the current lines 56-58, which do not say which formats or why.

R3 must not name a version number for "the last release that used per-project
databases". This card did not establish one, and the README has no version history.

### R4. Finding the project, moving a repo

States:

- a command uses the registered project whose root is the current directory or its
  deepest ancestor, so it works from any subdirectory, and nested projects are allowed
  (inside a nested project its own root wins). This is kept from the current lines 42-45;
- outside any registered project, a data command fails with the quoted message
  `no registered project at or above <dir>; run \`brd init\` there`;
- re-running `brd init` in a registered root only renames it (`--name`);
- `brd init --relink <old-path-or-id>`, run in the new location, moves an existing
  project there, keeping its id and board. It takes either the project id (from
  `brd projects`) or the old root path; `--name` renames it at the same time;
- `brd forget` removes a project and its stored board and document backups, never
  files in the repo. With no argument it removes the current project. With a path it
  removes the project registered at exactly that path. `--project <id>` works from
  anywhere, for a project whose directory is gone. Cards in other projects that were
  blocked on its cards stay blocked, showing those blockers as not-found, until the
  ids come back (for example, by importing the project again).

### R5. Moving boards between machines

States everything the current lines 60-73 state, split into short paragraphs of at
most about 6 lines each, rather than one long line:

- the `bash` example (`brd export > docs/board/snapshot.json`, `brd import …`) stays;
- snapshot shape (a list of project entries); `brd export` writes the current
  project and `brd export --all` writes every project, from any directory;
- import keeps original ids, content, timestamps and document backups, and never
  writes or deletes source files in the repo (use `brd doc restore <id>`);
- placement: a one-project snapshot goes to the current project, registering the
  current directory if needed, so no `brd init` is required. A multi-project snapshot
  goes to the project with the same id, else to its recorded root if that directory
  exists. Import refuses when an entry cannot be placed;
- replacement: a target project that already has entities is replaced. Import
  prints what it will remove and add, then asks y/N, defaulting to no. `--yes` skips
  the question. Without a terminal and without `--yes`, import refuses and writes
  nothing;
- edges: edges from other projects into a replaced project are kept as not-found,
  and edges to ids not in the database are kept and counted as not-found. Both
  reconnect when the ids return. Import refuses, touching nothing, when an id belongs
  to a project it is not replacing;
- the two-machine recipe: `brd export --all > board.json` on one machine and
  `brd import --yes board.json` on the other. This restores every project whose root
  exists there, with ids, hierarchy and edges intact. Re-importing a project's own
  export changes nothing;
- older one-object `brd export` snapshots and `brd tree` snapshots still import.

### R6. Usage block

The `## Usage` code block gains these lines, aligned with the existing `#` comments
column:

- `brd init --relink <old-path-or-id>` (after a repo moved)
- `brd forget --project <id>` (forget a project whose directory is gone)
- `brd export --all > board.json` (snapshot every project)
- `brd import --yes board.json` (restore it on another machine)

No existing Usage line is removed or changed.

### R7. Style

- Prose wraps at 72 columns or fewer, like the rest of the README. Code fences,
  table-free lists and quoted messages are the only lines allowed to be longer.
- Commands, paths, flags and quoted messages are in backticks. Code fences are
  ```` ```bash ````.
- Every message quoted in the README matches the source string byte-for-byte, with
  the source's placeholders (`N`, `<dir>`, `<ref>`) written as such.
- Plain words, short sentences; no marketing.

## Error paths the README must cover

| Situation | What the README tells the reader |
|-----------|----------------------------------|
| Command run outside any registered project | the `no registered project at or above …` message, and that `brd init` (or `--relink`) fixes it |
| Repo moved; old root gone | `brd init --relink <old-path-or-id>` from the new location |
| Project's directory deleted | `brd forget --project <id>`; ids from `brd projects` |
| Migration aborts (shared ids, unreadable board) | the command fails and names the cause; nothing renamed; the next command retries; `brd purge` still works |
| Older brd copy still installed | upgrade every copy together; the old copy no longer sees the migrated boards |
| Very old in-repo `.brd/` or UUID-marker board | open once with the last per-project release before upgrading |
| Import target has entities, no terminal | refuses without `--yes`, writing nothing |
| Import entry cannot be placed / id owned by another project | refuses, touching nothing |

## Tests

**No new automated tests.** The card says "No tests of its own". The README is
prose, and no test in `tests/` reads `README.md` (`grep -rn README tests src` is
empty). A test that pinned README wording would only duplicate the tests that
already pin the behaviour it describes:

| Behaviour described | Already pinned by (tier: unit/integration, CLI via `CliRunner`) |
|--------------------|-----------------------------|
| migration of v0-v4 boards, empty registry, missing board | `tests/test_single_db_migration.py:120,157,230,245` |
| old files renamed, never deleted; sidecars follow | `tests/test_single_db_migration.py:209,529` |
| notice text on stderr; skipped files listed | `tests/test_single_db_migration.py:601,634` |
| migration from outside a project; no migration for `--help`/`prompt` | `tests/test_single_db_migration.py:674,692` |
| abort with shared ids, retry succeeds; purge without migrating | `tests/test_single_db_migration.py:347,547,577,719` |
| no-project error | `tests/test_cli_app.py:108` |
| relink by path / id / unknown / onto another root | `tests/test_cli.py:123-166` |
| forget current / path / `--project` / both refused / edges kept | `tests/test_cli.py:210-294,1128` |
| export/import placement, replacement, confirmation | `tests/test_snapshot.py`, `tests/test_cli.py` (cards 5.1-5.3) |

The plan's verification steps, instead of tests:

1. **Full suite, unchanged and green:** `uv run pytest`. This proves no code moved.
2. **Diff scope:** `git diff --stat 97f9009..HEAD -- . ':!docs/superpowers'` (97f9009 is
   this card's base; earlier branch commits belong to sibling cards) lists
   only `README.md`.
3. **Fact check:** for every quoted message in the new README, `grep -rnF` finds the
   same text in `src/brd/` (allowing for the placeholders). For every command and
   flag named, `uv run brd <command> --help` shows it.
4. **Wrap check:** `awk 'length > 72' README.md` prints only lines inside code
   fences.
5. **Smoke run of the README recipe** with a scratch data dir
   (`export XDG_DATA_HOME=$(mktemp -d)`) and a temp repo: `brd init`, `brd add
   --title x`, `brd export > s.json`, `brd forget`, `brd import --yes s.json`,
   `brd projects`; then, from a directory outside any project, `brd export --all`
   succeeds and `brd list` fails with the quoted `no registered project at or
   above …` message.

## Out of scope

- Any change under `src/` or `tests/`, including help text and `brd prompt`, which
  belonged to sibling card 6.1 (84795ab7).
- `HACKING.md`, whose layout section (lines 5-7, which still name `cli.py`) is stale.
  That is a separate fix.
- The `## Documents` section, beyond leaving it accurate. Its "backup copy next to the
  board database" is still true.
- The parent design doc and other specs.
- Release notes or a CHANGELOG (the repo has none), and naming a specific release
  version.
- Orchestrator / agent-manager documentation ([P] lines 250-251).

---

# 6.2 README: one database, migration, relink, export/import — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `README.md`'s `## Storage` section into four short subsections that explain the one database, the one-time upgrade from per-project databases, finding/relinking/forgetting projects, and export/import, and add four lines to the `## Usage` block.

**Architecture:** Documentation only. One file changes: `README.md`. No code, help text, JSON shape, message or exit code changes. Every fact is worded from the code as built (see the spec's "Behaviour as built" table); every quoted message is checked byte-for-byte against `src/brd/`.

**Tech Stack:** Markdown; verification with `grep`, `awk`, `uv run brd`, `uv run pytest`.

**Spec:** `docs/superpowers/specs/6-2-readme-one-database-aae281df.md` (prepended above, verbatim).

## Global Constraints

- Only `README.md` changes. `git diff --stat 97f9009..HEAD -- . ':!docs/superpowers'` must list only `README.md`.
- No change under `src/` or `tests/`; `HACKING.md`, `## Documents`, `## Install`, `## For agents` untouched.
- Top-level headings stay `Install`, `Usage`, `Storage`, `Documents`, `For agents`, in that order.
- `## Storage` gains exactly these `###` subsections, in order: `### One database`, `### Upgrading from per-project databases`, `### Finding the project, moving a repo`, `### Moving boards between machines`.
- Prose wraps at 72 columns or fewer. Only lines inside code fences and lines that are a single quoted message may be longer.
- Commands, paths, flags and quoted messages are in backticks. Code fences are ```` ```bash ````.
- Every quoted message matches the source string byte-for-byte, with placeholders (`N`, `K`, `<dir>`, `<hash>`) written as such.
- Do not name a version number for "the last release that used per-project databases".
- Plain words, short sentences; no marketing.
- No new automated tests (spec "Tests" section). Verification is the five checks in Task 2.

## Review Focus

1. **A user with two installed copies of brd** (e.g. `uv tool` and a project venv) — expects a clear, standalone instruction to upgrade every copy together, and why. Pinned by Task 1 Step 4 check (d): the paragraph starts with "Upgrade every installed copy of brd together."
2. **A message containing backticks** (``no registered project at or above <dir>; run `brd init` there``) — a reader expects it to render as one code span, not broken markup. Pinned by Task 1 Step 4 check (e): the line uses double-backtick delimiters.
3. **The migration notice is split across two f-strings in `src/brd/consolidate.py:30-31`** — a reader who greps their stderr for the README's text expects an exact match. Pinned by Task 2 Step 3: both halves are grepped, and the joined string is compared.
4. **A reader on a narrow terminal / plain-text viewer** — expects no prose line over 72 columns. Pinned by Task 1 Step 4 check (f) and Task 2 Step 4.
5. **Unbalanced code fences** after splicing — everything after would render as code. Pinned by Task 1 Step 4 check (g): the count of fence lines in `README.md` is even.

---

## File Structure

- Modify: `README.md`
  - lines 17-36 (`## Usage` code block): add four lines after line 28 (`brd projects ...`).
  - lines 38-73 (`## Storage` through the long import paragraph): replaced wholesale by the new section. Line 74 (blank) and line 75 (`## Documents`) onward stay.

Two tasks: Task 1 rewrites `## Storage` (R1-R5, R7); Task 2 adds the Usage lines (R6) and runs the full verification. A reviewer could accept one and reject the other.

---

### Task 1: Rewrite `## Storage` into four subsections

**Files:**
- Modify: `README.md:38-73`

**Interfaces:**
- Consumes: nothing.
- Produces: the `## Storage` section with the four `###` headings named in Global Constraints. Task 2 relies on the heading `### Moving boards between machines` existing and on lines 1-37 of `README.md` being unchanged by this task.

- [ ] **Step 1: Write the failing check**

Save this check script outside the repo (it is not committed):

```bash
cat > /tmp/readme62-check.sh <<'CHECK'
#!/usr/bin/env bash
# Checks README.md against spec 6.2 R1-R5, R7. Exit 0 = pass.
f=README.md
fail=0
need() { grep -qF -- "$1" "$f" || { echo "MISSING: $1"; fail=1; }; }
# (a) headings, in order
got=$(grep -E '^##+ ' "$f" | tr '\n' '|')
want='## Install|## Usage|## Storage|### One database|### Upgrading from per-project databases|### Finding the project, moving a repo|### Moving boards between machines|## Documents|## For agents|'
[ "$got" = "$want" ] || { echo "HEADINGS: $got"; fail=1; }
# (b) R2/R3 facts
need '`$XDG_DATA_HOME/brd/brd.db`'
need 'next to it, in `docs/`'
need '`master.db`'
need '`.migrated` suffix and never deleted'
need '`brd: migrated N projects into brd.db (old files kept as *.migrated)`'
need '`brd: skipped K unregistered board files: projects/<hash>.db, ...`'
need '`brd purge` still'
need '`brd --help` and `brd prompt` do not'
need 'in-repo `.brd/` directory or a UUID `.brd` marker'
# (c) R4/R5 facts
need '``no registered project at or above <dir>; run `brd init` there``'
need '`brd init --relink <old-path-or-id>`'
need '`brd forget --project <id>`'
need 'asks y/N (default no)'
need '`brd export --all > board.json`'
need '`brd import --yes board.json`'
need 'Older one-object `brd export`'
# (d) Review Focus 1
need 'Upgrade every installed copy of brd together.'
# (e) Review Focus 2: no single-backtick form of the message
grep -qE '^`no registered project' "$f" && { echo "SINGLE-BACKTICK MESSAGE"; fail=1; }
# (f) wrap: prose lines over 72, outside fences, that are not a lone quoted message
long=$(awk '/^```/{c=!c; next} !c && length>72 && !/^`[^`].*`$/ && !/^``.*``$/ {print FNR": "$0}' "$f")
[ -z "$long" ] || { echo "LONG LINES:"; echo "$long"; fail=1; }
# (g) fences balanced
n=$(grep -c '^```' "$f"); [ $((n % 2)) -eq 0 ] || { echo "ODD FENCES: $n"; fail=1; }
# no version number for the last per-project release
grep -nE 'release[^.]*[0-9]+\.[0-9]+' "$f" && { echo "VERSION NAMED"; fail=1; }
exit $fail
CHECK
chmod +x /tmp/readme62-check.sh
```

Note on check (f): the pre-existing `## Documents` line 80 (`gone, brd serves the backup and reports it as \`missing\`. brd never writes`) is 73 columns. `## Documents` is out of scope, so the check prints it; treat exactly that one line as the only allowed failure of (f). (Task 1 does not change line numbers before line 38, but after the rewrite the Documents line moves; identify it by its text, not its number.)

- [ ] **Step 2: Run it to verify it fails**

Run: `/tmp/readme62-check.sh; echo "exit=$?"`
Expected: `exit=1`, with `HEADINGS: ## Install|## Usage|## Storage|## Documents|## For agents|` (no `###` headings yet), eleven `MISSING:` lines (e.g. `MISSING: \`master.db\``, `MISSING: Upgrade every installed copy of brd together.`), and `LONG LINES:` listing lines 68 and 73 of the old Storage section (68 is 73 columns; 73 is the 1705-character import paragraph) and the Documents line 80.

- [ ] **Step 3: Replace lines 38-73 with the new section**

Write the new section to a scratch file exactly as below (the outer four-backtick fence is not part of the content):

````bash
cat > /tmp/readme62-storage.md <<'STORAGE'
## Storage

### One database

Every project's board lives in one file, `~/.local/share/brd/brd.db`
(or `$XDG_DATA_HOME/brd/brd.db` when that is set). Document backups sit
next to it, in `docs/`. `brd init` registers the current directory in
that file and writes nothing into the repo. Nothing project-specific is
committed to git, so a board doesn't travel with a clone to another
machine; see "Moving boards between machines" below.

### Upgrading from per-project databases

Older versions of brd kept a registry, `master.db`, and one board file
per project under `projects/`. The first brd command that reads data
moves every registered project into `brd.db` at once: its cards,
issues, documents, comments and document backups, with their ids and
timestamps. Any data command does this, even one run outside a
project; `brd --help` and `brd prompt` do not.

The old files are renamed with a `.migrated` suffix and never deleted.
Once your boards look right, you can delete them by hand. The command
reports the move on stderr:

`brd: migrated N projects into brd.db (old files kept as *.migrated)`

Board files under `projects/` that `master.db` did not register are
left alone and listed in a second line:

`brd: skipped K unregistered board files: projects/<hash>.db, ...`

If the move cannot finish, for example because two boards share an id,
the command fails and names what clashed. Nothing is renamed, and the
next brd command tries again once you fix the cause. `brd purge` still
works in that state.

Upgrade every installed copy of brd together. An older brd (in another
virtualenv, or under `pipx` or `uv tool`) still reads `master.db` and
`projects/`. After the move it no longer finds those boards, and
anything it records never reaches `brd.db`.

Older versions also wrote a `.brd` marker file and added `.brd` to
`.gitignore`. brd now ignores both; delete them by hand if you like.

Boards in the very old formats that `master.db` never registered, an
in-repo `.brd/` directory or a UUID `.brd` marker, are not moved. Open
each of them once with the last release that still used per-project
databases, so that it gets registered, before you upgrade. Without
that step the upgrade cannot find them.

### Finding the project, moving a repo

A command uses the registered project whose root is the current
directory or its deepest ancestor, so it works from any subdirectory,
and nested projects are allowed: inside a nested project, its own root
wins. Outside any registered project, a data command fails with:

``no registered project at or above <dir>; run `brd init` there``

Run `brd init` there to register a new project, or `brd init --relink`
if the project already exists elsewhere. Re-running `brd init` in a
registered root keeps its id and board and only renames it (`--name`).

If you move a repo, run `brd init --relink <old-path-or-id>` in its new
location: the existing project, with its id and board, now lives at the
current directory. It takes either the project id (from `brd projects`)
or the old root path; `--name` renames it at the same time.

`brd forget` removes a project and its stored board and document
backups; it never touches files in the repo. With no argument it
removes the current project; with a path, the project registered at
exactly that path. `brd forget --project <id>` works from anywhere,
for a project whose directory is gone; `brd projects` lists the ids.
Cards in other projects that were blocked on its cards stay blocked,
showing those blockers as not-found, until the ids come back (for
example, when you import the project again).

### Moving boards between machines

To keep a durable, diffable record in git and move a board between
machines, commit a snapshot and restore from it:

```bash
brd export > docs/board/snapshot.json   # commit this
brd import docs/board/snapshot.json     # on another machine/clone
```

A snapshot is a list of project entries: each one is a project (id,
name, root path) with its cards, issues, documents, comments, tags and
refs. `brd export` writes the current project; `brd export --all`
writes every registered project and works from any directory.

`brd import` restores a snapshot, preserving the original ids, content
and timestamps, including document backups. It never writes or deletes
documents' source files in the repo; restore a missing file with
`brd doc restore <id>`.

A one-project snapshot lands in the current project. Outside any
project, the current directory is registered first (keeping the
snapshot's project id when no project has it), so no `brd init` is
needed.

A multi-project snapshot (from `brd export --all`) places each entry
in the registered project with the same id, else registers it at its
recorded root path if that directory exists; it works from any
directory. Import refuses, touching nothing, when an entry cannot be
placed.

A target project that already has entities is replaced: import prints
what it will remove and add, asks y/N (default no), then deletes that
project's cards, issues, documents and comments and loads the
snapshot's in their place. `--yes` skips the question; without a
terminal and without `--yes`, import refuses and writes nothing.

Edges from other projects into a replaced project are kept: they show
as not-found until their ids return, and reconnect when they do. Edges
to ids that are not in the database are kept and counted as not-found;
importing the missing project later reconnects them. Import refuses,
touching nothing, when an id in the snapshot belongs to a project it
is not replacing.

So `brd export --all > board.json` on one machine and
`brd import --yes board.json` on another restores every project whose
root exists, with ids, hierarchy and edges intact. Re-importing a
project's own export changes nothing. Older one-object `brd export`
snapshots and `brd tree` snapshots still import.
STORAGE
````

Then splice it in, replacing everything from the `## Storage` line up to (not including) the blank line before `## Documents`:

```bash
python3 - <<'PY'
from pathlib import Path
readme = Path("README.md")
lines = readme.read_text().split("\n")
start = lines.index("## Storage")
end = lines.index("## Documents")
assert lines[end - 1] == "", "expected a blank line before ## Documents"
new = Path("/tmp/readme62-storage.md").read_text().rstrip("\n").split("\n")
lines[start:end - 1] = new
readme.write_text("\n".join(lines))
PY
```

Why each sentence is true (for the reviewer; do not paste into the README): spec "Behaviour as built" table — `src/brd/paths.py:6-23` (location, `docs/`), `src/brd/master.py:27-67` and `src/brd/cli/_app.py:74-77` (any data command migrates; `--help`/`prompt` do not), `src/brd/consolidate.py:19,28-38,114-229` (what moves, ids kept, `.migrated` rename, notice text, skipped files), `src/brd/consolidate.py:66-112` and `src/brd/master.py:221-237` (abort, retry, purge), `src/brd/master.py:89-133` (resolution, error text, relink), `src/brd/cli/project.py:53-87` (forget), `src/brd/cli/snapshot.py:41-145` (export/import).

- [ ] **Step 4: Run the check to verify it passes**

Run: `/tmp/readme62-check.sh; echo "exit=$?"`
Expected: the only output before `exit=` is

```
LONG LINES:
<n>: gone, brd serves the backup and reports it as `missing`. brd never writes
exit=1
```

(the pre-existing 73-column `## Documents` line, out of scope). No `MISSING:`, `HEADINGS:`, `SINGLE-BACKTICK`, `ODD FENCES` or `VERSION NAMED` line. If anything else prints, fix the README text, not the check.

Also confirm nothing outside the Storage section moved:

Run: `git diff -U0 README.md | grep -E '^@@'`
Expected: hunks only at or after old line 38; none touching lines 1-37 or the `## Documents`/`## For agents` text.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "Explain the one database, the upgrade, relink and forget, and export/import in the README

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Usage lines, then full verification

**Files:**
- Modify: `README.md:28` (insert four lines after `brd projects ...`)

**Interfaces:**
- Consumes: Task 1's `README.md` (Storage section in place; lines 1-37 unchanged) and `/tmp/readme62-check.sh` (recreate it from Task 1 Step 1 if missing).
- Produces: the final `README.md`.

- [ ] **Step 1: Write the failing check**

```bash
cat > /tmp/readme62-usage.sh <<'CHECK'
#!/usr/bin/env bash
# Spec 6.2 R6: four Usage lines, '#' at column 43 like the others.
new=(
 'brd init --relink <old-path-or-id>        # after a repo moved'
 'brd forget --project <id>                 # forget a project whose directory is gone'
 'brd export --all > board.json             # snapshot every project'
 'brd import --yes board.json               # restore it on another machine'
)
fail=0
for l in "${new[@]}"; do
  grep -qxF -- "$l" README.md || { echo "MISSING: $l"; fail=1; }
done
# Existing Usage lines unchanged: the Usage section minus the four new
# lines must equal the Usage section at the card's base commit 97f9009.
usage() { awk '/^## Usage/{u=1} /^## Storage/{u=0} u'; }
diff <(usage < README.md | grep -vxF -f <(printf '%s\n' "${new[@]}")) \
     <(git show 97f9009:README.md | usage) \
  || { echo "EXISTING USAGE CHANGED"; fail=1; }
exit $fail
CHECK
chmod +x /tmp/readme62-usage.sh
```

- [ ] **Step 2: Run it to verify it fails**

Run: `/tmp/readme62-usage.sh; echo "exit=$?"`
Expected: four `MISSING:` lines, no `EXISTING USAGE CHANGED`, `exit=1`.

- [ ] **Step 3: Insert the four lines after the `brd projects` line**

Use the Edit tool on `README.md`. Replace:

```
brd projects                              # list all registered projects
```

with:

```
brd projects                              # list all registered projects
brd init --relink <old-path-or-id>        # after a repo moved
brd forget --project <id>                 # forget a project whose directory is gone
brd export --all > board.json             # snapshot every project
brd import --yes board.json               # restore it on another machine
```

Each `#` sits at column 43, like the existing lines (`brd init` + 34 spaces). Lines inside the code fence may exceed 72 columns, as existing Usage lines already do.

- [ ] **Step 4: Run both checks to verify they pass**

Run: `/tmp/readme62-usage.sh; echo "exit=$?"`
Expected: no output, `exit=0`.

Run: `/tmp/readme62-check.sh; echo "exit=$?"`
Expected: exactly the same output as Task 1 Step 4 (only the pre-existing 73-column `## Documents` line under `LONG LINES:`; `exit=1`).

- [ ] **Step 5: Fact check — every quoted message is in the source**

Run each; every command must print at least one match:

```bash
grep -nF 'brd: migrated {self.migrated} projects into brd.db ' src/brd/consolidate.py
grep -nF '(old files kept as *{SUFFIX})' src/brd/consolidate.py
grep -nF 'SUFFIX = ".migrated"' src/brd/consolidate.py
grep -nF 'brd: skipped {len(self.skipped)} unregistered board files: ' src/brd/consolidate.py
grep -nF 'no registered project at or above {resolved}; run `brd init` there' src/brd/master.py
```

Expected: matches at `src/brd/consolidate.py:30`, `:31`, `:19`, `:35` and `src/brd/master.py:95`. Joined with `N`/`K`/`<dir>` for the placeholders, they equal the README's
`brd: migrated N projects into brd.db (old files kept as *.migrated)`,
`brd: skipped K unregistered board files: projects/<hash>.db, ...` (the source joins the skipped paths, which are `projects/<hash>.db`, with `, `), and
``no registered project at or above <dir>; run `brd init` there``.

Then confirm each command and flag named in the README exists:

```bash
uv run brd init --help   | grep -F -- '--relink'
uv run brd init --help   | grep -F -- '--name'
uv run brd forget --help | grep -F -- '--project'
uv run brd export --help | grep -F -- '--all'
uv run brd import --help | grep -F -- '--yes'
uv run brd doc restore --help | grep -F 'Usage'
uv run brd projects --help | grep -F 'Usage'
uv run brd purge --help  | grep -F 'Usage'
```

Expected: each prints one or more lines.

- [ ] **Step 6: Smoke-run the README recipe in a scratch data dir**

```bash
B=$PWD
export XDG_DATA_HOME=$(mktemp -d); R=$(mktemp -d); O=$(mktemp -d)
cd "$R"
uv run --project "$B" brd init
uv run --project "$B" brd add --title x
uv run --project "$B" brd export > s.json
uv run --project "$B" brd forget
uv run --project "$B" brd import --yes s.json; echo "import rc=$?"
uv run --project "$B" brd projects
cd "$O"
uv run --project "$B" brd export --all | head -c 60; echo
uv run --project "$B" brd list; echo "list rc=$?"
cd "$B"; unset XDG_DATA_HOME
```

Expected: `import rc=0` with `"registered": true` in the import JSON; `brd projects` lists the one project with the same id `brd init` printed; `brd export --all` from `$O` prints `{"ok": true, "data": {"brd_export": 2, ...`; `brd list` prints `{"ok": false, "error": {"type": "ProjectNotFoundError", "message": "no registered project at or above /tmp/...; run `brd init` there"}}` and `list rc=1`.

- [ ] **Step 7: Full suite and diff scope**

Run: `uv run pytest -q`
Expected: all tests pass (no code changed).

Run: `git diff --stat 97f9009..HEAD -- . ':!docs/superpowers'` (after Step 8's commit) or `git diff --stat 97f9009 -- . ':!docs/superpowers'` (before it).
Expected: one line, `README.md | ...`, and the summary `1 file changed`.

Run: `git status --short`
Expected: only `README.md` (and, before the workflow commits them, the spec/plan under `docs/superpowers/`).

- [ ] **Step 8: Commit**

```bash
git add README.md
git commit -m "List brd init --relink, forget --project and export --all/import --yes in the README usage

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review against the spec

- R1 (four subsections, order, other headings kept, nothing dropped): Task 1 Step 3 content; check (a). Every fact of old lines 38-73 reappears: location/XDG and "writes nothing" (One database), subdirectory/nested resolution (Finding), relink and forget --project (Finding), `.brd` marker/`.gitignore` (Upgrading), very-old formats (Upgrading, now with which formats and why), export example, snapshot shape, every sentence of the old line 73 (Moving boards).
- R2: One database paragraph; check (b).
- R3: Upgrading subsection, every bullet; exact notice and skipped-line text; no version number (check); upgrade-every-copy paragraph.
- R4: Finding subsection, including the quoted error, re-init renames only, relink id-or-path and `--name`, forget no-arg/path/`--project`, not-found blockers.
- R5: Moving boards subsection, seven short paragraphs of at most 6 lines each, bash example kept, refusals, two-machine recipe, older snapshots.
- R6: Task 2.
- R7: checks (e), (f), (g); Task 2 Step 5 byte-for-byte checks. Quoted messages stand alone on their own lines in single (or, for the one with embedded backticks, double) backticks, rather than in a fence, because R7 reserves fences for `bash`.
- Error-path table: outside project (Finding, quoted message + `brd init`/`--relink`), repo moved (relink), directory deleted (`forget --project`, `brd projects`), migration aborts (Upgrading), older copy (Upgrading), very old formats (Upgrading), import without terminal / unplaceable / foreign id (Moving boards).
- Verification 1-5 of the spec: Task 2 Steps 7, 7, 5, Task 1 Step 4 + Task 2 Step 4, Task 2 Step 6.
- Known exception: the pre-existing 73-column line in `## Documents` (out of scope per the spec) is the one line the wrap check reports.
<!-- task-pipeline: validated -->
