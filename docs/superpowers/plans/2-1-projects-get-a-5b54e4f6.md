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

---

# Projects Get a Stable UUID Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every registered project gets a uuid4 `id` that never changes once assigned, and every board command receives the resolved `Project` through `Ctx(conn, project)` instead of a bare root path.

**Architecture:** `master.db`'s `projects` table gains `id TEXT PRIMARY KEY NOT NULL` with `root_path` demoted to `NOT NULL UNIQUE`. `db.init_master_schema` returns immediately when the table already has the target shape. Otherwise it takes `BEGIN IMMEDIATE`, re-reads the columns, and either creates the table or rebuilds a legacy/pre-id table into `projects_new`, assigning fresh ids, then swaps it in. A failure rolls the whole rebuild back. `db.upsert_project` keeps the stored id/created_at on conflict and returns the stored row. `master.init_project` returns that row. A new `master.registered_project(root)` looks the marker-resolved root up in `master.db` and raises `ProjectNotFoundError` when it is not registered. `cli._app.open_project` calls it before opening the board db.

**Tech Stack:** Python 3.12+, SQLite (`sqlite3`, `uuid`), typer, pytest, run with `uv run pytest`.

**Spec:** `docs/superpowers/specs/2-1-projects-get-a-5b54e4f6.md` (reproduced in full above this plan).

## Global Constraints

- `projects` columns are exactly `id`, `name`, `root_path`, `created_at`. `id` is the only primary key (`TEXT PRIMARY KEY NOT NULL`), and `root_path` is `TEXT NOT NULL UNIQUE`. Ids are `str(uuid.uuid4())`: canonical, lowercase.
- `Project` fields are, in order: `id: str`, `name: str`, `root_path: str`, `created_at: str`.
- The legacy detector keys on `db_path`, never on `"id" in columns`.
- `init_master_schema` never changes an existing target table: no new ids, no rebuild.
- A migration either completes or leaves the table exactly as it was.
- Re-running `brd init` only updates `name`. `id` and `created_at` keep their stored values.
- `Ctx` is a dataclass with exactly two fields, `conn: sqlite3.Connection` and `project: Project`. There is no `root` field.
- A marker without a registered row raises `ProjectNotFoundError`, and its message names the root and says `brd init`. No auto-registration. The board db is not opened or created.
- Marker resolution (`master.resolve_project_root`), `paths.project_db_path`, `brd purge`, and per-project db file names are unchanged.
- Do not add `db.get_project_by_id`.
- Verification command: `uv run pytest` (`HACKING.md:3`). There is no lint or typecheck step.

## Review Focus

1. **Empty legacy/current tables.** A `master.db` whose `projects` table exists but has no rows must migrate to the target shape without error. Pinned by `test_init_master_schema_migrates_empty_current_table` and `test_init_master_schema_migrates_empty_legacy_table` (Task 1).
2. **Duplicate `root_path` rows in the original legacy table.** Legacy `root_path` was not unique. Inserting the duplicates into the new `UNIQUE` column must not raise: they collapse to one row. Pinned by `test_init_master_schema_collapses_duplicate_legacy_root_paths` (Task 1).
3. **Root-path string mismatch.** The user runs from a subdirectory or through a symlinked cwd. `init` stores `str(Path.cwd())`, and resolution returns the resolved marker parent. These must be the same string, or the user gets a spurious `ProjectNotFoundError`. Pinned by `test_open_project_from_a_subdirectory_resolves_the_same_project` and `test_open_project_through_a_symlinked_cwd_resolves_the_same_project` (Task 2).
4. **`brd projects --pretty` with the new field.** The generic `str(data)` path must still print, and it must include the id. Pinned by `test_projects_pretty_includes_the_id` (Task 1).
5. **Re-running `brd init` without `--name` after a rename.** This resets the name to the directory name and keeps the id. Pinned by the `third` assertions in `test_init_project_rerun_keeps_id_and_created_at` (Task 1).

Not testable here, so it goes in the commit message instead: an older brd binary running against an upgraded `master.db` uses `"id" in columns` and will DROP and rebuild the table without ids. Every installed copy must be upgraded together.

---

### Task 1: Projects have a stable uuid4 id (model, master.db schema/migration, init/projects/forget output)

Covers spec B1-B5 and spec tests 1-18.

