<!-- task-pipeline: validated -->
# Spec (verbatim)

# Issue #10 — Core: card operations (create, update, block, unblock)

Date: 2026-09-17
Parent story: #1 "Implement brd CLI v1" · Plan section: `docs/superpowers/plans/2026-09-17-brd-cli.md` lines 1320-1547 ("Task 9: Core — card operations"), to be followed verbatim, TDD style.

## Scope

Exactly two files change:

- `src/brd/core.py` — append the card write operations.
- `tests/test_core.py` — append unit tests.

Nothing else. No `db.py`, `master.py`, `output.py`, `cli.py`, schema, or packaging changes; those belong to sibling sub-issues. In particular `core.next_cards` and `core.build_tree` are issue #11's (plan Task 10, line 1551+) and must not appear here.

This subtask builds on the state of branch `m1/task-9`, where `core.py` already provides `CycleError`, `resolve_status`, `would_create_parent_cycle`, `would_create_block_cycle`, and `db.py` already provides `get_card`, `insert_card`, `update_card_fields`, `add_blocked_by_edge`, `remove_blocked_by_edge`, `list_blockers_of`, `list_children`. The current `m1/task-5` worktree state does not yet contain those; they are prerequisites, not deliverables.

## Constraints inherited from the milestone design

- No ORM. `core.py` issues no SQL and imports no typer — it is a thin, independently testable layer over `db.py` (design doc lines 33-46).
- Core functions receive an already-open `conn: sqlite3.Connection` and never open, close, or commit-manage connections themselves; connection lifetime is the caller's (one connection per command).
- Card ids are UUID4 strings; `created_at`/`updated_at` are UTC ISO-8601 strings from `datetime.now(timezone.utc).isoformat()`.
- `"blocked"` is a derived read-time status (`resolve_status`) and is never persisted; the project schema's CHECK constraint allows only `todo`/`in_progress`/`done`. `update_card` rejects it at the core layer before it can reach `db.update_card_fields` — defense in depth in front of the DB CHECK.

## Public surface produced

- `core.CardNotFoundError(Exception)`
- `core.InvalidStatusError(Exception)`
- `core.CLEAR_PARENT = object()` — sentinel meaning "explicitly set `parent_id` to NULL".
- `core.create_card(conn, title: str, description: str | None = None, parent_id: str | None = None, blocked_by: list[str] | None = None) -> Card`
- `core.update_card(conn, card_id: str, title: str | None = None, description: str | None = None, status: str | None = None, parent_id: str | object | None = None) -> Card`
- `core.block_card(conn, card_id: str, blocker_id: str) -> None`
- `core.unblock_card(conn, card_id: str, blocker_id: str) -> None`

Internal helpers `_now()` and `_require_card(conn, card_id) -> Card` are private to the module.

## Observable behavior

**create_card** — validates `parent_id` (when given) and every id in `blocked_by` exist, then inserts a card with a fresh UUID4 id, `status="todo"`, `created_at == updated_at == _now()`, and the given `parent_id`/`description` (both may be `None`). After insert, each blocker is checked with `would_create_block_cycle` and then written via `db.add_blocked_by_edge`. Returns the `Card` it constructed, which equals `db.get_card(conn, card.id)`.

**update_card** — partial update. For `title`, `description`, `status`, a value of `None` means "leave unchanged", so those fields cannot be cleared through this API in v1. `parent_id` is three-valued: `None` leaves the parent unchanged (a documented gotcha — it does *not* clear it), `core.CLEAR_PARENT` writes NULL, any other value re-parents after validating the new parent exists and that `would_create_parent_cycle` is false. `status="blocked"` is rejected outright. Only the explicitly provided fields plus `updated_at` are written; if no field was provided, no write happens at all (and `updated_at` is left alone). Returns the re-read card.

**block_card** — validates both cards exist, refuses the edge if `would_create_block_cycle`, otherwise adds the `blocked_by` edge. Adding an edge that already exists is delegated to `db.add_blocked_by_edge` (idempotent at the db layer); core adds no extra dedup logic.

**unblock_card** — validates `card_id` exists, then removes the edge. No cycle check is needed on removal, and removing a non-existent edge is a no-op via `db.remove_blocked_by_edge`.

## Error paths

