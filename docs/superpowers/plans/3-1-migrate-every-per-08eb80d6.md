# 3.1 Migrate every per-project board into one brd.db

Card: `08eb80d6-8a8b-4239-91f2-ba821fe66955`. It is the first subtask of story `4939dac5`
"One database". The milestone is `6aa7043a` "Single database and cross-project blocking".
No blockers. Siblings run after it in this order: 3.2 `222a1279` (resolve by deepest root,
drop the `.brd` marker), 3.3 `91e68a83` (`init --relink`, `forget --project`) and 3.4
`9da10121` (leak guard).

Parent design spec: `docs/superpowers/specs/2026-10-06-single-db-cross-project-blocking-design.md`.
It is in the main checkout (`/home/mtts/Code/brd/docs/...`), not in this branch's history.
Citations look like **[P §n Lx]**.

## Goal

Today every registered project has its own board file, `projects/<sha256(root)>.db`, and
`master.db` holds the registry. After this card, brd keeps all of them in one file,
`$XDG_DATA_HOME/brd/brd.db`. The first command that finds `master.db` and no `brd.db` runs
the migration once. After that, every command reads and writes `brd.db` only. Document
backups move to `$XDG_DATA_HOME/brd/docs/<id>.md`.

The `.brd` marker still decides which project the cwd belongs to (card text). Removing it
is card 3.2.

Apart from where the data lives, user-visible behaviour does not change. Every command
prints the same stdout and returns the same errors, with two exceptions: the one-time
notice on stderr (B4), and the migration's own failure (B5).

## Inherited constraints

| Constraint | Source |
|---|---|
| One database, `$XDG_DATA_HOME/brd/brd.db`, holding every project. `master.db` and `projects/<hash>.db` are no longer used. | [P D2 L32] |
| `brd.db` uses the v4 schema of [P §1 L48-81] at `PRAGMA user_version = 4`. It is the same schema as today's v4 board (`src/brd/db.py`), but its `projects` table holds every project. | [P §1 L45] |
| Doc backups live at `$XDG_DATA_HOME/brd/docs/<doc_id>.md`. | [P §1 L45-46] |
| The migration runs once, from any command, when `master.db` exists and `brd.db` does not. | [P §3 L127] |
| Create `brd.db`, take `BEGIN IMMEDIATE`, then re-check that the migration has not already happened. Concurrent first runs queue on the busy timeout. | [P §3 L129-130] |
| Every registered project: open `projects/<sha256(root)>.db`, upgrade it with the existing `migrate_project`, copy every row keeping ids and timestamps, copy `<hash>.docs/<id>.md` to `docs/<id>.md`. A registered project with no db file is registered empty. | [P §3 L131-134]; card text (v4, see Deviations) |
| One transaction for all projects. If an id is present in two boards, the migration aborts and names both projects and the ids. Nothing is renamed, so the next run retries. | [P §3 L135-137] |
| After commit, rename `master.db`, each migrated `*.db` and each `*.docs` with a `.migrated` suffix. Never delete them. A failed rename leaves a stray file but does not re-run the migration, because `brd.db` exists. | [P §3 L138-140] |
| Report on stderr: `brd: migrated N projects into brd.db (old files kept as *.migrated)`, plus any unregistered `projects/*.db` files that were skipped. | [P §3 L141-142] |
| Required tests: legacy boards at v0–v3, missing db file, unregistered db, duplicate id across boards (aborts, nothing renamed), concurrent first runs, doc backups moved, old files renamed. | [P Testing L259-261]; card text |
| Edge targets are still validated as same-project by code. Nothing in this card relaxes that. | [P Implementation order L279-280] |

### Deviations from the parent spec (card text wins)

- [P §3 L132] says each board is brought "to v3" and gets "a new project UUID". The card
  says to bring it to **v4** with the existing migrations. Since card 2.1, every
  registered project already has a UUID, and every v4 board records that UUID in its own
  `projects` row. The migration therefore **keeps the registry's project id**
  (`id`, `name`, `root_path`, `created_at` from `master.db`) and assigns no new ones.
- [P §3 L144-147] drops `init`'s in-repo `.brd/` directory migration and its UUID-marker
  migration. Card 3.2 does that. In this card both keep working, but they now copy into
  `brd.db` (B8).

## Terms

- **data dir**: `paths.data_dir()`, which is `$XDG_DATA_HOME/brd` or
  `~/.local/share/brd` (`src/brd/paths.py:6-11`).
- **legacy board**: `<data dir>/projects/<sha256(resolved root)>.db`, the path given by
  today's `paths.project_db_path(Path(root_path))` (`src/brd/paths.py:18-22`).
- **legacy backups**: the `<hash>.docs/` directory next to a legacy board
  (`paths.project_docs_dir`, `src/brd/paths.py:25-26`).
- **registered project**: a row of `master.db`'s `projects` table after
  `db.init_master_schema` has run. That function rebuilds a pre-id or legacy registry and
  gives each row an id (`src/brd/db.py:59-75`).
- **migrated**: `brd.db` exists and has `user_version = 4`. In this spec, "brd.db exists"
  always means migrated. An empty `brd.db` file left behind by an aborted attempt does not
  count (B5).

## Behaviour

### B1. Where data lives after this card

- New `paths.brd_db_path()` returns `<data dir>/brd.db`.
- New `paths.docs_dir()` returns `<data dir>/docs`.
- `db.docs_dir(conn)` returns the `docs` directory next to the connection's database file.
  For `brd.db` that is `paths.docs_dir()`. `documents.py:53` and `refs.py:37` keep calling
  `db.docs_dir(conn)`, so every document backup is now read from and written to
  `<data dir>/docs/<id>.md`.
- Every command that touches board data or the registry uses one connection to `brd.db`:
  every `open_project()` command, `init`, `projects` and `forget`. It looks the project up
  in `brd.db`'s `projects` table. It never opens `master.db` or a legacy board again,
  except to run the migration (B2).
- Commands that touch no data do not create or migrate anything. These are `brd prompt`,
  `--help`, and `--version` if it exists.

### B2. Opening the database (every data command except `purge`)

Run this at the start of the command. For `open_project()` that is before the `.brd`
marker is resolved, so any command on an unmigrated install migrates, even one run outside
a project:

1. If `brd.db` is migrated, use it.
2. Otherwise connect to `brd.db` (this creates the file) and take `BEGIN IMMEDIATE`. If
   another process is migrating, this waits on the busy timeout (`db.connect`,
   `timeout=10`). Once the lock is held, check again:
   - `user_version` is already 4: someone else finished. Roll back and use the file.
   - `master.db` exists: run the migration (B3) in this transaction.
   - `master.db` does not exist (fresh install): create the empty v4 schema with no
     `projects` rows, set `user_version = 4`, commit, and print nothing on stderr.
3. If the migration commits, rename the old files (B4) and print the notice (B4).

A fresh `brd.db` has the same tables, indexes and triggers as `db.migrate_project` gives
a fresh board (`tests/test_migration.py:114-127`). Its `projects` table holds every
registered project, or nothing on a fresh install.

### B3. The migration (inside the `BEGIN IMMEDIATE` transaction on `brd.db`)

1. Open `master.db` and run `db.init_master_schema` on it, which upgrades a legacy
   registry. Read the registered projects.