**Files:**
- Modify: `src/brd/models.py:5-8` (`Project`)
- Modify: `src/brd/db.py:1-2` (imports), `src/brd/db.py:18-52` (`init_master_schema`), `src/brd/db.py:266-280` (`_row_to_project`, `upsert_project`)
- Modify: `src/brd/master.py:89-100` (`init_project` tail)
- Test: `tests/test_models.py:4-11,29-37`
- Test: `tests/test_db.py:1-6` (imports), `27-82`, `116-126`, `172-250`
- Test: `tests/test_master.py` (append), `tests/test_cli.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `brd.models.Project(id: str, name: str, root_path: str, created_at: str)`, a dataclass with fields in that order.
  - `brd.db.new_project_id() -> str`, which returns `str(uuid.uuid4())`. Task 2's tests use it, and the atomicity test monkeypatches it.
  - `brd.db.init_master_schema(conn) -> None`, which reaches the target schema from all four starting states.
  - `brd.db.upsert_project(conn, project: Project) -> Project`, which returns the stored row.
  - `brd.db.get_project(conn, root_path: str) -> Project | None` and `brd.db.list_projects(conn) -> list[Project]`, now with `id`.
  - `brd.master.init_project(root_path: Path, name: str | None = None) -> Project`, which returns the stored row.

- [ ] **Step 1: Update the Project model tests**

In `tests/test_models.py`, replace `test_project_fields` (lines 4-11) with:

```python
def test_project_fields():
    p = Project(
        id="0b5e7c1a-4a3e-4c7e-9a52-3f1d2b6c8e90",
        name="brd",
        root_path="/repo",
        created_at="2026-09-17T00:00:00",
    )
    assert p.id == "0b5e7c1a-4a3e-4c7e-9a52-3f1d2b6c8e90"
    assert p.name == "brd"
    assert p.root_path == "/repo"
```

and replace `test_project_field_order_is_positional` (lines 29-37) with:

```python
def test_project_field_order_is_positional():
    p = Project(
        "0b5e7c1a-4a3e-4c7e-9a52-3f1d2b6c8e90",
        "brd",
        "/repo",
        "2026-09-17T00:00:00",
    )
    assert p.id == "0b5e7c1a-4a3e-4c7e-9a52-3f1d2b6c8e90"
    assert p.name == "brd"
    assert p.root_path == "/repo"
    assert p.created_at == "2026-09-17T00:00:00"
```

- [ ] **Step 2: Write the failing master.db schema and project-row tests**

In `tests/test_db.py`, change the imports at the top (lines 1-6) to:

```python
import sqlite3
import uuid

import pytest

from brd import db
from brd.models import Card, Project
```

Replace lines 27-82 with the block below. The range starts at `def test_init_master_schema_creates_projects_table` and runs up to, but not including, `def test_init_project_schema_creates_cards_and_blocked_by_tables`. Together these tests cover spec tests 1, 3, 4, 5, 6 and 7, and Review Focus 1 and 2:

```python
def _project_table_info(conn):
    return {row["name"]: row for row in conn.execute("PRAGMA table_info(projects)")}


def _project_rows(conn):
    return {
        row["root_path"]: dict(row)
        for row in conn.execute("SELECT * FROM projects")
    }


def _is_uuid4(value):
    return uuid.UUID(value).version == 4 and str(uuid.UUID(value)) == value


