# 4.2 A not-found blocker blocks; forget keeps incoming edges

Card: `37d4b3dc-f0fd-423f-babe-e3e24bc15c07`. It is the second subtask of story `43766a3a`
"Cross-project edges" (spec section 4 and D6-D8), in milestone `6aa7043a` "Single database
and cross-project blocking". It comes after card 4.1 (`910aabf8`), which is merged into
this branch. Since 4.1, blocker targets and ref targets may belong to any project.

Parent design spec: `docs/superpowers/specs/2026-10-06-single-db-cross-project-blocking-design.md`.
It is in the main checkout (`/home/mtts/Code/brd/docs/...`), not in this branch's history.
Citations look like **[P §n Lx]**. Sibling spec 4.1 is
`docs/superpowers/specs/4-1-blockers-and-ref-910aabf8.md`, cited as **[4.1 Lx]**.

## Goal

An edge target can now be an id that is **not found**: no `entities` row has that id. This
card fixes three things about such targets:

1. A not-found blocker keeps its card `blocked` (fail closed). Today it is skipped, so the
   card resolves to `todo` and shows up in `brd next`.
2. `brd forget` stops deleting edges that other projects point at the forgotten project's
   entities. Those edges stay and become not-found. If the ids come back (for example on a
   later import), they reconnect.
3. Every command that reads an edge keeps working when the edge is not-found. `brd unblock`
   removes a not-found blocker edge. `brd ref remove` removes a not-found explicit ref.
   `brd show` of the source does not crash.

`brd delete` keeps removing the edges that point at the deleted entity. That behaviour
comes from card 2.2 and does not change.

## Inherited constraints

| Constraint | Source |
|---|---|
| Edge targets (`blocked_by.blocks_on_id`, `refs.dst_id`) carry no foreign key. An edge whose target is not in the database is kept and reported as `not-found`. | [P D6 L36], [P §1 L68-80] |
| A `not-found` blocker blocks (fail closed). | [P D7 L37] |
| `brd delete` removes edges pointing at the deleted entity. `brd forget` does **not** remove incoming edges from other projects. They become `not-found` and reconnect if the ids return. | [P D8 L38] |
| `core.delete_card`, `issues.delete` and `documents.delete` also delete `blocked_by` rows with `blocks_on_id = ?` and `refs` rows with `dst_id = ?`. | [P §1 L92-94] |
| `brd forget` deletes the `projects` row, which cascades to everything the project owns. It does not touch incoming edges from other projects. | [P §1 L95-96] |
| `is_released(id)`: `kind_of` is a global lookup. `None` gives `False` (not-found blocks, D7). For an issue: `status != 'open'`. For a card: it resolves to a releasing status, or (D1) it has children and every child is released. | [P §4 L161-166] |
| `RELEASING` stays `{done, merged, canceled, archived}`. Recursion keeps the `seen` guard. The cycle check walks `blocked_by` across projects, and **a not-found id ends a path**. | [P §4 L169-171] |
| `blocked_by` stays a list of ids wherever it appears today. | [P §4 L173-174] |
| Mutating commands, including the `block`/`unblock` source and the `ref` source, require the entity to belong to the current project. | [P §2 L112-115] |
| Phase 3 includes "not-found resolution" and "`forget` keeping incoming edges". | [P Implementation order L281-283] |
| Tests: "not-found blocks"; "`delete` removes incoming edges; `forget` keeps incoming edges as not-found". | [P Testing L262], [P Testing L265-266] |
| 4.1 left `resolve_status`'s `continue` for a missing blocker in place for this card. 4.1 also left the not-found rule, `forget` and `unblock` of a not-found edge to this card. | [4.1 L215-218] |
| `brd forget` must not gain incoming-edge cleanup; per D8 it keeps those edges as not-found. | 2.2 spec, `docs/superpowers/specs/2-2-deleting-an-entity-a6a8dd67.md:149-151` |

### Notes on the sources

