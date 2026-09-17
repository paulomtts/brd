<!-- task-pipeline: validated -->
# Spec (verbatim)

> The following is the design spec this plan implements, copied verbatim from `docs/superpowers/specs/issue-9-design.md`.

---

# Issue #9 — Core: status derivation and cycle validation

Subtask of story #1 (`brd` CLI v1). Implements Task 8 of `docs/superpowers/plans/2026-09-17-brd-cli.md` (lines 1115-1316). This narrows the already-agreed design in `docs/superpowers/specs/2026-09-17-brd-cli-design.md`; no new design decisions are made here.

## Scope

Create `src/brd/core.py` (new module) and `tests/test_core.py` (new test file), containing exactly four public names:

- `CycleError(Exception)` — empty marker exception. Defined here, raised by later subtasks' write paths; caught once at the `cli.py` boundary (design spec lines 169-174). `core.py` does not catch or print it.
- `resolve_status(conn, card: Card) -> str`
- `would_create_parent_cycle(conn, card_id: str, new_parent_id: str) -> bool`
- `would_create_block_cycle(conn, card_id: str, new_blocker_id: str) -> bool`

Nothing else. `create_card`/`update_card`/`block`/`unblock` belong to issue #10; `next`/tree building belong to issue #11; all `db.py` query functions belong to issues #6/#7.

### Layering constraints (design spec lines 33-52)

`core.py` is business logic only: no `typer` import, no SQL strings, no `sqlite3` cursor use. It imports `sqlite3` for the `Connection` type annotation only, and reaches storage exclusively through `brd.db` functions (`get_card`, `list_blockers_of`). It performs no writes — `resolve_status` is pure computation and must never persist a derived status back to the `cards` row (`status` never stores `'blocked'`; design spec lines 109-113).

### Sequencing dependency (already satisfied)

`core.py` consumes `db.get_card`, `db.insert_card`, `db.list_blockers_of` and `db.add_blocked_by_edge`, which are issue #7 (Task 6) scope. The plan is a strictly linear PR stack, and issue #7's work has already landed on this worktree's base — `db.py` already provides `connect`, `init_master_schema`, `init_project_schema`, `insert_project`, `get_project_by_id`, `get_project_by_name`, `list_projects`, `insert_card`, `get_card`, `update_card_fields`, `list_cards`, `add_blocked_by_edge`, `remove_blocked_by_edge`, `list_blockers_of`, and `list_children`. No further sequencing action is needed for this subtask. Do not reimplement card/edge queries inside `core.py` — that would violate the layering rule and duplicate a sibling's scope.

## Observable behavior

### `resolve_status(conn, card)`

Returns the card's *displayed* status, one of `todo`, `in_progress`, `done`, `blocked`.

- `card.status` is `in_progress` or `done` → returned unchanged; blockers are irrelevant.
- `card.status` is `todo` → for each blocker id from `db.list_blockers_of(conn, card.id)` (edge semantics: `card_id` is blocked by `blocks_on_id`, design spec lines 115-124), fetch the blocker card and recursively resolve *its* status. If any blocker's resolved status is not `"done"`, return `"blocked"`; if all are `done` (or there are no blockers), return `"todo"`.
- Blocking is therefore transitive: a `todo` card whose blocker is itself `blocked` is `blocked`.
- Recursion carries a private `_seen: set[str] | None = None` parameter. A card id already in `_seen` short-circuits to `"todo"` rather than recursing. This is defensive only — the cycle predicates below are supposed to prevent such a graph ever being persisted — and is not part of the public contract.
- A blocker id that resolves to a missing card (`db.get_card` returns `None`) is skipped, not treated as unresolved.

### `would_create_parent_cycle(conn, card_id, new_parent_id)`

Ancestor check: walk the `parent_id` chain upward starting at `new_parent_id`, following `db.get_card(...).parent_id` until `None`. Returns `True` if `card_id` is encountered anywhere in that chain (direct parent or any indirect ancestor), else `False`. A `None` parent link or a missing card terminates the walk with `False`.

### `would_create_block_cycle(conn, card_id, new_blocker_id)`