| Condition | Raised |
| --- | --- |
| `create_card` with an unknown `parent_id` | `CardNotFoundError` |
| `create_card` with any unknown id in `blocked_by` | `CardNotFoundError` (all blockers validated before insert) |
| `create_card` where a blocker would close a block cycle | `CycleError` |
| `update_card` / `block_card` / `unblock_card` on an unknown `card_id` | `CardNotFoundError` |
| `block_card` with an unknown `blocker_id` | `CardNotFoundError` |
| `update_card` with an unknown new `parent_id` | `CardNotFoundError` |
| `update_card(status="blocked")` | `InvalidStatusError` (checked before any field is assembled or written) |
| `update_card` re-parenting into an ancestor cycle | `CycleError` |
| `block_card` edge that would close a block cycle | `CycleError` |

Error messages carry the offending ids, e.g. `no card with id {card_id}`, `blocking {card_id} on {blocker_id} would create a cycle`.

## Test list

Test-placement rule (design doc lines 183-192): this repo has only two tiers, keyed by module — `core.py`/`db.py` get **unit tests against a temp SQLite file with no mocking of SQLite**, and `cli.py` gets end-to-end tests against a temp XDG data dir. This subtask touches only `core.py`, so **every test below is a core unit test in `tests/test_core.py`**; there is no CLI surface here and therefore no end-to-end test in this subtask. Reuse the existing local `conn` fixture (tmp_path-backed `db.connect` + `db.init_project_schema`) and `_card()` helper already defined in that file on `m1/task-9`; do not introduce a `conftest.py`.

Unit tier, `tests/test_core.py`:

1. `test_create_card_defaults_to_todo` — status is `todo`, title round-trips, `db.get_card` returns an equal `Card`.
2. `test_create_card_with_parent_and_blocked_by` — `parent_id` set, `db.list_blockers_of` returns the blocker.
3. `test_create_card_rejects_unknown_parent` — `CardNotFoundError`.
4. `test_create_card_rejects_unknown_blocker` — `CardNotFoundError`.
5. `test_update_card_changes_only_given_fields` — changing `title` leaves `description` intact.
6. `test_update_card_rejects_blocked_status` — `InvalidStatusError`.
7. `test_update_card_rejects_parent_cycle` — re-parenting A under its own child B raises `CycleError`.
8. `test_update_card_can_clear_parent` — `parent_id=core.CLEAR_PARENT` yields `parent_id is None`.
9. `test_block_card_adds_edge` — `db.list_blockers_of` reflects the new edge.
10. `test_block_card_rejects_cycle` — reversing an existing block raises `CycleError`.
11. `test_unblock_card_removes_edge` — blockers list is empty afterwards.

The plan's Step 1 test bodies (lines 1340-1416) are the normative source for these; copy them as written.

## Done when

- The eleven tests above exist in `tests/test_core.py` and pass.
- `uv run pytest` passes for the whole suite (previously-green tests from tasks 1-8 stay green).
- No typecheck or lint step is configured in `pyproject.toml`; there is nothing else to run.

---

# Core Card Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the four card write operations — `create_card`, `update_card`, `block_card`, `unblock_card` — to `src/brd/core.py`, with their error types and the `CLEAR_PARENT` sentinel.

**Architecture:** `core.py` is a thin, typer-free, SQL-free layer over `db.py`. Each new function validates its inputs against the database through `db.get_card`, consults the already-existing cycle detectors (`would_create_parent_cycle`, `would_create_block_cycle`), and then delegates every write to a `db.*` helper. All functions take an already-open `sqlite3.Connection` owned by the caller. Tests are core unit tests in `tests/test_core.py` driving a real temp-file SQLite database — no mocks.

**Tech Stack:** Python 3.11+ stdlib (`sqlite3`, `uuid`, `datetime`), dataclasses from `brd.models`, pytest (`uv run pytest`). No ORM, no lint or typecheck tooling configured.

**Spec:** `docs/superpowers/specs/issue-10-design.md` (also reproduced verbatim at the top of this file).

## Global Constraints