2. For each registered project, in `created_at` order, bring its board to v4 (no rows are
   copied yet):
   - If its legacy board file does not exist, it is "registered empty": nothing to open.
   - Otherwise open the board and run `db.migrate_project(board_conn, project)`. This
     upgrades the old file in place (the card's "existing migrations").
     If the board is at v4 but records a different project, `migrate_project` raises
     `MigrationError` (`src/brd/db.py:379-389`). That aborts the whole migration.
3. Check for duplicates before any row is copied. If an `entities.id` or `comments.id`
   appears in more than one board, abort with `MigrationError`. The message names both
   projects (by name and root path) and lists every duplicate id. A raw `IntegrityError`
   must never surface.
4. For each registered project, in `created_at` order: insert its `projects` row, then
   copy every row of `entities`, `cards`, `issues`, `documents`, `comments`, `tags`,
   `blocked_by` and `refs` unchanged: same ids, same `created_at`/`updated_at`, same
   statuses, same `project_id` columns. Insert `entities` first. Foreign keys are on and
   immediate on this connection, and a child card may come before its parent in the old
   board's row order. So either insert cards parents-first, or run
   `PRAGMA defer_foreign_keys = ON` inside the transaction so the check happens at commit
   (see step 5). Registered-empty projects get only the `projects` row.
5. After all inserts, `PRAGMA foreign_key_check` on `brd.db` must be empty. Otherwise
   abort with `MigrationError`, as `migrate_project` does at `src/brd/db.py:398-402`.
6. Copy every `*.md` file in each migrated project's legacy backups to
   `<data dir>/docs/<same name>`, overwriting a file of the same name. Create
   `<data dir>/docs` if needed. A missing legacy backups directory is not an error.
7. Set `user_version = 4` and commit.

**Unregistered board files** are `projects/*.db` files whose path is not the legacy board
of any registered project. This includes `<legacy-uuid>.db` files left from the oldest
format. They are not opened, not copied and not renamed. A `*.docs` directory whose board
is unregistered is also left alone.

### B4. After commit: renames and notice

- Rename `master.db` to `master.db.migrated`. Rename each migrated legacy board
  `<hash>.db` to `<hash>.db.migrated`. Rename each legacy backups directory `<hash>.docs`
  to `<hash>.docs.migrated`. Close every connection to a file before renaming it.
- If a `-wal` or `-shm` sidecar of a renamed database is still present, rename it to go
  with the new name: `master.db-wal` becomes `master.db.migrated-wal`. This keeps the
  `.migrated` file openable with all of its data.
- Never delete a file. If a rename fails (`OSError`), ignore it and carry on with the
  rest. The migration has committed and is not re-run, because `brd.db` is migrated.
- Unregistered files are not renamed.
- Write the notice to **stderr**, never to stdout, so stdout stays one JSON envelope:

  ```
  brd: migrated N projects into brd.db (old files kept as *.migrated)
  ```

  `N` counts every registered project, including empty ones (`0` is allowed). If any
  unregistered board files were skipped, add one more line:

  ```
  brd: skipped K unregistered board files: projects/<a>.db, projects/<b>.db
  ```

  List the names in sorted order. Only the process that performed the migration prints
  the notice. Later runs, and concurrent runs that found the work already done, print
  nothing extra.
- The command then runs as usual on `brd.db`. Its stdout and exit code are what they would
  be on an already-migrated install.

### B5. Abort

The migration aborts on any of these:

- a duplicate id (B3.3);
- a board/registry mismatch (B3.2);
- a foreign key violation (B3.5);
- a legacy board file that cannot be read as SQLite.

For the last one, the `sqlite3.DatabaseError` is wrapped in a `MigrationError` that names
the project and the file.

When it aborts:

- The `brd.db` transaction rolls back. `brd.db` may remain as a file, but it has
  `user_version = 0`, no tables and no rows. Do not delete it: another process may be
  waiting on its lock. The next command sees it as not migrated and retries (B2).
- Nothing is renamed. `master.db`, every legacy board and every `*.docs` directory keep
  their names. A legacy board may have been upgraded in place to v4 by `migrate_project`.
  That is allowed, and a later retry is idempotent.
- No file in `<data dir>/docs` that existed before the attempt is changed. Duplicate and
  mismatch checks come before any doc is copied (B3.2, B3.3, B3.5 precede B3.6). If a later step fails, remove the docs
  this attempt copied.
- The command fails with the normal error envelope: `{"ok": false, "error": {"type":
  "MigrationError", ...}}` on stdout, exit code 1. No notice is printed.

### B6. Concurrent first runs

Several processes or threads may start a command at the same moment on an unmigrated
install. All of them succeed. The migration runs exactly once:

- the rows in `brd.db` are not duplicated;
- exactly one notice is printed in total;
- `master.db.migrated` exists and `master.db` does not.

A process that read "not migrated" before the winner committed waits on the lock. Its
re-check (B2.2) then finds `user_version = 4`.

### B7. Project registry commands on `brd.db`

- `brd init` (`master.init_project`): upserts the project into `brd.db`'s `projects`
  table, with the same id-keeping and rename-only-the-name semantics as today
  (`db.upsert_project`). It still writes the `.brd` marker and the `.gitignore` line,
  which card 3.2 removes. It no longer creates a legacy board file. It no longer recovers
  a project id from a stray legacy board (`master._board_project` / `_settle_project`
  fallback). The only registry is `brd.db`.
- `init`, `projects` and `forget` must turn a `BrdError` raised while opening the database
  (e.g. `MigrationError`) into the error envelope and exit 1, like `run()` does; today
  `init` and `projects` have no such handler.
- `brd projects` lists the `projects` rows of `brd.db`, in the same shape as today.
- `brd forget [PATH]` (PATH defaults to the cwd, matched against `root_path` exactly, as
  today): deletes that project's `projects` row in `brd.db`. The cascade through `entities` removes everything the
  project owns. It also deletes `<data dir>/docs/<id>.md` for each of the project's
  documents (read the document ids before the row is deleted, because the cascade removes
  them) and removes the `.brd` marker at `PATH` if present. Other projects' rows and backups are
  untouched. It returns the forgotten project, as today. If the root is not registered,
  it raises `ProjectNotFoundError`, as today. Card 3.3 adds `--project`.
- `brd purge`: does **not** run the migration, because it is the escape hatch when a
  migration aborts. Both its confirmation prompt and its result use a non-migrating
  count (the CLI today calls `list_all_projects()` first, which must not be used here). It counts registered projects from `brd.db` if it is migrated, else
  from `master.db` if it exists, else 0. Then it removes the whole data dir, as today,
  `.migrated` files included.
- `open_project()` (`src/brd/cli/_app.py:64-73`): resolves the root through the marker as
  today, then looks the project up in `brd.db`. If it is not registered, it raises
  `ProjectNotFoundError` with today's message (`master.py:190-194`). `Ctx.conn` is the
  `brd.db` connection. If anything fails after the connection opens, the connection is
  closed (`tests/test_cli_app.py:118` behaviour stays).

### B8. Legacy in-repo formats during `init` (kept until 3.2)

`master._migrate_in_repo_format` (`.brd/` directory with a `board.db`) and
`_migrate_legacy_uuid_marker` (a `.brd` file holding a UUID that points at
`projects/<uuid>.db`) keep their current behaviour. The difference is that `_copy_cards`
now inserts the copied cards (after the project's `projects` row has been upserted into
`brd.db`, since `entities.project_id` has a foreign key; via `db.insert_entity`, under the project's id) and the
edges between copied cards into `brd.db`, instead of into a per-project board.

## Out of scope

- Resolving the project by the deepest registered root, and dropping the marker,
  `find_marker`, the `.gitignore` edit and the legacy init migrations: card **3.2**.
- `init --relink`, `forget --project`, and removing a forgotten project's backups by
  project id when its directory is gone: card **3.3**. In this card, `forget` keeps
  today's command-line surface.
- The leak-guard test, and scoping changes to listings: card **3.4**. The 2.x cards
  already scope queries by `project_id`.
- Cross-project edges, not-found blockers, `blockers` output, and `forget` keeping
  incoming edges: story S4 / phase 3 [P Implementation order L281-283].
- Export/import v2: phase 4.
- Release notes for very old formats [P §3 L146-147].
- Adopting an unregistered legacy board when a later `brd init` runs in its root. The
  board stays where it is and is ignored.
- Id collisions between a legacy `.brd` UUID-marker board and other projects already in
  `brd.db` during `init` (B8). This is pre-existing, and the ids are UUIDs.

## Tests

The suite uses two tiers. Both are plain pytest in the flat `tests/` dir, with no markers.

- **Unit**: calls `master`/`db`/`paths` functions directly, with
  `monkeypatch.setenv("XDG_DATA_HOME", ...)` and `tmp_path`. Use it where the behaviour
  is a property of the files on disk, so the test can set up legacy files exactly and
  inspect them afterwards.
- **CLI**: `tests/cli_helpers.invoke/ok/err` through Typer's `CliRunner`. Use it where
  the behaviour is something a user sees: stdout envelope, stderr notice, exit code.
  `CliRunner` in the installed Typer 0.27 keeps `result.stdout` and `result.stderr`
  apart (checked), so tests can assert on both.

Build legacy boards with the real historical migrations, as
`tests/test_migration.py:_make_v0` (L32) and `_make_v3` (L76) do, plus
`_make_v1`/`_make_v2_without_archived` (L249, L257) for v1 and v2. A v4 legacy board is
`db.connect(paths.project_db_path(root))` followed by `db.migrate_project(conn, project)`
and factory inserts. Register legacy projects by writing `master.db` through
`db.connect(paths.master_db_path())`, `db.init_master_schema` and `db.upsert_project`.
Shared builders for these legacy layouts go in a helper in the new test file, not in
`factories.py`.

New file: `tests/test_single_db_migration.py`, one module, for B2–B6.

| # | Test | Tier | Why this tier |
|---|---|---|---|
| T1 | Three registered projects whose boards are at v0, v2 and v3, plus one at v4 with an issue, a document (with a backup file), a comment, a tag, a ref and a `blocked_by` edge. After the migration, `brd.db` has `user_version` 4 and one `projects` row per registry row, with the registry's id, name, root_path and created_at. Every row of every table is present with unchanged ids and timestamps, and `entities.project_id` is the owning project. | unit | Row-exact comparison against files built on disk. |
| T2 | A registered project with no board file ends up as a `projects` row in `brd.db` with no entities, and N counts it. | unit | Pure file-layout condition. |
| T3 | An unregistered `projects/<x>.db` (and `<x>.docs/`) is not copied and keeps its name. The stderr notice has the `skipped 1 unregistered board files: projects/<x>.db` line. | CLI | The notice is user-facing stderr. |
| T4 | Two boards share a card id, and a comment id appears in two boards. The command fails with a `MigrationError` envelope, exit 1. The message has both project names and every duplicate id. `master.db`, both boards and their `.docs` dirs keep their names. `brd.db` is absent or has `user_version` 0 and no tables. `<data dir>/docs` has no new files. A second run after the duplicate is removed from one board succeeds. | CLI | Error envelope, plus the retry a user would do. |
| T5 | A v4 legacy board recording a different project id than the registry aborts the same way (`MigrationError`, nothing renamed). | unit | Error path of the core function. |
| T6 | A legacy board file that is not SQLite (random bytes) aborts with `MigrationError` naming the project. No traceback. | CLI | The user would otherwise see a raw stack trace. |
| T7 | Concurrent first runs: 4 threads behind a `threading.Barrier` each open the database (the B2 entry point) on an unmigrated install with two boards. Repeat 5 times, as in `tests/test_migration.py:203`. There are no errors, rows are not duplicated, `master.db.migrated` exists and `master.db` does not, and the notice was emitted exactly once (count by capturing what each call reports, or with `capsys`). | unit | Threads need direct function calls; CliRunner is not thread-safe. |
| T8 | Doc backups moved: `<hash>.docs/<id>.md` contents appear at `<data dir>/docs/<id>.md`, and after the migration `brd show <doc-id>` / `brd doc` restore reads them. | unit + CLI | File move (unit), plus proof that commands read the new location (CLI). |
| T9 | Old files renamed: `master.db.migrated`, `<hash>.db.migrated` and `<hash>.docs.migrated` exist; none of the originals do. `master.db.migrated` still opens and lists the registry rows. | unit | Pure file-layout condition. |
| T10 | A rename that fails (monkeypatch `Path.rename` to raise for one board) does not fail the command. The next command does not migrate again: no notice, and the row count is unchanged. | unit | Fault injection on the file system. |
| T11 | The notice goes to stderr only. On the migrating run, `result.stdout` parses as the normal JSON envelope of the command (e.g. `brd list`), and `result.stderr` starts with `brd: migrated 2 projects into brd.db (old files kept as *.migrated)`. The next run has empty stderr. | CLI | User-visible streams. |
| T12 | Fresh install (no `master.db`, no `brd.db`): `brd init` creates `brd.db` at v4, prints no notice, and creates no `master.db` and no `projects/` dir. | CLI | The first experience of a new user. |
| T13 | `master.db` exists but is empty or legacy-shaped (pre-id) with a board: the migration upgrades the registry via `init_master_schema` and migrates. With zero rows, the notice says `migrated 0 projects` and `master.db` is still renamed. | unit | Registry edge cases. |
| T14 | `brd purge` on an unmigrated install whose migration would abort (a duplicate id) succeeds, reports the registry count, and removes the data dir. | CLI | The escape hatch must work from the command line. |
| T15 | `brd forget` removes only the cwd project's rows and its `docs/<id>.md` backups from `brd.db`. A second project's cards and backups survive. | CLI | User-visible command, in the new layout. |
| T16 | Running `brd init` again in a registered root keeps the id and created_at in `brd.db`, and the project's cards survive. Two roots get distinct ids. | unit | Reworked from `tests/test_master.py:46,286,303`. |

### Existing tests that must change (layout moves; behaviour asserted stays the same)

- `tests/test_paths.py:21-52`: keep the `master_db_path`/`project_db_path` tests, since
  these paths are legacy inputs the migration still reads. Add `brd_db_path` and
  `docs_dir` tests.
- `tests/test_master.py`: these tests read `paths.project_db_path(repo)`. They must read
  `brd.db` instead (L11, L46, L82, L113, L161-169, L192, L217, L259, L343).
  `test_resolve_project_db_*` move to whatever replaces `resolve_project_db`, or are
  deleted along with it if nothing in `src` still calls it. Delete
  `test_init_project_board_row_matches_registry` (L376), because the board-recovery
  fallback is gone (B7). Replace its intent with T16.
- `tests/test_migration.py:191-200`: `docs_dir` now sits as `docs/` next to the db. Keep
  `project_docs_dir` (a legacy path) as it is.
- `tests/test_cli_app.py:19-50` (`test_commands_migrate_a_v0_board`): it now proves that a
  v0 legacy board is migrated into `brd.db` by `brd list`. L115: assert that `brd.db`
  holds no project row for the unregistered marker repo, instead of asserting that a
  legacy board file does not exist.
- `tests/test_snapshot.py:135,170,220`: backups are at `paths.docs_dir() / f"{id}.md"`.
- `tests/test_cli.py:59,127,760,777,915`: they open `brd.db` (`paths.brd_db_path()`)
  instead of the legacy board. L59/L127 assert the project row in `brd.db` instead of the
  board file.
- `tests/conftest.py` `pconn` and `tests/factories.py:59`: unchanged. `db.docs_dir` now
  points at `tmp_path/docs`.

The full suite (`uv run pytest`, 577 passing at baseline) stays green. No lint or
typecheck is configured.

## Interfaces handed to the planner

These are names only. The plan fixes the signatures.

- `paths.brd_db_path() -> Path`, `paths.docs_dir() -> Path`.
- One entry point, used by `master.*` and `cli._app.open_project`, that returns a
  migrated `brd.db` connection. Suggested name: `master.connect() -> sqlite3.Connection`,
  replacing `master._master_conn`. It reports the notice through a callback or by
  returning it, so T7 can count it without parsing stderr.
- The migration itself in a new module `src/brd/consolidate.py`. This keeps `master.py`
  focused, and the story owns that module. It is called only from the entry point, with
  the open `brd.db` connection already inside `BEGIN IMMEDIATE`.
- `db.init_brd_schema(conn)`: creates the empty v4 schema with no `projects` row. It
  shares the v4 DDL with `migrate_project`, so the two cannot drift.

---

# 3.1 Migrate every per-project board into one brd.db — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep every project's board data in one file, `$XDG_DATA_HOME/brd/brd.db`. The first command that finds `master.db` and no migrated `brd.db` migrates all registered legacy boards into it, once.

**Architecture:** A new module `src/brd/consolidate.py` copies the registry and every registered legacy board into `brd.db` in one transaction, then renames the old files with a `.migrated` suffix. A new entry point, `master.connect()`, returns a migrated `brd.db` connection. Every data command (`open_project`, `init`, `projects`, `forget`) opens the database only through it. `db.init_brd_schema` builds the empty v4 schema by running the same migrations a fresh board runs, so the two schemas cannot drift.

**Tech Stack:** Python ≥3.12, stdlib `sqlite3`, Typer 0.27 (CLI), pytest (run with `uv run pytest`).

**Spec:** `docs/superpowers/specs/3-1-migrate-every-per-08eb80d6.md`. It is reproduced above this line; executors read both.

## Global Constraints

- One database: `$XDG_DATA_HOME/brd/brd.db` (`paths.brd_db_path()`). Its schema is v4, `PRAGMA user_version = 4` (`db.SCHEMA_VERSION`).
- Doc backups: `$XDG_DATA_HOME/brd/docs/<doc_id>.md` (`paths.docs_dir()`).
- The migration runs once, from any data command, when `master.db` exists and `brd.db` is not migrated (`user_version` < 4).
- Notice, on **stderr** only, printed only by the process that migrated, exact text: `brd: migrated N projects into brd.db (old files kept as *.migrated)`. If files were skipped, a second line follows: `brd: skipped K unregistered board files: projects/<a>.db, projects/<b>.db` (names sorted).
- Never delete an old file. Rename it with the `.migrated` suffix. A failed rename (`OSError`) is ignored.
- If the migration aborts: nothing is renamed, `brd.db` is left at `user_version = 0` with no tables, no pre-existing file in `docs/` changes, and the command prints `{"ok": false, "error": {"type": "MigrationError", ...}}` and exits 1.
- `brd purge` never migrates.
- `brd prompt` and `--help` never create or migrate anything.
- The `.brd` marker and the legacy in-repo `init` migrations stay (card 3.2 removes them).
- Edge targets stay same-project; nothing here relaxes that.
- No new dependencies. No lint or typecheck is configured. The full suite (`uv run pytest`, 577 passing at baseline) must be green at the end of every task.
- Every git commit ends with the trailer line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

These are inputs the spec implies but its test list does not exercise. Each line says what a user would reasonably expect, most likely first. Each one has a test in the task named.

1. **A command run outside any project on an unmigrated install** (e.g. `brd list` in `~`) still migrates (stderr notice, `master.db.migrated` exists) and then fails with `ProjectNotFoundError`. Task 6.
2. **Two first runs on a brand-new machine** (no `master.db`, no `brd.db`) both succeed. Switching a brand-new file to WAL fails right away with "database is locked" under contention; this was reproduced while planning. Task 4 (`db.connect` retries the WAL switch).
3. **A legacy board that stores a child card before its parent** (row order) still migrates with its `parent_id` intact. Task 2.
4. **`brd init` re-run in a registered root on an unmigrated install** keeps the registry's id and `created_at`, and the project's cards stay under that id. Task 5.
5. **`brd prompt` / `--help` / `brd doc --help` on an unmigrated install** create no `brd.db` and leave `master.db` in place. Task 6.

## Known consequence (not a regression to fix here)

All projects of one install now share `brd.db`, so entity ids are unique across the install. Exporting project A and importing that snapshot into project B **on the same install** now fails with `EntityAlreadyExistsError`, because the ids already exist. Export/import v2 (phase 4) handles placement. The snapshot round-trip tests in `tests/test_snapshot.py` and `tests/test_cli.py` model a second machine, so Task 5 gives their "fresh project" its own data dir. Unscoped `export` queries for comments/tags/refs are card 3.4's leak guard and are not touched here.

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `src/brd/paths.py` | add `brd_db_path()`, `docs_dir()` | 1 |
| `src/brd/db.py` | `init_brd_schema`; `_migrate_to_v4` accepts `project=None`; `connect` retries the WAL switch; `docs_dir` → `docs/` next to the db | 1, 4, 5 |
| `src/brd/consolidate.py` (new) | the one-time migration: `migrate(conn) -> Report`, `retire(old_files)`, `Report`, `TABLES` | 2, 3, 4 |
| `src/brd/master.py` | `connect(notify)` entry point; registry functions on `brd.db`; `registry_count()`; legacy in-repo copies into `brd.db` | 2, 5 |
| `src/brd/cli/_app.py` | `open_project` uses `master.connect()` | 5 |
| `src/brd/cli/project.py` | `init`/`projects` error envelopes; `purge` uses `registry_count()` | 5, 6 |
| `tests/test_single_db_migration.py` (new) | B2–B6 tests, legacy-layout builders | 2, 3, 4, 5, 6 |
| `tests/test_paths.py`, `tests/test_migration.py`, `tests/test_db.py` | path, schema, docs_dir, WAL-race tests | 1, 4, 5 |
| `tests/test_master.py`, `tests/test_cli_app.py`, `tests/test_cli.py`, `tests/test_snapshot.py` | existing tests moved to the new layout | 5 |

---

### Task 1: New paths and the empty brd.db schema

**Files:**
- Modify: `src/brd/paths.py` (append after `master_db_path`, L14-15)
- Modify: `src/brd/db.py:353-386` (`_migrate_to_v4`), and add `init_brd_schema` after `init_project_schema` (L432-433)
- Test: `tests/test_paths.py`, `tests/test_migration.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `paths.brd_db_path() -> Path`: returns `data_dir() / "brd.db"`.
  - `paths.docs_dir() -> Path`: returns `data_dir() / "docs"`. It does **not** create the directory.
  - `db.init_brd_schema(conn: sqlite3.Connection) -> None`: builds every v4 table, index and trigger with no `projects` row. It runs inside the caller's transaction (the caller has foreign keys off and holds `BEGIN IMMEDIATE`), does not set `user_version` and does not commit.
  - `db._migrate_to_v4(conn, project: Project | None)`: when `project` is `None`, inserts no `projects` row.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_paths.py`:

```python
def test_brd_db_path(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.brd_db_path() == tmp_path / "brd" / "brd.db"


def test_docs_dir_sits_in_the_data_dir_and_is_not_created(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.docs_dir() == tmp_path / "brd" / "docs"
    assert not paths.docs_dir().exists()
```

Append to `tests/test_migration.py`:

```python
def test_brd_schema_matches_a_fresh_board_without_its_project(tmp_path):
    board = db.connect(tmp_path / "board.db")
    db.migrate_project(board, PROJECT)
    brd = db.connect(tmp_path / "brd.db")
    brd.execute("PRAGMA foreign_keys=OFF")
    brd.execute("BEGIN IMMEDIATE")
    db.init_brd_schema(brd)
    brd.commit()

    query = "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
    assert [tuple(r) for r in brd.execute(query)] == [tuple(r) for r in board.execute(query)]
    assert _rows(brd, "projects") == []
    # The caller sets the version once its own work is done.
    assert brd.execute("PRAGMA user_version").fetchone()[0] == 0
    board.close()
    brd.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_paths.py tests/test_migration.py -q`
Expected: 3 failures: `AttributeError: module 'brd.paths' has no attribute 'brd_db_path'`, `... no attribute 'docs_dir'`, and `AttributeError: module 'brd.db' has no attribute 'init_brd_schema'`.

- [ ] **Step 3: Implement the paths**

In `src/brd/paths.py`, insert after `master_db_path` (after L15):

```python
def brd_db_path() -> Path:
    return data_dir() / "brd.db"


def docs_dir() -> Path:
    return data_dir() / "docs"
```

- [ ] **Step 4: Implement `init_brd_schema`**

In `src/brd/db.py`, replace the start of `_migrate_to_v4` (the signature through the `_rebuild_table(conn, "entities", ...)` call, L353-368):

```python
def _migrate_to_v4(conn: sqlite3.Connection, project: Project) -> None:
    # Drop the register triggers first: ALTER TABLE RENAME re-parses every
    # trigger, and their INSERT INTO entities would break the rebuilds.
    for table, _ in _ENTITY_KINDS:
        conn.execute(f"DROP TRIGGER IF EXISTS {table}_register_entity")
    # A legacy board may carry a stray projects table; the board's own row
    # replaces it.
    conn.execute("DROP TABLE IF EXISTS projects")
    conn.execute(_PROJECTS_SQL.format(name="projects"))
    conn.execute(
        "INSERT INTO projects (id, name, root_path, created_at) VALUES (?, ?, ?, ?)",
        (project.id, project.name, project.root_path, project.created_at),
    )
    _rebuild_table(
        conn, "entities", _ENTITIES_SQL, "id, kind, project_id", "id, kind, ?", (project.id,)
    )
    _rebuild_table(
        conn,
        "documents",
        _DOCUMENTS_SQL,
        f"id, project_id, {_DOCUMENT_COLUMNS}",
        f"id, ?, {_DOCUMENT_COLUMNS}",
        (project.id,),
    )
```

with:

```python
def _migrate_to_v4(conn: sqlite3.Connection, project: Project | None) -> None:
    # Drop the register triggers first: ALTER TABLE RENAME re-parses every
    # trigger, and their INSERT INTO entities would break the rebuilds.
    for table, _ in _ENTITY_KINDS:
        conn.execute(f"DROP TRIGGER IF EXISTS {table}_register_entity")
    # A legacy board may carry a stray projects table; the board's own row
    # replaces it.
    conn.execute("DROP TABLE IF EXISTS projects")
    conn.execute(_PROJECTS_SQL.format(name="projects"))
    # No project: brd.db's empty schema, with no rows to stamp.
    project_id = project.id if project is not None else None
    if project is not None:
        conn.execute(
            "INSERT INTO projects (id, name, root_path, created_at) VALUES (?, ?, ?, ?)",
            (project.id, project.name, project.root_path, project.created_at),
        )
    _rebuild_table(
        conn, "entities", _ENTITIES_SQL, "id, kind, project_id", "id, kind, ?", (project_id,)
    )
    _rebuild_table(
        conn,
        "documents",
        _DOCUMENTS_SQL,
        f"id, project_id, {_DOCUMENT_COLUMNS}",
        f"id, ?, {_DOCUMENT_COLUMNS}",
        (project_id,),
    )
```

(The rest of `_migrate_to_v4`, from the `blocked_by` rebuild on, is unchanged.)

Then insert after `init_project_schema` (after L433):

```python
def init_brd_schema(conn: sqlite3.Connection) -> None:
    """Build brd.db's empty v4 schema: the migrations a fresh board runs, so
    the two cannot drift, but with no projects row. Runs inside the caller's
    transaction with foreign keys off, as migrate_project runs them; the
    caller sets user_version and commits."""
    _migrate_to_v1(conn)
    _migrate_to_v2(conn)
    _migrate_to_v3(conn)
    _migrate_to_v4(conn, None)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_paths.py tests/test_migration.py -q`
Expected: all pass.

Run: `uv run pytest -q`
Expected: 580 passed.

- [ ] **Step 6: Commit**

```bash
git add src/brd/paths.py src/brd/db.py tests/test_paths.py tests/test_migration.py
git commit -m "Add brd.db and docs paths and the empty brd.db schema

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The migration: legacy boards into brd.db, old files renamed, notice

**Files:**
- Create: `src/brd/consolidate.py`
- Modify: `src/brd/master.py` (imports at L1-7; add `connect` and helpers after `_now`, L11-13)
- Create: `tests/test_single_db_migration.py`

**Interfaces:**
- Consumes: `paths.brd_db_path()`, `paths.docs_dir()`, `db.init_brd_schema(conn)` (Task 1); existing `paths.master_db_path()`, `paths.project_db_path(Path)`, `paths.project_docs_dir(Path)`, `db.connect`, `db.init_master_schema`, `db.list_projects`, `db.migrate_project`, `db.SCHEMA_VERSION`.
- Produces:
  - `consolidate.TABLES: tuple[str, ...]` = `("entities", "cards", "issues", "documents", "comments", "tags", "blocked_by", "refs")`.
  - `consolidate.SUFFIX = ".migrated"`.
  - `consolidate.Report` dataclass: `migrated: int`, `skipped: list[str]` (sorted `"projects/<name>.db"`), `retired: list[Path]`. Method `notice() -> str` returns one or two lines joined by `"\n"`, with no trailing newline.
  - `consolidate.migrate(conn: sqlite3.Connection) -> Report`. `conn` is `brd.db`, inside `BEGIN IMMEDIATE` with foreign keys off. Commits on success. On failure it raises and leaves the rollback to the caller.
  - `consolidate.retire(old_files: list[Path]) -> None`: renames each path to `<name>.migrated`.
  - `master.connect(notify: Callable[[str], None] = _to_stderr) -> sqlite3.Connection`: the B2 entry point. It returns an open, migrated `brd.db` connection with foreign keys on. `notify` is called once with `Report.notice()`, and only by the call that migrated. It closes the connection before re-raising any error.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_single_db_migration.py`:

```python
import sqlite3
from pathlib import Path

import pytest

from brd import db, master, paths
from brd.models import Project
from tests.factories import NOW, make_card, make_issue
from tests.test_migration import INSERT_CARD, _make_v0, _make_v2_without_archived, _make_v3

TABLES = ("entities", "cards", "issues", "documents", "comments", "tags", "blocked_by", "refs")
NOTICE = "brd: migrated {n} projects into brd.db (old files kept as *.migrated)"


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    return tmp_path / "data" / "brd"


def register(base: Path, name: str, created_at: str = "2026-01-01T00:00:00+00:00") -> Project:
    """Register base/name in master.db, the way brd did before brd.db."""
    root = base / name
    root.mkdir(parents=True)
    conn = db.connect(paths.master_db_path())
    try:
        db.init_master_schema(conn)
        return db.upsert_project(
            conn, Project(id=db.new_project_id(), name=name, root_path=str(root), created_at=created_at)
        )
    finally:
        conn.close()


def board_path(project: Project) -> Path:
    return paths.project_db_path(Path(project.root_path))


def backups_path(project: Project) -> Path:
    return paths.project_docs_dir(Path(project.root_path))


def migrated(path: Path) -> Path:
    return path.with_name(path.name + ".migrated")


def v4_board(project: Project) -> sqlite3.Connection:
    conn = db.connect(board_path(project))
    db.migrate_project(conn, project)
    return conn


def add_document(conn, project: Project, doc_id: str, stem: str, content: str) -> None:
    """A document row on a legacy board plus its backup in <hash>.docs/.
    (factories.make_document would put the backup next to the db file.)"""
    with conn:
        db.insert_entity(conn, project.id, doc_id, "document")
        conn.execute(
            "INSERT INTO documents (id, project_id, title, source_path, stem, content_hash, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (doc_id, project.id, stem, f"docs/{stem}.md", stem, "0" * 64, NOW, NOW),
        )
    backups = backups_path(project)
    backups.mkdir(parents=True, exist_ok=True)
    (backups / f"{doc_id}.md").write_text(content)


def rows(conn, table: str, columns: str = "*") -> list[tuple]:
    return sorted(tuple(r) for r in conn.execute(f"SELECT {columns} FROM {table}"))


def open_brd():
    """master.connect, with the notices it reports collected."""
    notices: list[str] = []
    conn = master.connect(notify=notices.append)
    return conn, notices


def seed_four_versions(base: Path) -> list[Project]:
    """Registered projects whose boards sit at v0, v2, v3 and v4. The v4 one
    holds a parent/child pair, an issue, a document with its backup, a
    comment, a tag, a ref and a blocked_by edge."""
    v0 = register(base, "v0", "2026-01-01T00:00:00+00:00")
    _make_v0(board_path(v0), cards=[("a-p", None), ("a-c", "a-p")], edges=[("a-c", "a-p")])

    v2 = register(base, "v2", "2026-01-02T00:00:00+00:00")
    _make_v2_without_archived(board_path(v2))
    legacy = sqlite3.connect(board_path(v2))
    legacy.execute(INSERT_CARD, ("b-1", "B", None))
    legacy.commit()
    legacy.close()

    v3 = register(base, "v3", "2026-01-03T00:00:00+00:00")
    _make_v3(board_path(v3))

    v4 = register(base, "v4", "2026-01-04T00:00:00+00:00")
    conn = v4_board(v4)
    make_card(conn, "d-card", project_id=v4.id)
    make_card(conn, "d-child", parent_id="d-card", project_id=v4.id)
    make_issue(conn, "d-issue", project_id=v4.id)
    add_document(conn, v4, "d-doc", "notes", "# Notes\n")
    conn.execute(
        "INSERT INTO comments (id, entity_id, author, body, created_at) "
        "VALUES ('d-comment', 'd-card', 'me', 'hi', ?)",
        (NOW,),
    )
    conn.execute("INSERT INTO tags (entity_id, tag) VALUES ('d-doc', 'design')")
    conn.execute("INSERT INTO refs (src_id, dst_id, origin) VALUES ('d-card', 'd-doc', 'explicit')")
    conn.execute("INSERT INTO blocked_by (card_id, blocks_on_id) VALUES ('d-child', 'd-issue')")
    conn.commit()
    conn.close()
    return [v0, v2, v3, v4]


def test_boards_at_v0_v2_v3_and_v4_move_into_brd_db_unchanged(data, tmp_path):
    projects = seed_four_versions(tmp_path)

    conn, notices = open_brd()
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert rows(conn, "projects") == sorted(
            (p.id, p.name, p.root_path, p.created_at) for p in projects
        )
        # Each board was upgraded in place, then copied; the renamed file is
        # that upgraded board, so brd.db must hold exactly the union of them.
        boards = [sqlite3.connect(migrated(board_path(p))) for p in projects]
        try:
            for table in TABLES:
                expected = sorted(row for board in boards for row in rows(board, table))
                assert rows(conn, table) == expected, table
        finally:
            for board in boards:
                board.close()
        v0, v2, v3, v4 = projects
        owners = dict(rows(conn, "entities", "id, project_id"))
        assert (owners["a-p"], owners["b-1"], owners["p"], owners["d-card"]) == (
            v0.id, v2.id, v3.id, v4.id,
        )
        assert tuple(
            conn.execute("SELECT created_at, updated_at FROM cards WHERE id = 'a-p'").fetchone()
        ) == ("now", "now")
        assert tuple(
            conn.execute("SELECT created_at, updated_at FROM cards WHERE id = 'd-card'").fetchone()
        ) == (NOW, NOW)
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()
    assert notices == [NOTICE.format(n=4)]


def test_registered_project_without_a_board_is_registered_empty(data, tmp_path):
    empty = register(tmp_path, "empty")

    conn, notices = open_brd()
    try:
        assert rows(conn, "projects") == [(empty.id, "empty", empty.root_path, empty.created_at)]
        assert rows(conn, "entities") == []
    finally:
        conn.close()
    assert notices == [NOTICE.format(n=1)]


def test_unregistered_board_files_are_left_alone(data, tmp_path):
    kept = register(tmp_path, "kept")
    conn = v4_board(kept)
    make_card(conn, "k-1", project_id=kept.id)
    conn.close()
    stray = data / "projects" / "stray.db"
    _make_v0(stray, cards=[("s-1", None)], edges=[])
    legacy_uuid = data / "projects" / "07a7d240-444a-4b71-b585-b5bc7b50fdf3.db"
    _make_v0(legacy_uuid, cards=[("u-1", None)], edges=[])
    (data / "projects" / "stray.docs").mkdir()
    (data / "projects" / "stray.docs" / "x.md").write_text("stray")

    conn, notices = open_brd()
    try:
        assert rows(conn, "cards", "id") == [("k-1",)]
    finally:
        conn.close()
    for path in (stray, legacy_uuid, data / "projects" / "stray.docs"):
        assert path.exists() and not migrated(path).exists()
    assert not (data / "docs" / "x.md").exists()
    assert notices == [
        NOTICE.format(n=1)
        + "\nbrd: skipped 2 unregistered board files: "
        "projects/07a7d240-444a-4b71-b585-b5bc7b50fdf3.db, projects/stray.db"
    ]


def test_document_backups_move_to_the_shared_docs_dir(data, tmp_path):
    owner = register(tmp_path, "owner")
    conn = v4_board(owner)
    add_document(conn, owner, "doc-1", "notes", "# Notes\n")
    conn.close()

    brd, _ = open_brd()
    brd.close()

    assert (paths.docs_dir() / "doc-1.md").read_text() == "# Notes\n"
    assert (migrated(backups_path(owner)) / "doc-1.md").read_text() == "# Notes\n"


def test_old_files_are_renamed_never_deleted(data, tmp_path):
    owner = register(tmp_path, "owner")
    conn = v4_board(owner)
    add_document(conn, owner, "doc-1", "notes", "x")
    conn.close()

    brd, _ = open_brd()
    brd.close()

    for path in (paths.master_db_path(), board_path(owner), backups_path(owner)):
        assert not path.exists(), path
        assert migrated(path).exists(), path
    registry = sqlite3.connect(migrated(paths.master_db_path()))
    try:
        assert [tuple(r) for r in registry.execute("SELECT id, root_path FROM projects")] == [
            (owner.id, owner.root_path)
        ]
    finally:
        registry.close()


def test_empty_registry_migrates_zero_projects(data):
    conn = db.connect(paths.master_db_path())
    db.init_master_schema(conn)
    conn.close()

    brd, notices = open_brd()
    try:
        assert rows(brd, "projects") == []
    finally:
        brd.close()
    assert notices == [NOTICE.format(n=0)]
    assert not paths.master_db_path().exists()
    assert migrated(paths.master_db_path()).is_file()


def test_pre_id_registry_is_upgraded_then_migrated(data, tmp_path):
    root = tmp_path / "old"
    root.mkdir()
    legacy = sqlite3.connect(paths.master_db_path())
    legacy.execute(
        "CREATE TABLE projects (root_path TEXT PRIMARY KEY, name TEXT NOT NULL, "
        "created_at TEXT NOT NULL)"
    )
    legacy.execute(
        "INSERT INTO projects VALUES (?, 'old', '2026-01-01T00:00:00')", (str(root),)
    )
    legacy.commit()
    legacy.close()
    _make_v0(paths.project_db_path(root), cards=[("o-1", None)], edges=[])

    brd, notices = open_brd()
    try:
        [project] = db.list_projects(brd)
        assert (project.name, project.root_path) == ("old", str(root))
        assert rows(brd, "entities", "id, project_id") == [("o-1", project.id)]
    finally:
        brd.close()
    assert notices == [NOTICE.format(n=1)]


def test_child_card_stored_before_its_parent_still_migrates(data, tmp_path):
    owner = register(tmp_path, "owner")
    _make_v0(board_path(owner), cards=[("child", "parent"), ("parent", None)], edges=[])

    brd, _ = open_brd()
    try:
        assert db.get_card(brd, "child").parent_id == "parent"
    finally:
        brd.close()


def test_fresh_install_gets_an_empty_v4_brd_db_and_no_notice(data):
    brd, notices = open_brd()
    try:
        assert brd.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert brd.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert rows(brd, "projects") == []
    finally:
        brd.close()
    assert notices == []
    assert not paths.master_db_path().exists()
    assert not (data / "projects").exists()


def test_second_connect_neither_migrates_nor_notifies(data, tmp_path):
    owner = register(tmp_path, "owner")
    conn = v4_board(owner)
    make_card(conn, "c1", project_id=owner.id)
    conn.close()
    first, _ = open_brd()
    first.close()

    second, notices = open_brd()
    try:
        assert rows(second, "cards", "id") == [("c1",)]
        assert len(rows(second, "projects")) == 1
    finally:
        second.close()
    assert notices == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_single_db_migration.py -q`
Expected: every test fails with `AttributeError: module 'brd.master' has no attribute 'connect'`.

- [ ] **Step 3: Create `src/brd/consolidate.py`**

```python
"""The one-time move of every per-project board into brd.db.

Before brd.db, each registered project had its own board file,
projects/<sha256(root)>.db, with its document backups in <hash>.docs/, and
master.db held the registry. migrate() copies all of them into brd.db in one
transaction; retire() then renames the old files with a .migrated suffix."""

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from brd import db, paths
from brd.models import Project

# Copied in this order; foreign keys are off while they copy.
TABLES = ("entities", "cards", "issues", "documents", "comments", "tags", "blocked_by", "refs")
SUFFIX = ".migrated"


@dataclass
class Report:
    migrated: int
    skipped: list[str]
    retired: list[Path]

    def notice(self) -> str:
        lines = [
            f"brd: migrated {self.migrated} projects into brd.db "
            f"(old files kept as *{SUFFIX})"
        ]
        if self.skipped:
            lines.append(
                f"brd: skipped {len(self.skipped)} unregistered board files: "
                + ", ".join(self.skipped)
            )
        return "\n".join(lines)


def _board_path(project: Project) -> Path:
    return paths.project_db_path(Path(project.root_path))


def _backups_path(project: Project) -> Path:
    return paths.project_docs_dir(Path(project.root_path))


def _registered() -> list[Project]:
    conn = db.connect(paths.master_db_path())
    try:
        db.init_master_schema(conn)
        return db.list_projects(conn)
    finally:
        conn.close()


def _open_board(project: Project) -> sqlite3.Connection | None:
    """The project's legacy board, upgraded in place to v4; None when it has
    no board file (it is registered empty)."""
    path = _board_path(project)
    if not path.is_file():
        return None
    board = db.connect(path)
    try:
        db.migrate_project(board, project)
    except BaseException:
        board.close()
        raise
    return board


def _copy(conn: sqlite3.Connection, project: Project, board: sqlite3.Connection | None) -> None:
    # The registry's row, not the board's: ids were settled in master.db.
    conn.execute(
        "INSERT INTO projects (id, name, root_path, created_at) VALUES (?, ?, ?, ?)",
        (project.id, project.name, project.root_path, project.created_at),
    )
    if board is None:
        return
    for table in TABLES:
        rows = board.execute(f"SELECT * FROM {table}").fetchall()
        if rows:
            columns = rows[0].keys()
            conn.executemany(
                f"INSERT INTO {table} ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                [tuple(row) for row in rows],
            )


def _copy_backups(projects: list[Project], created: list[Path]) -> None:
    """Copy every legacy backup into docs/, recording in `created` each file
    this made, so a failure before commit can remove exactly those."""
    target = paths.docs_dir()
    for project in projects:
        source = _backups_path(project)
        if not source.is_dir():
            continue
        target.mkdir(parents=True, exist_ok=True)
        for backup in sorted(source.glob("*.md")):
            destination = target / backup.name
            if not destination.exists():
                created.append(destination)
            shutil.copyfile(backup, destination)


def _unregistered(projects: list[Project]) -> list[str]:
    folder = paths.data_dir() / "projects"
    if not folder.is_dir():
        return []
    registered = {_board_path(project) for project in projects}
    return sorted(
        f"projects/{path.name}" for path in folder.glob("*.db") if path not in registered
    )


def _retirees(projects: list[Project]) -> list[Path]:
    found = [paths.master_db_path()]
    for project in projects:
        found += [path for path in (_board_path(project), _backups_path(project)) if path.exists()]
    return found


def migrate(conn: sqlite3.Connection) -> Report:
    """Copy master.db's projects and every registered legacy board into brd.db.

    conn is brd.db, already inside BEGIN IMMEDIATE with foreign keys off.
    Commits on success; on failure raises with the backups it copied removed
    and leaves the rollback to the caller. retire() renames the old files
    once this has committed."""
    projects = _registered()
    boards: list[tuple[Project, sqlite3.Connection | None]] = []
    try:
        for project in projects:
            boards.append((project, _open_board(project)))
        db.init_brd_schema(conn)
        for project, board in boards:
            _copy(conn, project, board)
    finally:
        for _, board in boards:
            if board is not None:
                board.close()
    created: list[Path] = []
    try:
        _copy_backups(projects, created)
        conn.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION}")
        conn.commit()
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return Report(
        migrated=len(projects), skipped=_unregistered(projects), retired=_retirees(projects)
    )


def retire(old_files: list[Path]) -> None:
    """Rename each old file with the .migrated suffix; never delete one."""
    for path in old_files:
        path.rename(path.with_name(path.name + SUFFIX))
```

- [ ] **Step 4: Add `master.connect`**

In `src/brd/master.py`, replace the imports (L1-7):

```python
import shutil
from datetime import datetime, timezone
from pathlib import Path

from brd import db, paths
from brd.models import Project
from brd.errors import ProjectNotFoundError  # noqa: F401  (re-exported)
```

with:

```python
import shutil
import sqlite3
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from brd import consolidate, db, paths
from brd.models import Project
from brd.errors import ProjectNotFoundError  # noqa: F401  (re-exported)
```

Then insert right after `_now` (after L13):

```python
def _to_stderr(text: str) -> None:
    # Looked up at call time, so test runners that swap sys.stderr see it.
    print(text, file=sys.stderr)


def _version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def connect(notify: Callable[[str], None] = _to_stderr) -> sqlite3.Connection:
    """The brd.db connection every data command uses. An install that is not
    migrated yet is set up first: from master.db and the legacy boards when
    master.db exists (notify gets the one-time notice), else empty."""
    conn = db.connect(paths.brd_db_path())
    try:
        if _version(conn) < db.SCHEMA_VERSION:
            report = _set_up(conn)
            if report is not None:
                consolidate.retire(report.retired)
                notify(report.notice())
    except BaseException:
        conn.close()
        raise
    return conn


def _set_up(conn: sqlite3.Connection) -> consolidate.Report | None:
    """Migrate or create brd.db under its write lock; the report when this
    call migrated, None when it created an empty one or found it done."""
    conn.commit()
    # Must be issued outside a transaction; SQLite ignores it inside one.
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        # IMMEDIATE takes the write lock up front: a concurrent first run
        # waits here on the busy timeout, then finds the work already done.
        conn.execute("BEGIN IMMEDIATE")
        if _version(conn) >= db.SCHEMA_VERSION:
            conn.rollback()
            return None
        if paths.master_db_path().is_file():
            return consolidate.migrate(conn)
        db.init_brd_schema(conn)
        conn.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION}")
        conn.commit()
        return None
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_single_db_migration.py -q`
Expected: 10 passed.

Run: `uv run pytest -q`
Expected: 590 passed. Commands still use the legacy layout; nothing calls `master.connect` yet.

- [ ] **Step 6: Commit**

```bash
git add src/brd/consolidate.py src/brd/master.py tests/test_single_db_migration.py
git commit -m "Migrate every registered legacy board into brd.db on first connect

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Abort paths: duplicates, mismatch, unreadable board, FK check, backup cleanup

**Files:**
- Modify: `src/brd/consolidate.py`: replace `_open_board` and `migrate`; add `_label` and `_check_duplicates`; import `MigrationError`
- Test: `tests/test_single_db_migration.py` (append)

**Interfaces:**
- Consumes: `consolidate.migrate`, `master.connect` (Task 2); test helpers `register`, `board_path`, `backups_path`, `migrated`, `v4_board`, `add_document`, `open_brd` (Task 2).
- Produces:
  - Every abort raises `brd.errors.MigrationError`, with one exception: an `OSError` from copying backups propagates as is, after the copied backups are removed.
  - The duplicate message has the form `cannot migrate into brd.db: project <a> (<root a>) and project <b> (<root b>) share ids <id>, <id>; no file was renamed, remove the duplicates and run brd again`.
  - Board errors have the form `cannot migrate the board of project <name> (<root>) at <path>: <cause>`.
  - Test helpers `seed_shared_ids(base) -> tuple[Project, Project]` and `assert_nothing_migrated(projects)`, used by Tasks 5 and 6.

- [ ] **Step 1: Write the failing tests**

Add `import shutil` to the imports of `tests/test_single_db_migration.py` (after `import sqlite3`). Add these imports too:

```python
from brd.errors import MigrationError
from tests.factories import OTHER_PROJECT, add_project
```

Then append:

```python
def seed_shared_ids(base: Path) -> tuple[Project, Project]:
    """Two registered v4 boards that both hold card 'dup' and comment
    'k-dup', each with one document backup."""
    first = register(base, "first", "2026-01-01T00:00:00+00:00")
    second = register(base, "second", "2026-01-02T00:00:00+00:00")
    for project in (first, second):
        conn = v4_board(project)
        make_card(conn, "dup", project_id=project.id)
        conn.execute(
            "INSERT INTO comments (id, entity_id, author, body, created_at) "
            "VALUES ('k-dup', 'dup', 'me', 'hi', ?)",
            (NOW,),
        )
        conn.commit()
        add_document(conn, project, f"doc-{project.name}", "notes", "body")
        conn.close()
    return first, second


def assert_nothing_migrated(projects: list[Project]) -> None:
    assert paths.master_db_path().is_file()
    assert not migrated(paths.master_db_path()).exists()
    for project in projects:
        assert board_path(project).is_file()
        assert not migrated(board_path(project)).exists()
        assert not migrated(backups_path(project)).exists()
    brd = paths.brd_db_path()
    if brd.exists():
        conn = sqlite3.connect(brd)
        try:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == 0
        finally:
            conn.close()


def test_shared_ids_abort_naming_both_projects_and_every_id(data, tmp_path):
    first, second = seed_shared_ids(tmp_path)
    notices: list[str] = []

    with pytest.raises(MigrationError) as excinfo:
        master.connect(notify=notices.append)

    message = str(excinfo.value)
    for text in ("first", first.root_path, "second", second.root_path, "dup", "k-dup"):
        assert text in message
    assert notices == []
    assert_nothing_migrated([first, second])
    assert backups_path(first).is_dir() and backups_path(second).is_dir()
    assert not (data / "docs").exists()

    conn = db.connect(board_path(second))
    db.delete_card(conn, "dup")  # the cascade takes comment k-dup with it
    conn.close()
    brd, notices = open_brd()
    try:
        assert rows(brd, "entities", "id") == sorted(
            [("dup",), ("doc-first",), ("doc-second",)]
        )
    finally:
        brd.close()
    assert notices == [NOTICE.format(n=2)]


def test_board_recording_another_project_aborts(data, tmp_path):
    owner = register(tmp_path, "owner")
    stranger = Project(id=db.new_project_id(), name="stranger", root_path="/elsewhere", created_at=NOW)
    conn = db.connect(board_path(owner))
    db.migrate_project(conn, stranger)
    conn.close()

    with pytest.raises(MigrationError) as excinfo:
        master.connect()

    assert "owner" in str(excinfo.value)
    assert str(board_path(owner)) in str(excinfo.value)
    assert_nothing_migrated([owner])


def test_unreadable_board_aborts_naming_the_project_and_file(data, tmp_path):
    owner = register(tmp_path, "owner")
    board_path(owner).write_bytes(b"not a database " * 100)

    with pytest.raises(MigrationError) as excinfo:
        master.connect()

    assert "owner" in str(excinfo.value)
    assert str(board_path(owner)) in str(excinfo.value)
    assert_nothing_migrated([owner])


def test_rows_of_an_unregistered_project_fail_the_foreign_key_check(data, tmp_path):
    owner = register(tmp_path, "owner")
    conn = v4_board(owner)
    add_project(conn, OTHER_PROJECT)
    make_card(conn, "stray", project_id=OTHER_PROJECT.id)
    conn.close()

    with pytest.raises(MigrationError, match="foreign key"):
        master.connect()

    assert_nothing_migrated([owner])


def test_failed_backup_copy_removes_the_backups_it_copied(data, tmp_path, monkeypatch):
    owner = register(tmp_path, "owner")
    conn = v4_board(owner)
    add_document(conn, owner, "doc-a", "a", "A")
    add_document(conn, owner, "doc-b", "b", "B")
    conn.close()
    (data / "docs").mkdir()
    (data / "docs" / "keep.md").write_text("mine")
    real_copyfile = shutil.copyfile
    calls = []

    def copyfile(source, target):
        calls.append(source)
        if len(calls) == 2:
            raise OSError("disk full")
        return real_copyfile(source, target)

    monkeypatch.setattr(shutil, "copyfile", copyfile)
    with pytest.raises(OSError, match="disk full"):
        master.connect()

    assert sorted(path.name for path in (data / "docs").iterdir()) == ["keep.md"]
    assert (data / "docs" / "keep.md").read_text() == "mine"
    assert_nothing_migrated([owner])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_single_db_migration.py -q`
Expected: 4 of the 5 new tests fail:
- `test_shared_ids_...`: raw `sqlite3.IntegrityError: UNIQUE constraint failed: entities.id`.
- `test_board_recording_another_project_aborts`: the `MigrationError` text names neither "owner" nor the path.
- `test_unreadable_board_...`: raw `sqlite3.DatabaseError: file is not a database`.
- `test_rows_of_an_unregistered_project_...`: `DID NOT RAISE` (the migration commits).

`test_failed_backup_copy_...` should already pass: Task 2 removes created backups on failure. Keep it as a guard for the B5 rule.

- [ ] **Step 3: Implement the checks**

In `src/brd/consolidate.py`, add after `from brd import db, paths`:

```python
from brd.errors import MigrationError
```

Replace the whole `_open_board` function with:

```python
def _label(project: Project) -> str:
    return f"project {project.name} ({project.root_path})"


def _open_board(project: Project) -> sqlite3.Connection | None:
    """The project's legacy board, upgraded in place to v4; None when it has
    no board file (it is registered empty)."""
    path = _board_path(project)
    if not path.is_file():
        return None
    board = None
    try:
        board = db.connect(path)
        db.migrate_project(board, project)
        return board
    except BaseException as exc:
        if board is not None:
            board.close()
        # Not SQLite, or a board that records another project: name both.
        if isinstance(exc, (sqlite3.DatabaseError, MigrationError)):
            raise MigrationError(
                f"cannot migrate the board of {_label(project)} at {path}: {exc}"
            ) from exc
        raise


def _check_duplicates(boards: list[tuple[Project, sqlite3.Connection | None]]) -> None:
    """Abort before anything is copied when two boards hold the same entity or
    comment id; brd.db would otherwise fail on a raw IntegrityError."""
    projects = {project.id: project for project, _ in boards}
    clashes: dict[tuple[str, str], list[str]] = {}
    for table in ("entities", "comments"):
        owners: dict[str, str] = {}
        for project, board in boards:
            if board is None:
                continue
            for row in board.execute(f"SELECT id FROM {table}"):
                first = owners.setdefault(row[0], project.id)
                if first != project.id:
                    clashes.setdefault((first, project.id), []).append(row[0])
    if clashes:
        parts = [
            f"{_label(projects[a])} and {_label(projects[b])} share ids {', '.join(sorted(ids))}"
            for (a, b), ids in clashes.items()
        ]
        raise MigrationError(
            "cannot migrate into brd.db: "
            + "; ".join(parts)
            + "; no file was renamed, remove the duplicates and run brd again"
        )
```

Replace the whole `migrate` function with:

```python
def migrate(conn: sqlite3.Connection) -> Report:
    """Copy master.db's projects and every registered legacy board into brd.db.

    conn is brd.db, already inside BEGIN IMMEDIATE with foreign keys off.
    Commits on success; on failure raises (MigrationError for anything in the
    old files) with the backups it copied removed, and leaves the rollback to
    the caller. retire() renames the old files once this has committed."""
    projects = _registered()
    boards: list[tuple[Project, sqlite3.Connection | None]] = []
    try:
        for project in projects:
            boards.append((project, _open_board(project)))
        _check_duplicates(boards)
        db.init_brd_schema(conn)
        try:
            for project, board in boards:
                _copy(conn, project, board)
        except sqlite3.IntegrityError as exc:
            raise MigrationError(f"cannot migrate into brd.db: {exc}") from exc
    finally:
        for _, board in boards:
            if board is not None:
                board.close()
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise MigrationError(
            f"cannot migrate into brd.db: {len(violations)} foreign key violation(s); "
            "no file was renamed"
        )
    created: list[Path] = []
    try:
        _copy_backups(projects, created)
        conn.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION}")
        conn.commit()
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return Report(
        migrated=len(projects), skipped=_unregistered(projects), retired=_retirees(projects)
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_single_db_migration.py -q`
Expected: 15 passed.

Run: `uv run pytest -q`
Expected: 595 passed.

- [ ] **Step 5: Commit**

```bash
git add src/brd/consolidate.py tests/test_single_db_migration.py
git commit -m "Abort the brd.db migration on shared ids, foreign boards and unreadable files

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Concurrent first runs, failed renames, WAL sidecars

**Files:**
- Modify: `src/brd/db.py:1-16` (imports and `connect`)
- Modify: `src/brd/consolidate.py`: replace `retire`, add `_rename`
- Test: `tests/test_db.py` (append), `tests/test_single_db_migration.py` (append)

**Interfaces:**
- Consumes: `master.connect`, `consolidate.retire` (Task 2); test helpers from Tasks 2 and 3.
- Produces: `db.connect(db_path)` with the same signature. It now retries the switch to WAL for up to the 10-second busy timeout when it gets "database is locked". `consolidate.retire(old_files)` now ignores `OSError` and renames `-wal`/`-shm` sidecars alongside their database.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db.py`:

```python
def test_concurrent_first_opens_of_a_new_file_all_succeed(tmp_path):
    import threading

    # Switching a brand-new file to WAL can fail at once under contention,
    # without waiting on the busy timeout; every first open must still work.
    for attempt in range(20):
        path = tmp_path / f"new{attempt}.db"
        barrier = threading.Barrier(4, timeout=20)
        errors = []

        def open_it():
            try:
                barrier.wait()
                db.connect(path).close()
            except Exception as exc:  # noqa: BLE001 — collected and asserted below
                errors.append(exc)

        threads = [threading.Thread(target=open_it) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == [], attempt
```

Append to `tests/test_single_db_migration.py` (add `import threading` to its imports):

```python
def test_concurrent_first_runs_migrate_exactly_once(tmp_path, monkeypatch):
    for attempt in range(5):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / f"data{attempt}"))
        for name in ("one", "two"):
            project = register(tmp_path / f"roots{attempt}", name)
            conn = v4_board(project)
            make_card(conn, f"{name}-card", project_id=project.id)
            conn.close()
        barrier = threading.Barrier(4, timeout=20)
        notices: list[str] = []
        errors = []

        def first_run():
            try:
                barrier.wait()
                master.connect(notify=notices.append).close()
            except Exception as exc:  # noqa: BLE001 — collected and asserted below
                errors.append(exc)

        threads = [threading.Thread(target=first_run) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert errors == []
        assert notices == [NOTICE.format(n=2)]
        conn = db.connect(paths.brd_db_path())
        try:
            assert rows(conn, "cards", "id") == [("one-card",), ("two-card",)]
            assert len(rows(conn, "projects")) == 2
        finally:
            conn.close()
        assert migrated(paths.master_db_path()).is_file()
        assert not paths.master_db_path().exists()


def test_concurrent_first_runs_on_a_fresh_install_all_succeed(tmp_path, monkeypatch):
    for attempt in range(10):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / f"fresh{attempt}"))
        barrier = threading.Barrier(4, timeout=20)
        notices: list[str] = []
        errors = []

        def first_run():
            try:
                barrier.wait()
                master.connect(notify=notices.append).close()
            except Exception as exc:  # noqa: BLE001 — collected and asserted below
                errors.append(exc)

        threads = [threading.Thread(target=first_run) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == []
        assert notices == []


def test_failed_rename_neither_fails_nor_reruns_the_migration(data, tmp_path, monkeypatch):
    owner = register(tmp_path, "owner")
    conn = v4_board(owner)
    make_card(conn, "c1", project_id=owner.id)
    conn.close()
    stuck = board_path(owner)
    real_rename = Path.rename

    def rename(self, target):
        if self == stuck:
            raise PermissionError("read-only")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", rename)
    first, notices = open_brd()
    first.close()
    assert notices == [NOTICE.format(n=1)]
    assert stuck.is_file()
    assert migrated(paths.master_db_path()).is_file()

    second, again = open_brd()
    try:
        assert rows(second, "cards", "id") == [("c1",)]
    finally:
        second.close()
    assert again == []


def test_wal_sidecar_follows_its_database(data, tmp_path):
    owner = register(tmp_path, "owner")
    holder = v4_board(owner)
    make_card(holder, "c1", project_id=owner.id)
    board = board_path(owner)
    # This open connection keeps the board's -wal file on disk.
    try:
        assert board.with_name(board.name + "-wal").exists()
        brd, _ = open_brd()
        brd.close()
        renamed = migrated(board)
        assert renamed.is_file()
        assert renamed.with_name(renamed.name + "-wal").exists()
        assert not board.with_name(board.name + "-wal").exists()
    finally:
        holder.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_db.py::test_concurrent_first_opens_of_a_new_file_all_succeed tests/test_single_db_migration.py -q`
Expected failures:
- `test_concurrent_first_opens_of_a_new_file_all_succeed` and `test_concurrent_first_runs_on_a_fresh_install_all_succeed`: `OperationalError('database is locked')`. While planning, about 45% of attempts failed this way, so 20 and 10 attempts fail almost surely. If a run passes by luck, re-run once.
- `test_concurrent_first_runs_migrate_exactly_once`: same error, from the brand-new `brd.db`.
- `test_failed_rename_...`: `PermissionError: read-only`.
- `test_wal_sidecar_...`: the `-wal` assertion after the migration.

- [ ] **Step 3: Make `db.connect` retry the WAL switch**

In `src/brd/db.py`, replace the head of the file (L1-16):

```python
import sqlite3
import uuid
from pathlib import Path

from brd.errors import MigrationError
from brd.models import Card, Project


def connect(db_path: Path) -> sqlite3.Connection:
    # Wait for concurrent writers (e.g. parallel first-run migrations)
    # instead of failing immediately with "database is locked".
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
```

with:

```python
import sqlite3
import time
import uuid
from pathlib import Path

from brd.errors import MigrationError
from brd.models import Card, Project

_BUSY_TIMEOUT = 10


def _use_wal(conn: sqlite3.Connection) -> None:
    # Switching a brand-new file to WAL can fail at once with "database is
    # locked" while another connection does the same: SQLite does not run the
    # busy handler there. Retry for as long as the busy timeout would wait.
    deadline = time.monotonic() + _BUSY_TIMEOUT
    while True:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc) or time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


