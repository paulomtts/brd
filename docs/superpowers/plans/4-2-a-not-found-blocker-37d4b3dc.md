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

---

# 4.2 A Not-Found Blocker Blocks; Forget Keeps Incoming Edges Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make an edge whose target id has no `entities` row (a "not-found" edge) fail closed for status resolution, make `brd forget` leave other projects' edges into the forgotten project in place, and keep every edge reader working on such edges.

**Architecture:** Three small production changes. `core.resolve_status` looks each blocker up with the global `entities.kind_of` and returns `blocked` when it is `None`. `db.delete_project` stops deleting incoming `blocked_by`/`refs` rows and only deletes the `projects` row (the FK cascade removes what the project owns). `refs._summaries` fills `{"id", "kind": None, "title": None}` for a missing target, and `pretty._ref_line` renders such an item as `not-found <id>`.

**Tech Stack:** Python 3, sqlite3, Typer (CLI), pytest. Run everything with `uv run pytest`.

**Spec:** `docs/superpowers/specs/4-2-a-not-found-blocker-37d4b3dc.md` (prepended above).

## Global Constraints

- Edge targets (`blocked_by.blocks_on_id`, `refs.dst_id`) carry no foreign key; a not-found edge is kept, never filtered.
- A `not-found` blocker blocks (fail closed, D7).
- `RELEASING` stays `{done, merged, canceled, archived}`; recursion keeps the `seen` guard.
- `brd delete` (`db.delete_incoming_edges`, `entities.delete`, `db.delete_card`) is unchanged: it still removes incoming edges.
- `brd forget` deletes only the `projects` row (cascade does the rest), still in one `with conn:` transaction; output and exit code unchanged.
- `blocked_by` stays a plain list of ids, in stored order.
- A not-found ref target is `{"id": "<dst_id>", "kind": null, "title": null, "origin": "<explicit|link>"}`, ordered `ORDER BY origin, dst_id` as today.
- `--pretty` renders a not-found ref target as `not-found <id>`.
- Do not change: `db.delete_incoming_edges`, `core.unblock_card`, `db.remove_blocked_by_edge`, `would_create_block_cycle`, `_require_blocker`, `refs.add_explicit` target check, `pretty._blocker`, `views`.
- No lint or typecheck is configured; verification is `uv run pytest`.

## Review Focus

- **A persisted cycle plus a not-found blocker** (`a → b → a`, `a → ghost`): `resolve_status` must end and return `blocked` for both. Pinned in Task 1 (`test_resolve_status_not_found_blocker_inside_a_persisted_cycle_ends_blocked`).
- **`brd list` / `brd tree` (JSON and `--pretty`) from the surviving project after forget**: exit 0, dependent shows `blocked`. Pinned in Task 3's CLI test.
- **Forgetting the project that holds the blocked card itself** (outgoing side): its own `blocked_by` rows and refs cascade away, nothing dangles. Pinned in Task 2's `test_delete_project_keeps_incoming_edges_from_other_projects` (the `a1 → b2` rows are gone).
- **Forget of a project with no incoming edges** behaves as before. Already pinned by the unchanged `tests/test_cli.py::test_forget_removes_only_the_current_projects_rows_and_backups` and `tests/test_db.py::test_delete_project_removes_the_row_and_everything_it_owns`; Task 2 runs them.
- **`brd ref add <src> <not-found id>` and `brd block <src> --by <not-found id>`** are still refused (`EntityNotFoundError` / `CardNotFoundError`). Pinned at the end of Task 3's CLI test.

## File Structure

- Modify `src/brd/core.py` — `resolve_status`: not-found blocker returns `blocked` (Task 1).
- Modify `src/brd/db.py` — `delete_project`: drop the two incoming-edge deletes, new docstring (Task 2).
- Modify `src/brd/master.py` — `_forget` docstring (Task 2).
- Modify `src/brd/refs.py` — `_summaries`: null kind/title for a not-found target (Task 3).
- Modify `src/brd/pretty.py` — `_ref_line`: `not-found <id>` (Task 3).
- Tests: `tests/test_core.py` (Task 1), `tests/test_db.py` and `tests/test_master.py` (Task 2), `tests/test_refs.py` and `tests/test_cli.py` (Task 3).

