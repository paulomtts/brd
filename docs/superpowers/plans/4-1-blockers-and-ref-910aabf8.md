# 4.1 Blockers and ref targets may live in another project

Card: `910aabf8-9d6e-472d-b34c-80674c81e403`. It is the first subtask of story `43766a3a`
"Cross-project edges" (spec section 4 and D6-D8). The milestone is `6aa7043a` "Single
database and cross-project blocking". Story S3 "One database" (`4939dac5`, cards 3.1-3.4)
is merged into this branch: every project lives in one `brd.db`, and code still refuses
edge targets owned by another project.

Parent design spec: `docs/superpowers/specs/2026-10-06-single-db-cross-project-blocking-design.md`.
It is in the main checkout (`/home/mtts/Code/brd/docs/...`), not in this branch's history.
Citations look like **[P §n Lx]**.

## Goal

An edge's **source** must still belong to the current project. Its **target** may now
belong to any project. This card lifts the same-project check on the targets of four
commands:

- `brd block <card> --by <target>`
- `brd add --blocked-by <target>`
- `brd issue open --blocks <card>` (the blocked card is the target; the new issue, always
  in the current project, is the source)
- `brd ref add <src> <dst>`, and its twin `brd issue open --ref <dst>`

Status resolution, container release and the cycle check already follow `blocked_by`
edges through unscoped lookups (`core.py:24-92`). So the production change is mostly
deleting checks. Most of the work is tests that prove resolution and the cycle check work
across projects.

## Inherited constraints

| Constraint | Source |
|---|---|
| Edge targets (`blocked_by.blocks_on_id`, `refs.dst_id`) carry no foreign key. | [P D6 L36], [P §1 L68-80] |
| Commands are scoped to the current project. Only edges, `show`, edge targets and `[[uuid]]` links cross projects. | [P D3 L33] |
| Mutating commands require the entity to belong to the current project. That includes the `block`/`unblock` source and the `ref` source. Otherwise the error names the owning project. | [P §2 L112-115] |
| Global: blocker targets of `brd block --by`, `add --blocked-by`, `issue open --blocks`; `brd ref add` targets; status resolution and the cycle check, which follow edges across projects. | [P §2 L117-120] |
| A container releases its dependents when its stored status is releasing, or when every child resolves to a releasing status (recursive). Its own status is unchanged. | [P D1 L31], [P §4 L161-167] |
| `RELEASING` stays `{done, merged, canceled, archived}`. Recursion keeps the `seen` guard. The cycle check walks `blocked_by` across projects. | [P §4 L169-171] |
| An issue releases its dependents once it is not open, whatever the close reason. | [P §4 L164] |
| Phase 3 lifts the same-project check on edge targets. | [P Implementation order L281-283] |
| Testing: cross-project card and issue blockers; cycle across projects rejected. | [P Testing L262-264] |
| `brd delete` still removes edges that point at the deleted entity. | [P D8 L38] |

## Behaviour

`P` is the current project. `Q` is another project registered in the same `brd.db`. "A
foreign X" means an X that `Q` owns. "Missing" means the id is in no project.

### B1. `brd block <card> --by <target>` / `core.block_card`

| Source (`<card>`) | Target | Result |
|---|---|---|
| card of P | card of P or Q | Edge added. Exit 0. Output is the source card's detail, with the target in `blocked_by`. |
| card of P | open issue of P or Q | Same as above. |
| card of P | document of P or Q | `InvalidBlockerError`: `a document can't block a card; only cards and issues can`. No edge. |
| card of P | missing id | `CardNotFoundError`: `no card or issue with id <id>`. No edge. (Unchanged. Card 4.2 decides how a stored not-found edge *resolves*, not whether one can be added.) |
| card of P | an id that would close a cycle, through any projects | `CycleError`: `blocking <card> on <target> would create a cycle`. No edge. |
| card of Q | anything | `CardNotFoundError` naming Q as the owner (unchanged). The source is checked **before** the target, so a foreign source with a foreign target reports the source. |
| missing / not a card | anything | `CardNotFoundError: no card with id <id>` (unchanged). |