- **Refs as well as blockers.** The card text talks about blockers. D8 says "incoming
  edges", and §1 L95-96 says forget "does not touch incoming edges". D6 names both
  `blocked_by.blocks_on_id` and `refs.dst_id` as edge targets. This spec therefore keeps
  **both** kinds of incoming edge on forget: blocker edges and refs (explicit and link).
  A kept ref whose target is gone must not break readers. Today
  `refs._summaries` (`src/brd/refs.py:131-132`) spreads `entities.summary(...)`, which is
  `None` for a missing id (`src/brd/entities.py:82-86`), so it raises `TypeError`. B5
  fixes that.
- **History of the forget cleanup.** Card 3.3 added the explicit incoming-edge deletes to
  `db.delete_project` as a temporary measure ("S4 changes that",
  `docs/superpowers/specs/3-3-brd-init-relink-and-91e68a83.md:42-52`). This card is that
  change.

## Terms

- **P**: the current project. **Q**: another project registered in the same `brd.db`.
- **Not-found id**: an id with no row in `entities`, in any project.
- **Not-found edge**: a `blocked_by` row whose `blocks_on_id` is not found, or a `refs`
  row whose `dst_id` is not found.
- Commands cannot *add* a not-found edge. `_require_blocker` (`src/brd/core.py:126-132`)
  and the ref target checks still refuse a missing id, and this card leaves that alone.
  So through brd's own commands a not-found edge only comes from `brd forget`. Tests may
  also write one directly with `db.add_blocked_by_edge` or a raw `INSERT INTO refs`.

## Behaviour

### B1. Status resolution: a not-found blocker blocks (D7)

`core.resolve_status(card)` for a card whose stored status is `todo`. For each blocker id:

| Blocker id is… | Effect on the card |
|---|---|
| not found (no `entities` row) | **`blocked`** (new; today the blocker is skipped) |
| an issue (any project) | `blocked` while the issue's status is `open`. Otherwise it releases. (Unchanged.) |
| a card (any project) | `blocked` unless the card is released (D1, unchanged) |
| a document | Unchanged: it does not block. No command can add one (`InvalidBlockerError`), so this is outside the card. |

Consequences, all through existing code paths that call `resolve_status`:

- A card with a not-found blocker reports `"status": "blocked"` in `brd show`, `brd list`
  and `brd tree`. It is **not** listed by `brd next`.
- A child of that card also resolves to `blocked` (parent rule, unchanged).
- A card blocked by a not-found id **plus** released blockers is still `blocked`. One
  not-found blocker is enough.
- A card whose stored status is not `todo` (for example `in_progress` or `done`) keeps its
  stored status. A not-found blocker does not change it (unchanged early return).
- **Releasing a dependent.** If card `X` has a not-found blocker, then a card blocked by
  `X` stays blocked until `X` is released. `X` is released when its own stored status is
  releasing, or when it has children that are all released (D1). A not-found blocker on
  `X` stops `X` from resolving to `todo`. It does not stop a `done` `X` from releasing.
- `blocked_by` in JSON output still lists the not-found id, as a plain string, in its
  stored position. `blocked_by` is never filtered.

### B2. Cycle check: a not-found id ends a path

`core.would_create_block_cycle(card_id, new_blocker_id)` treats a not-found id as a node
with no outgoing edges. A not-found id never closes a cycle unless it *is* `card_id`, and
it never raises an error. The code already behaves this way (`src/brd/core.py:81-92`: it
only reads `blocked_by` rows). This card pins it with a test:

- Card `a` is blocked by not-found `ghost`. `would_create_block_cycle(conn, "b", "a")` is
  `False`. `brd block b --by a` succeeds and stores the edge.
- `resolve_status` on a chain through a not-found id (`b` blocked by `a`, `a` blocked by
  `ghost`) returns `blocked` for both cards and ends normally.

### B3. `brd forget` keeps incoming edges (D8)

Before this card, `db.delete_project` (`src/brd/db.py:550-558`) deleted every
`blocked_by` row whose `blocks_on_id` was owned by the project, and every `refs` row whose
`dst_id` was owned by the project. After this card it deletes only the `projects` row. The
FK cascade then removes everything the project owns:

- Everything owned by the forgotten project goes, as before: its entities, cards, issues,
  documents, comments, tags, its **outgoing** `blocked_by` rows (`card_id` in the project)
  and its **outgoing** refs (`src_id` in the project).
- Rows owned by other projects stay, **including** their `blocked_by` rows and refs that
  point at the forgotten project's entities. Those become not-found edges.
- Document backups of the forgotten project are still removed (`master._forget`,
  unchanged).
- The whole delete is still one transaction. If the project delete fails, nothing changes
  (existing test `test_delete_project_keeps_incoming_edges_when_the_project_delete_fails`
  keeps holding).
- `brd forget`'s output and exit code are unchanged (the project's JSON, exit 0).

Seen by a user of project Q after `brd forget` of P, where Q's card `q1` was blocked by
P's todo card `p1`:

- `brd show q1` shows `"blocked_by": ["p1"]` and `"status": "blocked"`. Before forget,
  `p1` was todo, so `q1` was already blocked. It stays blocked.
- If `p1` had been `done` before the forget, `q1` was `todo` and is now **`blocked`**.
  Fail closed: brd cannot tell a missing blocker from an unfinished one.
- `brd next` from Q does not list `q1`.

### B4. `brd unblock` clears a not-found edge

`brd unblock <card of current project> --by <not-found id>` exits 0. It removes the
`blocked_by` row and prints the card's detail with that id gone from `blocked_by`. If
nothing else blocks the card, it resolves to `todo` again and shows up in `brd next`. This
works today (`core.unblock_card` only checks the source card, `src/brd/core.py:243-247`;
`db.remove_blocked_by_edge` deletes by the `(card_id, blocks_on_id)` pair without looking
up the target, `src/brd/db.py:665-672`). This card pins it with tests.

Unchanged error paths:

- The source card is in another project: `CardNotFoundError` naming the owner.
- The source is missing: `CardNotFoundError: no card with id <id>`.
- `--by` an id that is not among the card's blockers: no-op, exit 0 (unchanged).

`brd block <card> --by <not-found id>` is still refused with
`CardNotFoundError: no card or issue with id <id>` and writes no edge [4.1 B1]. So once
the user unblocks a not-found edge, they cannot add it back until the id exists again.

### B5. Refs readers tolerate a not-found target

A ref is kept on forget (B3), so readers must handle a `dst_id` that is not found:

- `refs.outgoing(src)`, as used by `brd show <src>` (`refs` field) and the output of
  `brd ref add` / `brd ref remove`, lists a not-found target as
  `{"id": "<dst_id>", "kind": null, "title": null, "origin": "<explicit|link>"}`. It is
  ordered with the other refs exactly as today (`ORDER BY origin, dst_id`). This uses the
  same `null` convention that card 4.3 uses for not-found blockers [P §4 L181-182].
- `refs.incoming(dst)` is not affected. Its rows' `src_id` always exists, because
  `refs.src_id` has an FK cascade.
- `brd show <src> --pretty` exits 0. In its `refs:` line, a not-found target is shown as
  `not-found <id>` instead of `<title> (<kind>)`. This matches the wording 4.3 uses for a
  missing blocker [P §4 L186-187].
- `brd ref remove <src> <not-found id>` exits 0 and removes the explicit ref. It already
  checks only the source (`src/brd/refs.py:120-128`). Its output lists the refs that
  remain.
- **Link refs:** a link ref (`origin = 'link'`) to a forgotten entity stays until the
  source is next reindexed (an edit to its text or comments). Then `refs.reindex` drops it,
  because `[[<id>]]` no longer resolves. That is today's reindex behaviour, and this card
  does not change it.

### B6. `brd delete` still removes incoming edges

Unchanged (card 2.2, [P D8 L38], [P §1 L92-94]). `db.delete_incoming_edges`
(`src/brd/db.py:689-694`) and its callers (`entities.delete`, `db.delete_card`) stay as
they are. Deleting a card or issue that another project's card is blocked by removes that
edge, and the dependent resolves as if the edge never existed. It does **not** become
not-found-blocked. One new test pins this across projects, next to the forget test, so the
two rules are checked side by side.

