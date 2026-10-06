# 4.3 Blockers detail in card output and --pretty

Card: `f6674b60-8524-43a1-8766-43e8a7cdd709`. It is the third subtask of story `43766a3a`
"Cross-project edges" (spec section 4), in milestone `6aa7043a` "Single database and
cross-project blocking". It comes after card 4.2 (`37d4b3dc`), which is merged into this
branch. Since 4.1 a blocker may belong to any project; since 4.2 a blocker may be
**not-found** (no `entities` row), and a not-found blocker blocks.

Parent design spec: `docs/superpowers/specs/2026-10-06-single-db-cross-project-blocking-design.md`.
It is in the main checkout (`/home/mtts/Code/brd/docs/...`), not in this branch's history.
Citations look like **[P §n Lx]**. Sibling specs: `4-1-blockers-and-ref-910aabf8.md`
(**[4.1 Lx]**) and `4-2-a-not-found-blocker-37d4b3dc.md` (**[4.2 Lx]**), both in
`docs/superpowers/specs/`.

## Goal

Today a card's output names its blockers only as ids (`blocked_by`). A reader cannot tell,
without more queries, which project a blocker is in, what it is called, what state it is
in, whether it still holds the card back, or whether it exists at all. And
`brd show --pretty` prints a not-found blocker as `[[None]] (card)` and a foreign blocker
as if it were on the same board.

This card adds a `blockers` array next to `blocked_by` in card detail, list items and tree
nodes, and makes `show --pretty` print foreign and not-found blockers differently from
same-project ones.

## Inherited constraints

| Constraint | Source |
|---|---|
| `blocked_by` stays a list of ids everywhere it appears today (card detail, list, tree, export) so existing consumers keep parsing it. | [P §4 L173-174] |
| Card detail, list items and tree nodes gain `blockers`: `[{id, kind, project {id, name}, title, status, released}]`. A missing target is `{id, kind: null, project: null, title: null, status: "not-found", released: false}`. | [P §4 L174-184] |
| `--pretty` renders a same-project blocker as today, a foreign one as `<project>: <title>`, and a missing one as `not-found <id>`. | [P §4 L186-187] |
| `released` follows `is_released`: not-found → `false`; issue → `status != 'open'`; card → resolves to a releasing status, or has children and every child is released (D1). `RELEASING` is `{done, merged, canceled, archived}`; recursion keeps the `seen` guard. | [P §4 L161-171], [P D1 L31], [P D7 L37] |
| A container's own stored/displayed status is unchanged by D1; only release changes. So a blocker's `status` and `released` can disagree (`todo` and `true`). | [P D1 L31] |
| Edge targets carry no foreign key; an edge whose target is not in the database is kept and reported as `not-found`. | [P D6 L36] |
| Export v2 entries carry "exactly today's v1 body plus `project`". Export is not part of this card and its card nodes must not gain `blockers`. | [P §5 L205], [P Implementation order L284] |
| `show` is global; edge targets cross projects. | [P D3 L33] |
| Help text and `brd prompt` contract text that mention `blockers` belong to S6. | [P §6 L239-248], card description |
| 4.2 left the `blockers` array, with the `null` convention for not-found, to this card. | [4.2 L170], [4.2 L274] |

## Behaviour

### B1. The `blockers` array

Every card object that has `blocked_by` today also has `blockers`, except export (B4).
That is:

- card detail returned by `show <card>`, `add`, `update`, `block`, `unblock`;
- each item of `list` and `next`;
- each node of `tree` at every depth (whole board and `tree <id>`).

`blockers` has one entry per id in `blocked_by`, **in the same order**. `blocked_by` is
unchanged: still a list of id strings.

Each entry has exactly these keys: `id`, `kind`, `project`, `title`, `status`, `released`.