def connect(db_path: Path) -> sqlite3.Connection:
    # Wait for concurrent writers (e.g. parallel first-run migrations)
    # instead of failing immediately with "database is locked".
    conn = sqlite3.connect(db_path, timeout=_BUSY_TIMEOUT)
    conn.row_factory = sqlite3.Row
    try:
        _use_wal(conn)
    except BaseException:
        conn.close()
        raise
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
```

- [ ] **Step 4: Make `retire` tolerant and sidecar-aware**

In `src/brd/consolidate.py`, replace the whole `retire` function with:

```python
def _rename(source: Path, target: Path) -> None:
    try:
        source.rename(target)
    except OSError:
        # brd.db is migrated, so this never runs again; the stray old file
        # is left for the user.
        pass


def retire(old_files: list[Path]) -> None:
    """Rename each old file with the .migrated suffix, and its -wal/-shm
    sidecars with it so the renamed file still opens with all its data.
    Never deletes a file."""
    for path in old_files:
        target = path.with_name(path.name + SUFFIX)
        _rename(path, target)
        for sidecar in ("-wal", "-shm"):
            source = path.with_name(path.name + sidecar)
            if source.exists():
                _rename(source, target.with_name(target.name + sidecar))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_db.py tests/test_single_db_migration.py -q`
Expected: all pass.

Run: `uv run pytest -q`
Expected: 600 passed.

- [ ] **Step 6: Commit**

```bash
git add src/brd/db.py src/brd/consolidate.py tests/test_db.py tests/test_single_db_migration.py
git commit -m "Survive concurrent first runs and failed renames of the brd.db migration

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Every command reads and writes brd.db