Reachability check over the blocking graph: stack-based DFS from `new_blocker_id`, expanding via `db.list_blockers_of`, with a `visited` set. Returns `True` if `card_id` is reachable (directly or transitively), else `False`.

### Independence of the two checks

Hierarchy and blocking are validated by two separate algorithms over two separate relations (design spec lines 126-135). They must not be merged into a shared generic graph walk.

## Error paths

- No exceptions are raised by any of the three functions in this subtask. `CycleError` is *defined* here and raised by callers in issues #10/#15; defining it now is intentional so the write paths have a typed exception to raise.
- Missing/dangling references (`db.get_card` returning `None`) are tolerated silently: skipped in `resolve_status`, terminating the walk in `would_create_parent_cycle`. They are not an error condition at this layer.
- Cyclic persisted data does not raise either — `resolve_status` terminates via `_seen`, the predicates terminate via `visited`. No infinite recursion, no `RecursionError` on a cyclic graph.

## Test list

Test-placement rule (design spec lines 183-192, a 2-tier taxonomy — unit vs. CLI end-to-end; there is no integration/conformance tier in this repo): `core.py` and `db.py` get **unit tests against a real temp SQLite file**, with SQLite never mocked; only `cli.py` gets end-to-end tests against a monkeypatched temp XDG data dir. Every test below is therefore a **unit test** in `tests/test_core.py`, driven through a `conn` fixture built from `db.connect(tmp_path / "project.db")` + `db.init_project_schema(...)`, with cards inserted via `db.insert_card` and edges via `db.add_blocked_by_edge`. None of these belong in a CLI e2e test, and no `sqlite3` object is mocked or faked.

The twelve tests are given verbatim in the plan (lines 1134-1239) and are the exact starting content for `tests/test_core.py`:

1. `test_resolve_status_todo_with_no_blockers_is_todo` — unit.
2. `test_resolve_status_todo_with_unresolved_blocker_is_blocked` — unit.
3. `test_resolve_status_todo_with_done_blocker_is_todo` — unit.
4. `test_resolve_status_todo_with_transitively_blocked_blocker_is_blocked` — unit.
5. `test_resolve_status_in_progress_is_unaffected_by_blockers` — unit.
6. `test_would_create_parent_cycle_direct` — unit.
7. `test_would_create_parent_cycle_indirect` — unit.
8. `test_would_create_parent_cycle_false_for_unrelated_cards` — unit.
9. `test_would_create_block_cycle_direct` — unit.
10. `test_would_create_block_cycle_indirect` — unit.
11. `test_would_create_block_cycle_false_for_unrelated_cards` — unit.
12. A module-local `_card(id_, status="todo", parent_id=None)` helper builds `Card` instances with fixed ISO timestamps (not a test; listed so it is not mistaken for missing scope).

Cycle-count note: the plan's file contains 11 test functions plus the fixture and helper; the "12 tests" figure in the breakdown counts the helper. No additional tests are in scope for this subtask.

## Verification

- Full suite: `uv run pytest`
- Typecheck: none configured.
- Lint: none configured.

Expected TDD sequence per the plan: tests fail with `ModuleNotFoundError: No module named 'brd.core'` before step 3, pass after. The plan's reference implementation (lines 1250-1304) is the exact target shape.

---

# Core Status Derivation and Cycle Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `src/brd/core.py` with `CycleError`, `resolve_status`, `would_create_parent_cycle`, and `would_create_block_cycle`, covered by unit tests in `tests/test_core.py`.

**Architecture:** `core.py` is the pure business-logic layer between `db.py` (storage) and `cli.py` (presentation). It reads through `brd.db` functions only — no SQL, no `sqlite3` cursor calls, no `typer`, and no writes. Status derivation is a recursive walk over the `blocked_by` relation; the two cycle predicates are deliberately separate algorithms over two separate relations (`parent_id` chain vs. blocking graph) and must not be merged.

**Tech Stack:** Python 3.12+, stdlib `sqlite3` (type annotation only in `core.py`), `pytest` 9.x via `uv run pytest`.

**Spec:** `docs/superpowers/specs/issue-9-design.md` (reproduced verbatim at the top of this file).