| Target | `kind` | `project` | `title` | `status` | `released` |
|---|---|---|---|---|---|
| card (any project) | `"card"` | `{"id", "name"}` of the owning project | card title | the card's **resolved** status (`resolve_status`, so `blocked` is possible) | `true` if it resolves to `done`/`merged`/`canceled`/`archived`, or it has children and every child is released (D1); else `false` |
| issue (any project) | `"issue"` | `{"id", "name"}` of the owning project | issue title | `"open"` or `"closed"` | `status != "open"` |
| document (only reachable through an imported snapshot; no command stores one) | `"document"` | `{"id", "name"}` of the owning project | document title | `null` | `true` (a document never blocks, `src/brd/core.py:51`) |
| not found | `null` | `null` | `null` | `"not-found"` | `false` |

`project` is filled for same-project blockers too, not only foreign ones.

`released` must agree with the card's own status: a `todo` card whose every blocker has
`released: true` (and whose parent is not blocked) resolves `todo`; a `todo` card with any
`released: false` blocker resolves `blocked`. In particular a container blocker whose
children are all released shows `status: "todo"` (its own status, unchanged) and
`released: true`.

Each entry is computed fresh (its own `seen` set), so a blocker in a stored cycle still
yields an entry instead of recursing forever.

### B2. `show --pretty` blocker line

The `blocked by:` line of a card in `show --pretty` is built from `blockers`, one item per
entry, in order, joined by `, ` (as today). "Same project" means the blocker's project id
equals the id of the project that **owns the shown card** (the `project` key `show`
already returns), not the cwd's project, and is compared by id, never by name.

| Blocker | Rendered as |
|---|---|
| same-project card | `[[<title>]] (card)` (unchanged) |
| same-project issue | `[[<title>]] (issue, <status>)` (unchanged) |
| same-project document | `[[<title>]] (card)` is today's text; keep today's behaviour (unreachable through commands) |
| foreign card, issue or document | `<project name>: <title>` |
| not found | `not-found <id>` |

Example, card in project `brd` blocked by a local card `Lexer`, a card `Foreign` of
project `other`, and a forgotten id `ghost`:

```
blocked by: [[Lexer]] (card), other: Foreign, not-found ghost
```

The line is absent when `blockers` is empty (unchanged). No other `--pretty` output
changes: `list --pretty`, `next --pretty` and `tree --pretty` print no blockers today and
still print none. `add`/`update`/`block`/`unblock` have no pretty renderer of their own
today and get none here.

### B3. No new errors

No command gains a failure mode. A not-found or foreign blocker never makes `show`,
`list`, `next`, `tree` or the mutating commands fail. Exit codes and error envelopes are
unchanged.

### B4. Export and tree import are unchanged

- `brd export` card nodes (`cards` and their nested `children`) have no `blockers` key.
  Today export builds its cards with `core.build_tree` (`src/brd/snapshot.py:15`), the
  same function `brd tree` uses, so adding the key to tree nodes must not leak it into
  export.
- A `brd tree` output, which now carries `blockers`, still imports as a legacy tree
  snapshot: import ignores the key (`blockers` is derived, not stored).

## Existing tests this changes

- `tests/test_cli.py::test_show_pretty_renders_a_foreign_blocker` pins
  `"blocked by: [[Foreign]] (card)"` (commit `faafde0`). B2 changes that line to
  `"blocked by: other: Foreign"`; the test is updated, not deleted.
- `tests/test_snapshot.py::test_round_trip_into_fresh_project` compares `show` output
  before and after importing into another project, popping only the top-level `project`.
  The child card there is blocked by issue `Q`, so its `blockers[0].project` differs
  between the two boards exactly like the top-level `project` does. The test must also
  drop or normalise `project` inside each `blockers` entry; everything else in
  `blockers` must still match.
- `tests/test_core.py::test_import_tree_round_trips_a_whole_board` compares two
  `build_tree` results by equality; both boards use the same `PROJECT`, so it keeps
  passing unchanged and now also proves `blockers` survive a tree round trip.

## Interfaces handed to the planner

- `core.blockers_of(conn, card_id) -> list[dict]` (new, public, in `src/brd/core.py`
  next to `_is_released`): the B1 entries in `db.list_blockers_of` order. It lives in
  `core` because `views` imports `core`, and `core._build_node` needs it too. It reuses
  `resolve_status` and `_is_released` (fresh `seen`) rather than restating the rules, and
  `db.owner_of` for `project`.