A foreign document target used to be refused as foreign (`core.py:124`, "ownership before
kind"). Now it is refused for its kind, like a local document.

### B2. `brd add --blocked-by <target>` / `core.create_card(blocked_by=[...])`

Each target follows the target rules of B1: a card or issue of any project is accepted, a
document is refused with `InvalidBlockerError`, and a missing id is refused with
`CardNotFoundError`. Every target is checked before the card is inserted, so a refusal
writes nothing (unchanged ordering, `core.py:152-165`). A new card cannot close a cycle.

### B3. `brd issue open --blocks <card>` / `issues.open_issue(blocks=[...])`

- `<card>` may be a card of P or of Q. The new issue (in P) is added to that card's
  `blocked_by`. The issue's `blocks` lists the card. While the issue is open, the card
  resolves to `blocked` in its own project's `list`, `next`, `tree` and `show`.
- `<card>` that is missing, or is an issue or document of any project, is refused with
  `CardNotFoundError: no card with id <id>` (unchanged wording).
- All `--blocks` and `--ref` ids are validated **before** the issue row is written. One bad
  id among several good ones means no issue, no edges and no refs are written (unchanged
  guarantee, `issues.py:85-92`).
- A new issue has no blockers, so it cannot close a cycle.

### B4. `brd ref add <src> <dst>` / `refs.add_explicit`, and `brd issue open --ref <dst>`

- `<src>` must belong to P. A foreign source is refused with the kind-specific not-found
  error naming Q (unchanged).
- `<dst>` may be a card, issue or document of P or Q. The explicit ref is stored. The
  `ref add` output (`{"id": src, "refs": [...]}`) lists the foreign target with its kind
  and title. `brd show <src>` lists it under `refs`. `brd show <dst>`, run from either
  project, lists `<src>` under `referenced_by`.
- A missing `<dst>` is refused with `EntityNotFoundError: no entity with id <id>`
  (unchanged). `<src> == <dst>` is refused with `SelfReferenceError` (unchanged).
- `issue open --ref <dst>` follows the same target rule. A missing id writes nothing.
- `ref remove` is unchanged: it already checks only the source (`refs.py:120-128`).

### B5. Status resolution across projects

These already hold in the code. This card pins them with tests.

- A todo card of P blocked by a card of Q resolves to `blocked` until that card resolves
  to a releasing status (`done`, `merged`, `canceled`, `archived`). Then it resolves to
  `todo` and appears in P's `brd next`.
- A card of P blocked by a foreign card that is itself `blocked` (its own blocker is open)
  stays `blocked` until the foreign chain releases.
- A todo card of P blocked by an issue of Q resolves to `blocked` while that issue is open.
  It resolves to `todo` once the issue is closed, with any reason. It goes back to
  `blocked` if the issue is reopened.
- Container release (D1) across projects: a card of P blocked by a container of Q (a card
  with children in Q) is released when every child of the container resolves to a
  releasing status, even though the container's own stored status is still `todo`. The
  container's displayed status does not change.
- A card of Q blocked by an open issue of P (B3) resolves to `blocked` in Q's `next` and
  `list`. It is released when the issue is closed from P.

### B6. Cycle check across projects

`would_create_block_cycle` follows edges whatever project owns each node:

- Direct: P's card `a` is blocked by Q's card `b`. Then, from Q, `brd block b --by a` is
  refused with `CycleError`.
- Indirect: `a`(P) by `b`(Q), `b`(Q) by `c`(P). Then `brd block c --by a` from P is
  refused with `CycleError`. The path goes through Q.
- A refused block writes no edge.

### B7. `unblock` of a cross-project edge

`brd unblock <card of P> --by <foreign target>` removes the edge (it already checks only the
source, `core.py:233-237`). The card resolves to `todo` again if nothing else blocks it.

## Changes in production code

These lines are named only so the planner has the full set. How to restructure them is the
plan's call.

- `src/brd/core.py:120-127` `_require_blocker`: drop the ownership check (line 125). Keep
  the missing-id check, then the kind check. Remove the "Ownership before kind" comment.
- `src/brd/core.py:221-228` `block_card`: still requires the source card in P. But
  `issue open --blocks` must add an edge whose `card_id` is a foreign card (B3). So
  `open_issue` cannot reach `block_card`'s source check with a foreign card. It needs an
  existence-and-kind check that is not tied to a project, and a way to add the edge without
  the source-in-P check. `brd block` must keep refusing a foreign source.
- `src/brd/issues.py:85-89`: replace `require_in_project` on ref targets with an
  existence-only check (`entities.require`). Replace `core.require_card(project_id, …)` on
  `--blocks` with a check that the id is a card in any project. Delete the "until S4"
  comment.
- `src/brd/refs.py:109-110`: the target check becomes `entities.require(conn, dst_id)`.
  Delete the "until S4" comment.

## Tests

Tiers used in this repo:

- **unit**: calls `core` / `issues` / `refs` directly against a temporary database. Use it
  for rules, error wording and "writes nothing". Fast and precise.
- **CLI**: runs `brd` through Typer's `CliRunner` against a real `brd.db` (`tests/test_cli.py`
  helpers `ok`, `err`, `_refused`, fixtures `foreign` and `foreign_entities`). Use it for
  the user-visible contract: the right command reaches the right rule, and the JSON shape is
  right.

### Existing tests to invert or rewrite

| Test | Now asserts | Becomes |
|---|---|---|
| `tests/test_project_scope.py` REFUSED `block_card_foreign_card_target`, `block_card_foreign_issue_target`, `create_card_foreign_blocker`, `open_issue_foreign_blocks` | foreign target refused | Remove from REFUSED. Covered by T1-T3 (accepted). |
| `tests/test_project_scope.py` REFUSED `block_card_foreign_document_target` | refused as foreign | Remove from REFUSED. T4 asserts `InvalidBlockerError`. |
| `tests/test_project_scope.py` SCOPED_REFUSED `open_issue_foreign_ref`, `open_issue_mixed_refs`, `ref_add_foreign_target` | foreign ref target refused | Remove. Covered by T5-T6. |
| `tests/test_cli.py:954` `test_blocker_targets_must_be_in_this_project` | refused | Rewrite as T12. |
| `tests/test_cli.py:961` `test_issue_open_refuses_a_foreign_blocks_card` | refused | Rewrite as T13. |
| `tests/test_cli.py:1007` (`issue open --ref` foreign card refused) | refused | Drop that line. T14 covers acceptance. |
| `tests/test_cli.py:1030` (`ref add mine <foreign issue>` refused) | refused | Drop that line. T14 covers acceptance. Keep line 1029 (foreign source) and 1031 (`ref remove` foreign source). |

These stay valid unchanged: `test_block_and_unblock_refuse_a_foreign_card`
(`tests/test_cli.py:947`), and REFUSED `block_card_foreign_source` and
`unblock_card_foreign_source`.

### New tests

Unit tests go in `tests/test_project_scope.py`, using its `two` fixture (P owns `p1`, `p2`;
Q owns `q1` with child `q-child`, issue `qi` and document `qd`; `q1` is already blocked by
`p2`). CLI tests go in `tests/test_cli.py`, next to the scope tests.

