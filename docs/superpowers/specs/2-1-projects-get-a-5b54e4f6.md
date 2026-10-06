# 2.1 Projects get a stable UUID; commands carry the Project

Card: `5b54e4f6-2f76-4697-8f28-2a140887c896` (subtask of story `54de5e9d` "Project-scoped
schema", milestone `6aa7043a` "Single database and cross-project blocking").

Parent design spec: `docs/superpowers/specs/2026-10-06-single-db-cross-project-blocking-design.md`
(commit `98c42de`; not yet merged into this branch's history, cited by section and line
number in that commit). Cited below as **[P §n Lx]**.

## Goal

Every registered project has a stable UUID that never changes once assigned, and every
board command receives the resolved `Project` (id, name, root path, creation time)
instead of a bare root path. This is the identity the rest of the story (entities record
their project, 2.3; scoped queries, 2.4/2.5) hangs off. Still on today's layout: the
projects table stays in `master.db`, boards stay in per-project files, and the current
project is still found through the `.brd` marker.

## Inherited constraints

| Constraint | Source |
|---|---|
| `projects.id` is a uuid4, `TEXT PRIMARY KEY`; `name TEXT NOT NULL`; `root_path TEXT NOT NULL UNIQUE`; `created_at TEXT NOT NULL`. | [P §1 L49-54] |
| `Ctx` becomes `(conn, project)`. | [P §2 L102] |
| A cwd that resolves to no registered project → `ProjectNotFoundError`. | [P §2 L100-102] |
| Re-running `brd init` in a registered root only updates the name (id and created_at stay). | [P §2 L104-106] |
| `brd projects` lists `id`, `name`, `root_path`. | [P §2 L122] |
| Ownership will live on `entities.project_id` referencing `projects(id)` — so the id must exist and be stable now. | [P D4 L34; §1 L58] |
| Marker-based resolution stays for this card; dropping the marker is a later card. | card description; [P §3 L144, Implementation order L276-278] |

## Behavior

### B1. Project model

`brd.models.Project` has exactly four fields in this order: `id: str`, `name: str`,
`root_path: str`, `created_at: str` (the order the card names). Because CLI output is
`dataclasses.asdict(project)`, every JSON object describing a project has keys in that
order: `id`, `name`, `root_path`, `created_at`.

### B2. master.db `projects` schema and in-place migration

After `db.init_master_schema(conn)` returns, the `projects` table has exactly the
columns `{id, name, root_path, created_at}` with `id` the primary key, `root_path`
`NOT NULL UNIQUE`, and every row's `id` a canonical lowercase uuid4 string
(`str(uuid.uuid4())`), unique across rows.

`init_master_schema` recognises four starting states and must reach the target from each:

| Starting state | How recognised | Result |
|---|---|---|
| No `projects` table | table absent | Target table created, empty. |
| Original legacy (`id` PK, unique `name`, `db_path`, `root_path`, `created_at`) | `db_path` column present | Rebuilt to target. Each row keeps `root_path`, `name`, `created_at` and gets a **fresh** uuid4 (legacy ids were arbitrary strings, e.g. `old-id`, and are discarded). Duplicate `root_path`s collapse to one row (today's `INSERT OR REPLACE` behaviour: last row read wins). |
| Current (`root_path` PK, `name`, `created_at`, no `id`) | no `id` column | Rebuilt to target in place. Every row keeps `root_path`, `name`, `created_at` and gets a fresh uuid4. |
| Target | `id` present, `db_path` absent | **No change.** Ids are untouched. |

Trap to avoid: today the legacy detector is `"id" in columns` (`src/brd/db.py:20`).
With the new column that test would treat every target table as legacy and rebuild it
(new ids on every command). The legacy detector must key on `db_path`.

Properties:

- **Stable.** Calling `init_master_schema` any number of times, on the same or on new
  connections to the same file, after the first migration, never changes any row's
  id. (It runs on every command via `master._master_conn`, `src/brd/master.py:16-19`.)
- **Atomic.** A migration either completes or leaves the table exactly as it was;
  never a half-built table or rows without ids.
- **Concurrent-safe.** Two processes running a first command at once on an
  un-migrated `master.db` end up with one set of ids — the second process sees the
  migrated table and changes nothing. (Take a write lock, e.g. `BEGIN IMMEDIATE`,
  then re-read the columns inside the transaction before deciding.)

### B3. Registering and reading projects (`db.py`)

- `db.upsert_project(conn, project) -> Project`:
  - `root_path` not registered: inserts the row with the given `id`, `name`,
    `created_at`; returns it.
  - `root_path` already registered: updates **only** `name`; the stored `id` and
    `created_at` are kept; returns the stored row (with the new name). The passed-in
    `id`/`created_at` are ignored.
- `db.get_project(conn, root_path)`, `db.list_projects(conn)` return `Project`s with
  `id` populated. `list_projects` order is unchanged (by `created_at`).
- `db.get_project_by_id(conn, project_id) -> Project | None` is **not** added here
  (no caller in this card; `forget --project <id>` belongs to a later card).
- `db.delete_project(conn, root_path)` unchanged.

### B4. `brd init`

- First run in a directory: registers it with a new uuid4; output (`ok` envelope) is
  the project with keys `id, name, root_path, created_at`.
- Re-run in a registered root (with or without `--name`): output carries the **same**
  `id` and the **original** `created_at` as the stored row; `name` is updated if
  `--name` is given (or reset to the dir name if not, as today). `master.init_project`
  returns what `upsert_project` returns, not a freshly built object.
- Everything else `init` does today (marker file, `.gitignore` line, in-repo and
  UUID-marker board migrations, per-project db creation) is unchanged.

### B5. `brd projects`, `brd forget`

- `brd projects` JSON: each entry has `id`, `name`, `root_path`, `created_at`; `id`
  equals the id `brd init` reported for that root. `--pretty` keeps today's generic
  rendering (it will now include the id; no new renderer required).
- `brd forget [path]` JSON: the removed project including its `id`. Lookup is still by
  root path. Behaviour otherwise unchanged.
- `brd purge` unchanged.

### B6. Commands carry the Project (`cli/_app.py`)

- `Ctx` is a dataclass with exactly two fields: `conn: sqlite3.Connection` and
  `project: Project`. No `root` field.
- `open_project()`:
  1. Resolves the root with `master.resolve_project_root(Path.cwd())` (marker
     resolution unchanged; no marker → `ProjectNotFoundError` as today).
  2. Looks the root up in `master.db` (`db.get_project(conn, str(root))`) and closes
     that master connection before returning or raising.
  3. Root has a marker but no registered row → `ProjectNotFoundError` whose message
     names the root and tells the user to run `brd init` there. The board db is not
     opened or created in that case. (Per [P §2 L100-102]; no auto-registration.)
  4. Opens and migrates the project db exactly as today
     (`paths.project_db_path(root)`, `db.migrate_project`), closing it if migration
     raises.
- Every command that used `ctx.root` passes `Path(ctx.project.root_path)` instead:
  `src/brd/cli/docs.py:23,39,63,78`, `src/brd/cli/snapshot.py:14,31`,
  `src/brd/cli/cards.py:54`. Observable behaviour of those commands is unchanged.
- Errors still surface through `fail()` as `{"ok": false, "error": {"type":
  "ProjectNotFoundError", ...}}` with exit code 1.

## Out of scope

- Moving `projects` out of `master.db` / single `brd.db`, the v4 schema, the
  migration from per-project files (S3 / [P §3]).
- `entities.project_id`, `documents.project_id`, dropping edge-target FKs (2.3).
- Explicit incoming-edge cleanup on delete (2.2).
- Any query scoping by project (2.4, 2.5); `brd show` reporting the owning project.
- Dropping the `.brd` marker, deepest-ancestor resolution, `init --relink`,
  `forget --project <id>` (later S3 cards, [P §2]).
- Export/import carrying project metadata ([P §5]).
- `paths.project_db_path` keeps hashing the root path; per-project file names do not
  change.

## Tests

Tiers in this repo: **unit** = direct calls into `brd.db` / `brd.models` with a temp
sqlite file (`tests/test_db.py`, `tests/test_models.py`); **integration** = `brd.master`
functions against an isolated `XDG_DATA_HOME` (`tests/test_master.py`); **CLI** = typer
`CliRunner` through `tests/cli_helpers` or `runner.invoke` (`tests/test_cli.py`,
`tests/test_cli_app.py`). All plain pytest.

### Unit — `tests/test_db.py` (schema/migration logic is pure SQL; cheapest place to pin every starting state)

1. `init_master_schema` on an empty db → columns `{id, name, root_path, created_at}`;
   `id` is the PK (`PRAGMA table_info` pk flag); `root_path` unique.
   (replaces `test_init_master_schema_creates_projects_table`)
2. Inserting two rows with the same `root_path` and different ids raises
   `IntegrityError`; inserting two rows with the same id raises `IntegrityError`.
   (replaces `test_projects_root_path_is_primary_key`)
3. Current 3-column table with two rows → after migration each row keeps
   `root_path/name/created_at`, has a valid uuid4 id (`uuid.UUID(id).version == 4`),
   ids differ.
4. Migration is stable: run `init_master_schema` three times (also once from a second
   connection to the same file) on a migrated current-shape table → ids identical to
   after the first run.
5. Original legacy table with `id='old-id'` → columns are the target set, row keeps
   root/name/created_at, id is a fresh uuid4 (≠ `'old-id'`). (updates
   `test_init_master_schema_migrates_legacy_schema_preserving_rows`)
6. Legacy migration then repeated calls → ids stable. (extends
   `test_init_master_schema_migration_is_idempotent`)
7. Migration atomicity: a current-shape table whose rebuild is forced to fail midway
   (e.g. monkeypatched uuid generator raising on the second row) → the table is
   unchanged (still 3 columns, original rows) and the error propagates.
8. `upsert_project` new root → `list_projects` returns exactly that Project (id
   included); return value equals it.
9. `upsert_project` same root, different id/created_at/name → one row; name updated;
   id and created_at are the first ones; return value equals the stored row.
10. Existing `test_list_projects_*` and `_sample_project` updated for the `id` field.

### Unit — `tests/test_models.py` (dataclass shape is a contract for `asdict` output)

11. `Project` keyword construction with `id`; positional order is
    `(id, name, root_path, created_at)`. (updates both Project tests)

### Integration — `tests/test_master.py` (init/forget compose db + filesystem)

12. `init_project` returns a Project with a uuid4 id equal to the stored row.
13. `init_project` twice on one root (second time with a new name) → same id, same
    created_at, new name; `list_all_projects` has one entry with that id.
14. Two different roots → two distinct ids.
15. `forget_project` returns the Project with its id.

### CLI — `tests/test_cli.py` (JSON output is the user-facing contract)

16. `brd init` JSON data keys are exactly `["id", "name", "root_path", "created_at"]`
    in that order; `id` parses as uuid4.
17. `brd projects` entry `id` equals the id from `brd init`; re-running `brd init`
    leaves it unchanged.
18. `brd forget` JSON includes the id.

### CLI — `tests/test_cli_app.py` (Ctx/open_project wiring and error envelope)

19. A command run inside a project receives `ctx.project` equal to the registered
    Project (e.g. register a throwaway command on a test typer app or call
    `_app.open_project()` directly from inside the `project` fixture repo and compare
    with `master.list_all_projects()[0]`), and `Ctx` has no `root` attribute.
20. Marker present but root not registered (write `.brd` by hand, never `init`) →
    `err("list") == "ProjectNotFoundError"`, message mentions `brd init`, and no
    project db file is created at `paths.project_db_path(repo)`.
21. Run from a subdirectory of a registered project → resolves the same Project.
22. `test_commands_migrate_a_v0_board` updated: register the repo directly in
    `master.db` (`master._master_conn()` + `db.upsert_project`) instead of relying on
    an unregistered marker, so it still proves a v0 board migrates on first command.
23. `test_open_project_closes_connection_when_migration_fails` updated: it now
    observes two `db.connect` calls (master, then project); assert **every** opened
    connection is closed, not `len(opened) == 1`.
24. Existing docs/snapshot/`show` CLI tests stay green unchanged (proves the
    `ctx.root` → `ctx.project.root_path` conversion).

## Review focus (inputs the tests above might miss)

- A `master.db` touched by an older brd and a newer brd alternately: the older brd's
  `"id" in columns` check would DROP and rebuild the new table without ids. Not
  fixable here; call it out in the commit message / release notes ("upgrade every
  installed copy together", as [P §3 L146-147] already says).
- Root path string mismatch between what `init` stored and what marker resolution
  returns (symlinked cwd, trailing slash): both must come from the resolved cwd so
  `get_project(str(root))` finds the row; otherwise users get a spurious
  `ProjectNotFoundError`.
- Empty legacy/current tables migrate without error.
- `brd projects --pretty` with the new field still prints (generic `str(data)` path).