- `views.card_detail` and `core._build_node` call `blockers_of` once and derive
  `blocked_by` from the same list, so the order cannot drift.
- `snapshot.export` keeps its v1 card-node shape (no `blockers`), however the planner
  chooses to achieve it.
- `pretty.render_detail` reads `data["blockers"]` and `data["project"]["id"]`; the
  re-querying `pretty._blocker` goes away or becomes a pure function of one entry.

## Tests

| # | Test | Tier | Why this tier | Proves |
|---|---|---|---|---|
| T1 | `test_blockers_of_a_same_project_card` (`tests/test_core.py`): `c` blocked by `b` (todo). `core.blockers_of(conn, c.id) == [{"id": b.id, "kind": "card", "project": {"id": PROJECT.id, "name": PROJECT.name}, "title": "B", "status": "todo", "released": False}]`. Then `b` set `done`: entry has `status "done"`, `released True`. | unit | The shape and the release rule with no CLI noise. | B1 |
| T2 | `test_blockers_of_a_container_whose_children_finished`: blocker `s` (todo) with children all `done`. Entry: `status "todo"`, `released True`; and `resolve_status(c) == "todo"`. | unit | Pins that `status` and `released` diverge for D1 containers. | B1 |
| T3 | `test_blockers_of_a_blocked_card`: `c` blocked by `b`, `b` blocked by open issue `i`. `c`'s entry for `b` has `status "blocked"`, `released False`. | unit | `status` is the resolved status, not the stored one. | B1 |
| T4 | `test_blockers_of_issues`: `c` blocked by open issue `i1` and closed issue `i2`. Entries in `list_blockers_of` order: `i1` → `kind "issue"`, `status "open"`, `released False`; `i2` → `"closed"`, `True`. | unit | Issue branch of the rule. | B1 |
| T5 | `test_blockers_of_a_not_found_id`: `c` with a raw edge to `"ghost"` (`db.add_blocked_by_edge`). Entry `== {"id": "ghost", "kind": None, "project": None, "title": None, "status": "not-found", "released": False}`. | unit | The not-found convention, exact keys. | B1 |
| T6 | `test_blockers_of_a_foreign_card` (`tests/test_core.py`, two projects via `tests/factories.py` `OTHER_PROJECT`): entry's `project == {"id": OTHER_PROJECT.id, "name": OTHER_PROJECT.name}`. | unit | Project comes from the blocker's owner, not the source's. | B1 |
| T7 | `test_blockers_of_a_document`: raw edge to a document. Entry `kind "document"`, `status None`, `released True`, and the card resolves `todo`. | unit | Import can store such an edge; `released` must match `resolve_status`. | B1 |
| T8 | `test_blockers_of_a_stored_cycle_terminates`: raw edges `a→b`, `b→a`. `blockers_of(a)` returns one entry for `b` without recursion error. | unit | Fresh `seen` guard. | B1 |
| T9 | `test_build_tree_nodes_carry_blockers`: parent with child blocked by `x` and by `"ghost"`; `build_tree` child node has `blocked_by == [ids…]` and `blockers` equal to `core.blockers_of(child)`, same order as `blocked_by`; root node has `blockers == []`. | unit | Tree nodes, nested depth. | B1 |
| T10 | `test_cli_card_outputs_carry_foreign_blockers` (`tests/test_cli.py`, `foreign_entities`): `mine` blocked by `FOREIGN` and `FOREIGN_ISSUE`. `block`'s output, `show`, the `list` item and the `tree` node each have `blockers` with `project == {"id": OTHER_PROJECT.id, "name": "other"}`, titles `"Foreign"` / `"Foreign issue"`, statuses `"todo"` / `"open"`, `released False`, in `blocked_by` order; `blocked_by` is still a list of strings. `add --blocked-by FOREIGN` output and a `next` item for an unblocked card (`blockers == []`) carry the key too. | CLI | The key must reach every command output listed in B1; only the CLI wiring proves that. | B1 |
| T11 | Extend `test_forget_leaves_a_foreign_card_blocked_until_unblocked` (`tests/test_cli.py`): after `forget`, `show`'s `blockers`, the `list` item's and the `tree` node's all equal `[{"id": theirs, "kind": None, "project": None, "title": None, "status": "not-found", "released": False}]`; `human("show", mine)` contains `f"blocked by: not-found {theirs}"`. | CLI | The real way a not-found blocker arises (forget). | B1, B2, B3 |
| T12 | Update `test_show_pretty_renders_a_foreign_blocker` (`foreign`): `"blocked by: other: Foreign" in human("show", mine)`; and add a separate test on `foreign_entities` (the `foreign` fixture has no foreign issue) rendering `other: Foreign issue`. | CLI | Pretty output is only observable through the CLI renderer. | B2 |
| T13 | `test_show_pretty_mixed_blockers_keep_order` (`tests/test_cli.py`, `foreign`): `mine` blocked by local card `Lexer`, `FOREIGN`, and raw edge `"ghost"` (seeded via `db.connect(paths.brd_db_path())` like the `foreign` fixture). The pretty line equals `"blocked by: " + ", ".join(...)` of `[[Lexer]] (card)`, `other: Foreign`, `not-found ghost` in `blocked_by` order (read `blocked_by` from JSON `show` to build the expected line). | CLI | Join, order and all three forms in one line. | B2 |
| T14 | `test_show_pretty_of_a_foreign_card_treats_its_own_project_as_local` (`tests/test_cli.py`, `foreign`): seed a second card `F2` in `OTHER_PROJECT` blocked by `FOREIGN`; from the current project, `human("show", F2)` contains `"blocked by: [[Foreign]] (card)"` (no `other: ` prefix). | CLI | "Same project" is the shown card's owner, not the cwd. | B2 |
| T15 | `test_show_pretty_same_project_blockers_unchanged`: existing `tests/test_pretty.py::test_show_card_blocked_by_issue` stays; add a local card blocker case expecting `"blocked by: [[A]] (card)"`. | CLI | Regression guard on "as today". | B2 |
| T16 | `test_export_card_nodes_have_no_blockers` (`tests/test_snapshot.py`, `populated`): `ok("export")`; no node in `cards` or any nested `children` has a `blockers` key; `blocked_by` still present. | CLI | Export is a CLI contract; the leak is through shared `build_tree`. | B4 |
| T17 | Existing `test_old_tree_snapshot_still_imports` (`tests/test_snapshot.py`) now feeds a tree output carrying `blockers`; it must still pass unchanged. Add an assertion that the fed `tree` JSON does contain `blockers`, so the test keeps meaning that. | CLI | Proves import ignores the derived key. | B4 |
| T18 | Update `test_round_trip_into_fresh_project` as described above (normalise `blockers[*].project`). | CLI | Keeps the round-trip guarantee honest with the new key. | B1, B4 |