**Files:**
- Modify: `src/brd/master.py`: everything below `_set_up` (the old L16-216 functions)
- Modify: `src/brd/db.py:436-439` (`docs_dir`)
- Modify: `src/brd/cli/_app.py:9` (imports), `:64-73` (`open_project`)
- Modify: `src/brd/cli/project.py:61` (`purge`)
- Modify tests: `tests/test_master.py` (full replacement below), `tests/test_cli_app.py`, `tests/test_cli.py`, `tests/test_snapshot.py`, `tests/test_migration.py`, `tests/test_single_db_migration.py` (append)

**Interfaces:**
- Consumes: `master.connect(notify)` (Task 2); test helpers `seed_shared_ids`, `register`, `v4_board`, `board_path`, `migrated`, `data` fixture (Tasks 2-3).
- Produces:
  - `master.registered_project(conn: sqlite3.Connection, root_path: Path) -> Project`. **The signature changes: it now takes `conn`.**
  - `master.init_project(root_path: Path, name: str | None = None) -> Project`, unchanged signature.
  - `master.list_all_projects() -> list[Project]` and `master.forget_project(root_path: Path) -> Project`, unchanged signatures.
  - `master.registry_count() -> int`: never migrates.
  - `master.purge_all() -> int`.
  - `master.resolve_project_db` is **deleted**, along with `_master_conn`, `_board_project` and `_settle_project`.
  - `db.docs_dir(conn) -> Path` now returns `Path(<db file>).parent / "docs"`.
  - `_app.open_project() -> Ctx`: `Ctx.conn` is the `brd.db` connection.