def _create_current_projects_table(conn, rows=()):
    conn.execute(
        """
        CREATE TABLE projects (
            root_path TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.executemany(
        "INSERT INTO projects (root_path, name, created_at) VALUES (?, ?, ?)", rows
    )
    conn.commit()


def _create_legacy_projects_table(conn, rows=()):
    conn.execute(
        """
        CREATE TABLE projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            root_path TEXT NOT NULL,
            db_path TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.executemany(
        "INSERT INTO projects (id, name, root_path, db_path, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def test_init_master_schema_creates_projects_table(conn):
    db.init_master_schema(conn)
    info = _project_table_info(conn)
    assert set(info) == {"id", "name", "root_path", "created_at"}
    assert info["id"]["pk"] == 1
    assert [name for name, row in info.items() if row["pk"]] == ["id"]
    assert _project_rows(conn) == {}


def test_init_master_schema_is_idempotent(conn):
    db.init_master_schema(conn)
    db.init_master_schema(conn)  # must not raise


def test_init_master_schema_migrates_current_schema_assigning_uuid4_ids(conn):
    _create_current_projects_table(
        conn,
        [
            ("/repo1", "one", "2026-01-01T00:00:00"),
            ("/repo2", "two", "2026-01-02T00:00:00"),
        ],
    )

    db.init_master_schema(conn)

    assert set(_project_table_info(conn)) == {"id", "name", "root_path", "created_at"}
    rows = _project_rows(conn)
    assert {k: (v["name"], v["created_at"]) for k, v in rows.items()} == {
        "/repo1": ("one", "2026-01-01T00:00:00"),
        "/repo2": ("two", "2026-01-02T00:00:00"),
    }
    ids = [row["id"] for row in rows.values()]
    assert all(_is_uuid4(i) for i in ids)
    assert len(set(ids)) == 2


def test_init_master_schema_migrates_empty_current_table(conn):
    _create_current_projects_table(conn)
    db.init_master_schema(conn)
    assert set(_project_table_info(conn)) == {"id", "name", "root_path", "created_at"}
    assert _project_rows(conn) == {}


def test_init_master_schema_never_changes_ids_once_assigned(tmp_path):
    db_path = tmp_path / "master.db"
    first = db.connect(db_path)
    _create_current_projects_table(
        first,
        [
            ("/repo1", "one", "2026-01-01T00:00:00"),
            ("/repo2", "two", "2026-01-02T00:00:00"),
        ],
    )
    db.init_master_schema(first)
    ids = {k: v["id"] for k, v in _project_rows(first).items()}

    db.init_master_schema(first)
    db.init_master_schema(first)
    second = db.connect(db_path)
    try:
        db.init_master_schema(second)
        assert {k: v["id"] for k, v in _project_rows(second).items()} == ids
    finally:
        second.close()
    assert {k: v["id"] for k, v in _project_rows(first).items()} == ids
    first.close()


def test_init_master_schema_migrates_legacy_schema_preserving_rows(conn):
    _create_legacy_projects_table(
        conn,
        [("old-id", "legacy-project", "/repo", "/old/db/path.db", "2026-01-01T00:00:00")],
    )

    db.init_master_schema(conn)

    assert set(_project_table_info(conn)) == {"id", "name", "root_path", "created_at"}
    row = conn.execute("SELECT * FROM projects").fetchone()
    assert row["root_path"] == "/repo"
    assert row["name"] == "legacy-project"
    assert row["created_at"] == "2026-01-01T00:00:00"
    assert row["id"] != "old-id"
    assert _is_uuid4(row["id"])


def test_init_master_schema_migrates_empty_legacy_table(conn):
    _create_legacy_projects_table(conn)
    db.init_master_schema(conn)
    assert set(_project_table_info(conn)) == {"id", "name", "root_path", "created_at"}
    assert _project_rows(conn) == {}


def test_init_master_schema_collapses_duplicate_legacy_root_paths(conn):
    _create_legacy_projects_table(
        conn,
        [
            ("a", "first", "/repo", "/a.db", "2026-01-01T00:00:00"),
            ("b", "second", "/repo", "/b.db", "2026-01-02T00:00:00"),
        ],
    )

    db.init_master_schema(conn)

    rows = conn.execute("SELECT * FROM projects").fetchall()
    assert len(rows) == 1
    assert rows[0]["root_path"] == "/repo"
    assert _is_uuid4(rows[0]["id"])


def test_init_master_schema_migration_is_idempotent(conn):
    _create_legacy_projects_table(
        conn,
        [("old-id", "legacy-project", "/repo", "/old/db/path.db", "2026-01-01T00:00:00")],
    )

    db.init_master_schema(conn)
    ids = {k: v["id"] for k, v in _project_rows(conn).items()}
    db.init_master_schema(conn)  # must not raise on the already-migrated table
    db.init_master_schema(conn)

    assert {k: v["id"] for k, v in _project_rows(conn).items()} == ids


def test_init_master_schema_migration_is_atomic(conn, monkeypatch):
    rows = [
        ("/repo1", "one", "2026-01-01T00:00:00"),
        ("/repo2", "two", "2026-01-02T00:00:00"),
    ]
    _create_current_projects_table(conn, rows)
    calls = []
    real_new_project_id = db.new_project_id

    def failing_new_project_id():
        calls.append(None)
        if len(calls) == 2:
            raise RuntimeError("boom")
        return real_new_project_id()

    monkeypatch.setattr(db, "new_project_id", failing_new_project_id)

    with pytest.raises(RuntimeError, match="boom"):
        db.init_master_schema(conn)

    assert set(_project_table_info(conn)) == {"root_path", "name", "created_at"}
    assert sorted(
        tuple(row) for row in conn.execute("SELECT root_path, name, created_at FROM projects")
    ) == rows
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"projects"}
    assert not conn.in_transaction
```

Replace `test_projects_root_path_is_primary_key` (lines 116-126) with the following (spec test 2):

```python
def test_projects_root_path_is_unique(conn):
    db.init_master_schema(conn)
    conn.execute(
        "INSERT INTO projects (id, name, root_path, created_at) VALUES (?, ?, ?, ?)",
        ("id-1", "dup", "/r", "now"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO projects (id, name, root_path, created_at) VALUES (?, ?, ?, ?)",
            ("id-2", "other", "/r", "now"),
        )


def test_projects_id_is_unique_and_required(conn):
    db.init_master_schema(conn)
    conn.execute(
        "INSERT INTO projects (id, name, root_path, created_at) VALUES (?, ?, ?, ?)",
        ("id-1", "one", "/r1", "now"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO projects (id, name, root_path, created_at) VALUES (?, ?, ?, ?)",
            ("id-1", "two", "/r2", "now"),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO projects (id, name, root_path, created_at) VALUES (?, ?, ?, ?)",
            (None, "three", "/r3", "now"),
        )
```

Replace lines 172-250 with the block below. The range starts at `def _sample_project` and runs through the end of `test_delete_project_removes_matching_row`. Leave `test_delete_project_is_a_noop_when_absent` and `test_delete_project_commits_so_another_connection_sees_it` as they are: they call `_sample_project()` with its defaults, which still work. This block covers spec tests 8, 9 and 10:

```python
def _sample_project(
    root_path="/repo",
    name="brd",
    id="11111111-1111-4111-8111-111111111111",
    created_at="2026-09-17T00:00:00",
):
    return Project(id=id, name=name, root_path=root_path, created_at=created_at)


def test_upsert_project_inserts_new(conn):
    db.init_master_schema(conn)
    stored = db.upsert_project(conn, _sample_project())
    assert db.list_projects(conn) == [_sample_project()]
    assert stored == _sample_project()


def test_upsert_project_updates_only_name_on_existing_root_path(conn):
    db.init_master_schema(conn)
    db.upsert_project(conn, _sample_project(name="brd"))
    stored = db.upsert_project(
        conn,
        _sample_project(
            name="renamed",
            id="22222222-2222-4222-8222-222222222222",
            created_at="2026-12-31T00:00:00",
        ),
    )
    expected = _sample_project(name="renamed")
    assert db.list_projects(conn) == [expected]
    assert stored == expected


def test_list_projects_returns_all(conn):
    db.init_master_schema(conn)
    db.upsert_project(conn, _sample_project("/repo1", "brd", id="id-1"))
    db.upsert_project(conn, _sample_project("/repo2", "other", id="id-2"))
    results = db.list_projects(conn)
    assert {(p.id, p.root_path) for p in results} == {("id-1", "/repo1"), ("id-2", "/repo2")}


def test_list_projects_orders_by_created_at(conn):
    db.init_master_schema(conn)
    later = _sample_project("/repo1", "brd", id="id-1", created_at="2026-09-17T12:00:00")
    earlier = _sample_project("/repo2", "other", id="id-2", created_at="2026-09-16T08:00:00")
    db.upsert_project(conn, later)
    db.upsert_project(conn, earlier)
    assert db.list_projects(conn) == [earlier, later]


def test_upsert_project_commits_so_another_connection_sees_it(tmp_path):
    db_path = tmp_path / "master.db"
    writer = db.connect(db_path)
    db.init_master_schema(writer)
    db.upsert_project(writer, _sample_project())
    reader = db.connect(db_path)
    try:
        assert db.list_projects(reader) == [_sample_project()]
    finally:
        reader.close()


def test_get_project_returns_matching_project(conn):
    db.init_master_schema(conn)
    db.upsert_project(conn, _sample_project("/repo1", "brd", id="id-1"))
    db.upsert_project(conn, _sample_project("/repo2", "other", id="id-2"))
    assert db.get_project(conn, "/repo2") == _sample_project("/repo2", "other", id="id-2")


def test_get_project_returns_none_when_absent(conn):
    db.init_master_schema(conn)
    assert db.get_project(conn, "/nope") is None


def test_delete_project_removes_matching_row(conn):
    db.init_master_schema(conn)
    db.upsert_project(conn, _sample_project("/repo1", "brd", id="id-1"))
    db.upsert_project(conn, _sample_project("/repo2", "other", id="id-2"))
    db.delete_project(conn, "/repo1")
    assert [p.root_path for p in db.list_projects(conn)] == ["/repo2"]
```

- [ ] **Step 3: Run the db and model tests to verify they fail**

Run: `uv run pytest tests/test_db.py tests/test_models.py -q`
Expected: `22 failed, 29 passed`. The failures are:
- `TypeError: Project.__init__() got an unexpected keyword argument 'id'` or `takes 4 positional arguments but 5 were given` (model and upsert tests).
- `AssertionError` on column sets (schema tests).
- `sqlite3.OperationalError: table projects has no column named id` (`test_projects_*`).
- `AttributeError: ... has no attribute 'new_project_id'` (atomicity test).

- [ ] **Step 4: Add `id` to the Project model**

In `src/brd/models.py`, replace the `Project` body (lines 5-8) so the class reads:

```python
@dataclass
class Project:
    id: str
    name: str
    root_path: str
    created_at: str
```

- [ ] **Step 5: Rewrite `init_master_schema` in `src/brd/db.py`**

Change the imports at the top of `src/brd/db.py` (lines 1-2) to:

```python
import sqlite3
import uuid
from pathlib import Path
```

Replace the whole `init_master_schema` function (lines 18-52) with:

```python
_PROJECTS_SQL = """
CREATE TABLE {name} (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    root_path TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
)
"""


def new_project_id() -> str:
    return str(uuid.uuid4())


def _project_columns(conn: sqlite3.Connection) -> set[str]:
    return {row[1] for row in conn.execute("PRAGMA table_info(projects)")}


def _is_target_projects(columns: set[str]) -> bool:
    # Key the legacy check on db_path: the original legacy table also had an
    # id column, so "id" alone cannot tell it apart from the target.
    return "id" in columns and "db_path" not in columns


def _rebuild_projects(conn: sqlite3.Connection) -> None:
    """Rebuild a legacy or pre-id projects table into the target shape,
    keeping root_path, name and created_at and assigning fresh ids."""
    rows = conn.execute("SELECT root_path, name, created_at FROM projects").fetchall()
    conn.execute(_PROJECTS_SQL.format(name="projects_new"))
    for row in rows:
        # OR REPLACE collapses duplicate legacy root_paths: last row read wins.
        conn.execute(
            "INSERT OR REPLACE INTO projects_new (id, name, root_path, created_at) "
            "VALUES (?, ?, ?, ?)",
            (new_project_id(), row["name"], row["root_path"], row["created_at"]),
        )
    conn.execute("DROP TABLE projects")
    conn.execute("ALTER TABLE projects_new RENAME TO projects")


def init_master_schema(conn: sqlite3.Connection) -> None:
    if _is_target_projects(_project_columns(conn)):
        return
    conn.commit()
    try:
        # IMMEDIATE takes the write lock up front, so a concurrent first run
        # waits here and then sees the migrated table instead of re-migrating.
        conn.execute("BEGIN IMMEDIATE")
        columns = _project_columns(conn)
        if not columns:
            conn.execute(_PROJECTS_SQL.format(name="projects"))
        elif not _is_target_projects(columns):
            _rebuild_projects(conn)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
```

Notes for the implementer:
- `new_project_id()` must be called by its module-level name inside `_rebuild_projects`, because the atomicity test monkeypatches `db.new_project_id`.
- `NOT NULL` on `id` is deliberate. SQLite lets a non-INTEGER `PRIMARY KEY` hold NULL, and `test_projects_id_is_unique_and_required` pins that NULL is rejected.
- The early `return` is the hot path: this function runs on every command, through `master._master_conn`.

- [ ] **Step 6: Carry `id` through the row helpers and make `upsert_project` return the stored row**

In `src/brd/db.py`, replace `_row_to_project` and `upsert_project` (lines 266-280) with:

```python
def _row_to_project(row: sqlite3.Row) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        root_path=row["root_path"],
        created_at=row["created_at"],
    )


def upsert_project(conn: sqlite3.Connection, project: Project) -> Project:
    """Register project, or rename the one already at its root_path. An
    existing row keeps its id and created_at; returns the stored row."""
    conn.execute(
        "INSERT INTO projects (id, name, root_path, created_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(root_path) DO UPDATE SET name = excluded.name",
        (project.id, project.name, project.root_path, project.created_at),
    )
    conn.commit()
    return get_project(conn, project.root_path)
```

Leave `list_projects`, `get_project` and `delete_project` unchanged. They already `SELECT *` and go through `_row_to_project`.

- [ ] **Step 7: Run the db and model tests to verify they pass**

Run: `uv run pytest tests/test_db.py tests/test_models.py -q`
Expected: `51 passed`.

(`master.init_project` is still broken at this point because it builds a `Project` without an `id`. The next steps fix it.)

- [ ] **Step 8: Write the failing master and CLI tests**

In `tests/test_master.py`, change the imports at the top to:

```python
import shutil
import uuid

import pytest

from brd import db, master, paths
```

and append these tests at the end of the file (spec tests 12-15 and Review Focus 5):

```python
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


def test_forget_project_returns_project_with_its_id(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    project = master.init_project(repo)

    assert master.forget_project(repo) == project
```

In `tests/test_cli.py`, change the first import line `import json` to:

```python
import json
import uuid
```

and append these tests at the end of the file (spec tests 16-18 and Review Focus 4):

```python
def _is_uuid4(value):
    return uuid.UUID(value).version == 4 and str(uuid.UUID(value)) == value


def test_init_reports_project_with_id_first(isolated_env):
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)["data"]
    assert list(data) == ["id", "name", "root_path", "created_at"]
    assert _is_uuid4(data["id"])
    assert data["root_path"] == str(isolated_env)


def test_projects_reports_the_id_init_assigned_and_rerun_keeps_it(isolated_env):
    first = json.loads(runner.invoke(app, ["init"]).stdout)["data"]
    second = json.loads(runner.invoke(app, ["init", "--name", "renamed"]).stdout)["data"]

    listed = json.loads(runner.invoke(app, ["projects"]).stdout)["data"]

    assert second["id"] == first["id"]
    assert second["created_at"] == first["created_at"]
    assert listed == [second]
    assert list(listed[0]) == ["id", "name", "root_path", "created_at"]


def test_projects_pretty_includes_the_id(isolated_env):
    project_id = json.loads(runner.invoke(app, ["init"]).stdout)["data"]["id"]
    result = runner.invoke(app, ["projects", "--pretty"])
    assert result.exit_code == 0
    assert project_id in result.stdout


def test_forget_reports_the_forgotten_project_id(isolated_env):
    project_id = json.loads(runner.invoke(app, ["init"]).stdout)["data"]["id"]
    result = runner.invoke(app, ["forget"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["data"]["id"] == project_id
```

- [ ] **Step 9: Run the master and CLI tests to verify they fail**

Run: `uv run pytest tests/test_master.py tests/test_cli.py -q`
Expected: `37 failed, 56 passed`. Every test that reaches `master.init_project` (including `brd init` through the CLI) fails with `TypeError: Project.__init__() missing 1 required positional argument: 'id'`.

- [ ] **Step 10: Make `init_project` assign a uuid4 and return the stored row**

In `src/brd/master.py`, replace the tail of `init_project` (lines 89-100, from `project = Project(` through `return project`) with:

```python
    project = Project(
        id=db.new_project_id(),
        name=project_name,
        root_path=str(root_path),
        created_at=_now(),
    )
    conn = _master_conn()
    try:
        return db.upsert_project(conn, project)
    finally:
        conn.close()
```

`forget_project`, `list_all_projects` and `purge_all` need no change. They return what `db.get_project`/`db.list_projects` return, which now includes `id`. `cli/project.py` needs no change either: it prints `dataclasses.asdict(project)`, whose key order follows the new field order.

- [ ] **Step 11: Run the master and CLI tests to verify they pass, then the whole suite**

Run: `uv run pytest tests/test_master.py tests/test_cli.py -q`
Expected: `93 passed`.

Run: `uv run pytest -q`
Expected: `427 passed`.

- [ ] **Step 12: Commit**

```bash
git add src/brd/models.py src/brd/db.py src/brd/master.py tests/test_models.py tests/test_db.py tests/test_master.py tests/test_cli.py
git commit -m "Give every registered project a stable uuid4 id

master.db's projects table gains id TEXT PRIMARY KEY; root_path becomes
NOT NULL UNIQUE. init_master_schema migrates the original legacy table
(detected by db_path) and the pre-id table in one BEGIN IMMEDIATE
transaction, assigning fresh uuid4s, and leaves an already-migrated
table untouched. Re-running brd init keeps the id and created_at.

Upgrade every installed copy of brd together: an older brd treats any
projects table with an id column as legacy and rebuilds it without ids."
```

---

### Task 2: Commands carry the resolved Project (`Ctx(conn, project)`)

Covers spec B6 and spec tests 19-24.

**Files:**
- Modify: `src/brd/master.py` (add `registered_project` after `resolve_project_root`, at line 119 before Task 1's edits)
- Modify: `src/brd/cli/_app.py:8-10` (imports), `52-55` (`Ctx`), `63-71` (`open_project`)
- Modify: `src/brd/cli/docs.py:23,39,63,78`, `src/brd/cli/snapshot.py:14,31`, `src/brd/cli/cards.py:1,54`
- Test: `tests/test_master.py` (append), `tests/test_cli_app.py` (rewrite)

**Interfaces:**
- Consumes (from Task 1): `brd.models.Project(id, name, root_path, created_at)`; `brd.db.new_project_id() -> str`; `brd.db.upsert_project(conn, project) -> Project`; `brd.db.get_project(conn, root_path: str) -> Project | None`; `brd.master.init_project(...) -> Project`; `brd.master._master_conn() -> sqlite3.Connection`.
- Produces:
  - `brd.master.registered_project(root_path: Path) -> Project`. It raises `ProjectNotFoundError` (message contains the root and `brd init`) when the root is not registered, and it closes its master connection in every case.
  - `brd.cli._app.Ctx(conn: sqlite3.Connection, project: Project)`.
  - `brd.cli._app.open_project() -> Ctx`.

- [ ] **Step 1: Write the failing `registered_project` tests**

Append these to the end of `tests/test_master.py`:

```python
def test_registered_project_returns_the_registered_row(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    project = master.init_project(repo)

    assert master.registered_project(repo) == project


def test_registered_project_raises_when_root_is_not_registered(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    with pytest.raises(master.ProjectNotFoundError, match="brd init"):
        master.registered_project(repo)
```

- [ ] **Step 2: Write the failing Ctx/open_project tests**

Replace the whole of `tests/test_cli_app.py` with the file below. Two existing tests are updated. `test_commands_migrate_a_v0_board` now registers the repo in `master.db` directly (spec test 22). `test_open_project_closes_connection_when_migration_fails` now expects two connections, master and then project, and asserts that every one of them is closed (spec test 23). The new tests are spec tests 19, 20 and 21, plus Review Focus 3:

```python
import dataclasses
import json
import sqlite3

import pytest

from brd import db, master, paths
from brd.cli import _app
from brd.models import Project
from tests.cli_helpers import err, invoke, ok


def test_cli_is_a_package_exposing_app():
    from brd.cli import app

    assert app is _app.app


def test_commands_migrate_a_v0_board(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".brd").write_text("")
    monkeypatch.chdir(repo)
    master_conn = master._master_conn()
    try:
        db.upsert_project(
            master_conn,
            Project(
                id=db.new_project_id(),
                name="repo",
                root_path=str(repo),
                created_at="2026-01-01T00:00:00",
            ),
        )
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
    conn = db.connect(paths.project_db_path(repo))
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_domain_errors_become_envelopes(project):
    assert err("show", "nope") == "CardNotFoundError"


def test_missing_project_is_an_envelope(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    assert err("list") == "ProjectNotFoundError"


def test_ctx_has_exactly_conn_and_project():
    assert [f.name for f in dataclasses.fields(_app.Ctx)] == ["conn", "project"]


def test_open_project_carries_the_registered_project(project):
    ctx = _app.open_project()
    try:
        assert ctx.project == master.list_all_projects()[0]
        assert ctx.project.root_path == str(project)
        assert not hasattr(ctx, "root")
    finally:
        ctx.conn.close()


def test_open_project_from_a_subdirectory_resolves_the_same_project(project, monkeypatch):
    nested = project / "a" / "b"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    ctx = _app.open_project()
    try:
        assert ctx.project == master.list_all_projects()[0]
    finally:
        ctx.conn.close()


def test_open_project_through_a_symlinked_cwd_resolves_the_same_project(
    project, tmp_path, monkeypatch
):
    link = tmp_path / "link"
    link.symlink_to(project, target_is_directory=True)
    monkeypatch.chdir(link)
    ctx = _app.open_project()
    try:
        assert ctx.project == master.list_all_projects()[0]
    finally:
        ctx.conn.close()


def test_unregistered_marker_is_a_project_not_found_envelope(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".brd").write_text("")
    monkeypatch.chdir(repo)

    result = invoke("list")

    assert result.exit_code == 1
    error = json.loads(result.stdout)["error"]
    assert error["type"] == "ProjectNotFoundError"
    assert "brd init" in error["message"]
    assert str(repo) in error["message"]
    assert not paths.project_db_path(repo).exists()


def test_open_project_closes_connection_when_migration_fails(project, monkeypatch):
    from brd.errors import MigrationError

    opened = []
    real_connect = db.connect

    def tracking_connect(path):
        conn = real_connect(path)
        opened.append(conn)
        return conn

    def failing_migrate(conn):
        raise MigrationError("boom")

    monkeypatch.setattr(db, "connect", tracking_connect)
    monkeypatch.setattr(db, "migrate_project", failing_migrate)
    assert err("list") == "MigrationError"
    assert len(opened) == 2
    for conn in opened:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            conn.execute("SELECT 1")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_master.py tests/test_cli_app.py -q`
Expected: `8 failed, 26 passed`. The failures are:
- `test_registered_project_returns_the_registered_row` and `test_registered_project_raises_when_root_is_not_registered`: `AttributeError: module 'brd.master' has no attribute 'registered_project'`.
- `test_ctx_has_exactly_conn_and_project`: `AssertionError` (`['conn', 'root']`).
- The three `test_open_project_*_resolves_the_same_project` / `carries_the_registered_project` tests: `AttributeError: 'Ctx' object has no attribute 'project'`.
- `test_unregistered_marker_is_a_project_not_found_envelope`: exit code 0, because today an unregistered marker silently creates a board.
- `test_open_project_closes_connection_when_migration_fails`: `assert 1 == 2`.

`test_commands_migrate_a_v0_board` already passes. It is updated now so it keeps passing once unregistered markers are rejected.

- [ ] **Step 4: Add `master.registered_project`**

In `src/brd/master.py`, insert this function directly after `resolve_project_root` and before `resolve_project_db`:

```python
def registered_project(root_path: Path) -> Project:
    conn = _master_conn()
    try:
        project = db.get_project(conn, str(root_path))
    finally:
        conn.close()
    if project is None:
        raise ProjectNotFoundError(
            f"{root_path} has a {MARKER_FILENAME} marker but is not a registered "
            "project; run `brd init` there"
        )
    return project
```

(`ProjectNotFoundError` is already imported at `src/brd/master.py:7`.)

- [ ] **Step 5: Make `Ctx` carry the Project and look it up in `open_project`**

In `src/brd/cli/_app.py`, change the imports (lines 9-10) to:

```python
from brd import db, master, output, paths
from brd.errors import BrdError
from brd.models import Project
```

Replace `Ctx` (lines 52-55) with:

```python
@dataclass
class Ctx:
    conn: sqlite3.Connection
    project: Project
```

Replace `open_project` (lines 63-71) with:

```python
def open_project() -> Ctx:
    root = master.resolve_project_root(Path.cwd())
    project = master.registered_project(root)
    conn = db.connect(paths.project_db_path(root))
    try:
        db.migrate_project(conn)
    except BaseException:
        conn.close()
        raise
    return Ctx(conn=conn, project=project)
```

`run()` is unchanged. It already turns the `ProjectNotFoundError` raised from `open_project` into an error envelope with exit code 1.

- [ ] **Step 6: Replace every `ctx.root` with `Path(ctx.project.root_path)`**

`src/brd/cli/docs.py` already imports `Path`. Make these four edits:

Line 23, in `add`'s `action`:
```python
        doc = documents.add(
            ctx.conn, Path(ctx.project.root_path), path, title=title, tag_list=list(tag_list)
        )
```

Line 39, in `list_cmd`'s `action`:
```python
        results = documents.sync_all(ctx.conn, Path(ctx.project.root_path))
```

Line 63, in `update`'s `action`:
```python
        doc, result = documents.update(
            ctx.conn, Path(ctx.project.root_path), doc_id, new_path=path, title=title
        )
```

Line 78, in `restore`'s `action`:
```python
        doc = documents.restore(ctx.conn, Path(ctx.project.root_path), doc_id, force=force)
```

`src/brd/cli/snapshot.py` already imports `Path`. Make these two edits:

Line 14:
```python
    run(pretty, lambda ctx: snapshot.export(ctx.conn, Path(ctx.project.root_path)))
```

Line 31:
```python
        return snapshot.load(ctx.conn, Path(ctx.project.root_path), raw)
```

`src/brd/cli/cards.py` does not import `Path`. Change its first line from `import sqlite3` to:

```python
import sqlite3
from pathlib import Path
```

and change line 54 (in `show`) to:

```python
        lambda ctx: views.detail(ctx.conn, Path(ctx.project.root_path), entity_id),
```

Then confirm that nothing still uses the old field:

Run: `grep -rn "ctx\.root" src`
Expected: no output.

- [ ] **Step 7: Run the tests to verify they pass, then the whole suite**

Run: `uv run pytest tests/test_master.py tests/test_cli_app.py -q`
Expected: `34 passed`.

Run: `uv run pytest -q`
Expected: `434 passed`. This includes the unchanged docs/snapshot/`show` CLI tests (`tests/test_cli_docs.py`, `tests/test_cli.py`, `tests/test_snapshot.py`), which is spec test 24.

- [ ] **Step 8: Commit**

```bash
git add src/brd/master.py src/brd/cli/_app.py src/brd/cli/docs.py src/brd/cli/snapshot.py src/brd/cli/cards.py tests/test_master.py tests/test_cli_app.py
git commit -m "Pass the resolved Project to every board command

Ctx is now (conn, project). open_project looks the marker-resolved root
up in master.db and raises ProjectNotFoundError (\"run brd init there\")
for a marker with no registered project instead of silently creating a
board. Commands that used ctx.root use Path(ctx.project.root_path)."
```

---

## Self-Review

1. **Spec coverage.**
   - B1: Task 1, Steps 1 and 4.
   - B2: Task 1, Step 5. All four starting states are covered: absent, original legacy, current, and target (by the idempotency tests). Atomicity is pinned by `test_init_master_schema_migration_is_atomic`. Concurrent safety comes from `BEGIN IMMEDIATE` plus re-reading the columns, and the second-connection part of `test_init_master_schema_never_changes_ids_once_assigned` pins that a second connection changes nothing.
   - B3: Task 1, Step 6. No `get_project_by_id` is added.
   - B4: Task 1, Step 10.
   - B5: needs no code change, because `asdict` follows the field order. It is pinned by Task 1's CLI tests.
   - B6: Task 2.
   - Spec tests 1-24: tests 1-7 are in Task 1 Step 2, the schema block. Test 2 is in the pk block. Tests 8-10 are in the upsert block. Test 11 is Step 1. Tests 12-15 are Step 8 (test_master). Tests 16-18 are Step 8 (test_cli). Tests 19-23 are in Task 2 Step 2. Test 24 is the full-suite run in Task 2 Step 7.
2. **Placeholder scan.** Every code step shows full code, and there is no TBD/TODO or "similar to" text. Task 2 repeats the `Project` signature instead of referring back to Task 1.
3. **Type consistency.**
   - `Project(id, name, root_path, created_at)` is the same in the model, `_row_to_project`, `init_project`, and the tests.
   - `db.new_project_id` has the same name in `db.py`, `master.py`, the atomicity test's monkeypatch, and `test_commands_migrate_a_v0_board`.
   - `db.upsert_project` returns `Project`, and `master.init_project` returns that value.
   - `master.registered_project(root_path: Path) -> Project` matches its call site in `open_project` and its tests.
   - `Ctx(conn=..., project=...)` is the same in `_app.py` and in `test_ctx_has_exactly_conn_and_project`.
4. **Review Focus.** All five lines name a test in the task that owns the code. Four of those tests were not in the spec's list and were added: the two empty-table tests, the duplicate-legacy-root test, the `--pretty` id test, and the symlinked-cwd test. Name-reset-on-rerun was folded into spec test 13. The older-binary hazard cannot be tested and goes in Task 1's commit message instead. There is one deliberate addition beyond the spec: `NOT NULL` on `projects.id`. The spec's own goal ("never rows without ids") requires it, because SQLite otherwise accepts a NULL text primary key.
5. **Pre-verification.** The test code and implementation in this plan were applied to a scratch copy of the current tree, with a fresh virtualenv, while the plan was written. Every expected count in the steps above was measured there:
   - Task 1 Step 3: 22 failed / 29 passed.
   - Step 7: 51 passed.
   - Step 9: 37 failed / 56 passed.
   - Step 11: 93 passed and 427 passed overall.
   - Task 2 Step 3: 8 failed / 26 passed.
   - Step 7: 34 passed and 434 passed overall.
<!-- task-pipeline: validated -->
