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

---

# 4.3 Blockers Detail in Card Output and --pretty Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every card object that carries `blocked_by` (except export) also carries a `blockers` array describing each blocker's kind, project, title, status and whether it is released, and `show --pretty` renders foreign and not-found blockers distinctly.

**Architecture:** One new public function, `core.blockers_of(conn, card_id)`, builds the entries from `db.list_blockers_of` using the existing `resolve_status` / `_is_released` rules. `views.card_detail` and `core._build_node` call it once and derive `blocked_by` from its ids. `core.build_tree` gains a `with_blockers` keyword that `snapshot.export` turns off, so export keeps its v1 shape. `pretty.render_detail` renders the `blocked by:` line from `data["blockers"]` and `data["project"]["id"]` with no further queries.

**Tech Stack:** Python 3, sqlite3, Typer CLI, pytest (run through `uv run pytest`).

**Spec:** `docs/superpowers/specs/4-3-blockers-detail-in-f6674b60.md` (prepended above).

## Global Constraints

- `blocked_by` stays a list of id strings everywhere it appears today (card detail, list, tree, export).
- `blockers` entry keys are exactly `id`, `kind`, `project`, `title`, `status`, `released`; `project` is `{"id", "name"}`.
- A missing target is `{"id": <id>, "kind": None, "project": None, "title": None, "status": "not-found", "released": False}`.
- `blockers` has one entry per `blocked_by` id, in the same order.
- `released`: not-found → `False`; issue → `status != "open"`; card → `_is_released` (resolves to `done`/`merged`/`canceled`/`archived`, or has children and every child is released); document → `True`.
- A card blocker's `status` is its **resolved** status (`resolve_status`), so `blocked` is possible and a released container may still show `todo`.
- `--pretty` blocker forms: same-project card `[[<title>]] (card)`, same-project issue `[[<title>]] (issue, <status>)`, foreign anything `<project name>: <title>`, not found `not-found <id>`.
- "Same project" = blocker project **id** equals the shown card's owning project id (`data["project"]["id"]`), never the cwd project, never by name.
- `brd export` card nodes (and nested `children`) have no `blockers` key.
- No command gains an error, exit code or envelope change. No help text or `brd prompt` change (that is S6).
- `uv run pytest` (whole suite) must pass. No typecheck or linter is configured.

## Review Focus

1. Two projects with the **same name**: a blocker from the other one must still render as `<name>: <title>`, because sameness is by id (test in Task 3: `test_show_pretty_tells_a_same_named_project_apart_by_id`).
2. A **document** blocker (only reachable through an imported snapshot) in another project must not crash `show` or `show --pretty`, must report `status None, released True`, and must leave the card `todo` (test in Task 3: `test_a_foreign_document_blocker_renders_and_never_blocks`).
3. A **multi-level container** blocker (milestone → story → subtask): `released` must flip exactly when the deepest unfinished child appears, while the milestone's `status` stays `todo` (test in Task 1: `test_blockers_of_a_milestone_whose_stories_released`).
4. A **finished foreign card** blocker: `released True`, the card resolves `todo` and shows in `next` (test in Task 2: `test_a_finished_foreign_blocker_is_released`).
5. A `show --pretty` of **another project's card** blocked by a card in the cwd project must label the cwd project's card as foreign (`<cwd name>: <title>`), not local (test in Task 3: `test_show_pretty_of_a_foreign_card_treats_its_own_project_as_local`).

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/brd/core.py` | Modify | Add `blockers_of` + `_blocker_entry` after `_is_released`; `_build_node` / `build_tree` gain `with_blockers` and emit `blockers`. |
| `src/brd/views.py` | Modify | `card_detail` emits `blockers` and derives `blocked_by` from it. |
| `src/brd/snapshot.py` | Modify | `export` calls `build_tree(..., with_blockers=False)`. |
| `src/brd/pretty.py` | Modify | `_blocker` becomes a pure function of one entry and the owner id; `render_detail` reads `data["blockers"]`. |
| `tests/test_core.py` | Modify | Unit tests for `blockers_of` and tree nodes. |
| `tests/test_cli.py` | Modify | CLI wiring tests, pretty tests, updated foreign/forget tests. |
| `tests/test_snapshot.py` | Modify | Export guard, tree-import guard, round-trip normalisation. |
| `tests/test_pretty.py` | Modify | Same-project card blocker regression guard. |

---

### Task 1: `core.blockers_of`

**Files:**
- Modify: `src/brd/core.py` (insert after `_is_released`, currently ending at line 73)
- Test: `tests/test_core.py` (import line 6; append tests at end of file)

**Interfaces:**
- Consumes: existing `core.resolve_status(conn, card, _seen=None) -> str`, `core._is_released(conn, card, seen) -> bool`, `db.list_blockers_of(conn, card_id) -> list[str]`, `db.get_card(conn, id) -> Card | None`, `db.owner_of(conn, id) -> Project | None`, `entities.kind_of(conn, id) -> str | None`, `entities.title_of(conn, id) -> str | None`.
- Produces: `core.blockers_of(conn: sqlite3.Connection, card_id: str) -> list[dict]` — entries `{"id": str, "kind": "card"|"issue"|"document"|None, "project": {"id": str, "name": str}|None, "title": str|None, "status": str|None, "released": bool}` in `db.list_blockers_of` order.

- [ ] **Step 1: Write the failing tests**

In `tests/test_core.py`, change line 6 from

```python
from tests.factories import OTHER_PROJECT, PROJECT, add_project, make_issue
```

to

```python
from tests.factories import OTHER_PROJECT, PROJECT, add_project, make_document, make_issue
```

Then append at the end of `tests/test_core.py` (the helpers `_card`, `_story_with_children` and `_blocked_on` already exist in this file; `_card` sets `title` equal to the id):

```python
def _entry(id_, kind, title, status, released, project=PROJECT):
    return {
        "id": id_,
        "kind": kind,
        "project": {"id": project.id, "name": project.name},
        "title": title,
        "status": status,
        "released": released,
    }