- [ ] **Step 1: Move the existing tests to the new layout (failing)**

**1a.** Replace `tests/test_master.py` entirely with:

```python
import shutil
import uuid

import pytest

from brd import db, master, paths
from brd.models import Project
from tests.factories import PROJECT, make_card, make_document


def _brd():
    return db.connect(paths.brd_db_path())


def _card_owner(card_id):
    """(title, project_id) of a card in brd.db, or None."""
    conn = _brd()
    try:
        row = conn.execute(
            "SELECT cards.title, entities.project_id FROM cards "
            "JOIN entities ON entities.id = cards.id WHERE cards.id = ?",
            (card_id,),
        ).fetchone()
    finally:
        conn.close()
    return tuple(row) if row else None


def test_init_project_creates_brd_db_and_gitignored_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    project = master.init_project(repo)

    marker = repo / ".brd"
    assert marker.is_file()
    assert marker.read_text() == ""
    assert project.name == "myrepo"
    assert project.root_path == str(repo)

    db_path = paths.brd_db_path()
    assert db_path.is_file()
    assert str(db_path).startswith(str(tmp_path / "data"))
    conn = _brd()
    try:
        assert db.list_projects(conn) == [project]
    finally:
        conn.close()

    gitignore = repo / ".gitignore"
    assert gitignore.exists()
    assert ".brd" in gitignore.read_text().splitlines()


def test_init_project_appends_to_existing_gitignore_once(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    (repo / ".gitignore").write_text("__pycache__/\n")

    master.init_project(repo)

    lines = (repo / ".gitignore").read_text().splitlines()
    assert lines.count(".brd") == 1
    assert "__pycache__/" in lines


def test_init_project_twice_preserves_existing_cards(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    project = master.init_project(repo)

    conn = _brd()
    try:
        make_card(conn, "c1", title="Existing card", project_id=project.id)
    finally:
        conn.close()

    master.init_project(repo)

    assert _card_owner("c1") == ("Existing card", project.id)


def test_init_project_upserts_name_on_rerun(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    master.init_project(repo, name="first-name")
    project = master.init_project(repo, name="second-name")

    assert project.name == "second-name"
    all_projects = master.list_all_projects()
    assert [p.name for p in all_projects] == ["second-name"]


def test_init_project_migrates_legacy_uuid_marker_preserving_cards(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    legacy_id = "07a7d240-444a-4b71-b585-b5bc7b50fdf3"
    (repo / ".brd").write_text(f"{legacy_id}\n")

    old_projects_dir = tmp_path / "data" / "brd" / "projects"
    old_projects_dir.mkdir(parents=True)
    old_db_path = old_projects_dir / f"{legacy_id}.db"
    old_conn = db.connect(old_db_path)
    db.init_project_schema(old_conn, PROJECT)
    make_card(old_conn, "c1", title="Old card")
    old_conn.close()

    project = master.init_project(repo)

    assert _card_owner("c1") == ("Old card", project.id)
    assert (repo / ".brd").read_text() == ""


def test_init_project_migrates_in_repo_format_preserving_cards(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    # Simulate a repo committed under the in-repo storage design: .brd/ is a
    # directory holding board.db, and it's absent from .gitignore.
    brd_dir = repo / ".brd"
    brd_dir.mkdir()
    old_db_path = brd_dir / "board.db"
    old_conn = db.connect(old_db_path)
    db.init_project_schema(old_conn, PROJECT)
    make_card(old_conn, "c1", title="In-repo card")
    old_conn.close()

    project = master.init_project(repo)

    assert brd_dir.is_file()  # the directory is gone; .brd is a marker file again
    assert _card_owner("c1") == ("In-repo card", project.id)

    gitignore_lines = (repo / ".gitignore").read_text().splitlines()
    assert ".brd" in gitignore_lines


def test_find_marker_walks_up_from_nested_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    nested = repo / "a" / "b"
    nested.mkdir(parents=True)
    master.init_project(repo)

    found = master.find_marker(nested)
    assert found == repo / ".brd"


def test_find_marker_returns_none_when_absent(tmp_path):
    somewhere = tmp_path / "nowhere"
    somewhere.mkdir()
    assert master.find_marker(somewhere) is None


def test_list_all_projects(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo1 = tmp_path / "repo1"
    repo1.mkdir()
    repo2 = tmp_path / "repo2"
    repo2.mkdir()
    master.init_project(repo1)
    master.init_project(repo2)

    results = master.list_all_projects()
    assert {p.name for p in results} == {"repo1", "repo2"}


def test_forget_project_removes_marker_and_registry_row(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    master.init_project(repo)

    forgotten = master.forget_project(repo)

    assert forgotten.name == "myrepo"
    assert not (repo / ".brd").exists()
    assert master.list_all_projects() == []


def test_forget_project_raises_when_not_registered(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    with pytest.raises(master.ProjectNotFoundError):
        master.forget_project(repo)


def test_forget_project_works_when_root_path_no_longer_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    master.init_project(repo)
    shutil.rmtree(repo)

    forgotten = master.forget_project(repo)

    assert forgotten.name == "myrepo"
    assert master.list_all_projects() == []


def test_purge_all_removes_entire_data_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "data" / "brd"
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo1 = tmp_path / "repo1"
    repo1.mkdir()
    repo2 = tmp_path / "repo2"
    repo2.mkdir()
    master.init_project(repo1)
    master.init_project(repo2)

    removed = master.purge_all()

    assert removed == 2
    assert not data_dir.exists()


def test_purge_all_returns_zero_when_nothing_registered(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert master.purge_all() == 0


def test_registry_count_reads_master_db_without_migrating(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    conn = db.connect(paths.master_db_path())
    db.init_master_schema(conn)
    for name in ("a", "b"):
        db.upsert_project(
            conn, Project(db.new_project_id(), name, str(tmp_path / name), "2026-01-01")
        )
    conn.close()

    assert master.registry_count() == 2
    assert not paths.brd_db_path().exists()
    assert paths.master_db_path().is_file()


def test_list_all_projects_is_empty_before_any_registration(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    assert master.list_all_projects() == []


def test_forget_removes_the_projects_document_backups(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    project = master.init_project(repo)
    conn = _brd()
    try:
        make_document(conn, "d1", "notes", content="backup", project_id=project.id)
    finally:
        conn.close()
    backup = paths.docs_dir() / "d1.md"
    assert backup.read_text() == "backup"

    master.forget_project(repo)

    assert not backup.exists()


def _is_uuid4(value):
    return uuid.UUID(value).version == 4 and str(uuid.UUID(value)) == value


def test_init_project_returns_stored_project_with_uuid4_id(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    project = master.init_project(repo)

    assert _is_uuid4(project.id)
    assert master.list_all_projects() == [project]


def test_init_project_rerun_keeps_id_and_created_at(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    first = master.init_project(repo, name="first-name")
    second = master.init_project(repo, name="second-name")
    third = master.init_project(repo)

    assert second.id == first.id
    assert second.created_at == first.created_at
    assert second.name == "second-name"
    assert third.id == first.id
    assert third.name == "myrepo"
    assert master.list_all_projects() == [third]


def test_init_project_gives_each_root_its_own_id(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo1 = tmp_path / "repo1"
    repo2 = tmp_path / "repo2"
    repo1.mkdir()
    repo2.mkdir()

    first = master.init_project(repo1)
    second = master.init_project(repo2)

    assert first.id != second.id


def test_init_rerun_keeps_the_brd_db_row_and_its_cards(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo1 = tmp_path / "repo1"
    repo2 = tmp_path / "repo2"
    repo1.mkdir()
    repo2.mkdir()
    first = master.init_project(repo1)
    conn = _brd()
    try:
        make_card(conn, "c1", project_id=first.id)
    finally:
        conn.close()

    master.init_project(repo1, name="renamed")
    other = master.init_project(repo2)

    conn = _brd()
    try:
        stored = {row["root_path"]: tuple(row) for row in conn.execute("SELECT * FROM projects")}
    finally:
        conn.close()
    assert stored[str(repo1)] == (first.id, "renamed", str(repo1), first.created_at)
    assert stored[str(repo2)][0] == other.id != first.id
    assert _card_owner("c1") == ("c1", first.id)


def test_init_on_an_unmigrated_install_keeps_the_registered_id(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    legacy = Project(db.new_project_id(), "myrepo", str(repo), "2026-01-01T00:00:00+00:00")
    conn = db.connect(paths.master_db_path())
    db.init_master_schema(conn)
    db.upsert_project(conn, legacy)
    conn.close()
    board = db.connect(paths.project_db_path(repo))
    db.migrate_project(board, legacy)
    make_card(board, "c1", project_id=legacy.id)
    board.close()

    project = master.init_project(repo)

    assert (project.id, project.created_at) == (legacy.id, legacy.created_at)
    assert _card_owner("c1") == ("c1", legacy.id)


def test_forget_project_returns_project_with_its_id(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    project = master.init_project(repo)

    assert master.forget_project(repo) == project


def test_registered_project_returns_the_registered_row(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    project = master.init_project(repo)

    conn = master.connect()
    try:
        assert master.registered_project(conn, repo) == project
    finally:
        conn.close()


def test_registered_project_raises_when_root_is_not_registered(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    conn = master.connect()
    try:
        with pytest.raises(master.ProjectNotFoundError, match="brd init"):
            master.registered_project(conn, repo)
    finally:
        conn.close()


def test_copy_cards_drops_dangling_legacy_edges(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    brd_dir = repo / ".brd"
    brd_dir.mkdir(parents=True)
    old_conn = db.connect(brd_dir / "board.db")
    db.init_project_schema(old_conn, PROJECT)
    make_card(old_conn, "c1")
    make_card(old_conn, "c2")
    db.add_blocked_by_edge(old_conn, "c2", "c1")
    db.add_blocked_by_edge(old_conn, "c1", "ghost")  # the legacy board's dangling edge
    old_conn.close()

    project = master.init_project(repo)

    conn = _brd()
    try:
        entities = conn.execute("SELECT id, project_id FROM entities ORDER BY id").fetchall()
        edges = conn.execute("SELECT card_id, blocks_on_id FROM blocked_by").fetchall()
    finally:
        conn.close()
    assert [tuple(r) for r in entities] == [("c1", project.id), ("c2", project.id)]
    assert [tuple(r) for r in edges] == [("c2", "c1")]
```

