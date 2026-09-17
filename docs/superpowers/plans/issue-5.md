<!-- task-pipeline: validated -->
# Spec (verbatim): Issue #5 — 1.4 DB connection management and schema

Subtask of story #1 ("1 Implement brd CLI v1"). Implements Task 4 of `docs/superpowers/plans/2026-09-17-brd-cli.md` (lines 343-501), narrowing the agreed design in `docs/superpowers/specs/2026-09-17-brd-cli-design.md` to a single module.

## Scope

Create `src/brd/db.py` — the lowest storage layer: open a SQLite connection with the project's standard pragmas, and create the master-tier and project-tier schemas. Plain stdlib `sqlite3` + `pathlib`; no ORM, no third-party dependency.

Create `tests/test_db.py` — unit tests against a real temp SQLite file.

**Out of scope** (owned by siblings, do not drift):
- Any CRUD/query function over `projects` (#6) or `cards`/`blocked_by` (#7).
- XDG path resolution — `db.connect` receives a `db_path: Path` argument and never calls `src/brd/paths.py` (#4, already implemented).
- `blocked` status derivation and `parent_id` / `blocked_by` cycle detection — those live in `core.py` (#9). This subtask contributes only the `CHECK` constraint that makes a literal `'blocked'` write impossible.
- Typed exceptions (`ProjectNotFoundError`, etc.), output envelope, CLI wiring.
- `.brd` marker handling and project registration (#8).

## Public interface

- `connect(db_path: Path) -> sqlite3.Connection` — opens the database at `db_path`, sets `row_factory = sqlite3.Row`, executes `PRAGMA journal_mode=WAL` and `PRAGMA foreign_keys=ON`, returns the connection. The caller owns the connection lifetime (one open/close per command invocation, per the design spec's Concurrency section; no daemon, no pooling, no context manager here).
- `init_master_schema(conn: sqlite3.Connection) -> None` — `CREATE TABLE IF NOT EXISTS projects` and commit.
- `init_project_schema(conn: sqlite3.Connection) -> None` — `CREATE TABLE IF NOT EXISTS cards` and `CREATE TABLE IF NOT EXISTS blocked_by`, then commit.

## Observable behavior

**Connection.** After `connect`, `PRAGMA journal_mode` reports `wal` (case-insensitively) and `PRAGMA foreign_keys` reports `1`. `conn.row_factory is sqlite3.Row`, so downstream query modules read columns by name. `connect` creates the file if it does not exist (standard `sqlite3.connect` behavior); it does not create parent directories — that is the caller's concern, already handled by `paths.py`.

**Master schema.** `projects` columns, in this order and matching `models.Project` field order: `id TEXT PRIMARY KEY`, `name TEXT NOT NULL UNIQUE`, `root_path TEXT NOT NULL`, `db_path TEXT NOT NULL`, `created_at TEXT NOT NULL`. Timestamps are ISO8601 strings. Calling `init_master_schema` twice on the same connection is a no-op the second time and must not raise.

**Project schema.** `cards` columns, in this order and matching `models.Card` field order: `id TEXT PRIMARY KEY`, `title TEXT NOT NULL`, `description TEXT` (nullable), `status TEXT NOT NULL CHECK (status IN ('todo', 'in_progress', 'done'))`, `parent_id TEXT REFERENCES cards(id)` (nullable, self-referential), `created_at TEXT NOT NULL`, `updated_at TEXT NOT NULL`. `blocked_by` columns: `card_id TEXT NOT NULL REFERENCES cards(id)`, `blocks_on_id TEXT NOT NULL REFERENCES cards(id)`, with composite `PRIMARY KEY (card_id, blocks_on_id)` — meaning "`card_id` is blocked by `blocks_on_id`". Calling `init_project_schema` twice must not raise.

**`blocked` is never stored.** Per the design spec (lines 109-113), `blocked` is a read-time-derived fourth status, not a column value. The `CHECK` constraint is the storage-level guarantee: any `INSERT`/`UPDATE` writing `status='blocked'` fails. Derivation itself is #9's job.

## Error paths

- `connect` on an unopenable path (missing parent directory, unwritable location) propagates `sqlite3.OperationalError` unchanged — no wrapping, no typed exception at this layer.
- Inserting a card with a `status` outside `('todo', 'in_progress', 'done')` — notably `'blocked'` — raises `sqlite3.IntegrityError`.
- Inserting a `blocked_by` row or a `cards.parent_id` referencing a non-existent card id raises `sqlite3.IntegrityError` (foreign keys are enforced because `connect` turns them on). Not asserted by this subtask's tests; it is a consequence of the pragma, and #7 owns edge-insert behavior.
- Duplicate `projects.name` or duplicate `(card_id, blocks_on_id)` raises `sqlite3.IntegrityError`. Also #6/#7's concern to surface.
- Both `init_*` functions are idempotent by construction (`IF NOT EXISTS`); neither raises on repeat calls. Neither migrates or alters an existing table with a different shape — v1 has no migrations.

## Test list

All tests in this subtask belong to the **`core.py`/`db.py` unit tier** per the design spec's Testing section (lines 183-192): "unit tests against a temp SQLite file … no mocking of SQLite itself". They live in `tests/test_db.py`, use a real `sqlite3` database under pytest's `tmp_path`, and mock nothing. The CLI end-to-end tier described in the same section (temp XDG data dir, monkeypatched env var) is owned by #13-#16 and gets no tests here.

Shared fixture: `conn(tmp_path)` — yields `db.connect(tmp_path / "test.db")`, closes it on teardown.

| # | Test | Tier | Asserts |
|---|---|---|---|
| 1 | `test_connect_enables_wal_and_foreign_keys` | db unit | `PRAGMA journal_mode` is `wal`; `PRAGMA foreign_keys` is `1` |
| 2 | `test_connect_sets_row_factory` | db unit | `conn.row_factory is sqlite3.Row` |
| 3 | `test_init_master_schema_creates_projects_table` | db unit | `PRAGMA table_info(projects)` column names == `{id, name, root_path, db_path, created_at}` |
| 4 | `test_init_master_schema_is_idempotent` | db unit | two consecutive calls do not raise |
| 5 | `test_init_project_schema_creates_cards_and_blocked_by_tables` | db unit | `cards` columns == `{id, title, description, status, parent_id, created_at, updated_at}`; `blocked_by` columns == `{card_id, blocks_on_id}` |
| 6 | `test_init_project_schema_is_idempotent` | db unit | two consecutive calls do not raise |
| 7 | `test_cards_status_check_constraint_rejects_blocked` | db unit | `INSERT` with `status='blocked'` raises `sqlite3.IntegrityError` |

The plan at lines 356-426 gives the exact test file content and at lines 437-489 the exact minimal implementation; follow both verbatim under TDD (write failing tests → verify `ModuleNotFoundError: No module named 'brd.db'` → implement → green).

## Verification

- Scoped, during development: `uv run pytest tests/test_db.py -v`
- Full suite: `uv run pytest`
- No typecheck or lint step configured for this repo.

## Done

`src/brd/db.py` and `tests/test_db.py` exist, all seven tests pass, the full suite is green, and the work is committed as exactly `git add src/brd/db.py tests/test_db.py` with message `Add DB connection management and schema creation`. `src/brd/models.py` and `src/brd/paths.py` are unmodified.

---

# DB Connection Management and Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `src/brd/db.py`, the storage layer that opens a SQLite connection with brd's standard pragmas and creates the master-tier (`projects`) and project-tier (`cards`, `blocked_by`) schemas.

**Architecture:** One new module, plain stdlib `sqlite3` + `pathlib`, no ORM and no third-party dependency. Three functions: `connect` returns a configured `sqlite3.Connection` whose lifetime the caller owns; `init_master_schema` and `init_project_schema` each run `CREATE TABLE IF NOT EXISTS` statements and commit, so both are idempotent. No queries, no path resolution, no business logic — siblings #6/#7/#9 own those.

**Tech Stack:** Python 3.12, stdlib `sqlite3`/`pathlib`, `pytest` (dev), `uv` for env management.

**Spec:** `docs/superpowers/specs/issue-5-design.md` (also reproduced verbatim at the top of this file)

## Global Constraints

- No ORM — plain stdlib `sqlite3` with a light wrapper (design spec: Architecture).
- `status` column never stores `'blocked'`; it is a read-time derived value (design spec: Data model).
- Both DB tiers live under the XDG data dir (`~/.local/share/brd/`), never inside project repos (design spec: Storage layout) — but this subtask receives `db_path` as an argument and never resolves paths itself.
- SQLite WAL mode; one connection opened/closed per command invocation, no daemon (design spec: Concurrency).
- Card IDs and project IDs are UUID4 strings stored as `TEXT` (design spec: Data model).
- Tests for `db.py` belong to the unit tier: real temp SQLite file via pytest `tmp_path`, no mocking of SQLite (design spec: Testing, lines 183-192). The CLI end-to-end tier is owned by #13-#16.
- `src/brd/models.py` and `src/brd/paths.py` must not be modified.

---

## File Structure

```
src/brd/db.py      # NEW — connect(), init_master_schema(), init_project_schema()
tests/test_db.py   # NEW — unit tier, real temp SQLite via tmp_path, no mocks
```

The worktree already contains `src/brd/__init__.py`, `src/brd/cli.py`, `src/brd/models.py`, `src/brd/paths.py`, `tests/__init__.py`, and sibling tests. Existing test files follow the `tests/test_<module>.py` convention (see `tests/test_paths.py`), so the new unit-tier file is `tests/test_db.py`. Nothing else is created, modified, or deleted.

---

### Task 1: DB connection management and schema

**Files:**
- Create: `src/brd/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: nothing from earlier subtasks — only stdlib `sqlite3` and `pathlib`. In particular this task does **not** import `brd.paths` or `brd.models`.
- Produces (relied on by #6, #7, #8):
  - `db.connect(db_path: Path) -> sqlite3.Connection`
  - `db.init_master_schema(conn: sqlite3.Connection) -> None`
  - `db.init_project_schema(conn: sqlite3.Connection) -> None`

- [ ] **Step 1: Write the failing test**

Create `tests/test_db.py` with exactly this content:

```python
import sqlite3

import pytest

from brd import db


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.db")
    yield connection
    connection.close()


def test_connect_enables_wal_and_foreign_keys(conn):
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1


def test_connect_sets_row_factory(conn):
    assert conn.row_factory is sqlite3.Row


def test_init_master_schema_creates_projects_table(conn):
    db.init_master_schema(conn)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(projects)")}
    assert columns == {"id", "name", "root_path", "db_path", "created_at"}


def test_init_master_schema_is_idempotent(conn):
    db.init_master_schema(conn)
    db.init_master_schema(conn)  # must not raise


def test_init_project_schema_creates_cards_and_blocked_by_tables(conn):
    db.init_project_schema(conn)
    card_columns = {row[1] for row in conn.execute("PRAGMA table_info(cards)")}
    assert card_columns == {
        "id",
        "title",
        "description",
        "status",
        "parent_id",
        "created_at",
        "updated_at",
    }
    edge_columns = {row[1] for row in conn.execute("PRAGMA table_info(blocked_by)")}
    assert edge_columns == {"card_id", "blocks_on_id"}


def test_init_project_schema_is_idempotent(conn):
    db.init_project_schema(conn)
    db.init_project_schema(conn)  # must not raise


def test_cards_status_check_constraint_rejects_blocked(conn):
    db.init_project_schema(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO cards (id, title, description, status, parent_id, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("c1", "t", None, "blocked", None, "now", "now"),
        )
```

Notes for the implementer: `row[1]` is the column-name field of `PRAGMA table_info`. The fixture rows come back as `sqlite3.Row`, which still supports positional indexing. Do not add mocks — this tier uses a real SQLite file under `tmp_path`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_db.py -v`
Expected: collection error — `ImportError: cannot import name 'db' from 'brd'`

- [ ] **Step 3: Write the minimal implementation**

Create `src/brd/db.py` with exactly this content:

```python
import sqlite3
from pathlib import Path


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_master_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            root_path TEXT NOT NULL,
            db_path TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def init_project_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cards (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT NOT NULL CHECK (status IN ('todo', 'in_progress', 'done')),
            parent_id TEXT REFERENCES cards(id),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS blocked_by (
            card_id TEXT NOT NULL REFERENCES cards(id),
            blocks_on_id TEXT NOT NULL REFERENCES cards(id),
            PRIMARY KEY (card_id, blocks_on_id)
        )
        """
    )
    conn.commit()
```

Column names and order match `src/brd/models.py` (`Project`: id, name, root_path, db_path, created_at; `Card`: id, title, description, status, parent_id, created_at, updated_at). Do not add query helpers, typed exceptions, cycle checks, or a `'blocked'` value to the `CHECK` list.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_db.py -v`
Expected: PASS — 7 passed.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: PASS — all tests green, including the pre-existing `tests/test_cli.py`, `tests/test_models.py`, `tests/test_paths.py`.

- [ ] **Step 6: Confirm no sibling files were touched**

Run: `git status --porcelain src/ tests/`
Expected: exactly two untracked entries, `?? src/brd/db.py` and `?? tests/test_db.py` — no ` M` modification lines for `src/brd/models.py` or `src/brd/paths.py`. (Untracked files under `docs/` and `.claude/` are expected and are excluded by the path filter.)

- [ ] **Step 7: Commit**

```bash
git add src/brd/db.py tests/test_db.py
git commit -m "$(cat <<'EOF'
Add DB connection management and schema creation

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011rpKbM8YZgV45PCeiFqncT
EOF
)"
```
