# Issue #11 — 1.10 Core: next-task selection and tree building

Subtask of story #1 ("Implement brd CLI v1"). Implements Task 10 of `docs/superpowers/plans/2026-09-17-brd-cli.md` (lines 1551-1677), which is followed verbatim: failing test → minimal implementation → passing test → commit.

## Scope

Add exactly two public functions plus one private helper to `src/brd/core.py`, and their tests to `tests/test_core.py`:

- `next_cards(conn: sqlite3.Connection, limit: int | None = None) -> list[Card]`
- `build_tree(conn: sqlite3.Connection, root_id: str | None = None) -> list[dict]`
- `_build_node(conn, card) -> dict` — recursive private helper for `build_tree`.

Nothing else. This subtask consumes, and must not re-implement or modify, work owned by siblings: `resolve_status` and cycle validation (#9), `create_card`/`update_card`/`block_card`/`unblock_card`, `CardNotFoundError` and the `_require_card` helper (#10), `db.list_cards`/`db.list_blockers_of`/`db.list_children` (#6, #7). It must not add the `brd next` / `brd tree` CLI commands (#16) or any output envelope / pretty rendering (#12) — `build_tree` returns plain dicts and `next_cards` returns `Card` dataclasses; formatting is somebody else's job.

### Branch prerequisite

The `m1/task-5` worktree is at the end of Task 4 (DB connect + schema only): `src/brd/core.py` does not exist, and `src/brd/db.py` has no query functions. Before any Task 10 code is written, this branch must be brought onto the end-state of Task 9 — `m1/task-10`'s HEAD, commit message "test: cover spec'd error paths and updated_at behavior for card writes" — by rebase/merge. Without it `core.resolve_status`, `core._require_card`, `db.list_cards`, `db.list_blockers_of` and `db.list_children` do not exist to import, and every test below fails for the wrong reason.

## Observable behavior

### `next_cards(conn, limit=None)`

- Returns every card whose **resolved** status is `"todo"`: the candidate set is `db.list_cards(conn, status="todo")` (stored status), each candidate then filtered through `resolve_status(conn, card)` so cards with at least one unresolved blocker (resolved status `"blocked"`) are dropped.
- Cards stored as `in_progress` or `done` are never returned — they are excluded by the `status="todo"` query itself.
- Ordering is `created_at` ascending, inherited from `db.list_cards`; no re-sorting in core.
- `limit=None` (default) returns all matches. An integer `limit` truncates the ordered list to the first `limit` items (`ready[:limit]`); a `limit` larger than the result set returns everything, and `limit=0` returns `[]`.
- Returns `[]` on an empty board or when every `todo` card is blocked.
- Read-only: no writes, no commit.

### `build_tree(conn, root_id=None)`

- Returns a **list** of root nodes in both modes.
- `root_id=None`: one node per top-level card, i.e. `db.list_cards(conn, parent_id=None)` — the explicit `None` sentinel meaning `parent_id IS NULL`, which is distinct from omitting the argument (`_UNSET` = no filter). Nested cards appear only inside their parent's `children`, never as roots.
- `root_id="<id>"`: a single-element list holding that card's subtree; the card is fetched through the existing `_require_card` helper.
- Node shape, exactly: `{"id": str, "title": str, "status": str, "blocked_by": list[str], "children": list[node]}`.
  - `status` is the **resolved** status from `resolve_status` — `"blocked"` never comes from the `status` column, which never literally stores `'blocked'`.
  - `blocked_by` is `db.list_blockers_of(conn, card.id)` verbatim — the list of `blocks_on_id` strings in whatever order `db.list_blockers_of` returns them (that function has no `ORDER BY`, so order is SQLite's insertion/rowid order, not sorted by the blockers' `created_at`); `[]` when unblocked. `build_tree` does no reordering.
  - `children` is built recursively from `db.list_children(conn, card.id)`, `created_at` ascending; `[]` for a leaf.
- Recursion depth is bounded by the parent hierarchy, which #9's `would_create_parent_cycle` guarantees is acyclic; no cycle handling is added here.
- Read-only: no writes, no commit.

## Error paths

- `build_tree(conn, root_id=<unknown id>)` raises `CardNotFoundError` — inherited unchanged from `_require_card` (#10). No new exception type is introduced by this subtask.
- `next_cards` has no error path: an empty board is an empty list, not an error. Invalid `limit` values are not validated here (CLI-level concern, #16).

## Test list

All tests are **core unit tests** under the design spec's testing rule (`docs/superpowers/specs/2026-09-17-brd-cli-design.md` lines 183-192): "core.py and db.py: unit tests against a temp SQLite file ... no mocking of SQLite itself". The repo has one flat `tests/` directory mirroring `src/brd/`, with no unit/integration/e2e split. Every test below therefore goes in `tests/test_core.py`, calling the functions directly against the existing `conn` fixture (`db.connect(tmp_path / "project.db")` + `db.init_project_schema(...)`) — a real temp-file SQLite database, no mocks, no CLI layer. None of these belong in `tests/test_cli.py`, which is reserved for the command-surface e2e tests of #13-16.

From the plan (lines 1568-1626), verbatim:

1. `test_next_cards_returns_unblocked_todo_oldest_first` — three cards, one blocked; result is `[a.id, blocker.id]` (blocked card dropped, creation order preserved). *Tier: core unit, `tests/test_core.py`.*
2. `test_next_cards_excludes_in_progress_and_done` — only the untouched `todo` card is returned. *Tier: core unit, `tests/test_core.py`.*
3. `test_next_cards_respects_limit` — three `todo` cards, `limit=2` returns 2. *Tier: core unit, `tests/test_core.py`.*
4. `test_build_tree_single_root_with_children_and_blockers` — `root_id=parent.id` returns one node, root `status == "todo"`, one child whose `status == "blocked"`, `blocked_by == [blocker.id]`, `children == []`. *Tier: core unit, `tests/test_core.py`.*
5. `test_build_tree_whole_board_returns_all_top_level_roots` — three top-level cards plus one nested; `build_tree(conn)` returns 3 roots. *Tier: core unit, `tests/test_core.py`.*

## Verification

`uv run pytest` — full suite green: the 23 tests currently passing on `m1/task-5` before the rebase in "Branch prerequisite," plus everything gained by rebasing onto `m1/task-10` (Tasks 6-9), plus the five tests above. The exact count is informational only; the pass/fail result is what gates this subtask. No typecheck or lint step is configured for this repo.