Compared with the old file: `test_resolve_project_db_*` and `test_init_project_board_row_matches_registry` (with `_board_project_ids`) are deleted, because the code they test is removed (B7). `test_init_rerun_keeps_the_brd_db_row_and_its_cards` (T16), `test_init_on_an_unmigrated_install_keeps_the_registered_id` (Review Focus 4) and `test_registry_count_reads_master_db_without_migrating` are new.

**1b.** In `tests/test_migration.py`, replace `test_docs_dir_sits_next_to_the_db` (L191-193) with:

```python
def test_docs_dir_sits_next_to_the_db(tmp_path):
    conn = db.connect(tmp_path / "project.db")
    assert db.docs_dir(conn).resolve() == (tmp_path / "docs").resolve()
```

**1c.** In `tests/test_cli_app.py`:

Replace `test_commands_migrate_a_v0_board` (L19-50) with:

```python
def test_commands_migrate_a_v0_board(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".brd").write_text("")
    monkeypatch.chdir(repo)
    project = Project(
        id=db.new_project_id(),
        name="repo",
        root_path=str(repo),
        created_at="2026-01-01T00:00:00",
    )
    master_conn = db.connect(paths.master_db_path())
    try:
        db.init_master_schema(master_conn)
        db.upsert_project(master_conn, project)
    finally:
        master_conn.close()
    legacy = sqlite3.connect(paths.project_db_path(repo))
    legacy.execute(
        "CREATE TABLE cards (id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT, "
        "status TEXT NOT NULL, parent_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    legacy.execute("CREATE TABLE blocked_by (card_id TEXT, blocks_on_id TEXT)")
    legacy.execute("INSERT INTO cards VALUES ('c1', 'Old', NULL, 'todo', NULL, 'now', 'now')")
    legacy.commit()
    legacy.close()

    assert [c["id"] for c in ok("list")] == ["c1"]
    conn = db.connect(paths.brd_db_path())
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert conn.execute("SELECT project_id FROM entities WHERE id = 'c1'").fetchone()[0] == (
            project.id
        )
    finally:
        conn.close()
    board = paths.project_db_path(repo)
    assert not board.exists()
    assert board.with_name(board.name + ".migrated").is_file()
```