def test_blockers_of_a_same_project_card(conn):
    db.insert_card(conn, PROJECT.id, _card("b"))
    _blocked_on(conn, "c", "b")
    assert core.blockers_of(conn, "c") == [_entry("b", "card", "b", "todo", False)]

    db.update_card_fields(conn, "b", status="done")
    assert core.blockers_of(conn, "c") == [_entry("b", "card", "b", "done", True)]


def test_blockers_of_a_container_whose_children_finished(conn):
    _story_with_children(conn, "s", ["done", "merged"])
    dependent = _blocked_on(conn, "c", "s")
    # Its own status stays todo; only release changes (D1).
    assert core.blockers_of(conn, "c") == [_entry("s", "card", "s", "todo", True)]
    assert core.resolve_status(conn, dependent) == "todo"


def test_blockers_of_a_milestone_whose_stories_released(conn):
    db.insert_card(conn, PROJECT.id, _card("m"))
    db.insert_card(conn, PROJECT.id, _card("s", parent_id="m"))
    db.insert_card(conn, PROJECT.id, _card("s-c0", status="done", parent_id="s"))
    db.insert_card(conn, PROJECT.id, _card("s2", status="canceled", parent_id="m"))
    dependent = _blocked_on(conn, "c", "m")
    assert core.blockers_of(conn, "c") == [_entry("m", "card", "m", "todo", True)]
    assert core.resolve_status(conn, dependent) == "todo"

    db.insert_card(conn, PROJECT.id, _card("s-c1", parent_id="s"))
    assert core.blockers_of(conn, "c") == [_entry("m", "card", "m", "todo", False)]
    assert core.resolve_status(conn, dependent) == "blocked"


def test_blockers_of_a_blocked_card(conn):
    make_issue(conn, "i")
    _blocked_on(conn, "b", "i")
    _blocked_on(conn, "c", "b")
    # The resolved status, not the stored todo.
    assert core.blockers_of(conn, "c") == [_entry("b", "card", "b", "blocked", False)]


def test_blockers_of_issues(conn):
    make_issue(conn, "i1", title="Open one")
    make_issue(conn, "i2", title="Closed one", status="closed")
    _blocked_on(conn, "c", "i1")
    db.add_blocked_by_edge(conn, "c", "i2")
    expected = {
        "i1": _entry("i1", "issue", "Open one", "open", False),
        "i2": _entry("i2", "issue", "Closed one", "closed", True),
    }
    blocked_by = db.list_blockers_of(conn, "c")
    assert sorted(blocked_by) == ["i1", "i2"]
    assert core.blockers_of(conn, "c") == [expected[i] for i in blocked_by]


