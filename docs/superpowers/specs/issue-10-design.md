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
