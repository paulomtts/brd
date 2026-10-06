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