---

### Task 1: A not-found blocker blocks

**Files:**
- Modify: `src/brd/core.py:24-53` (`resolve_status`)
- Test: `tests/test_core.py` (import line 6; replace the test at line 157; add new tests right after it)

**Interfaces:**
- Consumes: `entities.kind_of(conn, id) -> str | None` (global lookup, already imported in `core.py`), `db.list_blockers_of`, `db.get_card`, `_is_released`.
- Produces: `core.resolve_status(conn, card, _seen=None) -> str` returns `"blocked"` for a `todo` card with any blocker id that has no `entities` row. Signature unchanged. Tasks 2 and 3 rely on this behaviour.

- [ ] **Step 1: Add `make_issue` to the factories import in `tests/test_core.py`**

Line 6 currently reads:

```python
from tests.factories import OTHER_PROJECT, PROJECT, add_project
```

Change it to:

```python
from tests.factories import OTHER_PROJECT, PROJECT, add_project, make_issue
```

- [ ] **Step 2: Replace the old "skips missing blocker" test with the inverted T1 and add T2–T5 plus the cycle pin**

In `tests/test_core.py`, delete this whole test (line 157):

```python
def test_resolve_status_skips_blocker_whose_card_is_missing(conn):
    db.insert_card(conn, PROJECT.id, _card("c1"))
    conn.execute("PRAGMA foreign_keys=OFF")
    db.add_blocked_by_edge(conn, "c1", "ghost")
    card = db.get_card(conn, "c1")
    assert core.resolve_status(conn, card) == "todo"
```

and put these tests in its place:

```python
def _status(conn, card_id):
    return core.resolve_status(conn, db.get_card(conn, card_id))


def test_resolve_status_blocks_on_a_blocker_that_is_not_found(conn):
    db.insert_card(conn, PROJECT.id, _card("c1"))
    db.add_blocked_by_edge(conn, "c1", "ghost")
    assert _status(conn, "c1") == "blocked"


def test_resolve_status_not_found_blocker_wins_over_released_ones(conn):
    db.insert_card(conn, PROJECT.id, _card("c1"))
    db.insert_card(conn, PROJECT.id, _card("d", status="done"))
    make_issue(conn, "i", status="closed")
    db.add_blocked_by_edge(conn, "c1", "d")
    db.add_blocked_by_edge(conn, "c1", "i")
    db.add_blocked_by_edge(conn, "c1", "ghost")
    assert _status(conn, "c1") == "blocked"

    db.remove_blocked_by_edge(conn, "c1", "ghost")
    assert _status(conn, "c1") == "todo"


def test_resolve_status_not_found_blocker_blocks_children_and_spares_non_todo(conn):
    db.insert_card(conn, PROJECT.id, _card("p"))
    db.insert_card(conn, PROJECT.id, _card("ch", parent_id="p"))
    db.add_blocked_by_edge(conn, "p", "ghost")
    assert _status(conn, "ch") == "blocked"

    db.insert_card(conn, PROJECT.id, _card("wip", status="in_progress"))
    db.add_blocked_by_edge(conn, "wip", "ghost")
    assert _status(conn, "wip") == "in_progress"

    db.insert_card(conn, PROJECT.id, _card("x", status="done"))
    db.insert_card(conn, PROJECT.id, _card("y"))
    db.add_blocked_by_edge(conn, "x", "ghost")
    db.add_blocked_by_edge(conn, "y", "x")
    assert _status(conn, "x") == "done"
    assert _status(conn, "y") == "todo"


def test_resolve_status_not_found_blocker_inside_a_persisted_cycle_ends_blocked(conn):
    db.insert_card(conn, PROJECT.id, _card("a"))
    db.insert_card(conn, PROJECT.id, _card("b"))
    db.add_blocked_by_edge(conn, "a", "b")
    db.add_blocked_by_edge(conn, "b", "a")
    db.add_blocked_by_edge(conn, "a", "ghost")
    assert _status(conn, "a") == "blocked"
    assert _status(conn, "b") == "blocked"


def test_block_cycle_check_treats_a_not_found_id_as_a_dead_end(conn):
    db.insert_card(conn, PROJECT.id, _card("a"))
    db.insert_card(conn, PROJECT.id, _card("b"))
    db.add_blocked_by_edge(conn, "a", "ghost")

    assert core.would_create_block_cycle(conn, "b", "a") is False
    assert core.would_create_block_cycle(conn, "ghost", "a") is True

    core.block_card(conn, PROJECT.id, "b", "a")
    assert db.list_blockers_of(conn, "b") == ["a"]
    assert _status(conn, "b") == "blocked"
    assert _status(conn, "a") == "blocked"


def test_unblock_card_removes_a_not_found_edge(conn):
    db.insert_card(conn, PROJECT.id, _card("c1"))
    db.add_blocked_by_edge(conn, "c1", "ghost")
    assert _status(conn, "c1") == "blocked"

    core.unblock_card(conn, PROJECT.id, "c1", "ghost")

    assert db.list_blockers_of(conn, "c1") == []
    assert _status(conn, "c1") == "todo"
```

