<!-- task-pipeline: validated -->
<!-- SPEC (verbatim copy of docs/superpowers/specs/issue-11-design.md) -->

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

<!-- END SPEC -->

---

# Core next-task selection and tree building — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `core.next_cards` and `core.build_tree` to `src/brd/core.py` so the board can answer "what should I work on next?" and "what does the card hierarchy look like?" without any CLI or formatting code.

**Architecture:** Both functions are thin, read-only compositions over already-existing layers: `db.list_cards` / `db.list_blockers_of` / `db.list_children` supply the rows, and `core.resolve_status` (owned by #9) turns stored `todo` into the derived `todo` / `blocked` distinction. `next_cards` filters the `status="todo"` query through `resolve_status` and slices by `limit`; `build_tree` walks the `parent_id` hierarchy with a recursive private `_build_node` helper that emits plain dicts. No new exception types, no writes, no `conn.commit()`.

**Tech Stack:** Python 3.11+, stdlib `sqlite3` (no ORM), `pytest`, `uv` as the runner.

**Spec:** `docs/superpowers/specs/issue-11-design.md` (also prepended verbatim at the top of this file).

## Global Constraints

- No ORM — plain stdlib `sqlite3` only; `src/brd/db.py` already follows this and is the only module that issues SQL.
- The `status` column never literally stores `'blocked'`. Blocked-ness is always derived at read time via `core.resolve_status(conn, card)` (`src/brd/core.py:13-31`). Both new functions must call `resolve_status` rather than trusting `card.status`, except for the initial `status="todo"` database filter.
- Card IDs are UUID4 strings; `Card` / `Project` are frozen-shape dataclasses in `src/brd/models.py:4-21`.
- `db.list_cards(conn, status=None, parent_id=_UNSET)` (`src/brd/db.py:140-158`): `_UNSET` (the string `"__unset__"`, `src/brd/db.py:137`) means "no `parent_id` filter"; an explicit `parent_id=None` means `parent_id IS NULL`. These are distinct — `build_tree` must pass `parent_id=None` explicitly.
- `db.list_blockers_of(conn, card_id) -> list[str]` (`src/brd/db.py:181-185`) and `db.list_children(conn, parent_id) -> list[Card]` (`src/brd/db.py:188-192`) are the exact helpers to consume. `list_children` orders by `created_at`; `list_blockers_of` has no `ORDER BY` — do not add sorting in core.
- Scope fence: only `next_cards`, `build_tree`, and `_build_node` are added, plus their five tests. Do not touch `resolve_status`, the cycle helpers, the card write operations, `src/brd/db.py`, `src/brd/cli.py`, or add an output envelope.
- TDD is mandatory: failing test → run it and see it fail → minimal implementation → run it and see it pass → commit.

## File Structure

| File | Role in this change |
| --- | --- |
| `src/brd/core.py` | **Modify.** Append `next_cards`, `_build_node`, `build_tree` at the end of the file (after `unblock_card`, currently ending at line 160). No existing function is edited. |
| `tests/test_core.py` | **Modify.** Append five tests at the end of the file (currently ending at line 261), using the existing module-level `conn` fixture at lines 7-12. |

Nothing is created and nothing else is modified.

## Branch prerequisite (already satisfied — verify, do not redo)

The spec's "Branch prerequisite" section describes the `m1/task-5` worktree. The worktree this plan executes in — `/home/paulomtts/Code/brd/.claude/worktrees/m1/task-11`, branch `m1/task-11` — was cut fresh from `origin/m1/task-10`, so Tasks 6-9 are already present: `src/brd/core.py` exists with `resolve_status` (lines 13-31), `CardNotFoundError` (line 58), `_require_card` (lines 73-77) and the card write operations; `src/brd/db.py` has `list_cards`, `list_blockers_of` and `list_children`. Task 1 Step 1 below verifies this rather than performing any rebase. If that verification fails, stop and escalate — do not rebase or merge as part of this plan.

---

### Task 1: `next_cards` — unblocked todo selection

**Files:**
- Modify: `src/brd/core.py` (append after line 160, the end of `unblock_card`)
- Test: `tests/test_core.py` (append after line 261)

**Interfaces:**
- Consumes: `db.list_cards(conn, status="todo") -> list[Card]` (`src/brd/db.py:140`); `resolve_status(conn: sqlite3.Connection, card: Card) -> str` (`src/brd/core.py:13`); `create_card(conn, title=..., ...) -> Card`, `update_card(conn, card_id, status=...) -> Card`, `block_card(conn, card_id, blocker_id) -> None` (`src/brd/core.py:80,114,150`) for test setup; `Card` (`src/brd/models.py:13`).
- Produces: `core.next_cards(conn: sqlite3.Connection, limit: int | None = None) -> list[Card]` — cards whose resolved status is `"todo"`, `created_at` ascending, truncated to `limit` when `limit is not None`. Used later by the `brd next` CLI command (#16), which is out of scope here.

- [ ] **Step 1: Verify the baseline is the end of Task 9 and the suite is green**

Run:

```bash
uv run pytest
```

Expected: all tests pass. Then confirm the prerequisites this task imports actually exist:

```bash
grep -n "def resolve_status\|def _require_card\|class CardNotFoundError" src/brd/core.py
grep -n "def list_cards\|def list_blockers_of\|def list_children" src/brd/db.py
```

Expected: six matches (`resolve_status`, `_require_card`, `CardNotFoundError` in `core.py`; `list_cards`, `list_blockers_of`, `list_children` in `db.py`). If any are missing, stop and escalate — the branch is not on `origin/m1/task-10`.

- [ ] **Step 2: Write the three failing `next_cards` tests**

Append to `tests/test_core.py` (the `conn` fixture at lines 7-12 is already in this file — do not redefine it):

```python
def test_next_cards_returns_unblocked_todo_oldest_first(conn):
    a = core.create_card(conn, title="A")
    b = core.create_card(conn, title="B")
    blocker = core.create_card(conn, title="Blocker")
    core.block_card(conn, b.id, blocker.id)

    result = core.next_cards(conn)
    assert [c.id for c in result] == [a.id, blocker.id]


def test_next_cards_excludes_in_progress_and_done(conn):
    a = core.create_card(conn, title="A")
    core.update_card(conn, a.id, status="in_progress")
    b = core.create_card(conn, title="B")
    core.update_card(conn, b.id, status="done")
    c = core.create_card(conn, title="C")

    result = core.next_cards(conn)
    assert [card.id for card in result] == [c.id]


def test_next_cards_respects_limit(conn):
    core.create_card(conn, title="A")
    core.create_card(conn, title="B")
    core.create_card(conn, title="C")

    result = core.next_cards(conn, limit=2)
    assert len(result) == 2
```

- [ ] **Step 3: Run the tests to verify they fail**

Run:

```bash
uv run pytest tests/test_core.py -k next_cards -v
```

Expected: 3 failures, each `AttributeError: module 'brd.core' has no attribute 'next_cards'`.

- [ ] **Step 4: Write the minimal implementation**

Append to `src/brd/core.py`, after `unblock_card` (current last line 160):

```python
def next_cards(conn: sqlite3.Connection, limit: int | None = None) -> list[Card]:
    todo_cards = db.list_cards(conn, status="todo")
    ready = [card for card in todo_cards if resolve_status(conn, card) == "todo"]
    return ready[:limit] if limit is not None else ready
```

`sqlite3`, `db` and `Card` are already imported at `src/brd/core.py:1-6` — add no new imports.

- [ ] **Step 5: Run the tests to verify they pass**

Run:

```bash
uv run pytest tests/test_core.py -k next_cards -v
```

Expected: 3 passed.

- [ ] **Step 6: Run the full suite**

Run:

```bash
uv run pytest
```

Expected: every test passes — the pre-existing `tests/test_core.py` tests plus the three new ones, with no regressions elsewhere.

- [ ] **Step 7: Commit**

```bash
git add src/brd/core.py tests/test_core.py
git commit -m "Add core next_cards selection of unblocked todo cards

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011rpKbM8YZgV45PCeiFqncT"
```

---

### Task 2: `build_tree` — hierarchical node tree

**Files:**
- Modify: `src/brd/core.py` (append after the `next_cards` function added in Task 1)
- Test: `tests/test_core.py` (append after the `next_cards` tests added in Task 1)

**Interfaces:**
- Consumes: `resolve_status(conn: sqlite3.Connection, card: Card) -> str` (`src/brd/core.py:13`); `_require_card(conn: sqlite3.Connection, card_id: str) -> Card`, which raises `CardNotFoundError` for an unknown id (`src/brd/core.py:73-77`); `db.list_cards(conn, status=None, parent_id=_UNSET) -> list[Card]` (`src/brd/db.py:140`); `db.list_blockers_of(conn, card_id) -> list[str]` (`src/brd/db.py:181`); `db.list_children(conn, parent_id) -> list[Card]` (`src/brd/db.py:188`); `create_card(conn, title=..., parent_id=..., blocked_by=[...]) -> Card` (`src/brd/core.py:80`) for test setup.
- Produces:
  - `core._build_node(conn: sqlite3.Connection, card: Card) -> dict` — private recursive node builder returning `{"id": str, "title": str, "status": str, "blocked_by": list[str], "children": list[dict]}`.
  - `core.build_tree(conn: sqlite3.Connection, root_id: str | None = None) -> list[dict]` — a list of root nodes: every `parent_id IS NULL` card when `root_id is None`, or a one-element list holding `root_id`'s subtree. Consumed later by the `brd tree` CLI command (#16), which is out of scope here.

- [ ] **Step 1: Write the two failing `build_tree` tests**

Append to `tests/test_core.py`:

```python
def test_build_tree_single_root_with_children_and_blockers(conn):
    parent = core.create_card(conn, title="Parent")
    blocker = core.create_card(conn, title="Blocker")
    child = core.create_card(
        conn, title="Child", parent_id=parent.id, blocked_by=[blocker.id]
    )

    tree = core.build_tree(conn, root_id=parent.id)
    assert len(tree) == 1
    root_node = tree[0]
    assert root_node["id"] == parent.id
    assert root_node["status"] == "todo"
    assert len(root_node["children"]) == 1
    child_node = root_node["children"][0]
    assert child_node["id"] == child.id
    assert child_node["status"] == "blocked"
    assert child_node["blocked_by"] == [blocker.id]
    assert child_node["children"] == []


def test_build_tree_whole_board_returns_all_top_level_roots(conn):
    core.create_card(conn, title="Root1")
    core.create_card(conn, title="Root2")
    parent = core.create_card(conn, title="Root3")
    core.create_card(conn, title="Nested", parent_id=parent.id)

    tree = core.build_tree(conn)
    assert len(tree) == 3  # three top-level cards; "Nested" only appears as a child
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
uv run pytest tests/test_core.py -k build_tree -v
```

Expected: 2 failures, each `AttributeError: module 'brd.core' has no attribute 'build_tree'`.

- [ ] **Step 3: Write the minimal implementation**

Append to `src/brd/core.py`, after the `next_cards` function added in Task 1:

```python
def _build_node(conn: sqlite3.Connection, card: Card) -> dict:
    return {
        "id": card.id,
        "title": card.title,
        "status": resolve_status(conn, card),
        "blocked_by": db.list_blockers_of(conn, card.id),
        "children": [
            _build_node(conn, child) for child in db.list_children(conn, card.id)
        ],
    }


def build_tree(conn: sqlite3.Connection, root_id: str | None = None) -> list[dict]:
    if root_id is not None:
        card = _require_card(conn, root_id)
        return [_build_node(conn, card)]

    top_level = db.list_cards(conn, parent_id=None)
    return [_build_node(conn, card) for card in top_level]
```

Note the explicit `parent_id=None`: omitting the argument would use `db._UNSET` and return *every* card as a root. And `_require_card` is reused as-is so an unknown `root_id` raises the existing `CardNotFoundError` (spec "Error paths") — do not add a new exception type or a local `db.get_card` call.

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
uv run pytest tests/test_core.py -k build_tree -v
```

Expected: 2 passed.

- [ ] **Step 5: Run the full suite**

Run:

```bash
uv run pytest
```

Expected: every test passes — all pre-existing tests plus the five added across Tasks 1 and 2.

- [ ] **Step 6: Confirm the scope fence held**

Run:

```bash
git diff --stat origin/m1/task-10
```

Expected: exactly two files changed — `src/brd/core.py` and `tests/test_core.py` (plus `docs/superpowers/` files added by the workflow). If `src/brd/db.py`, `src/brd/cli.py` or any other source file appears, revert those hunks: this subtask only consumes #6/#7/#9/#10's work.

- [ ] **Step 7: Commit**

```bash
git add src/brd/core.py tests/test_core.py
git commit -m "Add core build_tree hierarchy construction

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011rpKbM8YZgV45PCeiFqncT"
```

---

## Notes on deliberate omissions

- **No new test for `build_tree(conn, root_id="unknown")`.** The spec's "Error paths" section states this raises `CardNotFoundError` *inherited unchanged* from `_require_card`, and its "Test list" is the five tests above, verbatim from the source plan. `_require_card`'s raising behavior is already covered by #10's tests in `tests/test_core.py` (e.g. `test_update_card_rejects_unknown_card`, lines 216-218). Adding a sixth test here would test #10's code, not this subtask's.
- **No `limit=0` / empty-board tests.** Those behaviors fall out of `ready[:limit]` and the empty query result; the spec lists them as observable consequences, not as test cases.
- **No typecheck or lint step.** This repo configures neither; `uv run pytest` is the sole verification command.