## Changes in production code

These lines are named only so the planner has the full set. How to restructure them is the
plan's call.

- `src/brd/core.py:35-44` `resolve_status`: a blocker id with no `entities` row returns
  `blocked`. Look it up with `entities.kind_of` (a global lookup) instead of falling
  through to the issues query and `continue`. Issue and card handling is unchanged. A
  document blocker still does not block.
- `src/brd/db.py:550-558` `delete_project`: drop both explicit deletes (lines 556-557) and
  rewrite the docstring. It still runs in one `with conn:` transaction.
- `src/brd/master.py:176-178` `_forget` docstring: drop "the edges pointing at its
  entities". Incoming edges from other projects are kept.
- `src/brd/refs.py:131-132` `_summaries` (or `entities.summary`'s caller): a not-found id
  gives `{"id", "kind": None, "title": None, "origin"}`. `_summaries` is the only caller
  of `entities.summary` today, so the fix can go in either function. Choose one.
- `src/brd/pretty.py:18-24` `_ref_line`: an item with `kind is None` renders as
  `not-found <id>`.

Not changed: `db.delete_incoming_edges`, `core.unblock_card`, `db.remove_blocked_by_edge`,
`would_create_block_cycle`, `_require_blocker`, `pretty._blocker` (card 4.3), `views`
(card 4.3).

## Tests

Tiers used in this repo:

- **unit**: calls `core` / `db` / `refs` / `master` directly against a temporary database
  (`conn` fixture in `tests/test_core.py`, `project_conn` in `tests/test_db.py`,
  `_two_projects` + `_brd()` in `tests/test_master.py`, factories `make_card` /
  `make_issue` in `tests/factories.py`). Use it for the rules: resolution, the cycle
  walk, which rows a delete leaves. It is fast and precise.
- **CLI**: runs `brd` through Typer's `CliRunner` against a real `brd.db`
  (`tests/test_cli.py` helpers `ok`, `err`, `invoke`, fixtures `isolated_env`, `foreign`).
  Use it for the user-visible contract: the command reaches the rule, the JSON shape is
  right, and `--pretty` does not crash.

### Existing tests to invert or rewrite

| Test | Now asserts | Becomes |
|---|---|---|
| `tests/test_core.py:157` `test_resolve_status_skips_blocker_whose_card_is_missing` | ghost blocker gives `todo` | Rename and invert to T1: ghost blocker gives `blocked`. Drop the stale `PRAGMA foreign_keys=OFF`; there is no FK on `blocks_on_id` in v4. |
| `tests/test_db.py:505` `test_delete_project_removes_incoming_edges_from_other_projects` | incoming `blocked_by` and refs deleted | Rewrite as T6: both incoming rows survive. |
| `tests/test_master.py:779` `test_forgetting_a_project_removes_edges_other_projects_point_at_it` | edges into the forgotten project gone; `b1` resolves `todo` | Rewrite as T7: edges kept, `b1` resolves `blocked`. |

`tests/test_db.py:535` `test_delete_project_keeps_incoming_edges_when_the_project_delete_fails`
stays valid unchanged, and still pins the transaction.

### New tests

| # | Test | Tier | Why this tier | Covers |
|---|---|---|---|---|
| T1 | `test_resolve_status_blocks_on_a_blocker_that_is_not_found` (`tests/test_core.py`): `c1` todo, edge `c1 → ghost` via `db.add_blocked_by_edge`. `resolve_status(c1) == "blocked"`. | unit | The core D7 rule, without CLI noise. | B1 |
| T2 | `test_resolve_status_not_found_blocker_wins_over_released_ones` (`tests/test_core.py`): `c1` blocked by `done` card `d` **and** closed issue `i` (`make_issue(..., status="closed")`) **and** `ghost`. Result `blocked`. Then remove only the `ghost` edge: result `todo`. | unit | Shows that one not-found blocker is enough and that it is the cause. | B1, B4 |
| T3 | `test_resolve_status_not_found_blocker_blocks_children_and_spares_non_todo` (`tests/test_core.py`): parent `p` blocked by `ghost`; todo child `ch` resolves `blocked`. An `in_progress` card blocked by `ghost` resolves `in_progress`. A `done` card `x` blocked by `ghost` still releases `y`, which is blocked by `x`: `y` resolves `todo`. | unit | The parent rule, the early return and release, applied to a not-found blocker. | B1 |
| T4 | `test_block_cycle_check_treats_a_not_found_id_as_a_dead_end` (`tests/test_core.py`): `a` blocked by `ghost`. `would_create_block_cycle(conn, "b", "a") is False`. `would_create_block_cycle(conn, "ghost", "a") is True` (the target *is* the id). `core.block_card(PROJECT.id, "b", "a")` stores the edge without error. `resolve_status` of `b` and of `a` is `blocked`. | unit | Pins the walk's end condition on a dangling id and shows resolution ends normally along a chain through it. | B2 |
| T5 | `test_unblock_card_removes_a_not_found_edge` (`tests/test_core.py`): `c1` blocked by `ghost` (resolves `blocked`). `core.unblock_card(conn, PROJECT.id, "c1", "ghost")`. `db.list_blockers_of(c1) == []`, and it resolves `todo`. | unit | The core unblock path on a target with no entity. | B4 |
| T6 | `test_delete_project_keeps_incoming_edges_from_other_projects` (`tests/test_db.py`, replaces line 505): same setup as today (`a1` in PROJECT; `b1`, `b2` in OTHER; `b1` blocked by `a1` and `b2`; explicit refs `b1→a1`, `b1→b2`; plus `a1` blocked by `b2` and an explicit ref `a1→b2`, both outgoing from PROJECT). After `db.delete_project(PROJECT.id)`: `_blocked_by_rows == {("b1","a1"), ("b1","b2")}` and `_ref_rows == {("b1","a1"), ("b1","b2")}`. The outgoing `a1` rows are gone through the cascade. | unit | Pins exactly which rows the SQL leaves: incoming kept, outgoing cascaded. | B3 |
| T7 | `test_forgetting_a_project_keeps_edges_other_projects_point_at_it` (`tests/test_master.py`, replaces line 779): `_two_projects`; `a1` in A, `a0` (`done`) in A; `b1`, `b2` (`done`) in B; `b1` blocked by `a1` and `b2`; `b3` in B blocked only by `a0` (resolves `todo` before the forget); explicit refs `b1→a1`, `b1→b2`. `master.forget_project_by_id(A)`. After: `list_blockers_of(b1)` is `{a1, b2}` (compare as sets); `resolve_status(b1) == "blocked"`; `resolve_status(b3) == "blocked"` (was `todo`: fail closed); the refs `b1→a1`, `b1→b2` remain; no `entities` row of A remains. This is the card's named test, "forget B leaves A's card blocked". | unit | `master._forget` is the forget entry point. A unit test proves both kinds of edge survive and that a done blocker becomes blocking. | B1, B3 |
| T8 | `test_deleting_an_entity_still_removes_edges_from_other_projects` (`tests/test_master.py`, next to T7): `_two_projects`; `a1` card and `ai` open issue in A; `b1` in B blocked by `a1` and `ai`; explicit ref `b1→a1`. `entities.delete(conn, "ai")`: `list_blockers_of(b1) == ["a1"]`. `db.delete_card(conn, "a1")` (the path `core.delete_card` uses): `list_blockers_of(b1) == []`, no ref `b1→a1`, and `b1` resolves `todo` (not `blocked`). | unit | Delete and forget must differ; this keeps B6 from regressing when someone "unifies" them. | B6 |
| T9 | `test_refs_outgoing_lists_a_not_found_target_with_null_kind_and_title` (`tests/test_refs.py`): `c1` with an explicit ref and a link ref (raw `INSERT INTO refs`) to `ghost`, plus an explicit ref to existing `c2`. `refs.outgoing(conn, "c1")` returns, in `ORDER BY origin, dst_id` order: `{"id": "c2", "kind": "card", "title": ..., "origin": "explicit"}`, `{"id": "ghost", "kind": None, "title": None, "origin": "explicit"}`, `{"id": "ghost", "kind": None, "title": None, "origin": "link"}`. | unit | The reader that crashes today. Unit tier pins the dict shape exactly. | B5 |
| T10 | `test_forget_leaves_a_foreign_card_blocked_until_unblocked` (`tests/test_cli.py`, next to the cross-project scope tests): register projects A and B (two directories under `tmp_path`, `brd init` in each, `monkeypatch.chdir` between them; reuse the `foreign` fixture's setup pattern if it fits). From B: `brd add --title mine` → `mine`. From A: `brd add --title theirs` → `theirs`. From B: `brd block mine --by theirs` and `brd ref add mine theirs`. Then `brd forget --project <A id>`. From B: `brd show mine` has `status == "blocked"`, `blocked_by == [theirs]`, and `refs == [{"id": theirs, "kind": None, "title": None, "origin": "explicit"}]`. `brd next` does not list `mine`. `brd show mine --pretty` exits 0 and its output contains `not-found <theirs>`. `brd unblock mine --by theirs` exits 0 with `blocked_by == []` and `status == "todo"`. `brd next` lists `mine`. `brd ref remove mine theirs` exits 0 with `refs == []`. `brd block mine --by theirs` returns `CardNotFoundError`. | CLI | The card's named scenario ("forget B leaves A's card blocked; unblock clears it"), end to end through the commands a user runs, including the JSON and pretty output. | B1, B3, B4, B5 |

## Review focus (inputs no test above names directly)

- **The same not-found id twice, or with a cycle back.** `resolve_status` with a persisted
  loop `a → b → a` plus `a → ghost` must still end normally and return `blocked`. The
  `seen` guard must not hide the not-found blocker.
- **`brd tree` and `brd list` from the surviving project** after forget. They call
  `resolve_status` per card, so they must show `blocked` for the dependent and must not
  crash in `views` / `pretty` on the not-found id (`pretty._blocker` prints `[[None]]
  (card)` until 4.3). Exit 0 is the contract here. The wording belongs to 4.3.
- **Forgetting the project that holds the blocked card itself** (the outgoing side). Its
  `blocked_by` rows cascade away, as today. Nothing dangles.
- **Forget of a project with no incoming edges** behaves exactly as before: same output,
  same rows removed.
- **`brd ref add <src> <not-found id>`** is still refused with `EntityNotFoundError`
  [4.1 B4]. This card must not loosen any target check while it touches `refs.py`.

## Out of scope

- **Card 4.3**: the `blockers` detail array (`kind`/`project`/`title` null, `status:
  "not-found"`, `released: false`) in card detail, list items and tree nodes, and
  `--pretty` rendering a missing blocker as `not-found <id>` and a foreign one as
  `<project>: <title>`. `pretty._blocker` and `views.card_detail` are untouched here.
  `blocked_by` stays a plain id list.
- **Story S6**: consumer-contract text in `brd --help` and `brd prompt` [P §6 L239-251].
- **Phase 4 (export/import v2)**: import's project replacement keeping incoming edges,
  reconnecting not-found edges on re-import, and the "edges still not-found" count
  [P §5 L228-237]. This card only makes the ids survive so that reconnection can happen.
- Adding a not-found edge through any command. `brd block --by`, `add --blocked-by`,
  `issue open --blocks/--ref` and `ref add` keep refusing missing ids [4.1 B1-B4].
- A document as a stored blocker (unreachable through commands; resolution unchanged).
- Re-adding link refs to forgotten ids on reindex (`refs.reindex` behaviour unchanged).
- Any change to `brd delete` / `db.delete_incoming_edges` (card 2.2).

## Verification

Full suite: `uv run pytest`. No lint or typecheck is configured (`pyproject.toml` has only
pytest in the dev group).
