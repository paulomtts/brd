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