`uv run pytest` (whole suite) must pass. No typecheck or linter is configured.

## Out of scope

- Help text and `brd prompt` contract text describing `blockers` (S6) [P §6 L239-248].
- Export/import v2 and any change to the export or snapshot format (S5 / phase 4)
  [P §5, P Implementation order L284]. This card only keeps export unchanged.
- An issue's `blocks` list and its `--pretty` `blocks:` line: issues are not cards and
  have no `blockers` [P §4 L174-175 names card detail, list items and tree nodes only].
- Blockers in `list --pretty`, `next --pretty` or `tree --pretty`.
- Not-found resolution, `forget` keeping edges, `unblock` of a not-found edge (done in 4.2).
- Lifting same-project checks on edge targets (done in 4.1).
- Any change to `resolve_status` / release rules (phase 1 and 4.2).

## Review focus (for the planner)

1. Same-project vs foreign compared by **project id**, against the shown card's owner: two
   projects may share a name, and `show` of another project's card must treat that
   project as local (T14).
2. `blocked_by` and `blockers` in the same order, from one read (T9, T13).
3. Export must not gain `blockers` through the shared `build_tree` (T16).
4. A blocker in a stored cycle, or a deep container chain, must not crash or recurse
   forever when computing `released` (T8).
5. A document blocker (import-only) must not crash the detail or the pretty line (T7).