In `test_unregistered_marker_is_a_project_not_found_envelope`, replace its last line (L115, `assert not paths.project_db_path(repo).exists()`) with:

```python
    conn = db.connect(paths.brd_db_path())
    try:
        assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0
    finally:
        conn.close()
```

Replace `test_open_project_closes_connection_when_migration_fails` (L118-138, the end of the file) with:

```python
def _track_connections(monkeypatch):
    opened = []
    real_connect = db.connect

    def tracking_connect(path):
        conn = real_connect(path)
        opened.append(conn)
        return conn

    monkeypatch.setattr(db, "connect", tracking_connect)
    return opened


def _assert_all_closed(opened):
    assert opened
    for conn in opened:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            conn.execute("SELECT 1")


def test_open_project_closes_connection_when_the_root_is_not_registered(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".brd").write_text("")
    monkeypatch.chdir(repo)
    opened = _track_connections(monkeypatch)

    assert err("list") == "ProjectNotFoundError"
    _assert_all_closed(opened)


def test_open_project_closes_connection_when_migration_fails(tmp_path, monkeypatch):
    from brd import consolidate
    from brd.errors import MigrationError

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".brd").write_text("")
    monkeypatch.chdir(repo)
    registry = db.connect(paths.master_db_path())
    db.init_master_schema(registry)
    registry.close()

    def failing_migrate(conn):
        raise MigrationError("boom")

    monkeypatch.setattr(consolidate, "migrate", failing_migrate)
    opened = _track_connections(monkeypatch)

    assert err("list") == "MigrationError"
    _assert_all_closed(opened)
```

(`dataclasses`, `json`, `sqlite3`, `pytest`, `db`, `master`, `paths`, `_app`, `Project`, `err`, `invoke` and `ok` are all still imported and used.)

**1d.** In `tests/test_cli.py`:

Replace L59 (`assert paths.project_db_path(isolated_env).is_file()`) in `test_init_registers_project` with:

```python
    conn = db.connect(paths.brd_db_path())
    try:
        stored = conn.execute("SELECT name, root_path FROM projects").fetchall()
    finally:
        conn.close()
    assert [tuple(r) for r in stored] == [("myrepo", str(isolated_env))]
```

Replace L127 (`assert not paths.project_db_path(isolated_env).is_file()`) in `test_forget_removes_current_project` with:

```python
    conn = db.connect(paths.brd_db_path())
    try:
        assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0
    finally:
        conn.close()
```

In `test_import_round_trips_a_board_into_a_fresh_project` (L545), insert the following line directly before `other_repo = isolated_env.parent / "other-repo"`:

```python
    # A second install: one install's projects share brd.db, where these ids exist.
    monkeypatch.setenv("XDG_DATA_HOME", str(isolated_env.parent / "other-data"))
```

Replace each `conn = db.connect(paths.project_db_path(project))` (L760, L777, L915; three occurrences) with `conn = db.connect(paths.brd_db_path())`.

The `foreign` fixture now inserts `OTHER_PROJECT` into the one `brd.db` that holds the real project, so `brd projects` lists two rows, ordered by `created_at`, and `OTHER_PROJECT` (2026-09-24) sorts first. In `test_show_is_global_and_names_the_owner` (L872), replace `registered = ok("projects")[0]` with:

```python
    registered = next(p for p in ok("projects") if p["id"] != OTHER_PROJECT.id)
```

(Without this the test fails: `assert {'id': '2638f...', 'name': 'repo'} == {'id': '22222222-...', 'name': 'other'}`. Verified by applying every edit of this task to a scratch copy; with this line the full suite is 615 passed.)

Append the T15 test:

```python
def test_forget_removes_only_the_current_projects_rows_and_backups(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    ids = {}
    for name in ("keep", "gone"):
        root = tmp_path / name
        root.mkdir()
        monkeypatch.chdir(root)
        ok("init")
        (root / "notes.md").write_text(f"{name} notes")
        parent = ok("add", "--title", "Parent")
        child = ok("add", "--title", "Child", "--parent", parent["id"])
        issue = ok("issue", "open", "--title", "Q", "--blocks", child["id"])
        ok("comment", "add", child["id"], "progress")
        doc = ok("doc", "add", "notes.md", "--tag", "design")
        ids[name] = {"parent": parent["id"], "child": child["id"], "issue": issue["id"], "doc": doc["id"]}

    monkeypatch.chdir(tmp_path / "gone")
    assert ok("forget")["name"] == "gone"

    assert not (paths.docs_dir() / f"{ids['gone']['doc']}.md").exists()
    assert (paths.docs_dir() / f"{ids['keep']['doc']}.md").read_text() == "keep notes"
    gone = list(ids["gone"].values())
    marks = ", ".join("?" for _ in gone)
    conn = db.connect(paths.brd_db_path())
    try:
        assert [r[0] for r in conn.execute("SELECT root_path FROM projects")] == [
            str(tmp_path / "keep")
        ]
        for table, column in (
            ("entities", "id"),
            ("comments", "entity_id"),
            ("tags", "entity_id"),
            ("blocked_by", "card_id"),
            ("blocked_by", "blocks_on_id"),
            ("refs", "src_id"),
        ):
            count = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {column} IN ({marks})", gone
            ).fetchone()[0]
            assert count == 0, (table, column)
    finally:
        conn.close()
    monkeypatch.chdir(tmp_path / "keep")
    assert {c["id"] for c in ok("list")} == {ids["keep"]["parent"], ids["keep"]["child"]}
    assert ok("show", ids["keep"]["doc"])["tags"] == ["design"]
    assert len(ok("show", ids["keep"]["child"])["comments"]) == 1
```

**1e.** In `tests/test_snapshot.py`, do these two edits **in this order**. The helper's body contains the same 4 lines, so a replace-all run after inserting it would rewrite the helper too.

First, replace **every** occurrence (8 of them: L46, L81, L93, L128, L141, L154, L209, L278) of this exact 4-line block:

```python
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    ok("init")
```

with:

```python
    other = _fresh_project(tmp_path, monkeypatch)
```

(With the Edit tool, use `replace_all: true` on the 4-line block.)

Then insert the helper after `_shows` (after L26), with one blank line before and two after, as the file's spacing has it:

```python
def _fresh_project(tmp_path, monkeypatch):
    """Init project `other` on a second install (its own data dir): one
    install's projects share brd.db, where the snapshot's ids already exist."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "other-data"))
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    ok("init")
    return other
```

The line numbers below are those of the original file, before either edit.

Replace L135 `assert not (paths.project_docs_dir(other) / f"{doc_id}.md").exists()` with:

```python
    assert not (paths.docs_dir() / f"{doc_id}.md").exists()
```

Replace both occurrences (L170, L220) of `docs_dir = paths.project_docs_dir(other)` with `docs_dir = paths.docs_dir()`.

**1f.** Append the T14 test to `tests/test_single_db_migration.py`, and add `from tests.cli_helpers import invoke, ok` to its imports:

```python
def test_purge_counts_the_registry_without_migrating(data, tmp_path):
    seed_shared_ids(tmp_path)  # a migration would abort

    declined = invoke("purge", input="n\n")
    assert declined.exit_code == 1
    assert "Delete all brd data for 2 project(s)?" in declined.stdout
    assert not paths.brd_db_path().exists()

    assert ok("purge", "--yes") == {"projects_removed": 2}
    assert not data.exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest -q`
Expected: failures in `tests/test_master.py` (no `brd.db`, `registry_count` and the new `registered_project` signature are missing), `tests/test_cli_app.py`, `tests/test_cli.py` (`test_init_registers_project`, the `foreign` fixtures, the T15 test) and `tests/test_migration.py::test_docs_dir_sits_next_to_the_db`. `test_purge_counts_the_registry_without_migrating` may already pass, because today's `purge` reads `master.db` without migrating. It guards the switch below.

- [ ] **Step 3: Point `db.docs_dir` at `docs/`**

In `src/brd/db.py`, replace `docs_dir`:

```python
def docs_dir(conn: sqlite3.Connection) -> Path:
    """Directory holding document backups: next to the db, `<db stem>.docs`."""
    main = next(row for row in conn.execute("PRAGMA database_list") if row["name"] == "main")
    return Path(main["file"]).with_suffix(".docs")
```

with:

```python
def docs_dir(conn: sqlite3.Connection) -> Path:
    """Directory holding document backups: `docs/` next to the db file. For
    brd.db that is paths.docs_dir()."""
    main = next(row for row in conn.execute("PRAGMA database_list") if row["name"] == "main")
    return Path(main["file"]).parent / "docs"
```

- [ ] **Step 4: Rewrite the registry functions on brd.db**

In `src/brd/master.py`, replace everything from `def _master_conn():` to the end of the file (the old `_master_conn`, `_copy_cards`, `_migrate_in_repo_format`, `_migrate_legacy_uuid_marker`, `_board_project`, `_settle_project`, `init_project`, `find_marker`, `resolve_project_root`, `registered_project`, `resolve_project_db`, `list_all_projects`, `forget_project` and `purge_all`) with:

```python
def _copy_cards(conn: sqlite3.Connection, old_db_path: Path, project: Project) -> None:
    """Copy a legacy board's cards, and the edges between them, into brd.db
    under project, whose projects row is already there."""
    old_conn = db.connect(old_db_path)
    try:
        copied: set[str] = set()
        with conn:
            for row in old_conn.execute("SELECT * FROM cards"):
                db.insert_entity(conn, project.id, row["id"], "card")
                conn.execute(
                    "INSERT INTO cards (id, title, description, status, "
                    "parent_id, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    tuple(row),
                )
                copied.add(row["id"])
            for row in old_conn.execute("SELECT card_id, blocks_on_id FROM blocked_by"):
                # Same rule as _migrate_to_v1: keep only edges between copied
                # cards. Edge targets have no FK, so nothing else would stop one.
                if row["card_id"] in copied and row["blocks_on_id"] in copied:
                    conn.execute(
                        "INSERT INTO blocked_by (card_id, blocks_on_id) VALUES (?, ?)",
                        tuple(row),
                    )
    finally:
        old_conn.close()


def _migrate_in_repo_format(conn: sqlite3.Connection, marker_dir: Path, project: Project) -> None:
    """Migrate the in-repo format (.brd/ directory with board.db, committed
    to git) back to central storage."""
    old_db_path = marker_dir / "board.db"
    if old_db_path.is_file():
        _copy_cards(conn, old_db_path, project)
    shutil.rmtree(marker_dir)


def _migrate_legacy_uuid_marker(conn: sqlite3.Connection, marker_file: Path, project: Project) -> None:
    """Migrate the original design (.brd file holding a UUID, cards in a
    central per-project db keyed by that UUID)."""
    legacy_id = marker_file.read_text().strip()
    old_db_path = paths.data_dir() / "projects" / f"{legacy_id}.db"
    if legacy_id and old_db_path.is_file():
        _copy_cards(conn, old_db_path, project)


def init_project(root_path: Path, name: str | None = None) -> Project:
    marker = root_path / MARKER_FILENAME
    conn = connect()
    try:
        # A root that is already registered keeps its id and created_at;
        # only the name changes.
        project = db.upsert_project(
            conn,
            Project(
                id=db.new_project_id(),
                name=name or root_path.name,
                root_path=str(root_path),
                created_at=_now(),
            ),
        )
        if marker.is_dir():
            _migrate_in_repo_format(conn, marker, project)
        elif marker.is_file():
            _migrate_legacy_uuid_marker(conn, marker, project)
    finally:
        conn.close()

    marker.write_text("")

    gitignore = root_path / ".gitignore"
    existing_lines = gitignore.read_text().splitlines() if gitignore.exists() else []
    if MARKER_FILENAME not in existing_lines:
        with gitignore.open("a") as f:
            if existing_lines and existing_lines[-1] != "":
                f.write("\n")
            f.write(f"{MARKER_FILENAME}\n")

    return project


def find_marker(start: Path) -> Path | None:
    current = start.resolve()
    while True:
        candidate = current / MARKER_FILENAME
        if candidate.is_file():
            return candidate
        if current.parent == current:
            return None
        current = current.parent


def resolve_project_root(start: Path) -> Path:
    marker = find_marker(start)
    if marker is None:
        raise ProjectNotFoundError(f"no {MARKER_FILENAME} marker found above {start}")
    return marker.parent


def registered_project(conn: sqlite3.Connection, root_path: Path) -> Project:
    project = db.get_project(conn, str(root_path))
    if project is None:
        raise ProjectNotFoundError(
            f"{root_path} has a {MARKER_FILENAME} marker but is not a registered "
            "project; run `brd init` there"
        )
    return project


def list_all_projects() -> list[Project]:
    conn = connect()
    try:
        return db.list_projects(conn)
    finally:
        conn.close()


def forget_project(root_path: Path) -> Project:
    conn = connect()
    try:
        project = db.get_project(conn, str(root_path))
        if project is None:
            raise ProjectNotFoundError(f"no registered project at {root_path}")
        # Read before the delete: the cascade through entities removes them.
        doc_ids = [
            row["id"]
            for row in conn.execute(
                "SELECT id FROM entities WHERE project_id = ? AND kind = 'document'",
                (project.id,),
            )
        ]
        db.delete_project(conn, str(root_path))
    finally:
        conn.close()

    for doc_id in doc_ids:
        (paths.docs_dir() / f"{doc_id}.md").unlink(missing_ok=True)

    marker = root_path / MARKER_FILENAME
    if marker.is_file():
        marker.unlink()

    return project


def _count_projects(db_path: Path, min_version: int) -> int | None:
    conn = db.connect(db_path)
    try:
        if _version(conn) < min_version:
            return None
        has_table = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'projects'"
        ).fetchone()[0]
        if not has_table:
            return 0
        return conn.execute("SELECT COUNT(DISTINCT root_path) FROM projects").fetchone()[0]
    finally:
        conn.close()


def registry_count() -> int:
    """How many projects are registered, read without migrating: purge is the
    way out when a migration aborts. brd.db once migrated, else master.db,
    else 0."""
    if paths.brd_db_path().is_file():
        count = _count_projects(paths.brd_db_path(), db.SCHEMA_VERSION)
        if count is not None:
            return count
    if paths.master_db_path().is_file():
        return _count_projects(paths.master_db_path(), 0)
    return 0


def purge_all() -> int:
    count = registry_count()
    shutil.rmtree(paths.data_dir())
    return count
```

