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