def test_blockers_of_a_not_found_id(conn):
    _blocked_on(conn, "c", "ghost")
    assert core.blockers_of(conn, "c") == [
        {
            "id": "ghost",
            "kind": None,
            "project": None,
            "title": None,
            "status": "not-found",
            "released": False,
        }
    ]


def test_blockers_of_a_foreign_card(conn):
    add_project(conn, OTHER_PROJECT)
    db.insert_card(conn, OTHER_PROJECT.id, _card("f"))
    _blocked_on(conn, "c", "f")
    assert core.blockers_of(conn, "c") == [
        _entry("f", "card", "f", "todo", False, project=OTHER_PROJECT)
    ]


def test_blockers_of_a_document(conn):
    # Only an imported snapshot can store this edge; a document never blocks.
    make_document(conn, "d", "notes", title="Notes")
    dependent = _blocked_on(conn, "c", "d")
    assert core.blockers_of(conn, "c") == [_entry("d", "document", "Notes", None, True)]
    assert core.resolve_status(conn, dependent) == "todo"


def test_blockers_of_a_stored_cycle_terminates(conn):
    db.insert_card(conn, PROJECT.id, _card("a"))
    _blocked_on(conn, "b", "a")
    db.add_blocked_by_edge(conn, "a", "b")
    assert core.blockers_of(conn, "a") == [_entry("b", "card", "b", "blocked", False)]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_core.py -k blockers_of -v`
Expected: 9 tests FAIL with `AttributeError: module 'brd.core' has no attribute 'blockers_of'`.

- [ ] **Step 3: Write the implementation**

In `src/brd/core.py`, insert directly after the end of `_is_released` (after the line `return bool(children) and all(_is_released(conn, child, seen) for child in children)`) and before `def would_create_parent_cycle`:

```python
def blockers_of(conn: sqlite3.Connection, card_id: str) -> list[dict]:
    # Each blocker in blocked_by order, with what a reader needs to judge it
    # without another query. `released` is the rule resolve_status applies,
    # so a container can show `todo` and still be released.
    return [_blocker_entry(conn, blocker_id) for blocker_id in db.list_blockers_of(conn, card_id)]


