# 1.1 A container releases dependents when every child is finished

Card: `f008c795-290f-4c6a-9865-863bcf130099` (subtask of story `13277ef5`
"Containers release their dependents", milestone `6aa7043a` "Single database and
cross-project blocking").

Parent design spec: `docs/superpowers/specs/2026-10-06-single-db-cross-project-blocking-design.md`,
committed in `98c42de` (not yet on this branch; read it with
`git show 98c42de:docs/superpowers/specs/2026-10-06-single-db-cross-project-blocking-design.md`).
Line numbers below refer to that file.

This spec narrows decision D1 to the current per-project schema. It makes no new
design decisions.

## Inherited constraints

| Constraint | Source |
|---|---|
| A container (card with children) releases its dependents when its stored status is releasing **or** every child resolves to a releasing status, recursively. | D1, line 31; §4 pseudocode, lines 161-166 |
| The container's own stored and displayed status does not change. | D1, line 31 |
| Childless cards behave as today. | D1, line 31 |
| `RELEASING` stays `{done, merged, canceled, archived}`. | §4, line 169 |
| Recursion keeps the existing `seen` guard. | §4, lines 169-170 |
| An issue blocker releases when its status is not `open`. | §4, line 164 |
| This phase changes `resolve_status` only and runs on the current schema. Single database, cross-project edges, not-found blockers and `blockers` output are later phases. | Implementation order, lines 273-284 (phase 1 is line 275) |
| Required tests: container releases when all children finish, including canceled/archived and nested containers; childless containers unchanged. | Testing, lines 262-264 |

## Terms

- **Stored status**: `cards.status`, one of `todo`, `in_progress`, `done`,
  `merged`, `canceled`, `archived` (`src/brd/db.py:58`).
- **Resolved status**: what `core.resolve_status(conn, card)` returns. It is the
  stored status, except that a stored `todo` becomes `blocked` when something
  holds the card.
- **Releasing statuses**: `_RELEASING_STATUSES` in `src/brd/core.py:21`, which is
  `{done, merged, canceled, archived}`.
- **Container**: a card with at least one child (`db.list_children` is not empty).
- **Released** (for a card used as a blocker): the card no longer holds back the
  cards blocked on it.

## Observable behavior

All behavior is visible through `core.resolve_status`. It flows unchanged to its
existing callers: `core.next_cards` (`src/brd/core.py:218,224`), tree nodes
(`src/brd/core.py:235`) and card detail (`src/brd/views.py:27`). Those callers
are not modified.

### B1. When a card blocker is released

A card `B` that appears in another card's `blocked_by` list is released when
**either** of these holds:

1. `resolve_status(B)` is a releasing status. This is today's rule.
2. `B` has at least one child, and every child is released by this same
   definition, applied recursively.

Otherwise `B` holds its dependent, and the dependent (stored `todo`) resolves to
`blocked`.

Consequences that the tests pin down:

- **B1a.** A story whose children are all in releasing statuses releases its
  dependents, whatever mix of `done`, `merged`, `canceled` and `archived` they have.
  The story's own stored status is `todo`.
- **B1b.** One child that resolves to `todo`, `in_progress` or `blocked` holds the
  container. One unfinished child is enough.
- **B1c.** Nested containers release only from the bottom up. A milestone whose
  children are stories releases only when every story is released. A story is
  released either through its stored status (rule 1) or through its own children
  (rule 2). One story with an unfinished subtask holds the milestone.
- **B1d.** A child that is a stored `todo` held by an open issue or an unreleased
  card resolves to `blocked`, so it holds its container.
- **B1e.** A container whose stored status is not releasing (`todo`, or
  `in_progress`, or `todo` but itself `blocked`) still releases once every child
  is released. D1's "or" means the container's own status and blockers do not
  matter once its children are all finished.
- **B1f.** A container whose stored status is releasing releases its dependents
  even if some of its children are unfinished (rule 1, unchanged).

### B2. The container's own status is unchanged

`resolve_status(container)` returns exactly what it returns today. A story with
stored `todo`, no blockers and all children `done` still resolves to `todo`.
Nothing is written to the database: `resolve_status` performs no writes. The
container's stored status stays as it was.

`core.next_cards` without `parent_id` still leaves out cards that have children
(`src/brd/core.py:222-226`). Container release changes which **dependents** show
up in `brd next`, not whether the container shows up.

### B3. Childless blockers and issue blockers are unchanged

- A childless card blocker is released only by rule 1. This is exactly today's
  behavior. Having no children never counts as "every child is released".
- Issue blockers keep today's handling (`src/brd/core.py:37-44`): an open issue
  blocks, a closed issue does not, and an id that is neither a card nor an issue
  is skipped. The not-found rule (D7) belongs to phase 3 and is out of scope.
- The parent-blocked rule (`src/brd/core.py:48-51`) is unchanged. A `todo` child
  of a parent that resolves to `blocked` is itself `blocked`.

### B4. Termination and the cycle guard

The `seen`-set guard stays: a card already on the current resolution path
resolves to `todo` rather than recursing. `resolve_status` must terminate on any
graph the database can hold, including graphs that loop through containment.
`would_create_block_cycle` (`src/brd/core.py:66-77`) walks only `blocked_by` edges
and not children, so such graphs can be persisted. Two examples:

- A child blocked by its own container (`C.parent = S`, `C blocked_by S`).
- A container's child blocked by the container's dependent (`A blocked_by S`,
  `C.parent = S`, `C blocked_by A`).

In both cases resolution terminates and fails closed: the dependent resolves to
`blocked`, and `C` resolves to `blocked`. This is a real deadlock. Reporting or
rejecting such edges is out of scope.

## Error paths

None are new. `resolve_status` raises nothing today and raises nothing after
this change. A child id that has disappeared cannot occur, because
`db.list_children` returns rows that exist. A container with zero children is a
childless card (B3).

## Files

- Modify: `src/brd/core.py`, only the card-blocker branch of `resolve_status`
  (line 45), plus at most one private helper next to it (for example
  `_is_released(conn, card, seen) -> bool`). The helper is mutually recursive
  with `resolve_status`, passes `seen` through, and reaches storage only through
  `brd.db` functions (`get_card`, `list_blockers_of`, `list_children`). Do not add
  SQL. Do not change the signatures of public functions.
- Modify: `tests/test_core.py`, adding tests only.

No other file changes. The card that owns this work is the only owner of
`resolve_status` (story `13277ef5`: "Owns: src/brd/core.py (resolve_status),
tests/test_core.py").

## Tests

All new tests live in `tests/test_core.py`. They use the existing `conn` fixture
(`tests/test_core.py:8-13`) and the `_card(id_, status, parent_id)` helper
(`tests/test_core.py:16-25`). They insert with `db.insert_card`, add edges with
`db.add_blocked_by_edge(conn, card_id, blocker_id)`, and re-read with
`db.get_card` before asserting `core.resolve_status(...)`. Issue blockers use
`issues.open_issue(conn, "q")` and `core.block_card`, as in
`tests/test_issues.py:66-79`. `tests/test_core.py` does not import `issues` today,
so add `issues` to its `from brd import ...` line. Names follow `test_resolve_status_<behavior>` and
`test_next_cards_<behavior>`.

**Tier for every test below: unit (core, real SQLite in `tmp_path`).** The change
is pure computation inside `resolve_status` over `db` reads. That is the existing
tier for every `resolve_status` and `next_cards` test, and it can build each
graph shape directly with exact stored statuses. The CLI layer only serializes
`resolve_status`'s return value and is not modified. A CLI test would add no
coverage of the changed code, so none is required.

| # | Test | Proves |
|---|---|---|
| T1 | `test_resolve_status_dependent_of_story_with_all_children_releasing_is_todo`: story `S` (stored `todo`) with four children in `done`, `merged`, `canceled` and `archived`; `D blocked_by S`. Assert `D` resolves to `todo`. | B1a, all four releasing statuses in one container |
| T2 | `test_resolve_status_dependent_of_story_with_one_todo_child_is_blocked`: same as T1 plus one `todo` child. Assert `D` is `blocked`. | B1b, todo child holds |
| T3 | `test_resolve_status_dependent_of_story_with_in_progress_child_is_blocked`: children `done` and `in_progress`. Assert `D` is `blocked`. | B1b, in_progress child holds |
| T4 | `test_resolve_status_dependent_of_story_with_blocked_child_is_blocked`: children `done`, plus a `todo` child blocked by an open issue. Assert `D` is `blocked`. Close the issue and set that child to `done`; assert `D` is `todo`. | B1d, blocked child holds; release follows once it finishes |
| T5 | `test_resolve_status_dependent_of_milestone_releases_only_when_every_story_does`: milestone `M` (`todo`) with stories `S1` and `S2` (both `todo`). `S1` has children all `done`. `S2` has one `done` child and one `todo` child. `D blocked_by M`. Assert `D` is `blocked`. Update `S2`'s `todo` child to `done` (`db.update_card_fields(conn, id, status="done")`). Assert `D` is `todo`. | B1c, nested release, bottom-up |
| T6 | `test_resolve_status_dependent_of_milestone_with_done_story_releases`: `M` with `S1` (stored `done`, one `todo` child) and `S2` (`todo`, children all `done`). Assert `D` blocked by `M` is `todo`. | B1c combined with B1f: a nested container released through rule 1 |
| T7 | `test_resolve_status_container_own_status_unchanged_when_children_done`: story `S` (`todo`, no blockers) with all children `done`. Assert `resolve_status(S) == "todo"` and `db.get_card(conn, S).status == "todo"`. | B2 |
| T8 | `test_resolve_status_childless_todo_blocker_still_blocks`: childless `B` (`todo`); `D blocked_by B`. Assert `D` is `blocked`. | B3, an empty child list does not release |
| T9 | `test_resolve_status_in_progress_container_with_all_children_done_releases`: `S` stored `in_progress`, children all `done`. Assert `D` is `todo`. | B1e |
| T10 | `test_resolve_status_blocked_container_with_all_children_done_releases`: `S` (`todo`) blocked by an unreleased card `X` (`todo`), children all `done`. Assert `D` is `todo`, and `S` itself still resolves to `blocked`. | B1e, B2 |
| T11 | `test_resolve_status_done_container_with_unfinished_child_releases`: `S` stored `done`, one `todo` child. Assert `D` is `todo`. | B1f, rule 1 unchanged |
| T12 | `test_resolve_status_child_blocked_by_own_container_terminates_blocked`: `S` (`todo`) with children `C1` (`done`) and `C2` (`todo`, `C2 blocked_by S`). Assert `resolve_status(C2) == "blocked"` and that the call returns. | B4, cycle through containment |
| T13 | `test_resolve_status_container_child_blocked_by_dependent_terminates_blocked`: `A blocked_by S`. `S` has child `C` (`todo`, `C blocked_by A`). Assert `A` is `blocked` and `C` is `blocked`. | B4, longer cycle through containment |
| T14 | `test_next_cards_includes_dependent_of_finished_container`: create story `S` with two children via `core.create_card`, and card `D` blocked by `S`. Set both children to `done`. Assert `D` is in `core.next_cards(conn)` and `S` is not. | B1a and B2 at the `next` boundary |

The existing tests in `tests/test_core.py:28-110` and `tests/test_issues.py:60-107`
must pass unchanged. They pin B3.

Verification: `uv run pytest` (`HACKING.md:3`). The project configures no lint or
typecheck.

## Review focus for the planner

The input classes most likely to bite a user, each of which has a test above:

1. A child resolving to `blocked` rather than stored `todo` must still hold the
   container (T4). An implementation that checks only stored child statuses
   would wrongly release.
2. A nested story child is stored `todo`, so it must be judged by the
   released rule recursively, not by `resolve_status` alone (T5, T6). Otherwise
   milestones never release.
3. An empty child list must not count as "all children released" (T8). A bare
   `all([])` is `True`.
4. Containment cycles must terminate and fail closed (T12, T13).
5. The container's own status must not flip to `todo`, `done` or anything else in
   tree, list or show output (T7, T10).

## Out of scope

- Deriving a displayed status for containers. This is the rejected option 2 named
  in the card. A container with all children finished still shows its stored
  status.
- Auto-closing containers, or writing any status.
- Rejecting or reporting edges that create cycles through containment. Only
  termination is required (B4).
- Not-found blockers (D7), cross-project edges and the `blockers` output field
  (§4, lines 173-187). These are phase 3.
- Single-database schema and scoping (D2-D5). These are phase 2 and the sibling
  stories under milestone `6aa7043a`.
- Export/import v2 (D9-D11). This is phase 4.
- Consumer-contract text in `brd --help` and `brd prompt` (§6, lines 239-251).
  This is phase 3.
- Changes to `next_cards`, `views.py`, the CLI, or `tests/test_issues.py`.

---

# Container Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A card blocker that has children releases its dependents once every child is released (recursively), without changing the container's own resolved or stored status.

**Architecture:** One private helper, `_is_released(conn, card, seen) -> bool`, is added to `src/brd/core.py` right after `resolve_status`. It is mutually recursive with `resolve_status`: a card is released if it resolves to a releasing status, or if it has at least one child and every child is released. The card-blocker branch of `resolve_status` calls it instead of comparing `resolve_status(...)` against `_RELEASING_STATUSES`. The `seen` set is passed through, and the helper fails closed (returns `False`) on a card already on the resolution path.

**Tech Stack:** Python 3, SQLite (`sqlite3`), pytest, run with `uv run pytest`.

**Spec:** `docs/superpowers/specs/1-1-a-container-f008c795.md` (reproduced in full above this plan).

## Global Constraints

- `_RELEASING_STATUSES` stays `frozenset({"done", "merged", "canceled", "archived"})` (`src/brd/core.py:21`). Do not edit it.
- Change only the card-blocker branch of `resolve_status` (`src/brd/core.py:45-46`) and add at most one private helper next to it.
- The helper reaches storage only through `brd.db` functions (`get_card`, `list_blockers_of`, `list_children`). Add no SQL.
- Do not change the signature of any public function. `resolve_status(conn, card, _seen=None) -> str` stays as is.
- `resolve_status` performs no writes and raises nothing.
- The container's own resolved and stored status does not change.
- Childless card blockers and issue blockers behave exactly as today.
- Only `src/brd/core.py` and `tests/test_core.py` change. `next_cards`, `views.py`, the CLI and `tests/test_issues.py` are not touched.
- New tests go in `tests/test_core.py` and are named `test_resolve_status_<behavior>` or `test_next_cards_<behavior>`.
- Verification command: `uv run pytest` (`HACKING.md:3`). There is no lint or typecheck step.

## Review Focus

1. A child that is stored `todo` but resolves to `blocked` (open issue, unreleased card) must hold its container. An implementation that reads stored child statuses would wrongly release. Pinned by `test_resolve_status_dependent_of_story_with_blocked_child_is_blocked` (T4).
2. A nested story is stored `todo`, so a milestone must judge it by the released rule recursively, not by `resolve_status` alone, or milestones never release. Pinned by T5 and T6.
3. A childless card must not count as "every child released"; a bare `all([])` is `True`. Pinned by `test_resolve_status_childless_todo_blocker_still_blocks` (T8) and the existing `test_resolve_status_todo_with_unresolved_blocker_is_blocked`.
4. Graphs that loop through containment must terminate and fail closed. This includes a persisted `parent_id` cycle, which `db.update_card_fields` can write even though `core.update_card` rejects it: without the helper's own `seen` check the child walk recurses forever. Pinned by T12, T13 and the extra test `test_resolve_status_terminates_on_persisted_parent_cycle` (T15) in this task.
5. The container's own status must not flip in tree, list or show output. Pinned by T7 and T10.

---

### Task 1: Containers release their dependents when every child is released

**Files:**
- Modify: `src/brd/core.py:45-46` (card-blocker branch of `resolve_status`)
- Modify: `src/brd/core.py` (insert `_is_released` between the end of `resolve_status`, currently line 53, and `def would_create_parent_cycle`, currently line 56)
- Test: `tests/test_core.py` (change the import on line 3; append tests at the end of the file)

**Interfaces:**
- Consumes (all existing):
  - `core.resolve_status(conn: sqlite3.Connection, card: Card, _seen: set[str] | None = None) -> str`
  - `core._RELEASING_STATUSES: frozenset[str]`
  - `db.list_children(conn, parent_id: str) -> list[Card]`
  - `db.get_card(conn, card_id: str) -> Card | None`
  - `db.insert_card(conn, card: Card) -> None`
  - `db.add_blocked_by_edge(conn, card_id: str, blocks_on_id: str) -> None`
  - `db.update_card_fields(conn, card_id: str, **fields) -> None`
  - `core.create_card(conn, title, description=None, parent_id=None, blocked_by=None) -> Card`
  - `core.update_card(conn, card_id, title=None, description=None, status=None, parent_id=None) -> Card`
  - `core.block_card(conn, card_id: str, blocker_id: str) -> None`
  - `core.next_cards(conn, limit=None, parent_id=None) -> list[Card]`
  - `issues.open_issue(conn, title, body=None, ref_ids=None, blocks=None) -> Issue` (has `.id`)
  - `issues.close(conn, issue_id: str, reason: str = "resolved") -> Issue`
  - Test helpers already in `tests/test_core.py`: fixture `conn` (lines 8-13) and `_card(id_, status="todo", parent_id=None) -> Card` (lines 16-25).
- Produces:
  - `core._is_released(conn: sqlite3.Connection, card: Card, seen: set[str]) -> bool` (private).
  - Test helpers in `tests/test_core.py`: `_story_with_children(conn, story_id, child_statuses, story_status="todo") -> None`, which inserts `story_id` and one child per status with ids `f"{story_id}-c{index}"`; and `_blocked_on(conn, card_id, blocker_id) -> Card`, which inserts a `todo` card blocked on `blocker_id` and returns it re-read.

Background for the engineer: `resolve_status` returns a card's stored status, except that a stored `todo` becomes `blocked` when an open issue, an unreleased card blocker, or a `blocked` parent holds it. A "container" is any card with at least one child. Today a container blocker releases only through its own status. After this task it also releases when all of its children are released. `_card` gives every card the same `created_at`; that is fine here.

- [ ] **Step 1: Import `issues` in the test module**

In `tests/test_core.py`, change line 3 from:

```python
from brd import core, db
```

to:

```python
from brd import core, db, issues
```

- [ ] **Step 2: Append the failing tests and their helpers**

Append exactly this to the end of `tests/test_core.py`:

```python


def _story_with_children(conn, story_id, child_statuses, story_status="todo"):
    db.insert_card(conn, _card(story_id, status=story_status))
    for index, status in enumerate(child_statuses):
        db.insert_card(conn, _card(f"{story_id}-c{index}", status=status, parent_id=story_id))


def _blocked_on(conn, card_id, blocker_id):
    db.insert_card(conn, _card(card_id))
    db.add_blocked_by_edge(conn, card_id, blocker_id)
    return db.get_card(conn, card_id)


def test_resolve_status_dependent_of_story_with_all_children_releasing_is_todo(conn):
    _story_with_children(conn, "s", ["done", "merged", "canceled", "archived"])
    dependent = _blocked_on(conn, "d", "s")

    assert core.resolve_status(conn, dependent) == "todo"


def test_resolve_status_dependent_of_story_with_one_todo_child_is_blocked(conn):
    _story_with_children(conn, "s", ["done", "merged", "canceled", "archived", "todo"])
    dependent = _blocked_on(conn, "d", "s")

    assert core.resolve_status(conn, dependent) == "blocked"


def test_resolve_status_dependent_of_story_with_in_progress_child_is_blocked(conn):
    _story_with_children(conn, "s", ["done", "in_progress"])
    dependent = _blocked_on(conn, "d", "s")

    assert core.resolve_status(conn, dependent) == "blocked"


def test_resolve_status_dependent_of_story_with_blocked_child_is_blocked(conn):
    _story_with_children(conn, "s", ["done", "todo"])
    issue = issues.open_issue(conn, "q")
    core.block_card(conn, "s-c1", issue.id)
    dependent = _blocked_on(conn, "d", "s")
    assert core.resolve_status(conn, db.get_card(conn, "s-c1")) == "blocked"

    assert core.resolve_status(conn, dependent) == "blocked"

    issues.close(conn, issue.id)
    db.update_card_fields(conn, "s-c1", status="done")
    assert core.resolve_status(conn, db.get_card(conn, "d")) == "todo"


def test_resolve_status_dependent_of_milestone_releases_only_when_every_story_does(conn):
    db.insert_card(conn, _card("m"))
    db.insert_card(conn, _card("s1", parent_id="m"))
    db.insert_card(conn, _card("s1-c0", status="done", parent_id="s1"))
    db.insert_card(conn, _card("s1-c1", status="done", parent_id="s1"))
    db.insert_card(conn, _card("s2", parent_id="m"))
    db.insert_card(conn, _card("s2-c0", status="done", parent_id="s2"))
    db.insert_card(conn, _card("s2-c1", status="todo", parent_id="s2"))
    dependent = _blocked_on(conn, "d", "m")

    assert core.resolve_status(conn, dependent) == "blocked"

    db.update_card_fields(conn, "s2-c1", status="done")
    assert core.resolve_status(conn, db.get_card(conn, "d")) == "todo"


def test_resolve_status_dependent_of_milestone_with_done_story_releases(conn):
    db.insert_card(conn, _card("m"))
    db.insert_card(conn, _card("s1", status="done", parent_id="m"))
    db.insert_card(conn, _card("s1-c0", status="todo", parent_id="s1"))
    db.insert_card(conn, _card("s2", parent_id="m"))
    db.insert_card(conn, _card("s2-c0", status="done", parent_id="s2"))
    db.insert_card(conn, _card("s2-c1", status="done", parent_id="s2"))
    dependent = _blocked_on(conn, "d", "m")

    assert core.resolve_status(conn, dependent) == "todo"


def test_resolve_status_container_own_status_unchanged_when_children_done(conn):
    _story_with_children(conn, "s", ["done", "done"])

    assert core.resolve_status(conn, db.get_card(conn, "s")) == "todo"
    assert db.get_card(conn, "s").status == "todo"


def test_resolve_status_childless_todo_blocker_still_blocks(conn):
    db.insert_card(conn, _card("b"))
    dependent = _blocked_on(conn, "d", "b")

    assert core.resolve_status(conn, dependent) == "blocked"


def test_resolve_status_in_progress_container_with_all_children_done_releases(conn):
    _story_with_children(conn, "s", ["done", "done"], story_status="in_progress")
    dependent = _blocked_on(conn, "d", "s")

    assert core.resolve_status(conn, dependent) == "todo"


def test_resolve_status_blocked_container_with_all_children_done_releases(conn):
    db.insert_card(conn, _card("x"))
    _story_with_children(conn, "s", ["done", "done"])
    db.add_blocked_by_edge(conn, "s", "x")
    dependent = _blocked_on(conn, "d", "s")

    assert core.resolve_status(conn, dependent) == "todo"
    assert core.resolve_status(conn, db.get_card(conn, "s")) == "blocked"


def test_resolve_status_done_container_with_unfinished_child_releases(conn):
    _story_with_children(conn, "s", ["todo"], story_status="done")
    dependent = _blocked_on(conn, "d", "s")

    assert core.resolve_status(conn, dependent) == "todo"


def test_resolve_status_child_blocked_by_own_container_terminates_blocked(conn):
    _story_with_children(conn, "s", ["done", "todo"])
    db.add_blocked_by_edge(conn, "s-c1", "s")

    assert core.resolve_status(conn, db.get_card(conn, "s-c1")) == "blocked"


def test_resolve_status_container_child_blocked_by_dependent_terminates_blocked(conn):
    _story_with_children(conn, "s", ["todo"])
    db.insert_card(conn, _card("a"))
    db.add_blocked_by_edge(conn, "a", "s")
    db.add_blocked_by_edge(conn, "s-c0", "a")

    assert core.resolve_status(conn, db.get_card(conn, "a")) == "blocked"
    assert core.resolve_status(conn, db.get_card(conn, "s-c0")) == "blocked"


def test_next_cards_includes_dependent_of_finished_container(conn):
    story = core.create_card(conn, title="story")
    first = core.create_card(conn, title="first", parent_id=story.id)
    second = core.create_card(conn, title="second", parent_id=story.id)
    dependent = core.create_card(conn, title="dependent", blocked_by=[story.id])
    core.update_card(conn, first.id, status="done")
    core.update_card(conn, second.id, status="done")

    ready_ids = [card.id for card in core.next_cards(conn)]

    assert dependent.id in ready_ids
    assert story.id not in ready_ids


def test_resolve_status_terminates_on_persisted_parent_cycle(conn):
    db.insert_card(conn, _card("p"))
    db.insert_card(conn, _card("q", parent_id="p"))
    db.update_card_fields(conn, "p", parent_id="q")
    dependent = _blocked_on(conn, "d", "p")

    assert core.resolve_status(conn, dependent) == "blocked"
```

Mapping to the spec's table: T1 `..._all_children_releasing_is_todo`, T2 `..._one_todo_child_is_blocked`, T3 `..._in_progress_child_is_blocked`, T4 `..._blocked_child_is_blocked`, T5 `..._releases_only_when_every_story_does`, T6 `..._with_done_story_releases`, T7 `..._own_status_unchanged_when_children_done`, T8 `..._childless_todo_blocker_still_blocks`, T9 `..._in_progress_container_...`, T10 `..._blocked_container_...`, T11 `..._done_container_with_unfinished_child_releases`, T12 `..._child_blocked_by_own_container_...`, T13 `..._container_child_blocked_by_dependent_...`, T14 `test_next_cards_includes_dependent_of_finished_container`, T15 (Review Focus 4) `..._terminates_on_persisted_parent_cycle`.

- [ ] **Step 3: Run the new tests to verify the right ones fail**

Run: `uv run pytest tests/test_core.py -q`

Expected: `7 failed, 79 passed`. Exactly these fail, each on an assertion that expected `"todo"` and got `"blocked"` (or, for the `next_cards` test, on `dependent.id in ready_ids`):

```
FAILED tests/test_core.py::test_resolve_status_dependent_of_story_with_all_children_releasing_is_todo
FAILED tests/test_core.py::test_resolve_status_dependent_of_story_with_blocked_child_is_blocked
FAILED tests/test_core.py::test_resolve_status_dependent_of_milestone_releases_only_when_every_story_does
FAILED tests/test_core.py::test_resolve_status_dependent_of_milestone_with_done_story_releases
FAILED tests/test_core.py::test_resolve_status_in_progress_container_with_all_children_done_releases
FAILED tests/test_core.py::test_resolve_status_blocked_container_with_all_children_done_releases
FAILED tests/test_core.py::test_next_cards_includes_dependent_of_finished_container
```

The other eight new tests already pass. They pin behavior that must not regress (holding containers, childless blockers, rule 1, the container's own status, termination). If any test fails with an error other than an assertion (for example `NameError` or `ImportError`), fix the test code before going on.

- [ ] **Step 4: Route the card-blocker branch through the new helper**

In `src/brd/core.py`, inside `resolve_status`, replace:

```python
        if resolve_status(conn, blocker, seen) not in _RELEASING_STATUSES:
            return "blocked"
```

with:

```python
        if not _is_released(conn, blocker, seen):
            return "blocked"
```

Leave the issue branch above it and the parent-blocked check below it as they are.

- [ ] **Step 5: Add the `_is_released` helper**

In `src/brd/core.py`, insert this function between the end of `resolve_status` (its final `return "todo"`) and `def would_create_parent_cycle`, keeping two blank lines on each side:

```python
def _is_released(conn: sqlite3.Connection, card: Card, seen: set[str]) -> bool:
    # A card stops holding its dependents once it resolves to a releasing
    # status, or once it has children and every one of them is released.
    # Its own status is left alone either way.
    if resolve_status(conn, card, seen) in _RELEASING_STATUSES:
        return True
    if card.id in seen:
        # Already on this resolution path (a loop through blocked_by or
        # containment): fail closed rather than recurse forever.
        return False
    children = db.list_children(conn, card.id)
    seen = seen | {card.id}
    return bool(children) and all(_is_released(conn, child, seen) for child in children)
```

Why each line matters:
- Rule 1 comes first, so a container stored `done`/`merged`/`canceled`/`archived` releases whatever its children are (T6, T11).
- `card.id in seen` returns `False`, not `True`: a card already on the path has not been shown released, so the dependent stays `blocked` (fail closed). Without this check a persisted `parent_id` cycle recurses until `RecursionError` (T15).
- `seen | {card.id}` builds a new set, as `resolve_status` does, so sibling branches do not see each other's paths.
- `bool(children) and ...` stops an empty child list counting as released (T8).
- Each child is judged with `_is_released`, not `resolve_status`, so a nested story stored `todo` with all children finished counts as released (T5), and a child that resolves to `blocked` holds the container (T4).

- [ ] **Step 6: Run the core tests to verify they pass**

Run: `uv run pytest tests/test_core.py -q`

Expected: `86 passed`.

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -q`

Expected: `412 passed` (397 existing plus the 15 new tests), with no failures. In particular `tests/test_core.py:28-110` and `tests/test_issues.py:60-107` pass unchanged.

- [ ] **Step 8: Check the diff touches only the two allowed files**

Run: `git status --short`

Expected: only ` M src/brd/core.py` and ` M tests/test_core.py` (plus any untracked `docs/superpowers/...` files that were already there). Run `git diff src/brd/core.py` and confirm it contains only the two-line change in `resolve_status` and the new `_is_released` function, with no SQL and no change to `_RELEASING_STATUSES`.

- [ ] **Step 9: Commit**

```bash
git add src/brd/core.py tests/test_core.py
git commit -m "Release a container's dependents once every child is released"
```

---

## Self-Review

1. **Spec coverage.** B1a: T1. B1b: T2, T3. B1c: T5, T6. B1d: T4. B1e: T9, T10. B1f: T11, T6. B2: T7, T10, T14. B3: T8, plus the existing tests in `tests/test_core.py:28-110` and `tests/test_issues.py:60-107` (Step 7). B4: T12, T13, T15. Error paths: no new raises; the helper adds none. Files: only `src/brd/core.py` and `tests/test_core.py` (Step 8). All 14 spec tests T1-T14 are in Step 2 with the spec's names.
2. **Placeholder scan.** Every code step shows the full code; no TBD/TODO or "similar to" references.
3. **Type consistency.** `_is_released(conn, card, seen)` takes a `Card` and a `set[str]` in both its definition (Step 5) and its call site (Step 4, where `blocker` is a `Card` and `seen` is the `set[str]` built by `resolve_status`). Test helper names `_story_with_children` and `_blocked_on` match between definition and use; child ids follow `f"{story_id}-c{index}"`, so `"s-c1"` and `"s-c0"` refer to the second and first child.
4. **Review Focus.** All five lines name a test in this task. Line 4 needed one test the spec did not list (T15, persisted parent cycle). It was added to Step 2, and the expected counts in Steps 3, 6 and 7 include it.
5. **Pre-verification.** The test code and implementation in this plan were run against the current tree while the plan was written. Before the change: 7 failed and 79 passed in `tests/test_core.py`, as listed in Step 3. After the change: 412 passed in the full suite. With the `card.id in seen` check removed, only T15 fails, which confirms that T15 pins the check.
<!-- task-pipeline: validated -->