- [ ] **Step 5: Open projects through `master.connect`**

In `src/brd/cli/_app.py`, replace L9 `from brd import db, master, output, paths` with:

```python
from brd import master, output
```

Replace `open_project` (L64-73) with:

```python
def open_project() -> Ctx:
    # Connect (and so migrate) first: any data command on an unmigrated
    # install migrates, even one run outside a project.
    conn = master.connect()
    try:
        root = master.resolve_project_root(Path.cwd())
        project = master.registered_project(conn, root)
    except BaseException:
        conn.close()
        raise
    return Ctx(conn=conn, project=project)
```

In `src/brd/cli/project.py`, in `purge`, replace L61 `all_projects = master.list_all_projects()` and its use in the prompt:

```python
    all_projects = master.list_all_projects()
    if not yes:
        confirmed = typer.confirm(
            f"Delete all brd data for {len(all_projects)} project(s)? "
            "This cannot be undone."
        )
```

with:

```python
    # Never migrates: purge must work when a migration aborts.
    count = master.registry_count()
    if not yes:
        confirmed = typer.confirm(
            f"Delete all brd data for {count} project(s)? "
            "This cannot be undone."
        )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass, 603 passed. That is 600, plus 3 new tests in `test_master.py` (T16, Review Focus 4, `registry_count`), minus 3 deleted from `test_master.py`, plus 1 net in `test_cli_app.py`, plus 1 T15, plus 1 T14. If the count differs, make sure nothing failed; the exact number is not the point.

Run: `grep -rn "project_db_path\|project_docs_dir\|_master_conn\|resolve_project_db" src/`
Expected: only `src/brd/paths.py` (the definitions) and `src/brd/consolidate.py` (legacy inputs).

- [ ] **Step 7: Commit**

```bash
git add src/brd/master.py src/brd/db.py src/brd/cli/_app.py src/brd/cli/project.py \
  tests/test_master.py tests/test_cli_app.py tests/test_cli.py tests/test_snapshot.py \
  tests/test_migration.py tests/test_single_db_migration.py
git commit -m "Read and write every project in brd.db; backups move to docs/

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: User-facing migration: error envelopes for init/projects, stderr notice, CLI checks

**Files:**
- Modify: `src/brd/cli/project.py:17-34` (`init`, `projects`)
- Test: `tests/test_single_db_migration.py` (append)

**Interfaces:**
- Consumes: everything above. Test helpers `data`, `register`, `board_path`, `backups_path`, `migrated`, `v4_board`, `add_document`, `seed_shared_ids`, `assert_nothing_migrated`, `NOTICE`, `invoke`, `ok`.
- Produces: `brd init` and `brd projects` turn a `BrdError` (e.g. `MigrationError`) into the error envelope and exit code 1.

- [ ] **Step 1: Write the failing tests**

Add `import json` to the imports of `tests/test_single_db_migration.py`. Append:

```python
@pytest.mark.parametrize("args", [["list"], ["projects"], ["init"]])
def test_unreadable_board_is_a_migration_error_envelope(data, tmp_path, monkeypatch, args):
    owner = register(tmp_path, "owner")
    board_path(owner).write_bytes(b"not a database " * 100)
    root = Path(owner.root_path)
    (root / ".brd").write_text("")
    monkeypatch.chdir(root)

    result = invoke(*args)

    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)  # an envelope, not a traceback
    error = json.loads(result.stdout)["error"]
    assert error["type"] == "MigrationError"
    assert "owner" in error["message"]
    assert str(board_path(owner)) in error["message"]
    assert result.stderr == ""


def test_shared_ids_fail_the_command_and_a_retry_succeeds(data, tmp_path, monkeypatch):
    first, second = seed_shared_ids(tmp_path)
    (Path(first.root_path) / ".brd").write_text("")
    monkeypatch.chdir(first.root_path)

    result = invoke("list")

    assert result.exit_code == 1
    error = json.loads(result.stdout)["error"]
    assert error["type"] == "MigrationError"
    for text in ("first", "second", "dup", "k-dup"):
        assert text in error["message"]
    assert result.stderr == ""
    assert_nothing_migrated([first, second])
    assert not (data / "docs").exists()

    conn = db.connect(board_path(second))
    db.delete_card(conn, "dup")
    conn.close()
    retry = invoke("list")
    assert retry.exit_code == 0
    assert [c["id"] for c in json.loads(retry.stdout)["data"]] == ["dup"]
    assert retry.stderr.startswith(NOTICE.format(n=2))


def test_skipped_unregistered_boards_are_reported_on_stderr(data, tmp_path, monkeypatch):
    kept = register(tmp_path, "kept")
    (data / "projects").mkdir(parents=True, exist_ok=True)
    stray = data / "projects" / "stray.db"
    _make_v0(stray, cards=[("s-1", None)], edges=[])
    monkeypatch.chdir(tmp_path)

    result = invoke("projects")

    assert result.exit_code == 0
    assert [p["id"] for p in json.loads(result.stdout)["data"]] == [kept.id]
    assert result.stderr == (
        NOTICE.format(n=1)
        + "\nbrd: skipped 1 unregistered board files: projects/stray.db\n"
    )
    assert stray.is_file() and not migrated(stray).exists()


def test_commands_read_backups_from_the_shared_docs_dir(data, tmp_path, monkeypatch):
    owner = register(tmp_path, "owner")
    conn = v4_board(owner)
    add_document(conn, owner, "doc-1", "notes", "# Notes\nbody\n")
    conn.close()
    root = Path(owner.root_path)
    (root / ".brd").write_text("")
    monkeypatch.chdir(root)

    ok("doc", "restore", "doc-1")

    assert (root / "docs" / "notes.md").read_text() == "# Notes\nbody\n"
    assert not backups_path(owner).exists()
    assert (paths.docs_dir() / "doc-1.md").is_file()


def test_notice_goes_to_stderr_and_stdout_stays_one_envelope(data, tmp_path, monkeypatch):
    for name in ("one", "two"):
        project = register(tmp_path, name)
        conn = v4_board(project)
        make_card(conn, f"{name}-card", project_id=project.id)
        conn.close()
    root = tmp_path / "one"
    (root / ".brd").write_text("")
    monkeypatch.chdir(root)

    first = invoke("list")
    assert first.exit_code == 0
    assert [c["id"] for c in json.loads(first.stdout)["data"]] == ["one-card"]
    assert first.stderr.startswith(NOTICE.format(n=2))

    second = invoke("list")
    assert second.exit_code == 0
    assert second.stderr == ""
    assert json.loads(second.stdout) == json.loads(first.stdout)


def test_fresh_install_init_creates_brd_db_without_notice(data, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)

    result = invoke("init")

    assert result.exit_code == 0
    assert json.loads(result.stdout)["ok"] is True
    assert result.stderr == ""
    conn = db.connect(paths.brd_db_path())
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert [r[0] for r in conn.execute("SELECT root_path FROM projects")] == [str(repo)]
    finally:
        conn.close()
    assert not paths.master_db_path().exists()
    assert not (data / "projects").exists()


def test_command_outside_any_project_still_migrates(data, tmp_path, monkeypatch):
    owner = register(tmp_path, "owner")
    conn = v4_board(owner)
    make_card(conn, "c1", project_id=owner.id)
    conn.close()
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)

    result = invoke("list")

    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["type"] == "ProjectNotFoundError"
    assert result.stderr.startswith(NOTICE.format(n=1))
    assert migrated(paths.master_db_path()).is_file()


@pytest.mark.parametrize("args", [["prompt"], ["--help"], ["doc", "--help"]])
def test_commands_without_data_do_not_migrate(data, tmp_path, args):
    register(tmp_path, "owner")

    result = invoke(*args)

    assert result.exit_code == 0
    assert result.stderr == ""
    assert paths.master_db_path().is_file()
    assert not paths.brd_db_path().exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_single_db_migration.py -q`
Expected: `test_unreadable_board_is_a_migration_error_envelope[projects]` and `[init]` fail. The `MigrationError` escapes uncaught (`result.exception` is the `MigrationError`, and `json.loads("")` raises). The other new tests should pass already; they pin the user-visible behaviour of Tasks 2-5.

- [ ] **Step 3: Add the envelopes**

In `src/brd/cli/project.py`, replace the bodies of `init` and `projects`:

```python
    """Register the current directory as a brd project."""
    project = master.init_project(Path.cwd(), name=name)
    output.print_result(output.ok_envelope(dataclasses.asdict(project)), pretty)
```

with:

```python
    """Register the current directory as a brd project."""
    try:
        project = master.init_project(Path.cwd(), name=name)
    except BrdError as exc:
        fail(exc, pretty)
    output.print_result(output.ok_envelope(dataclasses.asdict(project)), pretty)
```

and:

```python
    """List all registered projects."""
    all_projects = master.list_all_projects()
    envelope = output.ok_envelope([dataclasses.asdict(p) for p in all_projects])
    output.print_result(envelope, pretty)
```

with:

```python
    """List all registered projects."""
    try:
        all_projects = master.list_all_projects()
    except BrdError as exc:
        fail(exc, pretty)
    envelope = output.ok_envelope([dataclasses.asdict(p) for p in all_projects])
    output.print_result(envelope, pretty)
```

(`BrdError` and `fail` are already imported in this file. `forget` already has this handler.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_single_db_migration.py -q`
Expected: all pass.

Run: `uv run pytest -q`
Expected: all pass, 615 passed.

- [ ] **Step 5: Commit**

```bash
git add src/brd/cli/project.py tests/test_single_db_migration.py
git commit -m "Report brd.db migration errors from init and projects as envelopes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Spec coverage check

| Spec item | Task |
|---|---|
| B1 paths, `db.docs_dir`, one `brd.db` connection for every data command, no-data commands untouched | 1, 5, 6 (Review Focus 5) |
| B2 entry point, `BEGIN IMMEDIATE`, re-check, fresh install | 2 (`master.connect`), 4 (concurrency) |
| B3.1-B3.7 registry upgrade, per-board v4 upgrade, duplicate check before copy, row copy (FK off while copying, then checked), FK check, backups, `user_version` | 2, 3 |
| B3 unregistered files left alone | 2 (unit), 6 (stderr) |
| B4 renames, sidecars, ignored `OSError`, stderr notice from the migrator only | 2, 4, 6 |
| B5 abort: `brd.db` at v0, nothing renamed, docs untouched, envelope + exit 1 | 3, 6 |
| B6 concurrent first runs | 4 |
| B7 init/projects/forget/purge/open_project on `brd.db`, envelopes, non-migrating purge count | 5, 6 |
| B8 legacy in-repo formats copy into `brd.db` | 5 (`test_init_project_migrates_*`, `test_copy_cards_drops_dangling_legacy_edges`) |
| T1 / T2 / T9 / T13 | 2 |
| T3 | 2 (unit), 6 (CLI) |
| T4 | 3 (unit), 6 (CLI) |
| T5 | 3 |
| T6 | 3 (unit), 6 (CLI) |
| T7 / T10 | 4 |
| T8 | 2 (unit), 6 (CLI) |
| T11 / T12 | 6 (T12 unit part in 2) |
| T14 / T15 / T16 | 5 |
| Existing tests that must change | 5 (1a-1e) |

**Recommended execution:** Subagent-driven. Tasks 2-6 build on each other's exact names (`master.connect`, `consolidate.migrate`, the test helpers), and a mistake in Task 5's switch would hit every command, so a reviewer between tasks pays for itself.
<!-- task-pipeline: validated -->