- Branch `m1/task-10`, cut from `origin/m1/task-9`. Only two files may change: `src/brd/core.py` and `tests/test_core.py`.
- No ORM; `core.py` issues no SQL itself and imports no typer. Every read/write goes through `brd.db`.
- Core functions receive an already-open `conn: sqlite3.Connection`; they never open, close, or manage transactions on it.
- Card ids are UUID4 strings via `str(uuid.uuid4())`; `created_at`/`updated_at` are `datetime.now(timezone.utc).isoformat()` strings.
- `"blocked"` is never persisted — the schema CHECK allows only `todo`/`in_progress`/`done`; `update_card` rejects `status="blocked"` with `InvalidStatusError` before assembling any field dict.
- Do NOT add `core.next_cards` or `core.build_tree` — those belong to issue #11.
- Verification command for the whole repo: `uv run pytest`. There is no lint or typecheck step.

## File Structure

- `src/brd/core.py` (modify) — currently 53 lines: `CycleError`, `resolve_status`, `would_create_parent_cycle`, `would_create_block_cycle`. This plan appends the two new exception classes, the `CLEAR_PARENT` sentinel, the `_now`/`_require_card` private helpers, and the four public operations. Its import block (`import sqlite3` on line 1) grows to include `uuid` and `datetime`.
- `tests/test_core.py` (modify) — currently 137 lines of `resolve_status`/cycle-detection unit tests, with a local `conn` fixture (tmp_path-backed `db.connect` + `db.init_project_schema`) and a `_card()` helper. This plan appends eleven tests that use the same `conn` fixture. No `conftest.py` is introduced.

---

### Task 1: Module preamble — errors, sentinel, and private helpers plus `create_card`

**Files:**
- Modify: `src/brd/core.py:1` (import block) and end of file
- Test: `tests/test_core.py` (append after line 137)

**Interfaces:**
- Consumes: `db.get_card(conn, card_id) -> Card | None`, `db.insert_card(conn, card) -> None`, `db.add_blocked_by_edge(conn, card_id, blocks_on_id) -> None`, `db.list_blockers_of(conn, card_id) -> list[str]`, `core.would_create_block_cycle(conn, card_id, new_blocker_id) -> bool`, `core.CycleError`, `brd.models.Card` (fields: `id, title, description, status, parent_id, created_at, updated_at`, all `str` except `description`/`parent_id` which are `str | None`).
- Produces:
  - `core.CardNotFoundError(Exception)`
  - `core.InvalidStatusError(Exception)`
  - `core.CLEAR_PARENT` — a module-level `object()` sentinel
  - `core._now() -> str`
  - `core._require_card(conn: sqlite3.Connection, card_id: str) -> Card`
  - `core.create_card(conn: sqlite3.Connection, title: str, description: str | None = None, parent_id: str | None = None, blocked_by: list[str] | None = None) -> Card`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_core.py` (after the last existing test, `test_would_create_block_cycle_terminates_on_persisted_blocking_cycle`). These use the `conn` fixture already defined at the top of that file.

```python
def test_create_card_defaults_to_todo(conn):
    card = core.create_card(conn, title="New card")
    assert card.status == "todo"
    assert card.title == "New card"
    assert db.get_card(conn, card.id) == card


def test_create_card_with_parent_and_blocked_by(conn):
    parent = core.create_card(conn, title="Parent")
    blocker = core.create_card(conn, title="Blocker")
    child = core.create_card(
        conn, title="Child", parent_id=parent.id, blocked_by=[blocker.id]
    )
    assert child.parent_id == parent.id
    assert db.list_blockers_of(conn, child.id) == [blocker.id]


def test_create_card_rejects_unknown_parent(conn):
    with pytest.raises(core.CardNotFoundError):
        core.create_card(conn, title="Orphan", parent_id="nope")