| # | Test | Tier | Why this tier | Covers |
|---|---|---|---|---|
| T1 | `block_card(P, "p1", "q1")` and `block_card(P, "p1", "qi")` add both edges. `db.list_blockers_of(p1)` holds both. | unit | The core rule, with no CLI noise. | B1 |
| T2 | `create_card(P, "new", blocked_by=["p2", "qi"])` returns a card whose blockers are both ids. | unit | `create_card` has its own validation loop. | B2 |
| T3 | First mark `p2` done: the fixture has `q1` (the parent of `q-child`) blocked by `p2`, and a child inherits a blocked parent, so without this `q-child` could never resolve to `todo`. Then `open_issue(P, "t", blocks=["p1", "q-child"])`: the issue is owned by P; `blocks_of(issue)` is `["p1", "q-child"]` (sorted); `resolve_status(q-child)` is `blocked`; `core.next_cards(Q)` excludes `q-child`. After `issues.close(P, issue)`, `q-child` resolves to `todo` and is in `core.next_cards(Q)`. | unit | Shows that the target side of `--blocks` is a foreign card, and that resolution follows the edge into Q. | B3, B5 |
| T4 | `block_card(P, "p1", "qd")` raises `InvalidBlockerError` (not the foreign message). `create_card(P, "n", blocked_by=["qd"])` raises the same. Database state is unchanged (`_state`). | unit | The changed error precedence for a foreign document. | B1, B2 |
| T5 | `refs.add_explicit(P, "p1", "qi")` and `(P, "p1", "qd")` store explicit refs. `refs.outgoing(p1)` lists both with kind and title. `refs.incoming(qi)` lists `p1`. | unit | The ref target rule. | B4 |
| T6 | `open_issue(P, "t", ref_ids=["p1", "qd"])` stores refs to both. `open_issue(P, "t", ref_ids=["q1", "nope"])` raises `EntityNotFoundError` and writes nothing (`_state` unchanged). | unit | The twin path, and the all-or-nothing guarantee. | B4, B3 |
| T7 | `open_issue(P, "t", blocks=["q1", "qi"])` raises `CardNotFoundError: no card with id qi` and writes nothing. Same for `blocks=["p1", "nope"]`. | unit | A foreign non-card or missing id is still refused before the write. | B3 |
| T8 | Cross-project release by a card: `block_card(P, "p1", "q1")` makes `p1` `blocked` (q1 is todo and itself blocked by `p2`). Set `p2` done: `q1` resolves `todo`, `p1` still `blocked`. Set `q1` done: `p1` resolves `todo` and is in `next_cards(P)`. | unit | The transitive chain P→Q→P exercises the unscoped lookups. | B5 |
| T9 | Cross-project release by an issue: `block_card(P, "p1", "qi")`; `p1` is `blocked`. `issues.close(Q, "qi", reason=...)` releases it. `issues.reopen(Q, "qi")` blocks it again. | unit | Issue status read across projects. | B5 |
| T10 | Container release across projects: Q gets container `qs` with children `qs1`, `qs2`. `block_card(P, "p1", "qs")`. `p1` is `blocked`. With `qs1` done and `qs2` todo it is still `blocked`. With `qs2` canceled, `p1` resolves `todo`, while `qs`'s own `resolve_status` is still `todo`. | unit | D1 applied to a foreign container. | B5 |
| T11 | Cycle across projects. Direct: after `block_card(P, "p1", "q1")`, `block_card(Q, "q1", "p1")` raises `CycleError`. Indirect: `q1` is already blocked by `p2`; `block_card(P, "p2", "p1")` after `p1`-by-`q1` raises `CycleError`. `_state` is unchanged by each refused call. | unit | The cycle walk crosses project boundaries both ways. | B6 |
| T12 | CLI: `brd block mine --by FOREIGN` and `brd block mine --by FOREIGN_ISSUE` exit 0, and the output's `blocked_by` holds both ids with `status == "blocked"`. `brd add --title t --blocked-by FOREIGN` exits 0 with `blocked_by == [FOREIGN]`. `brd block mine --by FOREIGN_DOC` returns `InvalidBlockerError`. `brd next` excludes both blocked cards. `brd unblock mine --by FOREIGN` and `--by FOREIGN_ISSUE` exit 0, and `mine` is back in `brd next`. | CLI | The user-visible contract of `block`, `add --blocked-by` and `unblock`. | B1, B2, B7 |
| T13 | CLI: `brd issue open --title q --blocks FOREIGN` exits 0. Its `blocks` is `[FOREIGN]`. `brd show FOREIGN` has the issue id in `blocked_by` and `status == "blocked"`. After `brd issue close <issue>`, `brd show FOREIGN` has `status == "todo"`. | CLI | The `--blocks` path end to end, viewed through `show` (global). | B3, B5 |
| T14 | CLI: `brd ref add mine FOREIGN_ISSUE` exits 0 and its `refs` lists `{"id": FOREIGN_ISSUE, "kind": "issue", "title": "Foreign issue", ...}`. `brd issue open --title q --ref FOREIGN` exits 0 and `show` of that issue lists FOREIGN under `refs`. `brd ref add FOREIGN mine` is still refused (`_refused`). | CLI | The `ref add` and `--ref` outputs with a foreign target, and the source check that stays. | B4 |
| T15 | CLI: `brd show mine --pretty`, where `mine` is blocked by FOREIGN, exits 0 and prints the foreign title. | CLI | Pretty rendering must not break on a foreign blocker before 4.3 reshapes it. | Review focus |

## Review focus (inputs no test above names directly)

- A foreign **source** with a foreign target (`brd block FOREIGN --by FOREIGN_ISSUE`) must
  report the source as foreign, not accept it. It is covered by the precedence rule in B1.
  The plan should add a REFUSED case for it.
- `issue open` with one bad `--blocks` id after several good ones writes no issue row
  (T7). The plan's restructure of `open_issue` must keep validating before the insert.
- Running `brd block` twice with the same foreign target behaves exactly as it does for a
  local target. `db.add_blocked_by_edge` (`db.py:655-661`) is a plain `INSERT`. This card
  does not change duplicate handling either way.
- A self-block (`brd block a --by a`) is still a `CycleError`.

## Out of scope

- **Card 4.2**: a not-found blocker resolves to `blocked` (D7); `forget` keeping incoming
  edges (D8, `db.py:556-557`, `db.delete_incoming_edges`); the cycle check treating a
  not-found id as a dead end; `unblock` of a not-found edge. `resolve_status`'s `continue`
  for a missing blocker (`core.py:37-44`) stays as it is here.
- **Card 4.3**: the `blockers` detail array in card detail, list and tree output, and
  `--pretty` rendering a foreign blocker as `<project>: <title>`. `blocked_by` stays a
  plain id list (`views.py:31`, `core.py:286`), and `pretty._blocker` is unchanged.
- **Story S6**: the consumer-contract text in `brd --help` and `brd prompt` [P §6
  L239-251].
- Adding a not-found target through any command. It stays refused here.
- Parent links across projects. They stay refused (trigger `db.py:246-253`, [P §1 L61-62]).
- Export/import of cross-project edges (phase 4).

---

# 4.1 Blockers and Ref Targets May Live in Another Project Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the target of `brd block --by`, `brd add --blocked-by`, `brd issue open --blocks`, `brd ref add` and `brd issue open --ref` belong to any project in `brd.db`, while every edge's source stays scoped to the current project.

**Architecture:** Three deletions of same-project checks, one per path. `core._require_blocker` loses its ownership check (and its `project_id` parameter). `core` gains `require_any_card` (existence and kind, no project) and `add_block_edge` (blocker check, cycle check, insert — no source ownership check); `block_card` becomes `require_card` + `add_block_edge`, and `issues.open_issue` validates `--blocks` with `require_any_card` and writes with `add_block_edge`. `refs.add_explicit` and `issues.open_issue` check ref targets with `entities.require` (existence only). Status resolution and the cycle check already use unscoped lookups, so most of the work is tests that pin cross-project behaviour.

**Tech Stack:** Python 3, SQLite (`sqlite3`), Typer CLI, pytest, run through `uv`.

**Spec:** `docs/superpowers/specs/4-1-blockers-and-ref-910aabf8.md` (prepended above).

## Global Constraints

