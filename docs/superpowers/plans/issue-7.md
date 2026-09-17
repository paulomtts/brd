<!-- task-pipeline: validated -->
# Issue #7 — 1.6 Project DB card and edge queries

Narrows Task 6 of `docs/superpowers/plans/2026-09-17-brd-cli.md` (lines 625-861) for the per-project SQLite layer. Parent story: #1. This is one module extension (`src/brd/db.py`) plus its unit tests (`tests/test_db.py`).

## Scope

Add raw, parameterized card and `blocked_by` queries to `src/brd/db.py`, extending the existing module (currently 93 lines: `connect`, `init_master_schema`, `init_project_schema`, `_row_to_project`, and the master-tier `Project` queries `insert_project` / `get_project_by_id` / `get_project_by_name` / `list_projects` landed by sibling #6). `db.py` stays a thin SQL layer: no ORM, no business rules, no validation, no derived values.

In scope — eight public functions plus one private row mapper:

- `_row_to_card(row: sqlite3.Row) -> Card` — maps a `cards` row to `Card` in the field order pinned by `src/brd/models.py:15-21` (`id, title, description, status, parent_id, created_at, updated_at`).
- `insert_card(conn, card: Card) -> None` — single `INSERT` of all seven columns, then `commit()`.
- `get_card(conn, card_id: str) -> Card | None` — `None` when no row matches.
- `update_card_fields(conn, card_id: str, **fields) -> None` — builds `SET col = ?` clauses from the kwargs actually passed; updates any subset of `title`, `description`, `status`, `parent_id`, and `updated_at`. `updated_at` is supplied by the caller (core.py), never computed here. Untouched columns keep their values.
- `list_cards(conn, status: str | None = None, parent_id: str | None = _UNSET) -> list[Card]` — module-level sentinel `_UNSET = "__unset__"`. `parent_id` left at the sentinel means "no parent filter"; `parent_id=None` passed explicitly means "top-level cards only" (`parent_id IS NULL`); a string filters `parent_id = ?`. `status=None` means no status filter. Filters combine with `AND`; results ordered by `created_at`.
- `add_blocked_by_edge(conn, card_id, blocks_on_id) -> None` — `INSERT` into `blocked_by`, meaning "`card_id` is blocked by `blocks_on_id`".
- `remove_blocked_by_edge(conn, card_id, blocks_on_id) -> None` — `DELETE` of that exact pair; removing a non-existent edge is a silent no-op at this layer.
- `list_blockers_of(conn, card_id) -> list[str]` — the `blocks_on_id` values for `card_id`, i.e. the IDs `card_id` is blocked by (not the reverse direction).
- `list_children(conn, parent_id) -> list[Card]` — cards whose `parent_id` matches, ordered by `created_at`.

Also required: extend the module's existing `from brd.models import Project` to `from brd.models import Card, Project` (sibling #6/Task 5 has already landed in this worktree, so the import and the master-tier `Project` queries already exist; this task only adds the `Card` import and the functions listed above).

Out of scope (owned by siblings, do not implement here):

- Master-DB project queries — #6 (Task 5).
- `blocked` status derivation. The `cards.status` CHECK allows only `todo`, `in_progress`, `done`; `blocked` is a read-only computed fourth value derived in `core.py` (#9/Task 8). `db.py` must not special-case or filter on `blocked`, and `list_cards(status="blocked")` is simply a query that returns nothing.
- Cycle validation for `parent_id` and for `blocked_by` — explicitly `core.py`'s responsibility per the design spec (lines 133-135), landing in #9.
- Card operations, `next` selection, tree building, output envelope, CLI wiring — #10, #11, #12, #13-17.
- Typed exceptions (`CardNotFoundError`, `CycleError`) — raised at the core/CLI boundary, not here.

## Observable behavior and error paths

All functions take an already-open connection from `db.connect` (WAL, `foreign_keys=ON`, `sqlite3.Row` row factory) and commit their own writes, consistent with the one-connection-per-command-invocation model.

Constraint violations surface as raw `sqlite3.IntegrityError` and are not caught or translated in this task:

- Inserting a card with a duplicate `id`, a dangling `parent_id`, or `status='blocked'`.
- Adding an edge referencing a non-existent card, or a duplicate `(card_id, blocks_on_id)` pair.

Non-error paths: `get_card` on a missing ID returns `None`; `list_cards` / `list_children` / `list_blockers_of` return empty lists rather than raising; `remove_blocked_by_edge` on a missing edge does nothing. `update_card_fields` performs no existence check — updating an unknown ID affects zero rows silently; callers in `core.py` do the existence check. Calling it with no field kwargs is a caller error and is not guarded (core always passes at least `updated_at`).

## Tests

Test-placement rule: `docs/superpowers/specs/2026-09-17-brd-cli-design.md:183-192` — `core.py` and `db.py` get unit tests run directly against a temp SQLite file (`tmp_path`) with no mocking of SQLite; `cli.py` gets end-to-end tests against a temp XDG data dir. Every test below is a **`db.py` unit test** in that first tier, appended to `tests/test_db.py` alongside the existing `conn` fixture. None belong in the end-to-end CLI tier (that surface arrives with #13-17).

New helpers in `tests/test_db.py`: a `project_conn` fixture (`db.connect(tmp_path / "project.db")` + `db.init_project_schema`, closed on teardown) mirroring the existing `conn` fixture, and `_sample_card(id_, title, status, parent_id)` returning a `Card` with fixed timestamps. `from brd.models import Card` goes with the module's other imports at the top of the file.

Test list (all db.py unit tier, exact bodies given at plan lines 671-739):

1. `test_insert_and_get_card` — round-trips a card; asserts full `Card` equality.
2. `test_get_card_returns_none_when_missing`.
3. `test_update_card_fields` — updates `title` + `updated_at`; asserts both changed and `description` survived untouched.
4. `test_list_cards_no_filter_returns_all`.
5. `test_list_cards_filters_by_status` — `status="done"` returns only the done card.
6. `test_list_cards_filters_by_parent_id` — string parent returns only that parent's child.
7. `test_list_cards_filters_by_explicit_none_parent` — `parent_id=None` returns only top-level cards, proving the `_UNSET` sentinel is distinct from an explicit `None`.
8. `test_add_and_list_blockers_of` — edge direction: after `add_blocked_by_edge(c1, c2)`, `list_blockers_of(c1) == ["c2"]`.
9. `test_remove_blocked_by_edge` — blockers list is empty afterwards.
10. `test_list_children` — both children of a parent are returned.

Existing tests in `tests/test_db.py` (schema shape, idempotency, CHECK/FK/duplicate-edge integrity) must keep passing unchanged.

## Verification

- `uv run pytest` (full suite) passes.
- No typecheck or lint step configured for this repo.

## Workflow

TDD per repo convention: write the tests first, confirm they fail with `AttributeError: module 'brd.db' has no attribute 'insert_card'`, add the minimal implementation given at plan lines 751-848, confirm green, then commit `src/brd/db.py` and `tests/test_db.py` with message `Add project DB card and blocked_by queries`.

---

# Project DB Card and Edge Queries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `src/brd/db.py` with raw parameterized SQL for `cards` CRUD, card listing/filtering, and `blocked_by` edge management, backed by unit tests against a real temp SQLite database.

**Architecture:** `db.py` is the thin persistence layer — SQLite connection management, schema creation, and raw parameterized queries, no ORM. This task appends a `_row_to_card` mapper and eight public functions that operate on an already-open connection from `db.connect` and commit their own writes. No business rules live here: `blocked` status derivation and parent/blocked cycle validation belong to `core.py` (issues #9/#10), and typed exceptions are raised at the core/CLI boundary.

**Tech Stack:** Python 3.12+, stdlib `sqlite3`, `dataclasses` models in `src/brd/models.py`, pytest with `tmp_path`, `uv` for running.

**Spec:** `docs/superpowers/specs/issue-7-design.md` (prepended verbatim above); design spec `docs/superpowers/specs/2026-09-17-brd-cli-design.md`.

## Global Constraints

- `db.py` role: "SQLite connection management, schema creation, and raw parameterized queries. No ORM." Connections are opened, used, and closed within a single command invocation.
- `cards.status` CHECK allows only `'todo'`, `'in_progress'`, `'done'`. `blocked` is NEVER stored — it is a computed read-only fourth value derived in `core.py`. `db.py` must not special-case it.
- `blocked_by(card_id, blocks_on_id)` with PK `(card_id, blocks_on_id)` means "`card_id` is blocked by `blocks_on_id`". Direction must not be inverted.
- Cycle validation for both `parent_id` and `blocked_by` is `core.py`'s responsibility (design spec lines 133-135) — no cycle logic in this task.
- `Card` field order is pinned by `src/brd/models.py:13-21`: `id, title, description, status, parent_id, created_at, updated_at`. Do not reorder.
- All SQL is parameterized with `?` placeholders. The only interpolated SQL is the `SET col = ?` clause list in `update_card_fields`, built from caller-supplied kwarg names.
- Test placement (design spec lines 183-192): `db.py` gets unit tests run directly against a temp SQLite file via `tmp_path`, with no mocking of SQLite. All tests in this plan go in `tests/test_db.py`. Nothing goes in the end-to-end CLI tier.
- Verification command for the repo: `uv run pytest`. No typecheck or lint step is configured.

---

### Task 1: Card and `blocked_by` queries in `db.py`

**Files:**
- Modify: `src/brd/db.py` (currently 93 lines — change the import on line 4, append new code after line 93)
- Test: `tests/test_db.py` (currently 203 lines — change the import on line 6, append new fixture/helper/tests after line 202)

**Interfaces:**
- Consumes: `db.connect(db_path: Path) -> sqlite3.Connection` and `db.init_project_schema(conn) -> None` (already in `src/brd/db.py`); `Card(id, title, description, status, parent_id, created_at, updated_at)` from `src/brd/models.py:13-21`.
- Produces (consumed later by `core.py` in #9/#10/#11):
  - `db.insert_card(conn: sqlite3.Connection, card: Card) -> None`
  - `db.get_card(conn: sqlite3.Connection, card_id: str) -> Card | None`
  - `db.update_card_fields(conn: sqlite3.Connection, card_id: str, **fields) -> None`
  - `db.list_cards(conn: sqlite3.Connection, status: str | None = None, parent_id: str | None = _UNSET) -> list[Card]` with module-level `_UNSET = "__unset__"`
  - `db.add_blocked_by_edge(conn: sqlite3.Connection, card_id: str, blocks_on_id: str) -> None`
  - `db.remove_blocked_by_edge(conn: sqlite3.Connection, card_id: str, blocks_on_id: str) -> None`
  - `db.list_blockers_of(conn: sqlite3.Connection, card_id: str) -> list[str]`
  - `db.list_children(conn: sqlite3.Connection, parent_id: str) -> list[Card]`

- [ ] **Step 1: Add the `Card` import to the test module**

In `tests/test_db.py`, change line 6 from `from brd.models import Project` to:

```python
from brd.models import Card, Project
```

- [ ] **Step 2: Append the `project_conn` fixture and `_sample_card` helper to the test module**

Append to the end of `tests/test_db.py` (after the existing `test_insert_project_rejects_duplicate_name`). This mirrors the existing `conn` fixture at lines 9-13 but also initializes the project schema:

```python
@pytest.fixture
def project_conn(tmp_path):
    connection = db.connect(tmp_path / "project.db")
    db.init_project_schema(connection)
    yield connection
    connection.close()


def _sample_card(id_="c1", title="Card", status="todo", parent_id=None):
    return Card(
        id=id_,
        title=title,
        description="desc",
        status=status,
        parent_id=parent_id,
        created_at="2026-09-17T00:00:00",
        updated_at="2026-09-17T00:00:00",
    )
```

- [ ] **Step 3: Write the failing card CRUD tests**

Append to `tests/test_db.py`:

```python
def test_insert_and_get_card(project_conn):
    db.insert_card(project_conn, _sample_card())
    result = db.get_card(project_conn, "c1")
    assert result == _sample_card()


def test_get_card_returns_none_when_missing(project_conn):
    assert db.get_card(project_conn, "nope") is None


def test_update_card_fields(project_conn):
    db.insert_card(project_conn, _sample_card())
    db.update_card_fields(project_conn, "c1", title="New title", updated_at="later")
    result = db.get_card(project_conn, "c1")
    assert result.title == "New title"
    assert result.updated_at == "later"
    assert result.description == "desc"  # untouched fields survive
```

- [ ] **Step 4: Write the failing `list_cards` filter tests**

Append to `tests/test_db.py`:

```python
def test_list_cards_no_filter_returns_all(project_conn):
    db.insert_card(project_conn, _sample_card("c1"))
    db.insert_card(project_conn, _sample_card("c2"))
    results = db.list_cards(project_conn)
    assert {c.id for c in results} == {"c1", "c2"}


def test_list_cards_filters_by_status(project_conn):
    db.insert_card(project_conn, _sample_card("c1", status="todo"))
    db.insert_card(project_conn, _sample_card("c2", status="done"))
    results = db.list_cards(project_conn, status="done")
    assert [c.id for c in results] == ["c2"]


def test_list_cards_filters_by_parent_id(project_conn):
    db.insert_card(project_conn, _sample_card("parent"))
    db.insert_card(project_conn, _sample_card("child", parent_id="parent"))
    results = db.list_cards(project_conn, parent_id="parent")
    assert [c.id for c in results] == ["child"]


def test_list_cards_filters_by_explicit_none_parent(project_conn):
    db.insert_card(project_conn, _sample_card("top"))
    db.insert_card(project_conn, _sample_card("parent2"))
    db.insert_card(project_conn, _sample_card("child", parent_id="parent2"))
    results = db.list_cards(project_conn, parent_id=None)
    assert {c.id for c in results} == {"top", "parent2"}
```

- [ ] **Step 5: Write the failing edge and children tests**

Append to `tests/test_db.py`:

```python
def test_add_and_list_blockers_of(project_conn):
    db.insert_card(project_conn, _sample_card("c1"))
    db.insert_card(project_conn, _sample_card("c2"))
    db.add_blocked_by_edge(project_conn, "c1", "c2")
    assert db.list_blockers_of(project_conn, "c1") == ["c2"]


def test_remove_blocked_by_edge(project_conn):
    db.insert_card(project_conn, _sample_card("c1"))
    db.insert_card(project_conn, _sample_card("c2"))
    db.add_blocked_by_edge(project_conn, "c1", "c2")
    db.remove_blocked_by_edge(project_conn, "c1", "c2")
    assert db.list_blockers_of(project_conn, "c1") == []


def test_list_children(project_conn):
    db.insert_card(project_conn, _sample_card("parent"))
    db.insert_card(project_conn, _sample_card("child1", parent_id="parent"))
    db.insert_card(project_conn, _sample_card("child2", parent_id="parent"))
    results = db.list_children(project_conn, "parent")
    assert {c.id for c in results} == {"child1", "child2"}
```

- [ ] **Step 6: Run the tests to verify they fail**

Run: `uv run pytest tests/test_db.py -v`

Expected: the ten new tests FAIL with `AttributeError: module 'brd.db' has no attribute 'insert_card'` (and, for `test_get_card_returns_none_when_missing`, `... has no attribute 'get_card'`). The 18 pre-existing tests in the file still PASS.

- [ ] **Step 7: Add the `Card` import and `_row_to_card` mapper to `db.py`**

In `src/brd/db.py`, change line 4 from `from brd.models import Project` to:

```python
from brd.models import Card, Project
```

Then append to the end of `src/brd/db.py` (after `list_projects`), mirroring the existing `_row_to_project` at lines 56-63:

```python
def _row_to_card(row: sqlite3.Row) -> Card:
    return Card(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        status=row["status"],
        parent_id=row["parent_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
```

- [ ] **Step 8: Implement `insert_card`, `get_card`, and `update_card_fields`**

Append to `src/brd/db.py`:

```python
def insert_card(conn: sqlite3.Connection, card: Card) -> None:
    conn.execute(
        "INSERT INTO cards (id, title, description, status, parent_id, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            card.id,
            card.title,
            card.description,
            card.status,
            card.parent_id,
            card.created_at,
            card.updated_at,
        ),
    )
    conn.commit()


def get_card(conn: sqlite3.Connection, card_id: str) -> Card | None:
    row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    return _row_to_card(row) if row else None


def update_card_fields(conn: sqlite3.Connection, card_id: str, **fields) -> None:
    columns = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [card_id]
    conn.execute(f"UPDATE cards SET {columns} WHERE id = ?", values)
    conn.commit()
```

- [ ] **Step 9: Implement the `_UNSET` sentinel and `list_cards`**

Append to `src/brd/db.py`:

```python
_UNSET = "__unset__"


def list_cards(
    conn: sqlite3.Connection,
    status: str | None = None,
    parent_id: str | None = _UNSET,
) -> list[Card]:
    query = "SELECT * FROM cards WHERE 1=1"
    params: list[str | None] = []
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    if parent_id is not _UNSET:
        if parent_id is None:
            query += " AND parent_id IS NULL"
        else:
            query += " AND parent_id = ?"
            params.append(parent_id)
    query += " ORDER BY created_at"
    rows = conn.execute(query, params).fetchall()
    return [_row_to_card(row) for row in rows]
```

- [ ] **Step 10: Implement the edge functions and `list_children`**

Append to `src/brd/db.py`:

```python
def add_blocked_by_edge(
    conn: sqlite3.Connection, card_id: str, blocks_on_id: str
) -> None:
    conn.execute(
        "INSERT INTO blocked_by (card_id, blocks_on_id) VALUES (?, ?)",
        (card_id, blocks_on_id),
    )
    conn.commit()


def remove_blocked_by_edge(
    conn: sqlite3.Connection, card_id: str, blocks_on_id: str
) -> None:
    conn.execute(
        "DELETE FROM blocked_by WHERE card_id = ? AND blocks_on_id = ?",
        (card_id, blocks_on_id),
    )
    conn.commit()


def list_blockers_of(conn: sqlite3.Connection, card_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT blocks_on_id FROM blocked_by WHERE card_id = ?", (card_id,)
    ).fetchall()
    return [row["blocks_on_id"] for row in rows]


def list_children(conn: sqlite3.Connection, parent_id: str) -> list[Card]:
    rows = conn.execute(
        "SELECT * FROM cards WHERE parent_id = ? ORDER BY created_at", (parent_id,)
    ).fetchall()
    return [_row_to_card(row) for row in rows]
```

- [ ] **Step 11: Run the test file to verify it passes**

Run: `uv run pytest tests/test_db.py -v`

Expected: PASS — all 28 tests (18 pre-existing + 10 new).

- [ ] **Step 12: Run the full suite**

Run: `uv run pytest`

Expected: PASS, no failures, no errors.

- [ ] **Step 13: Commit**

```bash
git add src/brd/db.py tests/test_db.py
git commit -m "Add project DB card and blocked_by queries"
```
