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