def test_create_card_rejects_unknown_blocker(conn):
    with pytest.raises(core.CardNotFoundError):
        core.create_card(conn, title="Card", blocked_by=["nope"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_core.py -v`
Expected: the four new tests FAIL with `AttributeError: module 'brd.core' has no attribute 'create_card'`. The 15 pre-existing tests in the file still pass.

- [ ] **Step 3: Extend the import block in `src/brd/core.py`**

Replace lines 1-4 of `src/brd/core.py`:

```python
import sqlite3

from brd import db
from brd.models import Card
```

with:

```python
import sqlite3
import uuid
from datetime import datetime, timezone

from brd import db
from brd.models import Card
```

- [ ] **Step 4: Append the error types, sentinel, helpers, and `create_card`**

Append to the end of `src/brd/core.py` (after `would_create_block_cycle`):

```python
class CardNotFoundError(Exception):
    pass


class InvalidStatusError(Exception):
    pass


CLEAR_PARENT = object()  # sentinel: "explicitly set parent_id to None"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_card(conn: sqlite3.Connection, card_id: str) -> Card:
    card = db.get_card(conn, card_id)
    if card is None:
        raise CardNotFoundError(f"no card with id {card_id}")
    return card


def create_card(
    conn: sqlite3.Connection,
    title: str,
    description: str | None = None,
    parent_id: str | None = None,
    blocked_by: list[str] | None = None,
) -> Card:
    if parent_id is not None:
        _require_card(conn, parent_id)

    blocked_by = blocked_by or []
    for blocker_id in blocked_by:
        _require_card(conn, blocker_id)

    now = _now()
    card = Card(
        id=str(uuid.uuid4()),
        title=title,
        description=description,
        status="todo",
        parent_id=parent_id,
        created_at=now,
        updated_at=now,
    )
    db.insert_card(conn, card)

    for blocker_id in blocked_by:
        if would_create_block_cycle(conn, card.id, blocker_id):
            raise CycleError(f"blocking {card.id} on {blocker_id} would create a cycle")
        db.add_blocked_by_edge(conn, card.id, blocker_id)

    return card
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_core.py -v`
Expected: PASS — 19 tests (15 pre-existing + 4 new).

- [ ] **Step 6: Commit**

```bash
git add src/brd/core.py tests/test_core.py
git commit -m "Add core.create_card with card-not-found and cycle validation"
```

---

### Task 2: `update_card` — partial update with the three-valued `parent_id`

**Files:**
- Modify: `src/brd/core.py` (append after `create_card`)
- Test: `tests/test_core.py` (append after the Task 1 tests)

**Interfaces:**
- Consumes: `core._require_card(conn, card_id) -> Card`, `core._now() -> str`, `core.CLEAR_PARENT`, `core.CardNotFoundError`, `core.InvalidStatusError`, `core.CycleError`, `core.would_create_parent_cycle(conn, card_id, new_parent_id) -> bool`, `core.create_card` (used by the tests to build fixtures), `db.update_card_fields(conn, card_id, **fields) -> None`.
- Produces: `core.update_card(conn: sqlite3.Connection, card_id: str, title: str | None = None, description: str | None = None, status: str | None = None, parent_id: str | object | None = None) -> Card` — returns the card re-read from the database after the write.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_core.py`:

```python
def test_update_card_changes_only_given_fields(conn):
    card = core.create_card(conn, title="Original", description="d")
    updated = core.update_card(conn, card.id, title="Updated")
    assert updated.title == "Updated"
    assert updated.description == "d"


def test_update_card_rejects_blocked_status(conn):
    card = core.create_card(conn, title="Card")
    with pytest.raises(core.InvalidStatusError):
        core.update_card(conn, card.id, status="blocked")


def test_update_card_rejects_parent_cycle(conn):
    a = core.create_card(conn, title="A")
    b = core.create_card(conn, title="B", parent_id=a.id)
    with pytest.raises(core.CycleError):
        core.update_card(conn, a.id, parent_id=b.id)


def test_update_card_can_clear_parent(conn):
    a = core.create_card(conn, title="A")
    b = core.create_card(conn, title="B", parent_id=a.id)
    updated = core.update_card(conn, b.id, parent_id=core.CLEAR_PARENT)
    assert updated.parent_id is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_core.py -v`
Expected: the four new tests FAIL with `AttributeError: module 'brd.core' has no attribute 'update_card'`. The 19 tests from Task 1 still pass.

- [ ] **Step 3: Write the minimal implementation**

Append to `src/brd/core.py` (after `create_card`):

```python
def update_card(
    conn: sqlite3.Connection,
    card_id: str,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
    parent_id: str | object | None = None,
) -> Card:
    _require_card(conn, card_id)

    if status == "blocked":
        raise InvalidStatusError("status cannot be set to 'blocked' directly; it is derived")

    fields: dict[str, str | None] = {}
    if title is not None:
        fields["title"] = title
    if description is not None:
        fields["description"] = description
    if status is not None:
        fields["status"] = status

    if parent_id is CLEAR_PARENT:
        fields["parent_id"] = None
    elif parent_id is not None:
        _require_card(conn, parent_id)
        if would_create_parent_cycle(conn, card_id, parent_id):
            raise CycleError(f"setting {card_id}'s parent to {parent_id} would create a cycle")
        fields["parent_id"] = parent_id

    if fields:
        fields["updated_at"] = _now()
        db.update_card_fields(conn, card_id, **fields)

    return _require_card(conn, card_id)
```

Note the deliberate gotcha this encodes: a plain `parent_id=None` means "leave the parent unchanged"; only `CLEAR_PARENT` writes NULL. `title`/`description`/`status` likewise cannot be cleared through this API in v1.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_core.py -v`
Expected: PASS — 23 tests.

- [ ] **Step 5: Commit**

```bash
git add src/brd/core.py tests/test_core.py
git commit -m "Add core.update_card with CLEAR_PARENT sentinel and blocked-status rejection"
```

---

### Task 3: `block_card` and `unblock_card`

**Files:**
- Modify: `src/brd/core.py` (append after `update_card`)
- Test: `tests/test_core.py` (append after the Task 2 tests)

**Interfaces:**
- Consumes: `core._require_card(conn, card_id) -> Card`, `core.would_create_block_cycle(conn, card_id, new_blocker_id) -> bool`, `core.CycleError`, `core.create_card` (test fixtures), `db.add_blocked_by_edge(conn, card_id, blocks_on_id) -> None`, `db.remove_blocked_by_edge(conn, card_id, blocks_on_id) -> None`, `db.list_blockers_of(conn, card_id) -> list[str]`.
- Produces:
  - `core.block_card(conn: sqlite3.Connection, card_id: str, blocker_id: str) -> None`
  - `core.unblock_card(conn: sqlite3.Connection, card_id: str, blocker_id: str) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_core.py`:

```python
def test_block_card_adds_edge(conn):
    a = core.create_card(conn, title="A")
    b = core.create_card(conn, title="B")
    core.block_card(conn, a.id, b.id)
    assert db.list_blockers_of(conn, a.id) == [b.id]


def test_block_card_rejects_cycle(conn):
    a = core.create_card(conn, title="A")
    b = core.create_card(conn, title="B")
    core.block_card(conn, a.id, b.id)
    with pytest.raises(core.CycleError):
        core.block_card(conn, b.id, a.id)


def test_unblock_card_removes_edge(conn):
    a = core.create_card(conn, title="A")
    b = core.create_card(conn, title="B")
    core.block_card(conn, a.id, b.id)
    core.unblock_card(conn, a.id, b.id)
    assert db.list_blockers_of(conn, a.id) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_core.py -v`
Expected: the three new tests FAIL with `AttributeError: module 'brd.core' has no attribute 'block_card'`. The 23 tests from Tasks 1-2 still pass.

- [ ] **Step 3: Write the minimal implementation**

Append to `src/brd/core.py` (after `update_card`):

```python
def block_card(conn: sqlite3.Connection, card_id: str, blocker_id: str) -> None:
    _require_card(conn, card_id)
    _require_card(conn, blocker_id)
    if would_create_block_cycle(conn, card_id, blocker_id):
        raise CycleError(f"blocking {card_id} on {blocker_id} would create a cycle")
    db.add_blocked_by_edge(conn, card_id, blocker_id)


def unblock_card(conn: sqlite3.Connection, card_id: str, blocker_id: str) -> None:
    _require_card(conn, card_id)
    db.remove_blocked_by_edge(conn, card_id, blocker_id)
```

`unblock_card` needs no cycle check: removing an edge can never close a cycle. Removing an edge that does not exist is a no-op at the `db` layer.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_core.py -v`
Expected: PASS — 26 tests.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: PASS — every test in the repo, including the tests inherited from tasks 1-8, is green. No lint or typecheck step is configured.

- [ ] **Step 6: Commit**

```bash
git add src/brd/core.py tests/test_core.py
git commit -m "Add core.block_card and core.unblock_card"
```

---

## Verification

- Full suite: `uv run pytest` — must be green.
- Typecheck: none configured.
- Lint: none configured.
- Diff check: `git diff --stat origin/m1/task-9` must list exactly `src/brd/core.py` and `tests/test_core.py`.