- An edge's **source** must belong to the current project; its **target** may belong to any project. [P D3 L33], [P §2 L112-120]
- `brd block` / `brd unblock` keep refusing a foreign source with `CardNotFoundError` naming the owner; the source is checked **before** the target.
- A missing blocker target stays `CardNotFoundError: no card or issue with id <id>`; a document target stays `InvalidBlockerError: a document can't block a card; only cards and issues can` — now also for a foreign document.
- A `--blocks` id that is missing, an issue, or a document stays `CardNotFoundError: no card with id <id>`.
- A missing ref target stays `EntityNotFoundError: no entity with id <id>`; `src == dst` stays `SelfReferenceError`.
- `issue open` validates every `--ref` and `--blocks` id **before** writing the issue row; one bad id writes nothing.
- `RELEASING` stays `{done, merged, canceled, archived}`; `resolve_status`, `_is_released` and `would_create_block_cycle` are not changed by this card.
- Out of scope: not-found blocker resolution (4.2), `blockers` detail array and `<project>: <title>` pretty rendering (4.3), help/prompt text (S6), cross-project parent links, export/import of cross-project edges.
- Dev loop: `uv run pytest`. All 827 existing tests pass before this card starts.

## Review Focus

1. **Foreign source with foreign target** (`brd block FOREIGN --by FOREIGN_ISSUE`): must report the source as foreign, not add the edge. Pinned by REFUSED case `block_card_foreign_source_foreign_target` (Task 1).
2. **One bad `--blocks` id after good ones** (`issue open --blocks p1 --blocks nope`): no issue row, no edges, no refs. Pinned by `test_open_issue_refuses_a_blocks_id_that_is_no_card_and_writes_nothing` (Task 2), parametrised over a foreign issue, a missing id and a foreign document.
3. **Blocking twice on the same foreign target**: behaves exactly as twice on a local target (both raise `sqlite3.IntegrityError` from the `blocked_by` primary key). Pinned by `test_a_repeated_foreign_block_fails_like_a_repeated_local_one` (Task 1).
4. **Self-block** (`brd block a --by a`): still `CycleError`, now that the ownership check no longer runs first. Pinned by `test_a_card_still_cannot_block_itself` (Task 1).
5. **Pretty `show` of a card blocked by a foreign card**: must render, not crash, before 4.3 reshapes it. Pinned by `test_show_pretty_renders_a_foreign_blocker` (Task 1).

## File Structure