## Global Constraints

- Branch: `m1/task-9`, worktree `/home/paulomtts/Code/brd/.claude/worktrees/m1/task-9`, cut from `origin/m1/task-8`. Do not assume any other subtask's code exists.
- Exactly two files are touched: create `src/brd/core.py`, create `tests/test_core.py`. No other file is modified.
- Exactly four public names in `core.py`: `CycleError`, `resolve_status`, `would_create_parent_cycle`, `would_create_block_cycle`. No `create_card`/`update_card`/`block`/`unblock` (issue #10), no `next`/tree (issue #11), no new `db.py` functions (issues #6/#7).
- Layering: `core.py` imports `sqlite3` for the `Connection` annotation only. No SQL strings, no cursor use, no `typer` import. Storage access exclusively through `brd.db`.
- `status` never stores `"blocked"` — `resolve_status` is pure computation and performs no writes.
- Edge semantics: `blocked_by(card_id, blocks_on_id)` means `card_id` is blocked by `blocks_on_id`. `db.list_blockers_of(conn, card_id) -> list[str]` returns the `blocks_on_id` values.
- `core.py` raises nothing in this subtask. `CycleError` is defined here for issues #10/#15 to raise and for `cli.py` to catch. Missing cards (`db.get_card` returns `None`) are tolerated silently.
- Test tier: all tests are **unit** tests in the flat `tests/` directory (`tests/test_core.py`), against a real temp-file SQLite connection. Never mock `sqlite3`. No CLI e2e test in this subtask.
- Verification: `uv run pytest`. No typecheck and no lint are configured in this repo.

## File Structure

- **Create `src/brd/core.py`** — the whole deliverable module. Grows across the three tasks below: `CycleError` + `resolve_status` (Task 1), `would_create_parent_cycle` (Task 2), `would_create_block_cycle` (Task 3). Final content is identical to the reference implementation in `docs/superpowers/plans/2026-09-17-brd-cli.md:1250-1304`.
- **Create `tests/test_core.py`** — unit tests. Grows across the same three tasks; final content is identical to `docs/superpowers/plans/2026-09-17-brd-cli.md:1134-1239` (shared `conn` fixture + `_card` helper + 11 test functions).
- **Read-only dependencies (do not modify):** `src/brd/db.py` (`connect`, `init_project_schema`, `insert_card`, `get_card`, `add_blocked_by_edge`, `list_blockers_of`) and `src/brd/models.py` (`Card` dataclass: `id`, `title`, `description`, `status`, `parent_id`, `created_at`, `updated_at`, all `str` except `description: str | None` and `parent_id: str | None`).

---

### Task 1: `CycleError` and `resolve_status`

**Files:**
- Create: `src/brd/core.py`
- Test: `tests/test_core.py`

**Interfaces:**
- Consumes: `brd.db.connect(db_path: Path) -> sqlite3.Connection`, `brd.db.init_project_schema(conn) -> None`, `brd.db.insert_card(conn, card: Card) -> None`, `brd.db.get_card(conn, card_id: str) -> Card | None`, `brd.db.add_blocked_by_edge(conn, card_id: str, blocks_on_id: str) -> None`, `brd.db.list_blockers_of(conn, card_id: str) -> list[str]`, `brd.models.Card`.
- Produces: `core.CycleError(Exception)` and `core.resolve_status(conn: sqlite3.Connection, card: Card, _seen: set[str] | None = None) -> str`, returning one of `"todo"`, `"in_progress"`, `"done"`, `"blocked"`. Also produces the `conn` fixture and `_card(id_, status="todo", parent_id=None) -> Card` helper in `tests/test_core.py`, reused by Tasks 2 and 3.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_core.py` with exactly this content:

```python
import pytest

from brd import core, db
from brd.models import Card


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "project.db")
    db.init_project_schema(connection)
    yield connection
    connection.close()


def _card(id_, status="todo", parent_id=None):
    return Card(
        id=id_,
        title=id_,
        description=None,
        status=status,
        parent_id=parent_id,
        created_at="2026-09-17T00:00:00",
        updated_at="2026-09-17T00:00:00",
    )