Notes for the engineer:
- `_card(id_, status="todo", parent_id=None)` is the helper already at the top of `tests/test_core.py`.
- The old test turned foreign keys off; there is no FK on `blocks_on_id` in the current schema, so the edge inserts fine without it.
- `make_issue(conn, "i", status="closed")` creates issue `i` in `PROJECT` with `close_reason="resolved"`.

- [ ] **Step 3: Run the new tests to see them fail**

Run: `uv run pytest tests/test_core.py -k "not_found or dead_end" -v`

Expected:
- FAIL `test_resolve_status_blocks_on_a_blocker_that_is_not_found` (`assert 'todo' == 'blocked'`)
- FAIL `test_resolve_status_not_found_blocker_wins_over_released_ones` (`'todo' == 'blocked'`)
- FAIL `test_resolve_status_not_found_blocker_blocks_children_and_spares_non_todo` (`'todo' == 'blocked'` on `ch`)
- FAIL `test_block_cycle_check_treats_a_not_found_id_as_a_dead_end` (`'todo' == 'blocked'` on `a`; `b` is already blocked through `a`'s todo status, so the failing line is the last one)
- FAIL `test_unblock_card_removes_a_not_found_edge` (`'todo' == 'blocked'` before the unblock)
- PASS `test_resolve_status_not_found_blocker_inside_a_persisted_cycle_ends_blocked` (the cycle already resolves to `blocked`; this test pins that the new code keeps ending normally and is a regression guard, not a RED driver)

- [ ] **Step 4: Change `resolve_status` in `src/brd/core.py`**

Replace the blocker loop (currently lines 35-46):

```python
    for blocker_id in db.list_blockers_of(conn, card.id):
        blocker = db.get_card(conn, blocker_id)
        if blocker is None:
            # Issues block while open, whatever reason they are later closed with.
            issue = conn.execute(
                "SELECT status FROM issues WHERE id = ?", (blocker_id,)
            ).fetchone()
            if issue is not None and issue["status"] == "open":
                return "blocked"
            continue
        if not _is_released(conn, blocker, seen):
            return "blocked"
```

with:

```python
    for blocker_id in db.list_blockers_of(conn, card.id):
        kind = entities.kind_of(conn, blocker_id)
        if kind is None:
            # Not found (say its project was forgotten): brd can't tell a
            # missing blocker from an unfinished one, so it blocks.
            return "blocked"
        if kind == "issue":
            # Issues block while open, whatever reason they are later closed with.
            issue = conn.execute(
                "SELECT status FROM issues WHERE id = ?", (blocker_id,)
            ).fetchone()
            if issue["status"] == "open":
                return "blocked"
            continue
        if kind == "card" and not _is_released(conn, db.get_card(conn, blocker_id), seen):
            return "blocked"
        # A document never blocks; no command can store one as a blocker.
```

Everything else in `resolve_status` (the early return, the `seen` guard, the parent rule) stays as it is.

- [ ] **Step 5: Run the new tests to see them pass**

Run: `uv run pytest tests/test_core.py -k "not_found or dead_end" -v`
Expected: all 6 PASS.

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest`
Expected: all PASS. (No other test stores a missing blocker and expects it to be skipped; the old `tests/test_master.py::test_forgetting_a_project_removes_edges_other_projects_point_at_it` still passes here because forget still deletes the edge until Task 2.)

- [ ] **Step 7: Commit**

```bash
git add src/brd/core.py tests/test_core.py
git commit -m "Make a blocker that is not found keep its card blocked"
```

---

### Task 2: `brd forget` keeps incoming edges; `brd delete` still removes them

**Files:**
- Modify: `src/brd/db.py:550-558` (`delete_project`)
- Modify: `src/brd/master.py:176-178` (`_forget` docstring)
- Test: `tests/test_db.py:505-518` (replace `test_delete_project_removes_incoming_edges_from_other_projects`)
- Test: `tests/test_master.py:779-812` (replace `test_forgetting_a_project_removes_edges_other_projects_point_at_it`, add a delete test after it)

**Interfaces:**
- Consumes: Task 1's `core.resolve_status` (a not-found blocker gives `"blocked"`); `master.forget_project_by_id(project_id) -> Project`; `entities.delete(conn, entity_id) -> None`; `db.delete_card(conn, card_id) -> None`; test helpers `_brd()`, `_two_projects(tmp_path, monkeypatch) -> (Project, Project)` in `tests/test_master.py`, `_blocked_by_rows`, `_ref_rows`, `_add_ref`, fixture `project_conn` in `tests/test_db.py`.
- Produces: `db.delete_project(conn, project_id) -> None` that deletes only the `projects` row in one transaction. Task 3's CLI test relies on forget leaving the `blocked_by` row and the explicit ref in place.

- [ ] **Step 1: Rewrite the db-level forget test (T6)**

In `tests/test_db.py`, replace the whole of:

```python
def test_delete_project_removes_incoming_edges_from_other_projects(project_conn):
    add_project(project_conn, OTHER_PROJECT)
    make_card(project_conn, "a1")
    make_card(project_conn, "b1", project_id=OTHER_PROJECT.id)
    make_card(project_conn, "b2", project_id=OTHER_PROJECT.id)
    db.add_blocked_by_edge(project_conn, "b1", "a1")
    db.add_blocked_by_edge(project_conn, "b1", "b2")
    _add_ref(project_conn, "b1", "a1")
    _add_ref(project_conn, "b1", "b2")

    db.delete_project(project_conn, PROJECT.id)

    assert _blocked_by_rows(project_conn) == {("b1", "b2")}
    assert _ref_rows(project_conn) == {("b1", "b2")}
```

with:

```python
def test_delete_project_keeps_incoming_edges_from_other_projects(project_conn):
    add_project(project_conn, OTHER_PROJECT)
    make_card(project_conn, "a1")
    make_card(project_conn, "b1", project_id=OTHER_PROJECT.id)
    make_card(project_conn, "b2", project_id=OTHER_PROJECT.id)
    db.add_blocked_by_edge(project_conn, "b1", "a1")
    db.add_blocked_by_edge(project_conn, "b1", "b2")
    _add_ref(project_conn, "b1", "a1")
    _add_ref(project_conn, "b1", "b2")
    # Outgoing from the forgotten project: these go with it, through the cascade.
    db.add_blocked_by_edge(project_conn, "a1", "b2")
    _add_ref(project_conn, "a1", "b2")

    db.delete_project(project_conn, PROJECT.id)

    assert _blocked_by_rows(project_conn) == {("b1", "a1"), ("b1", "b2")}
    assert _ref_rows(project_conn) == {("b1", "a1"), ("b1", "b2")}
```

Leave `test_delete_project_keeps_incoming_edges_when_the_project_delete_fails` (around line 535) untouched.

- [ ] **Step 2: Rewrite the master-level forget test (T7) and add the delete test (T8)**

In `tests/test_master.py`, replace the whole of `test_forgetting_a_project_removes_edges_other_projects_point_at_it` (lines 779-812, from its `def` line through the final `conn.close()` before `test_forget_current_project_forgets_the_deepest_root_above_the_cwd`) with:

```python
def test_forgetting_a_project_keeps_edges_other_projects_point_at_it(
    tmp_path, monkeypatch
):
    project_a, project_b = _two_projects(tmp_path, monkeypatch)
    conn = _brd()
    try:
        make_card(conn, "a1", project_id=project_a.id)
        make_card(conn, "a0", status="done", project_id=project_a.id)
        make_card(conn, "b1", project_id=project_b.id)
        make_card(conn, "b2", status="done", project_id=project_b.id)
        make_card(conn, "b3", project_id=project_b.id)
        db.add_blocked_by_edge(conn, "b1", "a1")
        db.add_blocked_by_edge(conn, "b1", "b2")
        db.add_blocked_by_edge(conn, "b3", "a0")
        with conn:
            for dst in ("a1", "b2"):
                conn.execute(
                    "INSERT INTO refs (src_id, dst_id, origin) VALUES ('b1', ?, 'explicit')",
                    (dst,),
                )
        assert core.resolve_status(conn, db.get_card(conn, "b1")) == "blocked"
        assert core.resolve_status(conn, db.get_card(conn, "b3")) == "todo"
    finally:
        conn.close()

    master.forget_project_by_id(project_a.id)

    conn = _brd()
    try:
        assert set(db.list_blockers_of(conn, "b1")) == {"a1", "b2"}
        assert core.resolve_status(conn, db.get_card(conn, "b1")) == "blocked"
        # a0 was done, so b3 was ready; now a0 is not found and b3 fails closed.
        assert core.resolve_status(conn, db.get_card(conn, "b3")) == "blocked"
        assert {
            (r["src_id"], r["dst_id"]) for r in conn.execute("SELECT src_id, dst_id FROM refs")
        } == {("b1", "a1"), ("b1", "b2")}
        assert conn.execute(
            "SELECT COUNT(*) FROM entities WHERE project_id = ?", (project_a.id,)
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_deleting_an_entity_still_removes_edges_from_other_projects(tmp_path, monkeypatch):
    project_a, project_b = _two_projects(tmp_path, monkeypatch)
    conn = _brd()
    try:
        make_card(conn, "a1", project_id=project_a.id)
        make_issue(conn, "ai", project_id=project_a.id)
        make_card(conn, "b1", project_id=project_b.id)
        db.add_blocked_by_edge(conn, "b1", "a1")
        db.add_blocked_by_edge(conn, "b1", "ai")
        with conn:
            conn.execute(
                "INSERT INTO refs (src_id, dst_id, origin) VALUES ('b1', 'a1', 'explicit')"
            )

        entities.delete(conn, "ai")
        assert db.list_blockers_of(conn, "b1") == ["a1"]

        db.delete_card(conn, "a1")
        assert db.list_blockers_of(conn, "b1") == []
        assert conn.execute(
            "SELECT COUNT(*) FROM refs WHERE src_id = 'b1' AND dst_id = 'a1'"
        ).fetchone()[0] == 0
        assert core.resolve_status(conn, db.get_card(conn, "b1")) == "todo"
    finally:
        conn.close()
```

Then update the import at the top of `tests/test_master.py` (line 6) from:

```python
from brd import core, db, master, paths
```

to:

```python
from brd import core, db, entities, master, paths
```

(`make_issue` is already imported from `tests.factories` on line 9.)

- [ ] **Step 3: Run the rewritten tests to see them fail**

Run: `uv run pytest tests/test_db.py::test_delete_project_keeps_incoming_edges_from_other_projects tests/test_master.py::test_forgetting_a_project_keeps_edges_other_projects_point_at_it tests/test_master.py::test_deleting_an_entity_still_removes_edges_from_other_projects -v`

Expected:
- FAIL `test_delete_project_keeps_incoming_edges_from_other_projects` (the sets lack `("b1", "a1")`)
- FAIL `test_forgetting_a_project_keeps_edges_other_projects_point_at_it` (`{'b2'} == {'a1', 'b2'}`)
- PASS `test_deleting_an_entity_still_removes_edges_from_other_projects` (B6 is unchanged; this test guards it from regressing and is not a RED driver)

- [ ] **Step 4: Make `db.delete_project` delete only the project row**

In `src/brd/db.py`, replace:

```python
def delete_project(conn: sqlite3.Connection, project_id: str) -> None:
    """Delete the project and, through the cascade, everything it owns. Edges
    from other projects that point at its entities have no foreign key to
    cascade through, so they go explicitly, in the same transaction."""
    owned = "SELECT id FROM entities WHERE project_id = ?"
    with conn:
        conn.execute(f"DELETE FROM blocked_by WHERE blocks_on_id IN ({owned})", (project_id,))
        conn.execute(f"DELETE FROM refs WHERE dst_id IN ({owned})", (project_id,))
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
```

with:

```python
def delete_project(conn: sqlite3.Connection, project_id: str) -> None:
    """Delete the project and, through the cascade, everything it owns,
    including its outgoing edges. Edges from other projects that point at
    its entities stay: they become not-found and reconnect if the ids return."""
    with conn:
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
```

- [ ] **Step 5: Update the `_forget` docstring in `src/brd/master.py`**

Replace:

```python
    """Delete the project find returns, the edges pointing at its entities,
    and its document backups."""
```

with:

```python
    """Delete the project find returns and its document backups. Edges from
    other projects pointing at its entities are kept, as not-found."""
```

- [ ] **Step 6: Run the three tests to see them pass**

Run: `uv run pytest tests/test_db.py::test_delete_project_keeps_incoming_edges_from_other_projects tests/test_master.py::test_forgetting_a_project_keeps_edges_other_projects_point_at_it tests/test_master.py::test_deleting_an_entity_still_removes_edges_from_other_projects -v`
Expected: 3 PASS.

- [ ] **Step 7: Run the forget/delete neighbours and the whole suite**

Run: `uv run pytest tests/test_db.py -k delete_project -v`
Expected: all PASS, including `test_delete_project_keeps_incoming_edges_when_the_project_delete_fails` (the transaction still rolls back) and `test_delete_project_removes_the_row_and_everything_it_owns`.

Run: `uv run pytest`
Expected: all PASS, including `tests/test_cli.py::test_forget_removes_only_the_current_projects_rows_and_backups` (no cross-project edges there, so nothing changes for it).

- [ ] **Step 8: Commit**

```bash
git add src/brd/db.py src/brd/master.py tests/test_db.py tests/test_master.py
git commit -m "Keep other projects' edges into a forgotten project as not-found"
```

---

### Task 3: Refs readers tolerate a not-found target; end-to-end forget scenario

**Files:**
- Modify: `src/brd/refs.py:131-132` (`_summaries`)
- Modify: `src/brd/pretty.py:18-24` (`_ref_line`)
- Test: `tests/test_refs.py` (append one test)
- Test: `tests/test_cli.py` (add one test right after `test_issue_open_can_block_a_foreign_card`, around line 980)

**Interfaces:**
- Consumes: Task 1 (`resolve_status` blocks on a not-found id), Task 2 (`brd forget` keeps the incoming `blocked_by` row and ref). CLI helpers `ok(*args) -> data`, `err(*args) -> error type str`, `human(*args) -> str` (appends `--pretty`, asserts exit 0) from `tests/cli_helpers.py`; fixture `pconn` (migrated `PROJECT` database) from `tests/conftest.py`; `make_card` from `tests/factories.py`.
- Produces: `refs.outgoing(conn, entity_id) -> list[dict]` where a not-found target is `{"id": dst_id, "kind": None, "title": None, "origin": origin}`. `pretty._ref_line(label, items) -> str | None` renders such an item as `not-found <id>`.

- [ ] **Step 1: Write the failing refs unit test (T9)**

Append to `tests/test_refs.py`:

```python
GHOST = "99999999-9999-4999-8999-999999999999"


def test_refs_outgoing_lists_a_not_found_target_with_null_kind_and_title(pconn):
    make_card(pconn, A)
    make_card(pconn, B, title="Bee")
    with pconn:
        pconn.executemany(
            "INSERT INTO refs (src_id, dst_id, origin) VALUES (?, ?, ?)",
            [(A, B, "explicit"), (A, GHOST, "explicit"), (A, GHOST, "link")],
        )

    # ORDER BY origin, dst_id: "9…" sorts before "b…".
    assert refs.outgoing(pconn, A) == [
        {"id": GHOST, "kind": None, "title": None, "origin": "explicit"},
        {"id": B, "kind": "card", "title": "Bee", "origin": "explicit"},
        {"id": GHOST, "kind": None, "title": None, "origin": "link"},
    ]
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/test_refs.py::test_refs_outgoing_lists_a_not_found_target_with_null_kind_and_title -v`
Expected: FAIL with `TypeError: 'NoneType' object is not a mapping` (from `{**entities.summary(...)}` in `refs._summaries`).

- [ ] **Step 3: Fix `refs._summaries`**

In `src/brd/refs.py`, replace:

```python
def _summaries(conn: sqlite3.Connection, rows, column: str) -> list[dict]:
    return [{**entities.summary(conn, row[column]), "origin": row["origin"]} for row in rows]
```

with:

```python
def _summaries(conn: sqlite3.Connection, rows, column: str) -> list[dict]:
    # A target whose project was forgotten has no entity row: keep its id
    # and null the rest, rather than drop the ref.
    return [
        {
            **(
                entities.summary(conn, row[column])
                or {"id": row[column], "kind": None, "title": None}
            ),
            "origin": row["origin"],
        }
        for row in rows
    ]
```

- [ ] **Step 4: Run it to see it pass**

Run: `uv run pytest tests/test_refs.py -v`
Expected: all PASS.

- [ ] **Step 5: Write the failing end-to-end CLI test (T10)**

In `tests/test_cli.py`, add this test right after `test_issue_open_can_block_a_foreign_card`:

```python
def test_forget_leaves_a_foreign_card_blocked_until_unblocked(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
    monkeypatch.chdir(tmp_path / "a")
    project_a = ok("init")
    theirs = ok("add", "--title", "theirs")["id"]
    monkeypatch.chdir(tmp_path / "b")
    ok("init")
    mine = ok("add", "--title", "mine")["id"]
    ok("block", mine, "--by", theirs)
    ok("ref", "add", mine, theirs)

    ok("forget", "--project", project_a["id"])

    shown = ok("show", mine)
    assert (shown["status"], shown["blocked_by"]) == ("blocked", [theirs])
    assert shown["refs"] == [
        {"id": theirs, "kind": None, "title": None, "origin": "explicit"}
    ]
    assert mine not in [c["id"] for c in ok("next")]
    assert [(c["id"], c["status"]) for c in ok("list")] == [(mine, "blocked")]
    assert [(n["id"], n["status"]) for n in ok("tree")] == [(mine, "blocked")]
    assert f"not-found {theirs}" in human("show", mine)
    human("list")
    human("tree")

    unblocked = ok("unblock", mine, "--by", theirs)
    assert (unblocked["blocked_by"], unblocked["status"]) == ([], "todo")
    assert mine in [c["id"] for c in ok("next")]
    assert ok("ref", "remove", mine, theirs)["refs"] == []

    # Commands still refuse to add an edge to a missing id.
    assert err("block", mine, "--by", theirs) == "CardNotFoundError"
    assert err("ref", "add", mine, theirs) == "EntityNotFoundError"
```

- [ ] **Step 6: Run it to see it fail**

Run: `uv run pytest tests/test_cli.py::test_forget_leaves_a_foreign_card_blocked_until_unblocked -v`
Expected: FAIL at `assert f"not-found {theirs}" in human("show", mine)` — the pretty refs line still prints `None (None)`. (The JSON assertions before it already pass after Step 3 and Tasks 1–2.)

- [ ] **Step 7: Render a not-found ref target in `pretty._ref_line`**

In `src/brd/pretty.py`, replace:

```python
def _ref_line(label: str, items: list[dict]) -> str | None:
    seen: dict[str, dict] = {}
    for item in items:
        seen.setdefault(item["id"], item)
    if not seen:
        return None
    return f"{label}: " + ", ".join(f"{i['title']} ({i['kind']})" for i in seen.values())
```

with:

```python
def _ref_item(item: dict) -> str:
    if item["kind"] is None:
        return f"not-found {item['id']}"
    return f"{item['title']} ({item['kind']})"


def _ref_line(label: str, items: list[dict]) -> str | None:
    seen: dict[str, dict] = {}
    for item in items:
        seen.setdefault(item["id"], item)
    if not seen:
        return None
    return f"{label}: " + ", ".join(_ref_item(i) for i in seen.values())
```

- [ ] **Step 8: Run the CLI test to see it pass**

Run: `uv run pytest tests/test_cli.py::test_forget_leaves_a_foreign_card_blocked_until_unblocked -v`
Expected: PASS.

- [ ] **Step 9: Run the whole suite**

Run: `uv run pytest`
Expected: all PASS (in particular `tests/test_pretty.py`, whose existing refs lines must render unchanged for found targets).

- [ ] **Step 10: Commit**

```bash
git add src/brd/refs.py src/brd/pretty.py tests/test_refs.py tests/test_cli.py
git commit -m "Show a ref whose target is not found instead of crashing"
```

---

## Spec coverage check

| Spec item | Task |
|---|---|
| B1 not-found blocker blocks; children blocked; non-todo kept; done card with not-found blocker still releases; `blocked_by` unfiltered | Task 1 (T1, T2, T3), Task 3 (T10 `blocked_by == [theirs]`) |
| B2 cycle check dead end; resolution along a chain through ghost | Task 1 (T4) |
| B3 forget keeps incoming `blocked_by` and refs; outgoing cascade; one transaction; output unchanged | Task 2 (T6, T7, existing rollback test), Task 3 (T10) |
| B4 unblock a not-found edge; block still refused | Task 1 (T5), Task 3 (T10) |
| B5 `refs.outgoing` null shape and order; `--pretty` `not-found <id>`; `ref remove` of a not-found ref | Task 3 (T9, T10) |
| B6 delete still removes incoming edges across projects | Task 2 (T8) |
| Existing tests to invert (`test_core.py:157`, `test_db.py:505`, `test_master.py:779`) | Task 1 Step 2, Task 2 Steps 1-2 |
| Docstrings `db.delete_project`, `master._forget` | Task 2 Steps 4-5 |
| Review focus (cycle + ghost, list/tree after forget, outgoing side, no incoming edges, ref add/block still refused) | Task 1, Task 2, Task 3 as listed in Review Focus |
<!-- task-pipeline: validated -->