def _blocker_entry(conn: sqlite3.Connection, blocker_id: str) -> dict:
    kind = entities.kind_of(conn, blocker_id)
    if kind is None:
        # Not found: it blocks, and there is nothing else to say about it.
        return {
            "id": blocker_id,
            "kind": None,
            "project": None,
            "title": None,
            "status": "not-found",
            "released": False,
        }
    if kind == "card":
        card = db.get_card(conn, blocker_id)
        status: str | None = resolve_status(conn, card)
        # A fresh seen set: each entry is computed on its own.
        released = _is_released(conn, card, set())
    elif kind == "issue":
        status = conn.execute(
            "SELECT status FROM issues WHERE id = ?", (blocker_id,)
        ).fetchone()["status"]
        released = status != "open"
    else:
        # A document never blocks; only an imported snapshot can store one.
        status, released = None, True
    owner = db.owner_of(conn, blocker_id)
    return {
        "id": blocker_id,
        "kind": kind,
        "project": {"id": owner.id, "name": owner.name},
        "title": entities.title_of(conn, blocker_id),
        "status": status,
        "released": released,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_core.py -v`
Expected: all PASS (the 9 new tests and every existing one).

- [ ] **Step 5: Commit**

```bash
git add src/brd/core.py tests/test_core.py
git commit -m "Describe each blocker of a card: project, title, status, released"
```

---

### Task 2: `blockers` in card detail, list, next and tree; export unchanged

**Files:**
- Modify: `src/brd/core.py` (`_build_node` and `build_tree`, currently lines ~305-326 before Task 1's insert)
- Modify: `src/brd/views.py:21-35` (`card_detail`)
- Modify: `src/brd/snapshot.py:15` (`export`)
- Test: `tests/test_core.py` (append), `tests/test_cli.py` (after `test_show_pretty_renders_a_foreign_blocker`, and inside `test_forget_leaves_a_foreign_card_blocked_until_unblocked`), `tests/test_snapshot.py` (`test_round_trip_into_fresh_project`, `test_old_tree_snapshot_still_imports`, new test)

**Interfaces:**
- Consumes: `core.blockers_of(conn, card_id) -> list[dict]` from Task 1.
- Produces:
  - `core.build_tree(conn, project_id, root_id=None, with_blockers: bool = True) -> list[dict]`; each node has `blocked_by: list[str]` and, when `with_blockers`, `blockers: list[dict]` (same entries as `blockers_of`), at every depth.
  - `views.card_detail(conn, card) -> dict` now has `blockers` right after `blocked_by`.
  - `snapshot.export` card nodes: unchanged v1 shape (no `blockers`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_core.py`:

```python
def test_build_tree_nodes_carry_blockers(conn):
    parent = core.create_card(conn, PROJECT.id, title="Parent")
    blocker = core.create_card(conn, PROJECT.id, title="Blocker")
    child = core.create_card(
        conn, PROJECT.id, title="Child", parent_id=parent.id, blocked_by=[blocker.id]
    )
    db.add_blocked_by_edge(conn, child.id, "ghost")

    (root,) = core.build_tree(conn, PROJECT.id, root_id=parent.id)
    (child_node,) = root["children"]
    assert root["blocked_by"] == [] and root["blockers"] == []
    assert sorted(child_node["blocked_by"]) == sorted([blocker.id, "ghost"])
    assert child_node["blockers"] == core.blockers_of(conn, child.id)
    assert [b["id"] for b in child_node["blockers"]] == child_node["blocked_by"]
    assert {b["id"]: b["status"] for b in child_node["blockers"]} == {
        blocker.id: "todo",
        "ghost": "not-found",
    }


def test_build_tree_without_blockers_keeps_the_v1_node_shape(conn):
    parent = core.create_card(conn, PROJECT.id, title="Parent")
    blocker = core.create_card(conn, PROJECT.id, title="Blocker")
    core.create_card(conn, PROJECT.id, title="Child", parent_id=parent.id, blocked_by=[blocker.id])

    (root,) = core.build_tree(conn, PROJECT.id, root_id=parent.id, with_blockers=False)
    (child_node,) = root["children"]
    assert "blockers" not in root and "blockers" not in child_node
    assert child_node["blocked_by"] == [blocker.id]
```

In `tests/test_cli.py`, insert right after `test_show_pretty_renders_a_foreign_blocker` (which ends with `assert "blocked by: [[Foreign]] (card)" in human("show", mine)`):

```python
def _blocker_entry(id_, kind, title, status, released, project=OTHER_PROJECT):
    return {
        "id": id_,
        "kind": kind,
        "project": {"id": project.id, "name": project.name},
        "title": title,
        "status": status,
        "released": released,
    }


def test_card_outputs_carry_foreign_blockers(foreign_entities):
    expected = {
        FOREIGN: _blocker_entry(FOREIGN, "card", "Foreign", "todo", False),
        FOREIGN_ISSUE: _blocker_entry(FOREIGN_ISSUE, "issue", "Foreign issue", "open", False),
    }
    mine = ok("add", "--title", "mine")["id"]
    ok("block", mine, "--by", FOREIGN)
    blocked = ok("block", mine, "--by", FOREIGN_ISSUE)
    (listed,) = [c for c in ok("list") if c["id"] == mine]
    (node,) = [n for n in ok("tree") if n["id"] == mine]
    for card in (blocked, ok("show", mine), listed, node):
        # blocked_by is still the plain list of ids; blockers follows its order.
        assert sorted(card["blocked_by"]) == sorted([FOREIGN, FOREIGN_ISSUE])
        assert card["blockers"] == [expected[b] for b in card["blocked_by"]]

    added = ok("add", "--title", "t", "--blocked-by", FOREIGN)
    assert (added["blocked_by"], added["blockers"]) == ([FOREIGN], [expected[FOREIGN]])
    assert ok("update", added["id"], "--title", "t2")["blockers"] == [expected[FOREIGN]]
    unblocked = ok("unblock", mine, "--by", FOREIGN)
    assert (unblocked["blocked_by"], unblocked["blockers"]) == (
        [FOREIGN_ISSUE],
        [expected[FOREIGN_ISSUE]],
    )
    free = ok("add", "--title", "free")["id"]
    assert [c["blockers"] for c in ok("next") if c["id"] == free] == [[]]


def test_a_finished_foreign_blocker_is_released(foreign):
    mine = ok("add", "--title", "mine", "--blocked-by", foreign)["id"]
    conn = db.connect(paths.brd_db_path())
    try:
        conn.execute("UPDATE cards SET status = 'done' WHERE id = ?", (foreign,))
        conn.commit()
    finally:
        conn.close()

    shown = ok("show", mine)
    assert shown["status"] == "todo"
    assert shown["blockers"] == [_blocker_entry(foreign, "card", "Foreign", "done", True)]
    assert mine in [c["id"] for c in ok("next")]
```

In `tests/test_cli.py`, inside `test_forget_leaves_a_foreign_card_blocked_until_unblocked`, right after the line

```python
    assert [(n["id"], n["status"]) for n in ok("tree")] == [(mine, "blocked")]
```

insert:

```python
    gone = [
        {
            "id": theirs,
            "kind": None,
            "project": None,
            "title": None,
            "status": "not-found",
            "released": False,
        }
    ]
    assert shown["blockers"] == gone
    assert [c["blockers"] for c in ok("list")] == [gone]
    assert [n["blockers"] for n in ok("tree")] == [gone]
```

In `tests/test_snapshot.py`, inside `test_round_trip_into_fresh_project`, replace

```python
    for data in (before, after):
        for shown in data.values():
            shown.pop("project")
    assert before == after
```

with

```python
    # So does each blocker's; here every blocker is on its card's own board.
    child_id = populated["child"]["id"]
    assert [b["id"] for b in before[child_id]["blockers"]] == [populated["issue"]["id"]]
    for data in (before, after):
        for shown in data.values():
            for blocker in shown.get("blockers", []):
                assert blocker.pop("project") == shown["project"]
            shown.pop("project")
    assert before == after
```

In `tests/test_snapshot.py`, replace the body of `test_old_tree_snapshot_still_imports` with:

```python
def test_old_tree_snapshot_still_imports(project, tmp_path, monkeypatch):
    a = ok("add", "--title", "A")
    ok("add", "--title", "B", "--blocked-by", a["id"])
    tree = ok("tree")
    # The tree output carries the derived `blockers`; import must ignore it.
    assert any(node["blockers"] for node in tree)
    snapshot = tmp_path / "tree.json"
    snapshot.write_text(json.dumps({"ok": True, "data": tree}))
    other = _fresh_project(tmp_path, monkeypatch)
    assert ok("import", snapshot) == {"imported": 2}
    assert err("import", snapshot) == "CardAlreadyExistsError"
```

Append to `tests/test_snapshot.py`:

```python
def _card_nodes(nodes):
    for node in nodes:
        yield node
        yield from _card_nodes(node["children"])


def test_export_card_nodes_have_no_blockers(populated):
    nodes = list(_card_nodes(ok("export")["cards"]))
    assert {n["id"] for n in nodes} == {populated["card"]["id"], populated["child"]["id"]}
    assert all("blockers" not in n and "blocked_by" in n for n in nodes)
    (child,) = [n for n in nodes if n["id"] == populated["child"]["id"]]
    assert child["blocked_by"] == [populated["issue"]["id"]]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_core.py tests/test_cli.py tests/test_snapshot.py -v -k "build_tree_nodes_carry_blockers or without_blockers or card_outputs_carry or finished_foreign or forget_leaves_a_foreign or round_trip_into_fresh or old_tree_snapshot_still or export_card_nodes"`
Expected:
- FAIL with `KeyError: 'blockers'`: `test_build_tree_nodes_carry_blockers`, `test_card_outputs_carry_foreign_blockers`, `test_a_finished_foreign_blocker_is_released`, `test_forget_leaves_a_foreign_card_blocked_until_unblocked`, `test_round_trip_into_fresh_project`, `test_old_tree_snapshot_still_imports`.
- FAIL with `TypeError: build_tree() got an unexpected keyword argument 'with_blockers'`: `test_build_tree_without_blockers_keeps_the_v1_node_shape`.
- PASS (guard, must still pass after Step 3): `test_export_card_nodes_have_no_blockers`.

- [ ] **Step 3: Write the implementation**

In `src/brd/core.py`, replace `_build_node` and `build_tree`:

```python
def _build_node(conn: sqlite3.Connection, card: Card) -> dict:
    return {
        "id": card.id,
        "title": card.title,
        "description": card.description,
        "status": resolve_status(conn, card),
        "blocked_by": db.list_blockers_of(conn, card.id),
        "created_at": card.created_at,
        "updated_at": card.updated_at,
        "children": [
            _build_node(conn, child) for child in db.list_children(conn, card.id)
        ],
    }


def build_tree(
    conn: sqlite3.Connection, project_id: str, root_id: str | None = None
) -> list[dict]:
    if root_id is not None:
        card = require_card(conn, project_id, root_id)
        return [_build_node(conn, card)]

    top_level = db.list_cards(conn, project_id, parent_id=None)
    return [_build_node(conn, card) for card in top_level]
```

with:

```python
def _build_node(conn: sqlite3.Connection, card: Card, with_blockers: bool) -> dict:
    node = {
        "id": card.id,
        "title": card.title,
        "description": card.description,
        "status": resolve_status(conn, card),
    }
    if with_blockers:
        # One read, so blocked_by and blockers keep the same order.
        blockers = blockers_of(conn, card.id)
        node["blocked_by"] = [blocker["id"] for blocker in blockers]
        node["blockers"] = blockers
    else:
        node["blocked_by"] = db.list_blockers_of(conn, card.id)
    return {
        **node,
        "created_at": card.created_at,
        "updated_at": card.updated_at,
        "children": [
            _build_node(conn, child, with_blockers)
            for child in db.list_children(conn, card.id)
        ],
    }


def build_tree(
    conn: sqlite3.Connection,
    project_id: str,
    root_id: str | None = None,
    with_blockers: bool = True,
) -> list[dict]:
    # Export turns with_blockers off: `blockers` is derived, never stored,
    # and export card nodes keep the v1 shape.
    if root_id is not None:
        card = require_card(conn, project_id, root_id)
        return [_build_node(conn, card, with_blockers)]

    top_level = db.list_cards(conn, project_id, parent_id=None)
    return [_build_node(conn, card, with_blockers) for card in top_level]
```

In `src/brd/views.py`, replace `card_detail` with:

```python
def card_detail(conn: sqlite3.Connection, card: Card) -> dict:
    # One read, so blocked_by and blockers keep the same order.
    blockers = core.blockers_of(conn, card.id)
    return {
        "id": card.id,
        "kind": "card",
        "title": card.title,
        "description": card.description,
        "status": core.resolve_status(conn, card),
        "parent_id": card.parent_id,
        "created_at": card.created_at,
        "updated_at": card.updated_at,
        "blocked_by": [blocker["id"] for blocker in blockers],
        "blockers": blockers,
        "children": [child.id for child in db.list_children(conn, card.id)],
        "comments": [comment_dict(c) for c in comments.for_entity(conn, card.id)],
        **links_of(conn, card.id),
    }
```

In `src/brd/snapshot.py`, inside `export`, change

```python
        "cards": core.build_tree(conn, project_id),
```

to

```python
        "cards": core.build_tree(conn, project_id, with_blockers=False),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: whole suite PASS (including `test_import_tree_round_trips_a_whole_board`, which now also round-trips `blockers`, and `test_show_pretty_renders_a_foreign_blocker`, still on today's pretty text until Task 3).

- [ ] **Step 5: Commit**

```bash
git add src/brd/core.py src/brd/views.py src/brd/snapshot.py tests/test_core.py tests/test_cli.py tests/test_snapshot.py
git commit -m "Add blockers to card detail, list, next and tree; keep export v1"
```

---

### Task 3: `show --pretty` renders foreign and not-found blockers

**Files:**
- Modify: `src/brd/pretty.py:33-39` (`_blocker`) and `src/brd/pretty.py:61-63` (`render_detail` card branch)
- Test: `tests/test_cli.py` (imports at lines 8-11; `test_show_pretty_renders_a_foreign_blocker`; `test_forget_leaves_a_foreign_card_blocked_until_unblocked`; new tests), `tests/test_pretty.py` (append)

**Interfaces:**
- Consumes: `data["blockers"]` (entries from Task 1/2) and `data["project"]["id"]` on `show` output (`views.detail`).
- Produces: `pretty._blocker(blocker: dict, project_id: str) -> str` (pure; no connection).

- [ ] **Step 1: Write the failing tests**

In `tests/test_cli.py`, change the imports

```python
from brd import db, paths
from brd.cli import app
from tests.cli_helpers import err, human, invoke, ok
from tests.factories import OTHER_PROJECT, add_project, make_card, make_document, make_issue
```

to

```python
from brd import db, paths
from brd.cli import app
from brd.models import Project
from tests.cli_helpers import err, human, invoke, ok
from tests.factories import (
    NOW,
    OTHER_PROJECT,
    add_project,
    make_card,
    make_document,
    make_issue,
)
```

Replace `test_show_pretty_renders_a_foreign_blocker` with:

```python
def test_show_pretty_renders_a_foreign_blocker(foreign):
    mine = ok("add", "--title", "mine")["id"]
    ok("block", mine, "--by", foreign)
    assert "blocked by: other: Foreign" in human("show", mine).splitlines()
```

Insert right after it (before `_blocker_entry`, which Task 2 added):

```python
def _seed_edges(card_id, *blocker_ids):
    """blocked_by rows no command would write (a missing or document target,
    or one from another project's card)."""
    conn = db.connect(paths.brd_db_path())
    try:
        for blocker_id in blocker_ids:
            db.add_blocked_by_edge(conn, card_id, blocker_id)
    finally:
        conn.close()


def test_show_pretty_renders_a_foreign_issue_blocker(foreign_entities):
    mine = ok("add", "--title", "mine", "--blocked-by", FOREIGN_ISSUE)["id"]
    assert "blocked by: other: Foreign issue" in human("show", mine).splitlines()


def test_a_foreign_document_blocker_renders_and_never_blocks(foreign_entities):
    mine = ok("add", "--title", "mine")["id"]
    _seed_edges(mine, FOREIGN_DOC)
    shown = ok("show", mine)
    assert shown["status"] == "todo"
    assert shown["blockers"] == [
        {
            "id": FOREIGN_DOC,
            "kind": "document",
            "project": {"id": OTHER_PROJECT.id, "name": OTHER_PROJECT.name},
            "title": "notes",
            "status": None,
            "released": True,
        }
    ]
    assert "blocked by: other: notes" in human("show", mine).splitlines()


def test_show_pretty_mixed_blockers_keep_order(foreign):
    lexer = ok("add", "--title", "Lexer")["id"]
    mine = ok("add", "--title", "mine", "--blocked-by", lexer, "--blocked-by", foreign)["id"]
    _seed_edges(mine, "ghost")
    rendered = {lexer: "[[Lexer]] (card)", foreign: "other: Foreign", "ghost": "not-found ghost"}
    blocked_by = ok("show", mine)["blocked_by"]
    assert sorted(blocked_by) == sorted(rendered)
    expected = "blocked by: " + ", ".join(rendered[b] for b in blocked_by)
    assert expected in human("show", mine).splitlines()


def test_show_pretty_of_a_foreign_card_treats_its_own_project_as_local(foreign):
    here = ok("add", "--title", "Here")
    conn = db.connect(paths.brd_db_path())
    try:
        make_card(conn, "F2", title="F2", project_id=OTHER_PROJECT.id)
    finally:
        conn.close()
    _seed_edges("F2", foreign, here["id"])
    # Shown from this project's cwd, but F2 belongs to `other`: its sibling
    # card is local and this project's card is the foreign one.
    here_name = ok("show", here["id"])["project"]["name"]
    rendered = {foreign: "[[Foreign]] (card)", here["id"]: f"{here_name}: Here"}
    blocked_by = ok("show", "F2")["blocked_by"]
    expected = "blocked by: " + ", ".join(rendered[b] for b in blocked_by)
    assert expected in human("show", "F2").splitlines()


def test_show_pretty_tells_a_same_named_project_apart_by_id(project):
    mine = ok("add", "--title", "mine")["id"]
    twin = Project(
        id="33333333-3333-4333-8333-333333333333",
        name=ok("show", mine)["project"]["name"],  # the cwd project's own name
        root_path="/twin",
        created_at=NOW,
    )
    conn = db.connect(paths.brd_db_path())
    try:
        add_project(conn, twin)
        make_card(conn, "twin-card", title="Twin", project_id=twin.id)
    finally:
        conn.close()
    ok("block", mine, "--by", "twin-card")
    assert f"blocked by: {twin.name}: Twin" in human("show", mine).splitlines()
```

In `test_forget_leaves_a_foreign_card_blocked_until_unblocked`, replace

```python
    assert f"not-found {theirs}" in human("show", mine)
    human("list")
    human("tree")
```

with

```python
    assert f"blocked by: not-found {theirs}" in human("show", mine).splitlines()
    # list, next and tree --pretty print no blockers, and still none.
    assert "blocked by" not in human("list") + human("tree")
```

Append to `tests/test_pretty.py`:

```python
def test_show_card_blocked_by_local_card(project):
    a = ok("add", "--title", "A")
    b = ok("add", "--title", "B", "--blocked-by", a["id"])
    assert "blocked by: [[A]] (card)" in human("show", b["id"]).splitlines()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli.py tests/test_pretty.py -v -k "pretty or foreign_document or forget_leaves_a_foreign or blocked_by_local or blocked_by_issue"`
Expected:
- FAIL (assertion: line not found, today's text is `[[Foreign]] (card)` / `[[Foreign issue]] (issue, open)` / `[[notes]] (card)` / `[[None]] (card)` / `[[Here]] (card)` / `[[Twin]] (card)`): `test_show_pretty_renders_a_foreign_blocker`, `test_show_pretty_renders_a_foreign_issue_blocker`, `test_a_foreign_document_blocker_renders_and_never_blocks`, `test_show_pretty_mixed_blockers_keep_order`, `test_show_pretty_of_a_foreign_card_treats_its_own_project_as_local`, `test_show_pretty_tells_a_same_named_project_apart_by_id`, `test_forget_leaves_a_foreign_card_blocked_until_unblocked`.
- PASS (guards, must still pass after Step 3): `test_show_card_blocked_by_local_card`, `test_show_card_blocked_by_issue`.

- [ ] **Step 3: Write the implementation**

In `src/brd/pretty.py`, replace

```python
def _blocker(conn: sqlite3.Connection, blocker_id: str) -> str:
    kind = entities.kind_of(conn, blocker_id)
    title = entities.title_of(conn, blocker_id)
    if kind == "issue":
        status = conn.execute("SELECT status FROM issues WHERE id = ?", (blocker_id,)).fetchone()
        return f"[[{title}]] (issue, {status['status']})"
    return f"[[{title}]] (card)"
```

with

```python
def _blocker(blocker: dict, project_id: str) -> str:
    # Local means owned by the shown card's project, compared by id: names
    # may repeat, and `show` of another project's card is local to that one.
    if blocker["kind"] is None:
        return f"not-found {blocker['id']}"
    if blocker["project"]["id"] != project_id:
        return f"{blocker['project']['name']}: {blocker['title']}"
    if blocker["kind"] == "issue":
        return f"[[{blocker['title']}]] (issue, {blocker['status']})"
    return f"[[{blocker['title']}]] (card)"
```

and in `render_detail`, replace

```python
        if data["blocked_by"]:
            extra.append("blocked by: " + ", ".join(_blocker(conn, b) for b in data["blocked_by"]))
```

with

```python
        if data["blockers"]:
            project_id = data["project"]["id"]
            extra.append(
                "blocked by: " + ", ".join(_blocker(b, project_id) for b in data["blockers"])
            )
```

(`entities` stays imported: `text` and the issue `blocks:` line still use it.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: whole suite PASS.

- [ ] **Step 5: Commit**

```bash
git add src/brd/pretty.py tests/test_cli.py tests/test_pretty.py
git commit -m "Render foreign and not-found blockers in show --pretty"
```

---

## Spec coverage check

| Spec item | Task |
|---|---|
| B1 `blockers` shape, release rule, not-found, document, cycle (T1-T8) | Task 1 |
| B1 on `show`/`add`/`update`/`block`/`unblock`/`list`/`next`/`tree` (T9, T10, T11 JSON) | Task 2 |
| B2 pretty forms, order, owner-by-id (T11 pretty, T12-T15) | Task 3 |
| B2 no blockers in `list`/`next`/`tree --pretty` | Task 3 (forget test asserts list/tree; `next --pretty` uses the same `render_list`) |
| B3 no new errors | Tasks 2-3: not-found, foreign and document blockers exercised through every command with `ok(...)` |
| B4 export without `blockers`, tree import ignores it (T16, T17) | Task 2 |
| Existing tests changed (foreign pretty, round trip) (T12, T18) | Tasks 3, 2 |
<!-- task-pipeline: validated -->
