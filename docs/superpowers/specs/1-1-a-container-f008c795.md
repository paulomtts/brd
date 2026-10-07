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