- `src/brd/core.py` — blocker target rule (`_require_blocker`), the project-free card check (`require_any_card`), the project-free edge writer (`add_block_edge`), `block_card`.
- `src/brd/issues.py` — `open_issue` validation and writes for `--ref` and `--blocks`.
- `src/brd/refs.py` — `add_explicit` target check.
- `tests/test_project_scope.py` — unit tier: the `two` fixture (P owns `p1`, `p2`; Q owns `q1` (blocked by `p2`) with child `q-child`, issue `qi`, document `qd` stem `qnotes`), `REFUSED` / `SCOPED_REFUSED` tables, `_state` snapshot helper.
- `tests/test_cli.py` — CLI tier: fixtures `foreign` (Q's card `FOREIGN`, title `Foreign`) and `foreign_entities` (adds `FOREIGN_ISSUE` "Foreign issue", `FOREIGN_DOC`), helpers `ok`, `err`, `_refused`, `human`.

---

### Task 1: Blocker targets of `block` and `add --blocked-by` may live in another project

**Files:**
- Modify: `src/brd/core.py:120-127` (`_require_blocker`), `src/brd/core.py:152-154` (`create_card` loop), `src/brd/core.py:221-228` (`block_card`)
- Test: `tests/test_project_scope.py` (imports at lines 9-19; `REFUSED` at lines 164-231; new tests after `test_a_missing_blocker_is_unchanged`, line ~262)
- Test: `tests/test_cli.py` (import at line 10; `test_blocker_targets_must_be_in_this_project` at line ~954)

**Interfaces:**
- Consumes: nothing new.
- Produces: `core._require_blocker(conn: sqlite3.Connection, blocker_id: str) -> None` (the `project_id` parameter is removed). Test helpers in `tests/test_project_scope.py`: `_status(conn, card_id) -> str` and `_next(conn, project_id) -> set[str]`, which Task 2 uses.

- [ ] **Step 1: Update `REFUSED` in `tests/test_project_scope.py`**

Delete these four entries from the `REFUSED` list (they assert the old refusal):

```python
    pytest.param(
        lambda c: core.block_card(c, P, "p1", "q1"), "q1", "card or issue",
        id="block_card_foreign_card_target",
    ),
    pytest.param(
        lambda c: core.block_card(c, P, "p1", "qi"), "qi", "card or issue",
        id="block_card_foreign_issue_target",
    ),
    pytest.param(
        lambda c: core.block_card(c, P, "p1", "qd"), "qd", "card or issue",
        id="block_card_foreign_document_target",
    ),
    pytest.param(
        lambda c: core.create_card(c, P, "new", blocked_by=["p2", "q1"]), "q1", "card or issue",
        id="create_card_foreign_blocker",
    ),
```

In their place (directly after the `unblock_card_foreign_source` entry) add:

```python
    pytest.param(
        lambda c: core.block_card(c, P, "q1", "qi"), "q1", "card",
        id="block_card_foreign_source_foreign_target",
    ),
```

Leave `open_issue_foreign_blocks` in place; Task 2 removes it.

- [ ] **Step 2: Add `CycleError` to the imports of `tests/test_project_scope.py`**

Change the `from brd.errors import (...)` block to:

```python
from brd.errors import (
    CardNotFoundError,
    CommentNotFoundError,
    CycleError,
    DocumentNotFoundError,
    DuplicatePathError,
    DuplicateStemError,
    EntityNotFoundError,
    InvalidBlockerError,
    IssueNotFoundError,
)
```

- [ ] **Step 3: Write the failing unit tests**

Insert directly after `test_a_missing_blocker_is_unchanged` in `tests/test_project_scope.py`:

```python
def _status(conn, card_id):
    return core.resolve_status(conn, db.get_card(conn, card_id))


def _next(conn, project_id):
    return {card.id for card in core.next_cards(conn, project_id)}


def test_a_card_or_issue_of_another_project_can_block(two):
    core.block_card(two, P, "p1", "q1")
    core.block_card(two, P, "p1", "qi")
    assert sorted(db.list_blockers_of(two, "p1")) == ["q1", "qi"]


def test_a_new_card_can_be_blocked_by_another_projects_issue(two):
    card = core.create_card(two, P, "new", blocked_by=["p2", "qi"])
    assert db.owner_of(two, card.id) == PROJECT
    assert sorted(db.list_blockers_of(two, card.id)) == ["p2", "qi"]


def test_a_foreign_document_is_refused_for_its_kind(two):
    before = _state(two)
    message = r"^a document can't block a card; only cards and issues can$"
    with pytest.raises(InvalidBlockerError, match=message):
        core.block_card(two, P, "p1", "qd")
    with pytest.raises(InvalidBlockerError, match=message):
        core.create_card(two, P, "n", blocked_by=["qd"])
    assert _state(two) == before


def test_a_card_still_cannot_block_itself(two):
    before = _state(two)
    with pytest.raises(CycleError, match=r"^blocking p1 on p1 would create a cycle$"):
        core.block_card(two, P, "p1", "p1")
    assert _state(two) == before


def test_a_repeated_foreign_block_fails_like_a_repeated_local_one(two):
    core.block_card(two, P, "p1", "p2")
    core.block_card(two, P, "p1", "q1")
    with pytest.raises(sqlite3.IntegrityError):
        core.block_card(two, P, "p1", "p2")
    with pytest.raises(sqlite3.IntegrityError):
        core.block_card(two, P, "p1", "q1")


def test_a_card_is_released_when_a_foreign_blocker_chain_releases(two):
    core.block_card(two, P, "p1", "q1")
    assert _status(two, "p1") == "blocked"
    # q1 is itself blocked by p2 (fixture): releasing p2 frees q1, not p1.
    core.update_card(two, P, "p2", status="done")
    assert _status(two, "q1") == "todo"
    assert _status(two, "p1") == "blocked"
    core.update_card(two, Q, "q1", status="done")
    assert _status(two, "p1") == "todo"
    assert "p1" in _next(two, P)


def test_a_foreign_issue_blocks_while_open_whatever_the_close_reason(two):
    core.block_card(two, P, "p1", "qi")
    assert _status(two, "p1") == "blocked"
    assert "p1" not in _next(two, P)
    issues.close(two, Q, "qi", reason="wontfix")
    assert _status(two, "p1") == "todo"
    assert "p1" in _next(two, P)
    issues.reopen(two, Q, "qi")
    assert _status(two, "p1") == "blocked"


def test_a_foreign_container_releases_when_every_child_releases(two):
    make_card(two, "qs", project_id=Q)
    make_card(two, "qs1", parent_id="qs", project_id=Q)
    make_card(two, "qs2", parent_id="qs", project_id=Q)
    core.block_card(two, P, "p1", "qs")
    assert _status(two, "p1") == "blocked"
    core.update_card(two, Q, "qs1", status="done")
    assert _status(two, "p1") == "blocked"
    core.update_card(two, Q, "qs2", status="canceled")
    assert _status(two, "p1") == "todo"
    assert _status(two, "qs") == "todo"


def test_a_cycle_through_another_project_is_refused(two):
    core.block_card(two, P, "p1", "q1")
    before = _state(two)
    with pytest.raises(CycleError, match=r"^blocking q1 on p1 would create a cycle$"):
        core.block_card(two, Q, "q1", "p1")
    assert _state(two) == before
    # q1 is blocked by p2 (fixture), so p2 -> p1 would close p2 -> p1 -> q1 -> p2.
    with pytest.raises(CycleError, match=r"^blocking p2 on p1 would create a cycle$"):
        core.block_card(two, P, "p2", "p1")
    assert _state(two) == before
```

`sqlite3` is already imported at the top of the file.

- [ ] **Step 4: Rewrite the CLI blocker-target test**

In `tests/test_cli.py`, change line 10 to also import `human`:

```python
from tests.cli_helpers import err, human, invoke, ok
```

Replace the whole of `test_blocker_targets_must_be_in_this_project`:

```python
def test_blocker_targets_must_be_in_this_project(foreign):
    mine = ok("add", "--title", "mine")["id"]
    _refused("block", mine, "--by", foreign)
    _refused("add", "--title", "t", "--blocked-by", foreign)
    assert ok("show", mine)["blocked_by"] == []
```

with:

```python
def test_blocker_targets_may_live_in_another_project(foreign_entities):
    mine = ok("add", "--title", "mine")["id"]
    ok("block", mine, "--by", FOREIGN)
    blocked = ok("block", mine, "--by", FOREIGN_ISSUE)
    assert sorted(blocked["blocked_by"]) == sorted([FOREIGN, FOREIGN_ISSUE])
    assert blocked["status"] == "blocked"
    added = ok("add", "--title", "t", "--blocked-by", FOREIGN)
    assert (added["blocked_by"], added["status"]) == ([FOREIGN], "blocked")
    assert err("block", mine, "--by", FOREIGN_DOC) == "InvalidBlockerError"
    next_ids = [c["id"] for c in ok("next")]
    assert mine not in next_ids and added["id"] not in next_ids
    ok("unblock", mine, "--by", FOREIGN)
    unblocked = ok("unblock", mine, "--by", FOREIGN_ISSUE)
    assert (unblocked["blocked_by"], unblocked["status"]) == ([], "todo")
    assert mine in [c["id"] for c in ok("next")]


def test_show_pretty_renders_a_foreign_blocker(foreign):
    mine = ok("add", "--title", "mine")["id"]
    ok("block", mine, "--by", foreign)
    assert "Foreign" in human("show", mine)
```

(`FOREIGN_ISSUE` and `FOREIGN_DOC` are module-level constants defined just above `foreign_entities`; Python resolves them at call time, so their position in the file does not matter.)

- [ ] **Step 5: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_project_scope.py tests/test_cli.py -q -k "another_project or foreign_document_is_refused_for_its_kind or block_itself or repeated_foreign_block or foreign_blocker_chain or foreign_issue_blocks_while_open or foreign_container_releases or cycle_through_another or foreign_source_foreign_target or pretty_renders_a_foreign_blocker"`

Expected: FAIL. The blocking tests fail with `CardNotFoundError: no card or issue with id q1 in this project; it belongs to project other (...)` (or `qi`, `qs`), and `test_a_foreign_document_is_refused_for_its_kind` fails because `CardNotFoundError` is raised instead of `InvalidBlockerError`. `test_a_card_still_cannot_block_itself` and `block_card_foreign_source_foreign_target` already PASS — they pin behaviour this change must keep.

- [ ] **Step 6: Drop the ownership check from `_require_blocker`**

In `src/brd/core.py`, replace:

```python
def _require_blocker(conn: sqlite3.Connection, project_id: str, blocker_id: str) -> None:
    kind = entities.kind_of(conn, blocker_id)
    if kind is None:
        raise CardNotFoundError(f"no card or issue with id {blocker_id}")
    # Ownership before kind: a foreign document is reported as foreign.
    _require_in_project(conn, project_id, blocker_id, "card or issue")
    if kind not in entities.BLOCKERS:
        raise InvalidBlockerError(f"a {kind} can't block a card; only cards and issues can")
```

with:

```python
def _require_blocker(conn: sqlite3.Connection, blocker_id: str) -> None:
    # A blocker may belong to any project; only the blocked card is scoped.
    kind = entities.kind_of(conn, blocker_id)
    if kind is None:
        raise CardNotFoundError(f"no card or issue with id {blocker_id}")
    if kind not in entities.BLOCKERS:
        raise InvalidBlockerError(f"a {kind} can't block a card; only cards and issues can")
```

In `create_card`, change:

```python
    for blocker_id in blocked_by:
        _require_blocker(conn, project_id, blocker_id)
```

to:

```python
    for blocker_id in blocked_by:
        _require_blocker(conn, blocker_id)
```

In `block_card`, change:

```python
    _require_blocker(conn, project_id, blocker_id)
```

to:

```python
    _require_blocker(conn, blocker_id)
```

- [ ] **Step 7: Run the new tests to verify they pass**

Run: the same command as Step 5.
Expected: PASS.

- [ ] **Step 8: Run the full suite**

Run: `uv run pytest -q`
Expected: all tests pass (`test_issue_open_refuses_a_foreign_blocks_card` and `REFUSED[open_issue_foreign_blocks]` still pass: `open_issue` is untouched until Task 2).

- [ ] **Step 9: Commit**

```bash
git add src/brd/core.py tests/test_project_scope.py tests/test_cli.py
git commit -m "Let brd block and add --blocked-by take a blocker from another project"
```

---

### Task 2: `issue open --blocks` may block another project's card

**Files:**
- Modify: `src/brd/core.py:113-118` (`require_card`), `src/brd/core.py:221-228` (`block_card`)
- Modify: `src/brd/issues.py:88-89` and `src/brd/issues.py:100-101` (`open_issue`)
- Test: `tests/test_project_scope.py` (`REFUSED`; new tests after `test_a_cycle_through_another_project_is_refused`)
- Test: `tests/test_cli.py` (`test_issue_open_refuses_a_foreign_blocks_card`, line ~961)

**Interfaces:**
- Consumes: `core._require_blocker(conn, blocker_id) -> None` (Task 1); test helpers `_status(conn, card_id) -> str`, `_next(conn, project_id) -> set[str]` and `_state(conn)` in `tests/test_project_scope.py`.
- Produces: `core.require_any_card(conn: sqlite3.Connection, card_id: str) -> Card` — raises `CardNotFoundError(f"no card with id {card_id}")` for a missing id or a non-card. `core.add_block_edge(conn: sqlite3.Connection, card_id: str, blocker_id: str) -> None` — checks the blocker (`_require_blocker`), the cycle, then inserts; no ownership check on either side.

- [ ] **Step 1: Remove `open_issue_foreign_blocks` from `REFUSED`**

In `tests/test_project_scope.py`, delete:

```python
    pytest.param(
        lambda c: issues.open_issue(c, P, "t", blocks=["p1", "q1"]), "q1", "card",
        id="open_issue_foreign_blocks",
    ),
```

- [ ] **Step 2: Write the failing unit tests**

Insert after `test_a_cycle_through_another_project_is_refused` in `tests/test_project_scope.py`:

```python
def test_an_issue_can_block_a_card_of_another_project(two):
    # q-child inherits its parent's block, and q1 is blocked by p2 (fixture):
    # release p2 first so q-child can resolve to todo once the issue closes.
    core.update_card(two, P, "p2", status="done")
    issue = issues.open_issue(two, P, "t", blocks=["p1", "q-child"])
    assert db.owner_of(two, issue.id) == PROJECT
    assert issues.blocks_of(two, issue.id) == ["p1", "q-child"]
    assert _status(two, "q-child") == "blocked"
    assert "q-child" not in _next(two, Q)
    issues.close(two, P, issue.id)
    assert _status(two, "q-child") == "todo"
    assert "q-child" in _next(two, Q)


@pytest.mark.parametrize(
    ("blocks", "bad"),
    [(["q1", "qi"], "qi"), (["p1", "nope"], "nope"), (["p1", "qd"], "qd")],
    ids=["foreign_issue", "missing", "foreign_document"],
)
def test_open_issue_refuses_a_blocks_id_that_is_no_card_and_writes_nothing(two, blocks, bad):
    before = _state(two)
    with pytest.raises(CardNotFoundError, match=rf"^no card with id {bad}$"):
        issues.open_issue(two, P, "t", blocks=blocks)
    assert _state(two) == before
```

- [ ] **Step 3: Rewrite the CLI `--blocks` test**

In `tests/test_cli.py`, replace:

```python
def test_issue_open_refuses_a_foreign_blocks_card(foreign):
    _refused("issue", "open", "--title", "q", "--blocks", foreign)
    assert ok("issue", "list") == []
```

with:

```python
def test_issue_open_can_block_a_foreign_card(foreign):
    issue = ok("issue", "open", "--title", "q", "--blocks", foreign)
    assert issue["blocks"] == [foreign]
    shown = ok("show", foreign)
    assert (shown["blocked_by"], shown["status"]) == ([issue["id"]], "blocked")
    ok("issue", "close", issue["id"])
    assert ok("show", foreign)["status"] == "todo"
```

- [ ] **Step 4: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_project_scope.py tests/test_cli.py -q -k "issue_can_block_a_card_of_another_project or blocks_id_that_is_no_card or issue_open_can_block_a_foreign_card"`

Expected: FAIL. `test_an_issue_can_block_a_card_of_another_project` and `test_issue_open_can_block_a_foreign_card` fail with `CardNotFoundError: no card with id q-child in this project; it belongs to project other (...)` (CLI: exit code 1). The `foreign_issue` case fails because the message names `q1` as foreign instead of `no card with id qi`. The `missing` and `foreign_document` cases already pass (`db.get_card` finds no card for either); they pin the write-nothing guarantee through the restructure.

- [ ] **Step 5: Add `require_any_card` and build `require_card` on it**

In `src/brd/core.py`, replace:

```python
def require_card(conn: sqlite3.Connection, project_id: str, card_id: str) -> Card:
    card = db.get_card(conn, card_id)
    if card is None:
        raise CardNotFoundError(f"no card with id {card_id}")
    _require_in_project(conn, project_id, card_id, "card")
    return card
```

with:

```python
def require_any_card(conn: sqlite3.Connection, card_id: str) -> Card:
    # Whichever project owns it: for edge targets, which may be any project's.
    card = db.get_card(conn, card_id)
    if card is None:
        raise CardNotFoundError(f"no card with id {card_id}")
    return card


def require_card(conn: sqlite3.Connection, project_id: str, card_id: str) -> Card:
    card = require_any_card(conn, card_id)
    _require_in_project(conn, project_id, card_id, "card")
    return card
```

- [ ] **Step 6: Split the edge write out of `block_card`**

In `src/brd/core.py`, replace:

```python
def block_card(
    conn: sqlite3.Connection, project_id: str, card_id: str, blocker_id: str
) -> None:
    require_card(conn, project_id, card_id)
    _require_blocker(conn, blocker_id)
    if would_create_block_cycle(conn, card_id, blocker_id):
        raise CycleError(f"blocking {card_id} on {blocker_id} would create a cycle")
    db.add_blocked_by_edge(conn, card_id, blocker_id)
```

with:

```python
def add_block_edge(conn: sqlite3.Connection, card_id: str, blocker_id: str) -> None:
    # No ownership check on either side: `issue open --blocks` blocks another
    # project's card. Callers that act on the card itself check it first.
    _require_blocker(conn, blocker_id)
    if would_create_block_cycle(conn, card_id, blocker_id):
        raise CycleError(f"blocking {card_id} on {blocker_id} would create a cycle")
    db.add_blocked_by_edge(conn, card_id, blocker_id)


def block_card(
    conn: sqlite3.Connection, project_id: str, card_id: str, blocker_id: str
) -> None:
    require_card(conn, project_id, card_id)
    add_block_edge(conn, card_id, blocker_id)
```

- [ ] **Step 7: Use them in `open_issue`**

In `src/brd/issues.py`, replace:

```python
    for card_id in blocks:
        core.require_card(conn, project_id, card_id)
```

with:

```python
    for card_id in blocks:
        # The new issue is this project's; the card it blocks may be any project's.
        core.require_any_card(conn, card_id)
```

and replace:

```python
    for card_id in blocks:
        core.block_card(conn, project_id, card_id, issue.id)
```

with:

```python
    for card_id in blocks:
        core.add_block_edge(conn, card_id, issue.id)
```

Both validation loops stay **before** the `with conn:` block that inserts the issue row.

- [ ] **Step 8: Run the new tests to verify they pass**

Run: the same command as Step 4.
Expected: PASS.

- [ ] **Step 9: Run the full suite**

Run: `uv run pytest -q`
Expected: all tests pass, including `REFUSED[block_card_foreign_source]`, `REFUSED[block_card_foreign_source_foreign_target]` and `test_block_and_unblock_refuse_a_foreign_card` (the `brd block` source is still scoped).

- [ ] **Step 10: Commit**

```bash
git add src/brd/core.py src/brd/issues.py tests/test_project_scope.py tests/test_cli.py
git commit -m "Let brd issue open --blocks block a card of another project"
```

---

### Task 3: Ref targets of `ref add` and `issue open --ref` may live in another project

**Files:**
- Modify: `src/brd/refs.py:107-110` (`add_explicit`)
- Modify: `src/brd/issues.py:85-87` (`open_issue` ref loop)
- Test: `tests/test_project_scope.py` (imports; `SCOPED_REFUSED` at lines ~388-472; new tests after `test_ref_remove_checks_only_the_source`, line ~712)
- Test: `tests/test_cli.py` (`test_issue_commands_are_scoped_to_this_project` line ~1007, `test_ref_commands_are_scoped_to_this_project` line ~1027)

**Interfaces:**
- Consumes: `entities.require(conn, entity_id) -> str` (existing; raises `EntityNotFoundError(f"no entity with id {entity_id}")`); `_state(conn)` in `tests/test_project_scope.py`.
- Produces: nothing new for other tasks.

- [ ] **Step 1: Remove the foreign-ref-target cases from `SCOPED_REFUSED`**

In `tests/test_project_scope.py`, delete these three entries:

```python
    pytest.param(
        lambda c: issues.open_issue(c, P, "t", ref_ids=["q1"]), CardNotFoundError, "q1", "card",
        id="open_issue_foreign_ref",
    ),
    pytest.param(
        lambda c: issues.open_issue(c, P, "t", ref_ids=["p1", "qd"]), DocumentNotFoundError,
        "qd", "document", id="open_issue_mixed_refs",
    ),
```

```python
    pytest.param(
        lambda c: refs.add_explicit(c, P, "p1", "qi"), IssueNotFoundError, "qi", "issue",
        id="ref_add_foreign_target",
    ),
```

Keep `ref_add_foreign_source` and `ref_remove_foreign_source`.

- [ ] **Step 2: Add `SelfReferenceError` to the imports**

Change the `from brd.errors import (...)` block to:

```python
from brd.errors import (
    CardNotFoundError,
    CommentNotFoundError,
    CycleError,
    DocumentNotFoundError,
    DuplicatePathError,
    DuplicateStemError,
    EntityNotFoundError,
    InvalidBlockerError,
    IssueNotFoundError,
    SelfReferenceError,
)
```

- [ ] **Step 3: Write the failing unit tests**

Insert after `test_ref_remove_checks_only_the_source` in `tests/test_project_scope.py`:

```python
def test_a_ref_can_target_another_projects_entity(two):
    refs.add_explicit(two, P, "p1", "qi")
    refs.add_explicit(two, P, "p1", "qd")
    assert refs.outgoing(two, "p1") == [
        {"id": "qd", "kind": "document", "title": "qnotes", "origin": "explicit"},
        {"id": "qi", "kind": "issue", "title": "qi", "origin": "explicit"},
    ]
    assert refs.incoming(two, "qi") == [
        {"id": "p1", "kind": "card", "title": "p1", "origin": "explicit"}
    ]


def test_ref_add_still_refuses_a_missing_target_and_itself(two):
    before = _state(two)
    with pytest.raises(EntityNotFoundError, match=r"^no entity with id nope$"):
        refs.add_explicit(two, P, "p1", "nope")
    with pytest.raises(SelfReferenceError):
        refs.add_explicit(two, P, "p1", "p1")
    assert _state(two) == before


def test_open_issue_refs_may_target_another_project(two):
    issue = issues.open_issue(two, P, "t", ref_ids=["p1", "qd"])
    assert [r["id"] for r in refs.outgoing(two, issue.id)] == ["p1", "qd"]


def test_open_issue_with_a_missing_ref_writes_nothing(two):
    before = _state(two)
    with pytest.raises(EntityNotFoundError, match=r"^no entity with id nope$"):
        issues.open_issue(two, P, "t", ref_ids=["q1", "nope"])
    assert _state(two) == before
```

- [ ] **Step 4: Update the CLI scope tests and add the ref-target test**

In `tests/test_cli.py`, in `test_issue_commands_are_scoped_to_this_project`, delete the line:

```python
    _refused("issue", "open", "--title", "q", "--ref", foreign_entities["card"])
```

Replace the whole of `test_ref_commands_are_scoped_to_this_project`:

```python
def test_ref_commands_are_scoped_to_this_project(foreign_entities):
    mine = ok("add", "--title", "mine")["id"]
    _refused("ref", "add", foreign_entities["card"], mine)
    _refused("ref", "add", mine, foreign_entities["issue"], error_type="IssueNotFoundError")
    _refused("ref", "remove", foreign_entities["card"], mine)
    assert ok("show", mine)["refs"] == []
    assert ok("show", foreign_entities["card"])["refs"] == []
```

with:

```python
def test_ref_commands_are_scoped_to_this_project(foreign_entities):
    mine = ok("add", "--title", "mine")["id"]
    _refused("ref", "add", foreign_entities["card"], mine)
    _refused("ref", "remove", foreign_entities["card"], mine)
    assert ok("show", mine)["refs"] == []
    assert ok("show", foreign_entities["card"])["refs"] == []


def test_ref_targets_may_live_in_another_project(foreign_entities):
    mine = ok("add", "--title", "mine")["id"]
    added = ok("ref", "add", mine, FOREIGN_ISSUE)
    assert added == {
        "id": mine,
        "refs": [
            {"id": FOREIGN_ISSUE, "kind": "issue", "title": "Foreign issue", "origin": "explicit"}
        ],
    }
    assert [r["id"] for r in ok("show", mine)["refs"]] == [FOREIGN_ISSUE]
    assert [r["id"] for r in ok("show", FOREIGN_ISSUE)["referenced_by"]] == [mine]
    issue = ok("issue", "open", "--title", "q", "--ref", FOREIGN)
    assert [r["id"] for r in ok("show", issue["id"])["refs"]] == [FOREIGN]
```

- [ ] **Step 5: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_project_scope.py tests/test_cli.py -q -k "ref_can_target_another or refuses_a_missing_target_and_itself or open_issue_refs_may_target or missing_ref_writes_nothing or ref_targets_may_live or ref_commands_are_scoped or issue_commands_are_scoped"`

Expected: FAIL. `test_a_ref_can_target_another_projects_entity`, `test_open_issue_refs_may_target_another_project` and `test_ref_targets_may_live_in_another_project` fail with a not-found error naming project `other`; `test_open_issue_with_a_missing_ref_writes_nothing` fails because `CardNotFoundError` (foreign `q1`) is raised instead of `EntityNotFoundError`. `test_ref_add_still_refuses_a_missing_target_and_itself` and the two edited scope tests already pass.

- [ ] **Step 6: Check only existence of the ref target in `add_explicit`**

In `src/brd/refs.py`, replace:

```python
    entities.require_in_project(conn, project_id, src_id)
    # Ref targets stay in the current project until S4 lifts the check.
    entities.require_in_project(conn, project_id, dst_id)
```

with:

```python
    entities.require_in_project(conn, project_id, src_id)
    # Like a blocker, a ref target may belong to any project.
    entities.require(conn, dst_id)
```

- [ ] **Step 7: Check only existence of `--ref` ids in `open_issue`**

In `src/brd/issues.py`, replace:

```python
    for ref_id in ref_ids:
        # Ref targets stay in the current project until S4 lifts the check.
        entities.require_in_project(conn, project_id, ref_id)
```

with:

```python
    for ref_id in ref_ids:
        entities.require(conn, ref_id)
```

`entities` is still used by `issues.require`, so its import stays.

- [ ] **Step 8: Run the new tests to verify they pass**

Run: the same command as Step 5.
Expected: PASS.

- [ ] **Step 9: Run the full suite**

Run: `uv run pytest -q`
Expected: all tests pass, including `SCOPED_REFUSED[ref_add_foreign_source]`, `SCOPED_REFUSED[ref_remove_foreign_source]` and `test_ref_remove_checks_only_the_source`.

- [ ] **Step 10: Commit**

```bash
git add src/brd/refs.py src/brd/issues.py tests/test_project_scope.py tests/test_cli.py
git commit -m "Let brd ref add and issue open --ref target another project's entity"
```

---

## Spec coverage check

| Spec item | Task |
|---|---|
| B1 card/issue target of P or Q accepted; document refused for kind; missing unchanged; cycle; foreign source first | Task 1 (T1, T4, T11, REFUSED `block_card_foreign_source_foreign_target`, existing `test_a_missing_blocker_is_unchanged`) |
| B2 `add --blocked-by` | Task 1 (T2, T4, T12) |
| B3 `issue open --blocks` foreign card; non-card/missing refused; validate before write | Task 2 (T3, T7, T13) |
| B4 `ref add` / `--ref` foreign target; missing / self unchanged; `ref remove` unchanged | Task 3 (T5, T6, T14, `test_ref_add_still_refuses_a_missing_target_and_itself`) |
| B5 resolution across projects (card chain, issue any reason + reopen, container, Q card blocked by P issue) | Task 1 (T8, T9, T10), Task 2 (T3, T13) |
| B6 cycle direct and indirect, no edge written | Task 1 (T11) |
| B7 `unblock` cross-project edge | Task 1 (T12) |
| Production changes: `_require_blocker`, `block_card`/`open_issue` split, `issues.py` checks, `refs.py` check, "until S4" comments deleted | Tasks 1-3 |
| Existing tests to invert/rewrite (REFUSED ×5, SCOPED_REFUSED ×3, `test_cli.py` ×4) | Task 1 (REFUSED ×4, `test_blocker_targets…`), Task 2 (REFUSED ×1, `test_issue_open_refuses…`), Task 3 (SCOPED_REFUSED ×3, lines 1007 and 1030) |
| T15 pretty show | Task 1 |
| Review focus: foreign source + foreign target, bad `--blocks` after good, duplicate, self-block | Task 1, Task 2 |
<!-- task-pipeline: validated -->