def test_resolve_status_todo_with_no_blockers_is_todo(conn):
    db.insert_card(conn, _card("c1"))
    card = db.get_card(conn, "c1")
    assert core.resolve_status(conn, card) == "todo"


def test_resolve_status_todo_with_unresolved_blocker_is_blocked(conn):
    db.insert_card(conn, _card("c1"))
    db.insert_card(conn, _card("blocker", status="todo"))
    db.add_blocked_by_edge(conn, "c1", "blocker")
    card = db.get_card(conn, "c1")
    assert core.resolve_status(conn, card) == "blocked"


def test_resolve_status_todo_with_done_blocker_is_todo(conn):
    db.insert_card(conn, _card("c1"))
    db.insert_card(conn, _card("blocker", status="done"))
    db.add_blocked_by_edge(conn, "c1", "blocker")
    card = db.get_card(conn, "c1")
    assert core.resolve_status(conn, card) == "todo"


def test_resolve_status_todo_with_transitively_blocked_blocker_is_blocked(conn):
    db.insert_card(conn, _card("c1"))
    db.insert_card(conn, _card("mid", status="todo"))
    db.insert_card(conn, _card("root", status="todo"))
    db.add_blocked_by_edge(conn, "c1", "mid")
    db.add_blocked_by_edge(conn, "mid", "root")
    card = db.get_card(conn, "c1")
    assert core.resolve_status(conn, card) == "blocked"


def test_resolve_status_in_progress_is_unaffected_by_blockers(conn):
    db.insert_card(conn, _card("c1", status="in_progress"))
    db.insert_card(conn, _card("blocker", status="todo"))
    db.add_blocked_by_edge(conn, "c1", "blocker")
    card = db.get_card(conn, "c1")
    assert core.resolve_status(conn, card) == "in_progress"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_core.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'brd.core'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/brd/core.py` with exactly this content:

```python
import sqlite3

from brd import db
from brd.models import Card


class CycleError(Exception):
    pass


def resolve_status(conn: sqlite3.Connection, card: Card, _seen: set[str] | None = None) -> str:
    if card.status != "todo":
        return card.status

    seen = _seen or set()
    if card.id in seen:
        # Defensive: a blocked_by cycle should never be persisted, but avoid
        # infinite recursion if one somehow exists.
        return "todo"
    seen = seen | {card.id}

    for blocker_id in db.list_blockers_of(conn, card.id):
        blocker = db.get_card(conn, blocker_id)
        if blocker is None:
            continue
        if resolve_status(conn, blocker, seen) != "done":
            return "blocked"

    return "todo"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_core.py -v`
Expected: PASS — 5 passed.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: PASS — all pre-existing tests in `tests/test_paths.py`, `tests/test_models.py`, `tests/test_db.py`, `tests/test_master.py`, `tests/test_cli.py` still pass, plus the 5 new ones.

- [ ] **Step 6: Commit**

```bash
git add src/brd/core.py tests/test_core.py
git commit -m "Add CycleError and recursive status derivation"
```

---

### Task 2: `would_create_parent_cycle`

**Files:**
- Modify: `src/brd/core.py`
- Test: `tests/test_core.py`

**Interfaces:**
- Consumes: `brd.db.get_card(conn, card_id: str) -> Card | None` (reads `.parent_id`), plus the `conn` fixture and `_card` helper from Task 1.
- Produces: `core.would_create_parent_cycle(conn: sqlite3.Connection, card_id: str, new_parent_id: str) -> bool` — `True` when `card_id` is an ancestor of `new_parent_id` (so reparenting would make `card_id` its own ancestor), else `False`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_core.py`, after `test_resolve_status_in_progress_is_unaffected_by_blockers`:

```python
def test_would_create_parent_cycle_direct(conn):
    db.insert_card(conn, _card("a"))
    db.insert_card(conn, _card("b", parent_id="a"))
    assert core.would_create_parent_cycle(conn, "a", "b") is True


def test_would_create_parent_cycle_indirect(conn):
    db.insert_card(conn, _card("a"))
    db.insert_card(conn, _card("b", parent_id="a"))
    db.insert_card(conn, _card("c", parent_id="b"))
    assert core.would_create_parent_cycle(conn, "a", "c") is True


def test_would_create_parent_cycle_false_for_unrelated_cards(conn):
    db.insert_card(conn, _card("a"))
    db.insert_card(conn, _card("b"))
    assert core.would_create_parent_cycle(conn, "a", "b") is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_core.py -k parent_cycle -v`
Expected: FAIL — `AttributeError: module 'brd.core' has no attribute 'would_create_parent_cycle'` on all 3.

- [ ] **Step 3: Write the minimal implementation**

Append to `src/brd/core.py`, after `resolve_status`:

```python
def would_create_parent_cycle(conn: sqlite3.Connection, card_id: str, new_parent_id: str) -> bool:
    current_id: str | None = new_parent_id
    while current_id is not None:
        if current_id == card_id:
            return True
        parent = db.get_card(conn, current_id)
        current_id = parent.parent_id if parent else None
    return False
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_core.py -v`
Expected: PASS — 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/brd/core.py tests/test_core.py
git commit -m "Add parent hierarchy cycle detection"
```

---

### Task 3: `would_create_block_cycle`

**Files:**
- Modify: `src/brd/core.py`
- Test: `tests/test_core.py`

**Interfaces:**
- Consumes: `brd.db.list_blockers_of(conn, card_id: str) -> list[str]`, plus the `conn` fixture and `_card` helper from Task 1.
- Produces: `core.would_create_block_cycle(conn: sqlite3.Connection, card_id: str, new_blocker_id: str) -> bool` — `True` when `card_id` is reachable from `new_blocker_id` through the blocking graph (directly or transitively), else `False`. This is a separate algorithm from `would_create_parent_cycle`; do not refactor the two into a shared generic graph walk.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_core.py`, after `test_would_create_parent_cycle_false_for_unrelated_cards`:

```python
def test_would_create_block_cycle_direct(conn):
    db.insert_card(conn, _card("a"))
    db.insert_card(conn, _card("b"))
    db.add_blocked_by_edge(conn, "a", "b")
    assert core.would_create_block_cycle(conn, "b", "a") is True


def test_would_create_block_cycle_indirect(conn):
    db.insert_card(conn, _card("a"))
    db.insert_card(conn, _card("b"))
    db.insert_card(conn, _card("c"))
    db.add_blocked_by_edge(conn, "a", "b")
    db.add_blocked_by_edge(conn, "b", "c")
    assert core.would_create_block_cycle(conn, "c", "a") is True


def test_would_create_block_cycle_false_for_unrelated_cards(conn):
    db.insert_card(conn, _card("a"))
    db.insert_card(conn, _card("b"))
    assert core.would_create_block_cycle(conn, "a", "b") is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_core.py -k block_cycle -v`
Expected: FAIL — `AttributeError: module 'brd.core' has no attribute 'would_create_block_cycle'` on all 3.

- [ ] **Step 3: Write the minimal implementation**

Append to `src/brd/core.py`, after `would_create_parent_cycle`:

```python
def would_create_block_cycle(conn: sqlite3.Connection, card_id: str, new_blocker_id: str) -> bool:
    stack = [new_blocker_id]
    visited: set[str] = set()
    while stack:
        current = stack.pop()
        if current == card_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        stack.extend(db.list_blockers_of(conn, current))
    return False
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_core.py -v`
Expected: PASS — 11 passed.

- [ ] **Step 5: Confirm the module's final shape**

Read `src/brd/core.py` and confirm it matches the spec's scope exactly: `import sqlite3`, `from brd import db`, `from brd.models import Card`, then `CycleError`, `resolve_status`, `would_create_parent_cycle`, `would_create_block_cycle` — no SQL strings, no `typer` import, no cursor calls, no writes, and no extra public names.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest`
Expected: PASS — every test in the repo, including the 11 in `tests/test_core.py`.

- [ ] **Step 7: Commit**

```bash
git add src/brd/core.py tests/test_core.py
git commit -m "Add blocking graph cycle detection"
```
