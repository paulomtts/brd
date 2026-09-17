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
