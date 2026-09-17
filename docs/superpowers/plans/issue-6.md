<!-- task-pipeline: validated -->
# Spec: Issue #6 — 1.5 Master DB queries

> Verbatim copy of `docs/superpowers/specs/issue-6-design.md`. The plan follows it.

---

# Issue #6 — 1.5 Master DB queries

Subtask of story #1 ("Implement brd CLI v1"). Implements Task 5 of `docs/superpowers/plans/2026-09-17-brd-cli.md` (lines 505-624), narrowing the agreed design in `docs/superpowers/specs/2026-09-17-brd-cli-design.md` to the master-tier query functions. Depends only on #5 (`db.connect`, `db.init_master_schema`, already implemented) and #3 (`models.Project`, already implemented).

## Scope

Append four public query functions plus one private row-mapper to `src/brd/db.py`, covering CRUD reads and the single write against the master-tier `projects` table. Plain stdlib `sqlite3`, parameterized `?` placeholders only, no ORM, no third-party dependency. Append the matching unit tests to `tests/test_db.py`.

**Out of scope** (owned by siblings, do not drift):
- Card and `blocked_by` edge queries against the per-project DB — `insert_card`, `get_card`, `update_card_fields`, `list_cards`, `add_blocked_by_edge`, `remove_blocked_by_edge`, `list_blockers_of`, `list_children`, and any `project_conn` fixture (#7).
- Project registration, UUID4 id generation, `created_at` stamping, `.brd` marker resolution, duplicate-name policy — `master.py` (#8) consumes these queries but owns those decisions. This subtask stores and reads whatever `Project` it is handed.
- XDG path resolution (#4) — these functions receive an open `sqlite3.Connection`, never a path.
- Typed exceptions (`ProjectNotFoundError`, …), output envelope, CLI wiring (#12-#16).
- Schema definition itself (#5) — unchanged here.

## Public interface

Appended to `src/brd/db.py`, with `from brd.models import Project` added to the top-level imports:

- `insert_project(conn: sqlite3.Connection, project: Project) -> None` — `INSERT INTO projects (id, name, root_path, db_path, created_at)` with the dataclass's five fields as bound parameters, then `conn.commit()` (matching the self-committing style of `init_master_schema` / `init_project_schema`, `src/brd/db.py:25,51`).
- `get_project_by_id(conn: sqlite3.Connection, project_id: str) -> Project | None` — `SELECT * FROM projects WHERE id = ?`, `fetchone()`, mapped to `Project` or `None`.
- `get_project_by_name(conn: sqlite3.Connection, name: str) -> Project | None` — `SELECT * FROM projects WHERE name = ?`, `fetchone()`, mapped to `Project` or `None`.
- `list_projects(conn: sqlite3.Connection) -> list[Project]` — `SELECT * FROM projects ORDER BY created_at`, `fetchall()`, mapped to a list (empty list when the table is empty).

Private helper:

- `_row_to_project(row: sqlite3.Row) -> Project` — maps `row["id"]`, `row["name"]`, `row["root_path"]`, `row["db_path"]`, `row["created_at"]` onto the dataclass. Column-name access is safe because `connect` sets `row_factory = sqlite3.Row` (`src/brd/db.py:7`). `Project` has no optional fields (`src/brd/models.py:4-10`), so all five must be supplied.

## Observable behavior

**Round-trip fidelity.** A `Project` inserted by `insert_project` and read back by `get_project_by_id` or `get_project_by_name` compares equal to the original — every field is a `str` stored in a `TEXT` column, so no coercion happens in either direction. `created_at` is an opaque ISO8601 string to this layer; it is never parsed, only stored and used as the `ORDER BY` key.

**Commit boundary.** `insert_project` commits before returning, so the row is durable and visible to a separately opened connection without further caller action. The read functions never commit and never mutate.

**Missing rows are not errors.** `get_project_by_id` and `get_project_by_name` return `None` when no row matches. They never raise for absence, and never return a partially populated `Project`. Turning `None` into a user-facing "project not found" error is #8's / the CLI's job.

**Ordering.** `list_projects` returns rows ordered by `created_at` ascending (lexicographic on the ISO8601 string, which is chronological for this format). Ties fall back to SQLite's unspecified order; callers must not rely on tie order.

**Name lookups assume uniqueness.** `projects.name` carries a `UNIQUE` constraint (`src/brd/db.py:18`), so `get_project_by_name` can safely `fetchone()` — at most one row can match.

## Error paths

- Inserting a project whose `name` duplicates an existing row raises `sqlite3.IntegrityError` (UNIQUE on `projects.name`), propagated unwrapped. Same for a duplicate `id` (PRIMARY KEY). This layer adds no typed exception; surfacing it as a friendly message belongs to #8/#13.
- Calling any of these functions on a connection whose master schema was never initialized raises `sqlite3.OperationalError: no such table: projects`, propagated unchanged. Callers initialize the schema first.
- Passing a `Project` with a `None` field would raise `sqlite3.IntegrityError` on the `NOT NULL` columns; the dataclass types forbid it, and no validation is added here.
- No other error handling: no `try`/`except`, no retries, no rollback logic. All SQL uses `?` placeholders, so malformed or hostile input is a value, never injected SQL.

## Test list

All tests in this subtask belong to the **`core.py`/`db.py` unit tier** per the design spec's Testing section (`docs/superpowers/specs/2026-09-17-brd-cli-design.md:183-192`): "unit tests against a temp SQLite file … no mocking of SQLite itself". They are appended to `tests/test_db.py`, reuse the existing `conn(tmp_path)` fixture (`tests/test_db.py:8-12`) backed by a real SQLite file, and mock nothing. The other tier named in that section — `cli.py` end-to-end tests against a monkeypatched temp XDG data dir — is owned by #13-#16; this subtask adds nothing to `tests/test_cli.py`. There is no third "integration" or "conformance" tier in this repo.

Shared helper added alongside the tests: `_sample_project(id_="p1", name="brd")`, returning a `Project` with fixed `root_path="/repo"`, `db_path="/data/p1.db"`, `created_at="2026-09-17T00:00:00"`.

| # | Test | Tier | Asserts |
|---|---|---|---|
| 1 | `test_insert_and_get_project_by_id` | db unit | after `init_master_schema` + `insert_project`, `get_project_by_id(conn, "p1")` equals the original `Project` |
| 2 | `test_get_project_by_id_returns_none_when_missing` | db unit | `get_project_by_id(conn, "nope")` is `None` on an initialized-but-empty table |
| 3 | `test_get_project_by_name` | db unit | `get_project_by_name(conn, "brd")` equals the inserted `Project` |
| 4 | `test_list_projects_returns_all` | db unit | after inserting `("p1","brd")` and `("p2","other")`, `{p.id for p in list_projects(conn)} == {"p1","p2"}` |

Each test calls `db.init_master_schema(conn)` itself, matching the existing style at `tests/test_db.py:26-35,68-80`. The plan gives the exact test bodies (lines 519-562) and the exact minimal implementation (lines 573-609); follow both verbatim under TDD: write the failing tests → verify `AttributeError: module 'brd.db' has no attribute 'insert_project'` → implement → green.

## Verification

- Scoped, during development: `uv run pytest tests/test_db.py -v`
- Full suite: `uv run pytest` — baseline before this subtask is 23 passed; expect 27 after.
- No typecheck or lint step configured for this repo.

## Done

`src/brd/db.py` gains `_row_to_project`, `insert_project`, `get_project_by_id`, `get_project_by_name`, `list_projects`; `tests/test_db.py` gains `_sample_project` and the four tests above; the full suite is green; the work is committed as exactly `git add src/brd/db.py tests/test_db.py` with message `Add master DB project queries`. `src/brd/models.py`, `src/brd/paths.py`, `src/brd/cli.py` and `tests/test_cli.py` are unmodified, and no card/edge query exists yet.

---

# Master DB Queries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the master-tier `projects` table queries (`insert_project`, `get_project_by_id`, `get_project_by_name`, `list_projects`) to `src/brd/db.py`, so later subtasks can register and look up projects.

**Architecture:** Plain module-level functions in the existing `src/brd/db.py`, taking an already-open `sqlite3.Connection` (produced by `db.connect`, which sets `row_factory = sqlite3.Row`) and returning `models.Project` dataclasses via a private `_row_to_project` mapper. All SQL uses `?` placeholders; the single write self-commits, matching `init_master_schema` / `init_project_schema`.

**Tech Stack:** Python 3.12, stdlib `sqlite3`, `pytest` (real temp SQLite file via the existing `conn(tmp_path)` fixture — nothing mocked), `uv` for env management.

**Spec:** `docs/superpowers/specs/issue-6-design.md` (reproduced verbatim above)

## Global Constraints

- No ORM — plain stdlib `sqlite3` with a light wrapper (spec: Architecture).
- `status` column never stores `'blocked'`; it's a read-time derived value (spec: Data model).
- Both DB tiers live under the XDG data dir (`~/.local/share/brd/`), never inside project repos (spec: Storage layout).
- `.brd` marker file must be added to the repo's `.gitignore` by `brd init` (spec: CLI surface / user-approved addendum).
- JSON output is the default; `--pretty`/`--human` opts into formatted text (spec: Output format).
- Every command's output uses the envelope `{"ok": true, "data": ...}` or `{"ok": false, "error": {"type", "message"}}`, non-zero exit on failure (spec: Output format, Error handling).
- SQLite WAL mode; one connection opened/closed per command invocation, no daemon (spec: Concurrency).
- Card IDs and project IDs are UUID4 strings (spec: Data model) — this subtask stores whatever id string it is given and generates none.
- Parameterized queries only: raw `?` placeholders, never string interpolation of values.

---

## File Structure

```
src/brd/db.py      # MODIFIED: gains `from brd.models import Project`, `_row_to_project`,
                   #           `insert_project`, `get_project_by_id`,
                   #           `get_project_by_name`, `list_projects`
tests/test_db.py   # MODIFIED: gains `from brd.models import Project`,
                   #           `_sample_project` helper, and 4 unit-tier tests
```

No other file is touched. `src/brd/models.py`, `src/brd/paths.py`, `src/brd/cli.py`, `tests/test_cli.py`, `tests/test_models.py`, `tests/test_paths.py` are unmodified.

Current state of the two files this task edits (on branch `m1/task-6`, cut from `origin/m1/task-5`):
- `src/brd/db.py` ends at line 52 with `init_project_schema`'s `conn.commit()` (line 51). Its imports are `import sqlite3` (line 1) and `from pathlib import Path` (line 2).
- `tests/test_db.py` ends at line 123 with the last assertion of `test_blocked_by_rejects_duplicate_edge`. Its imports are `import sqlite3`, `import pytest`, `from brd import db` (lines 1-5), followed by the `conn` fixture at lines 8-12.

---

### Task 1: Master DB project queries

**Files:**
- Modify: `src/brd/db.py` (imports at lines 1-2; append after line 52)
- Test: `tests/test_db.py` (imports at lines 1-5; append after line 123) — db unit tier, real temp SQLite via the existing `conn(tmp_path)` fixture at `tests/test_db.py:8-12`, no mocking

**Interfaces:**
- Consumes: `db.connect(db_path: Path) -> sqlite3.Connection` and `db.init_master_schema(conn: sqlite3.Connection) -> None` (already present, `src/brd/db.py:5-25`); `brd.models.Project(id: str, name: str, root_path: str, db_path: str, created_at: str)` (already present, `src/brd/models.py:4-10`).
- Produces:
  - `db.insert_project(conn: sqlite3.Connection, project: Project) -> None`
  - `db.get_project_by_id(conn: sqlite3.Connection, project_id: str) -> Project | None`
  - `db.get_project_by_name(conn: sqlite3.Connection, name: str) -> Project | None`
  - `db.list_projects(conn: sqlite3.Connection) -> list[Project]`
  - `db._row_to_project(row: sqlite3.Row) -> Project` (private; used only inside `db.py`)

- [ ] **Step 1: Write the failing tests**

Add this import line to the existing import block at the top of `tests/test_db.py`, directly below `from brd import db` (line 5):

```python
from brd.models import Project
```

Then append to the end of `tests/test_db.py` (after line 123):

```python
def _sample_project(id_="p1", name="brd"):
    return Project(
        id=id_,
        name=name,
        root_path="/repo",
        db_path="/data/p1.db",
        created_at="2026-09-17T00:00:00",
    )


def test_insert_and_get_project_by_id(conn):
    db.init_master_schema(conn)
    db.insert_project(conn, _sample_project())
    result = db.get_project_by_id(conn, "p1")
    assert result == _sample_project()


def test_get_project_by_id_returns_none_when_missing(conn):
    db.init_master_schema(conn)
    assert db.get_project_by_id(conn, "nope") is None


def test_get_project_by_name(conn):
    db.init_master_schema(conn)
    db.insert_project(conn, _sample_project())
    result = db.get_project_by_name(conn, "brd")
    assert result == _sample_project()


def test_list_projects_returns_all(conn):
    db.init_master_schema(conn)
    db.insert_project(conn, _sample_project("p1", "brd"))
    db.insert_project(conn, _sample_project("p2", "other"))
    results = db.list_projects(conn)
    assert {p.id for p in results} == {"p1", "p2"}
```

- [ ] **Step 2: Run the tests to verify they fail (RED)**

Run: `uv run pytest tests/test_db.py -v`

Expected: the three tests that call `db.insert_project` fail with `AttributeError: module 'brd.db' has no attribute 'insert_project'`, and `test_get_project_by_id_returns_none_when_missing` fails with `AttributeError: module 'brd.db' has no attribute 'get_project_by_id'`. The 11 pre-existing tests in the file still pass. Do not proceed until you have seen these four failures with those messages.

- [ ] **Step 3: Write the minimal implementation (GREEN)**

Add this import line to the top of `src/brd/db.py`, directly below `from pathlib import Path` (line 2), leaving a blank line before `def connect`:

```python
from brd.models import Project
```

Then append to the end of `src/brd/db.py` (after line 52, separated by two blank lines):

```python
def _row_to_project(row: sqlite3.Row) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        root_path=row["root_path"],
        db_path=row["db_path"],
        created_at=row["created_at"],
    )


def insert_project(conn: sqlite3.Connection, project: Project) -> None:
    conn.execute(
        "INSERT INTO projects (id, name, root_path, db_path, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            project.id,
            project.name,
            project.root_path,
            project.db_path,
            project.created_at,
        ),
    )
    conn.commit()


def get_project_by_id(conn: sqlite3.Connection, project_id: str) -> Project | None:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return _row_to_project(row) if row else None


def get_project_by_name(conn: sqlite3.Connection, name: str) -> Project | None:
    row = conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
    return _row_to_project(row) if row else None


def list_projects(conn: sqlite3.Connection) -> list[Project]:
    rows = conn.execute("SELECT * FROM projects ORDER BY created_at").fetchall()
    return [_row_to_project(row) for row in rows]
```

No `try`/`except`: `sqlite3.IntegrityError` (duplicate name or id) and `sqlite3.OperationalError` (schema never initialized) propagate unwrapped to the caller, per the spec's Error paths.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`

Expected: PASS — 15 passed in `tests/test_db.py` (11 pre-existing + the 4 new ones).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`

Expected: 27 passed (baseline was 23). No skips, no failures, no errors. If any pre-existing test in `tests/test_cli.py`, `tests/test_models.py` or `tests/test_paths.py` changed state, stop and investigate before committing.

- [ ] **Step 6: Commit**

```bash
git add src/brd/db.py tests/test_db.py
git commit -m "Add master DB project queries"
```

Only those two files may appear in the commit — confirm with `git status` that nothing else is staged.

---

## Verification

- Scoped, during development: `uv run pytest tests/test_db.py -v`
- Full suite: `uv run pytest` — 23 passed before this task, 27 passed after.
- No typecheck step and no lint step are configured for this repo; do not invent one.
