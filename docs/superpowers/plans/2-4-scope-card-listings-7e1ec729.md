# 2.4 Scope card listings and mutations to the current project

Card: `7e1ec729-fc07-4043-b101-faa6cfbf0dd4` (subtask of story `54de5e9d` "Project-scoped
schema", milestone `6aa7043a` "Single database and cross-project blocking"). Blocked by
2.3 (`da130e91`, done on this branch's parent: schema v4 with `entities.project_id`,
`src/brd/db.py:172-176`, and the same-project parent trigger, `src/brd/db.py:224-231`).

Parent design spec: `docs/superpowers/specs/2026-10-06-single-db-cross-project-blocking-design.md`
(in the main checkout; not in this branch's history). Cited by section and line as
**[P §n Lx]**.

## Goal

Card commands only see and change cards of the project they run in. The project is
`ctx.project` (`src/brd/cli/_app.py:53-56`):

- `brd list`, `brd next` and `brd tree` list only the current project's cards.
- `brd update`, `brd delete` (card branch), `brd block` / `brd unblock` (the card being
  changed), `brd comment add` on a card, and the `--parent` of `brd add` / `brd update`
  refuse a card from another project. The error is a `CardNotFoundError` (an
  `EntityNotFoundError`) that names the owning project.
- Blocker targets (`brd block --by`, `brd add --blocked-by`) must still be in the current
  project. This check is lifted in S4.
- `brd show <id>` stays global, and its output gains the owning project.

There is still one board file per project, holding one `projects` row. Users see no
difference until S3 puts every project in one `brd.db`. Until then, tests seed a second
project into one connection (`tests/factories.add_project`, `tests/factories.py:21-29`)
to exercise the filters.

## Inherited constraints

| Constraint | Source |
|---|---|
| Commands are scoped to the current project. Only edges, `show`, edge targets and `[[uuid]]` links cross projects. | [P D3 L33] |
| Ownership lives on `entities.project_id`. | [P D4 L34] |
| `list`, `next` and `tree` are filtered by `entities.project_id` through **one helper in `db.py`**. | [P §2 L109-111]; card text |
| Mutating commands (`update`, `delete`, the source of `block`/`unblock`, `comment`, …) require the entity to belong to the current project. Otherwise they raise `EntityNotFoundError` naming the owning project. | [P §2 L112-115] |
| `brd show <id>` is global, and its output includes the owning project. | [P §2 L117] |
| Status resolution and the cycle check follow edges globally. | [P §2 L119-120] |
| In phase 2, edge targets are still validated as same-project by code. | [P Implementation order L276-280]; card text ("Blocker targets keep the same-project check for now (lifted in S4)") |
| `blocked_by` stays a list of ids wherever it appears today. | [P §4 L173-174] |
| New functions that take the project take it as a **required** positional parameter `project_id: str`, second after `conn`, as `create_card`, `import_tree` and `insert_card` already do. They never fall back to "the board's only project". | 2.3 spec B4; `src/brd/core.py:140`, `src/brd/core.py:296` |

## Behaviour

Below, "P" is the current project (`ctx.project`) and "Q" is another project in the same
connection. "A foreign card" is a card whose `entities.project_id` is Q's id.

### B1. One scoping helper, one owner lookup (`db.py`)

- `db.in_project(id_column: str) -> str` returns the SQL fragment
  `JOIN entities AS scope ON scope.id = <id_column> AND scope.project_id = ?`. The caller
  binds the project id as the fragment's single parameter. This is the only place a
  query joins on `entities.project_id` to filter a listing. Card 2.5 reuses it for issues
  and documents.
- `db.owner_of(conn, entity_id: str) -> Project | None` returns the `projects` row that
  owns the entity, or `None` when the id is not in `entities`.

### B2. Listings show only P's cards

- `db.list_cards(conn, project_id, status=None, parent_id=_UNSET)` returns only cards
  owned by `project_id`. The status filter, the parent filter (including `parent_id=None`,
  meaning top-level) and the `created_at` order work as today.
- `brd list` (with or without `--status` / `--parent`) lists only P's cards.
  `--parent <foreign id>` returns `[]`, as an unknown parent id does today. It is not an
  error: `list` validates no ids today, and this card does not add validation.
- `brd next` without `--parent` returns only P's ready leaf cards. A P card blocked by
  anything is still excluded: status resolution is unchanged and global [P §2 L119-120].
- `brd next --parent <foreign id>` and `brd tree <foreign id>` fail with the foreign-card
  error (B4). `brd tree` with no root lists only P's top-level cards and their subtrees.
  Children are always in the same project as their parent (trigger, 2.3).
- `snapshot.export(conn, project_id, root)` passes the project to `build_tree`, so the
  export's `cards` holds only P's cards. Issues, documents, comments, tags and refs in the
  export are unchanged by this card (S5).

### B3. Signatures (callers pass `ctx.project.id`)

| Function | New signature |
|---|---|
| `db.list_cards` | `(conn, project_id, status=None, parent_id=_UNSET)` |
| `core.require_card` (new public name for `_require_card`) | `(conn, project_id, card_id) -> Card` |
| `core._require_blocker` | `(conn, project_id, blocker_id) -> None` |
| `core.update_card` | `(conn, project_id, card_id, title=None, description=None, status=None, parent_id=None)` |
| `core.block_card` | `(conn, project_id, card_id, blocker_id)` |
| `core.unblock_card` | `(conn, project_id, card_id, blocker_id)` |
| `core.delete_card` | `(conn, project_id, card_id, cascade=False)` |
| `core.next_cards` | `(conn, project_id, limit=None, parent_id=None)` |
| `core.build_tree` | `(conn, project_id, root_id=None)` |
| `snapshot.export` | `(conn, project_id, root)` |
| `cli.cards.delete_entity` | `(conn, project_id, entity_id, cascade)` |
| `comments.add` | `(conn, project_id, entity_id, body, author)` |

`core.create_card` and `issues.open_issue` keep their signatures. They pass their existing
`project_id` to the checks below. The duplicate `_require_card` in `src/brd/cli/cards.py:13-17`
goes away; the CLI uses `core.require_card`. Return values and the JSON shape of `list`,
`next`, `tree`, `add`, `update`, `block`, `unblock` and `delete` do not change.

### B4. The foreign-card error

`core.require_card(conn, project_id, card_id)`:

- No card with that id: `CardNotFoundError("no card with id <id>")`, as today.
- A foreign card: `CardNotFoundError` with the message
  `no card with id <id> in this project; it belongs to project <owner name> (<owner id>)`.
  The CLI envelope `type` is `CardNotFoundError`, the same as for a missing card
  (`src/brd/cli/_app.py:59-61`).
- A P card: returns it.

A refused command writes nothing: no row changes, no edge is added or removed, no comment
is added, and `updated_at` stays as it was.

Every path below goes through this check:

| Command / function | Id checked |
|---|---|
| `brd update` / `core.update_card` | the card, and `--parent` when given |
| `brd add --parent` / `core.create_card` | the parent |
| `brd delete` / `delete_entity` when the id is a card; `core.delete_card` | the card (with `--cascade`, every descendant is in P by the trigger) |
| `brd block` / `core.block_card` | the card being blocked |
| `brd unblock` / `core.unblock_card` | the card being unblocked |
| `brd next --parent`, `brd tree <root>` | the parent / root |
| `brd comment add <card id>` / `comments.add` | the entity, when its kind is `card` |
| `brd issue open --blocks <card>` / `issues.open_issue` | each `--blocks` card. This check runs **before** the issue row is inserted, replacing the global `db.get_card` pre-check at `src/brd/issues.py:85-87`, so a foreign `--blocks` leaves no issue behind. |

`brd update --parent <foreign card>` now fails with this error, before the same-project
trigger is reached, rather than with a raw `sqlite3.IntegrityError`.

If the id is a non-card entity (issue or document), these paths behave as today. For
example, `brd update <issue id>` still says `no card with id <id>`, whatever project owns
the issue. `brd delete` of an issue or document id is unchanged (2.5).

### B5. Blocker targets stay same-project

`core._require_blocker(conn, project_id, blocker_id)` is used by `brd block --by` and
`brd add --blocked-by`. It checks, in this order:

1. Id not in `entities`: `CardNotFoundError("no card or issue with id <id>")`, as today.
2. Owned by another project: `CardNotFoundError` with the message
   `no card or issue with id <id> in this project; it belongs to project <owner name> (<owner id>)`.
   This holds for any kind: a foreign card, issue or document.
3. A P entity whose kind is not a blocker (a document): `InvalidBlockerError`, as today.

`brd add --blocked-by <foreign id>` creates no card. All targets are checked before the
insert, as today (`src/brd/core.py:147-149`). `brd unblock --by` does not check its
target: it removes the edge if one exists, as today.

### B6. Status resolution and cycles are unchanged

`resolve_status`, `_is_released`, `would_create_block_cycle` and
`would_create_parent_cycle` keep their signatures and keep looking up by id across every
project [P §2 L119-120]. No new code path can create a foreign edge, but an edge seeded
directly in a test still affects status. Example: P card X `blocked_by` a Q card Y in
`todo` is shown as `blocked` in P's `list`, and Y is not listed.

### B7. `brd show` is global and names the owner

`views.detail(conn, root, entity_id)` (`brd show`) finds any entity by id, in any project,
as today. Its output gains one key, for every kind (card, issue, document):

```json
"project": {"id": "<owner project id>", "name": "<owner project name>"}
```

The other keys are unchanged, and a missing id is still
`CardNotFoundError("no card, issue, or document with id <id>")`. `views.card_detail`
does **not** gain the key, so `list`, `next`, `add`, `update`, `block` and `unblock`
output stays as it is. `--pretty` show output is unchanged.

## Tests

Tests stay flat in `tests/`. There are two tiers:

- **Unit:** in-process calls on a `pconn` connection (`tests/conftest.py:7-12`), with a
  second project seeded by `add_project(pconn, OTHER_PROJECT)` and cards made with
  `make_card(..., project_id=OTHER_PROJECT.id)`. This is where the filters and checks are
  pinned: two projects can share one connection only here, and only here can the
  database state after a refusal be read directly.
- **CLI:** `typer` runner through `tests/cli_helpers.py` with the `project` fixture
  (`tests/conftest.py:15-24`). The test opens the board file
  (`paths.project_db_path(repo)`), seeds OTHER_PROJECT and a foreign card into it, and
  closes it before invoking. This tier pins the wiring: `ctx.project.id` reaches each
  command, and the envelope `type` and message are what consumers parse.

New tests go in `tests/test_project_scope.py` (unit) and `tests/test_cli.py` (CLI).

| # | Test | Tier | Why this tier |
|---|---|---|---|
| T1 | `db.in_project("cards.id")` used in a raw query returns only the bound project's cards | Unit | The helper is a SQL fragment; only a direct query exercises it alone |
| T2 | `db.owner_of` returns the owning `Project` for P and Q entities, and `None` for an unknown id | Unit | Pure db function |
| T3 | `db.list_cards(conn, P)` returns only P's cards, and so do `status=` and `parent_id=None` (P and Q both have top-level `todo` cards) | Unit | Needs two projects in one connection |
| T4 | `next_cards(conn, P)` excludes Q's ready leaves. A P card blocked by a seeded Q `todo` card is excluded, and is included once Q's card is `done` (B6) | Unit | Two projects plus a directly seeded cross-project edge |
| T5 | `build_tree(conn, P)` holds only P's roots and subtrees. `build_tree(conn, P, root_id=<Q card>)` raises the foreign-card error | Unit | Same |
| T6 | `snapshot.export(conn, P, root)["cards"]` holds no Q card | Unit | Export is called in-process; no CLI path reaches a second project |
| T7 | Parametrised over `update_card` (fields), `update_card(parent_id=<Q card>)` with a P card, `create_card(parent_id=<Q card>)`, `delete_card` (with and without `cascade`), `block_card` (foreign source), `unblock_card` (foreign source with an existing edge), `next_cards(parent_id=<Q>)` and `comments.add` on a Q card: each raises `CardNotFoundError` whose message contains `OTHER_PROJECT.name` and `OTHER_PROJECT.id`, and the cards, blocked_by and comments tables are unchanged | Unit | Asserts the error and that nothing was written; only reading the database directly shows no write |
| T8 | `require_card` on a missing id still says `no card with id <id>`. `update_card` on a Q **issue** id still says `no card with id` | Unit | Unchanged error paths |
| T9 | `block_card(conn, P, <P card>, <Q card>)` and `block_card(..., <Q issue>)` raise `CardNotFoundError` naming Q, and add no edge. `create_card(conn, P, ..., blocked_by=[<Q card>])` raises the same and inserts no card. A Q document target also raises `CardNotFoundError` naming Q (ownership is checked before kind). A P document target still raises `InvalidBlockerError` | Unit | The same-project target check needs two projects |
| T10 | `issues.open_issue(conn, P, "t", blocks=[<Q card>])` raises `CardNotFoundError` naming Q, and the `issues` and `entities` tables gain no row | Unit | Pins that the check runs before the insert |
| T11 | `views.detail` on a P card, a Q card, a Q issue and a Q document returns `project == {"id", "name"}` of the owner, and the other keys match `card_detail` / `issue_detail` / `document_detail` | Unit | Show is global; only a second project shows the owner is not just "current" |
| T12 | All existing P-only behaviour still holds: the existing `test_core.py`, `test_issues.py`, `test_comments.py`, `test_db.py`, `test_migration.py`, `test_cli*.py`, `test_snapshot.py` and `test_pretty.py` pass with call sites updated to the new signatures | Unit + CLI | Regression |
| T13 | CLI: with a seeded foreign card F, `brd list`, `brd next` and `brd tree` output excludes F. `brd update F --title x`, `brd delete F`, `brd block F --by <P card>`, `brd unblock F --by <P card>` and `brd comment add F hi` each exit 1 with envelope type `CardNotFoundError` and a message naming `other` | CLI | Proves `ctx.project.id` reaches every command and pins the envelope consumers parse |
| T14 | CLI: `brd block <P card> --by F` and `brd add --title t --blocked-by F` exit 1 with `CardNotFoundError` naming `other` | CLI | Wiring of the target check |
| T15 | CLI: `brd show F` succeeds with `project.name == "other"`. `brd show <P card>` has `project.id == ` the registered project's id. `brd show nope` is still `CardNotFoundError` | CLI | The output shape is the user-visible contract |

## Out of scope

- Issues, documents, refs and tags: `issue list`, `issue update/close/reopen`, `doc
  list/sync` (including the `documents.sync_all` call inside `views.detail`), document
  uniqueness, `[[stem]]` resolution, `refs.reindex_mentions`, `ref add` sources, tag
  mutations, `comment list` / `comment delete`, comments on issues, and the issue and
  document branches of `brd delete`. These belong to **card 2.5** (`43ff4aca`).
- Export scoping beyond the `cards` section (S5), and import's `_require_import_target`
  (it still accepts any id already in the database, S5).
- Lifting the same-project check on blocker targets, the `blockers` output, and not-found
  blockers (S4) [P §4 L149-187].
- Moving to one `brd.db`, project resolution without the marker, and the
  all-commands leak guard [P Testing L255-257] (S3 / story-level).
- `--pretty` rendering of the owning project.
- Adding a `project` key to `card_detail` (list/next/add/update output).

## Notes for the planner

- About 134 existing test call sites use the old signatures of `list_cards`,
  `update_card`, `block_card`, `unblock_card`, `delete_card`, `next_cards`,
  `build_tree`, `snapshot.export`, `delete_entity` and `comments.add`. They are in
  `tests/test_core.py`, `test_issues.py`, `test_comments.py`, `test_db.py`,
  `test_migration.py` and `test_cli_issues.py`. Update each call site in the task that
  changes the signature, passing `PROJECT.id`, so the suite stays green task by task.
- `tests/test_project_scope.py:20-41` has stale lambdas (`core.create_card(conn, title="c")`
  and others). They pass only because `TypeError` is expected. Leave them alone.
- `list_cards` must select `cards.*`, since `entities` also has an `id` column. Bind the
  helper's project parameter before the status/parent parameters.
- Verification: `uv run pytest` (471 passing at the start of this card). There is no
  typecheck or lint configuration.

---

# 2.4 Scope card listings and mutations to the current project Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Card listings (`list`, `next`, `tree`, export's `cards`) show only the current project's cards, card mutations refuse a card owned by another project with a `CardNotFoundError` naming the owner, and `brd show` stays global but reports the owning project.

**Architecture:** Two new `db.py` primitives: `in_project(id_column)` (the single SQL join fragment that filters by `entities.project_id`) and `owner_of(conn, entity_id)`. `core.require_card(conn, project_id, card_id)` replaces `_require_card` and is the single ownership gate for every card-mutating path. `_require_blocker` gains the same ownership check for blocker targets. Every changed function takes `project_id: str` as a required positional parameter, second after `conn`, and the CLI passes `ctx.project.id`.

**Tech Stack:** Python 3, sqlite3, typer, pytest, run through `uv`.

**Spec:** `docs/superpowers/specs/2-4-scope-card-listings-7e1ec729.md` (reproduced above this plan).

## Global Constraints

- New or changed functions take the project as a **required** positional parameter `project_id: str`, second after `conn`. They never fall back to "the board's only project".
- `list`, `next` and `tree` filter by `entities.project_id` through **one helper in `db.py`** (`db.in_project`). No other query joins on `entities.project_id` to filter a listing.
- The foreign-card message is exactly `no card with id <id> in this project; it belongs to project <owner name> (<owner id>)`; the foreign-blocker message is exactly `no card or issue with id <id> in this project; it belongs to project <owner name> (<owner id>)`. Both raise `CardNotFoundError`.
- A missing card stays `no card with id <id>`; a missing blocker stays `no card or issue with id <id>`; a missing `show` id stays `no card, issue, or document with id <id>`.
- `resolve_status`, `_is_released`, `would_create_block_cycle` and `would_create_parent_cycle` keep their signatures and stay global.
- Return values and JSON shape of `list`, `next`, `tree`, `add`, `update`, `block`, `unblock`, `delete` do not change; `views.card_detail` does **not** gain a `project` key; `--pretty` output is unchanged.
- `blocked_by` stays a list of ids.
- Issues, documents, refs, tags, `comment list/delete`, comments on issues, and the issue/document branches of `brd delete` are out of scope (card 2.5): they behave as today.
- Verification: `uv run pytest` (471 passing at the start). No typecheck or lint.
- Do not touch the stale `TypeError` lambdas in `tests/test_project_scope.py:20-41`.

## Review Focus

- A repeatable option mixing a valid id and a foreign id (`brd add --blocked-by <P> --blocked-by <F>`, `brd issue open --blocks <P> --blocks <F>`): the command fails and writes nothing (no card, no issue, no edge on the P card). Pinned by `create_card_foreign_blocker` and `open_issue_foreign_blocks` in the `REFUSED` table (Task 4).
- `brd update <F>` with only `--status` or only `--clear-parent` (no title change): still refused, `updated_at` unchanged. Pinned by `update_card_status` and `update_card_clear_parent` (Task 2).
- `brd list --parent <F>` returns `[]`, not an error. Pinned by `test_list_cards_with_a_foreign_parent_is_empty` and the CLI listing test (Task 6).
- `brd delete <F> --cascade` where F has children: nothing deleted, not even the children. Pinned by `delete_card_cascade` (q1 has child q-child) (Task 3).
- A P card blocked by a Q card is shown `blocked` in P's listings while the Q card itself is not listed, and is released once the Q card is done. Pinned by `test_next_cards_skips_other_projects_and_follows_edges_across_them` (Task 6).

## File Structure

- `src/brd/db.py` — add `in_project`, `owner_of`; `list_cards` gains `project_id`.
- `src/brd/core.py` — `require_card`, `_require_in_project`, `_require_blocker(project_id)`, and the `project_id` parameter on `update_card`, `block_card`, `unblock_card`, `delete_card`, `next_cards`, `build_tree`; `_require_card` is removed in Task 6.
- `src/brd/issues.py` — `open_issue` checks `--blocks` cards with `core.require_card` before inserting.
- `src/brd/comments.py` — `add` gains `project_id`, checks card ownership.
- `src/brd/snapshot.py` — `export` gains `project_id`.
- `src/brd/views.py` — `detail` adds `project`.
- `src/brd/cli/cards.py`, `src/brd/cli/comments.py`, `src/brd/cli/snapshot.py` — pass `ctx.project.id`; drop the duplicate `_require_card`.
- Tests: `tests/test_project_scope.py` (unit), `tests/test_cli.py` (CLI), plus call-site updates in `tests/test_core.py`, `tests/test_issues.py`, `tests/test_comments.py`, `tests/test_db.py`.

---

### Task 1: `db.in_project` and `db.owner_of`

**Files:**
- Modify: `src/brd/db.py` (after `delete_project`, before `_row_to_card`)
- Test: `tests/test_project_scope.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `db.in_project(id_column: str) -> str` — returns `JOIN entities AS scope ON scope.id = <id_column> AND scope.project_id = ?`; caller binds the project id as its single parameter.
  - `db.owner_of(conn: sqlite3.Connection, entity_id: str) -> Project | None`.
  - Test fixture `two` and constants `P`, `Q` in `tests/test_project_scope.py`, used by every later task.

- [ ] **Step 1: Replace the import block of `tests/test_project_scope.py` and add the shared fixture**

Replace lines 1-7 of `tests/test_project_scope.py`:

```python
import sqlite3

import pytest

from brd import core, db, documents, issues, snapshot
from brd.models import Card
from tests.factories import NOW, OTHER_PROJECT, PROJECT, add_project, make_card
```

with:

```python
import re
import sqlite3

import pytest

from brd import comments, core, db, documents, issues, snapshot, views
from brd.cli import cards as cli_cards
from brd.errors import CardNotFoundError, InvalidBlockerError
from brd.models import Card
from tests.factories import (
    NOW,
    OTHER_PROJECT,
    PROJECT,
    add_project,
    make_card,
    make_document,
    make_issue,
)

P = PROJECT.id
Q = OTHER_PROJECT.id
```

Then append to the end of the file:

```python
@pytest.fixture
def two(pconn):
    """P owns cards p1 and p2. Q owns card q1 (parent of q-child, blocked by
    p2 through a directly seeded cross-project edge), issue qi and
    document qd."""
    add_project(pconn, OTHER_PROJECT)
    make_card(pconn, "p1")
    make_card(pconn, "p2")
    make_card(pconn, "q1", project_id=Q)
    make_card(pconn, "q-child", parent_id="q1", project_id=Q)
    make_issue(pconn, "qi", project_id=Q)
    make_document(pconn, "qd", "qnotes", content="q body", project_id=Q)
    db.add_blocked_by_edge(pconn, "q1", "p2")
    return pconn


def test_in_project_filters_a_raw_query_to_the_bound_project(two):
    query = f"SELECT cards.id FROM cards {db.in_project('cards.id')} ORDER BY cards.id"
    assert [row["id"] for row in two.execute(query, (P,))] == ["p1", "p2"]
    assert [row["id"] for row in two.execute(query, (Q,))] == ["q-child", "q1"]


def test_owner_of_returns_the_owning_project(two):
    assert db.owner_of(two, "p1") == PROJECT
    assert db.owner_of(two, "q1") == OTHER_PROJECT
    assert db.owner_of(two, "qi") == OTHER_PROJECT
    assert db.owner_of(two, "qd") == OTHER_PROJECT
    assert db.owner_of(two, "nope") is None
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_project_scope.py -k "in_project or owner_of" -v`
Expected: FAIL with `AttributeError: module 'brd.db' has no attribute 'in_project'` (and `owner_of`).

- [ ] **Step 3: Implement the helpers in `src/brd/db.py`**

Insert after `delete_project` (before `def _row_to_card`):

```python
def in_project(id_column: str) -> str:
    """The one join that scopes a query to a project: keeps rows whose
    `id_column` is an entity owned by the project bound to its single `?`."""
    return f"JOIN entities AS scope ON scope.id = {id_column} AND scope.project_id = ?"


def owner_of(conn: sqlite3.Connection, entity_id: str) -> Project | None:
    row = conn.execute(
        "SELECT projects.* FROM entities "
        "JOIN projects ON projects.id = entities.project_id WHERE entities.id = ?",
        (entity_id,),
    ).fetchone()
    return _row_to_project(row) if row else None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_project_scope.py -v`
Expected: PASS (all tests in the file, including the pre-existing ones).

- [ ] **Step 5: Commit**

```bash
git add src/brd/db.py tests/test_project_scope.py
git commit -m "Add db.in_project and db.owner_of for project-scoped queries"
```

---

### Task 2: `core.require_card`, scoped `update_card` and `create_card --parent`

**Files:**
- Modify: `src/brd/core.py` (`_require_card` area, `create_card`, `update_card`)
- Modify: `src/brd/cli/cards.py` (`update` command)
- Modify: `tests/test_core.py` (update_card call sites)
- Test: `tests/test_project_scope.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `db.owner_of(conn, entity_id) -> Project | None` (Task 1), fixture `two`, `P`, `Q` (Task 1).
- Produces:
  - `core.require_card(conn: sqlite3.Connection, project_id: str, card_id: str) -> Card`.
  - `core._require_in_project(conn, project_id: str, entity_id: str, what: str) -> None` — raises `CardNotFoundError("no <what> with id <id> in this project; it belongs to project <name> (<id>)")` when the entity exists in another project; does nothing for a missing id.
  - `core.update_card(conn, project_id, card_id, title=None, description=None, status=None, parent_id=None) -> Card`.
  - Test helpers `_foreign`, `_state`, list `REFUSED`, and test `test_refused_call_names_the_owner_and_writes_nothing` in `tests/test_project_scope.py`; fixture `foreign`, constant `FOREIGN` and helper `_refused` in `tests/test_cli.py`. Later tasks append to `REFUSED` and reuse `foreign` / `_refused`.
  - `core._require_card(conn, card_id)` is **kept unchanged** for now (still used by `block_card`, `unblock_card`, `delete_card`, `next_cards`, `build_tree`); Task 6 deletes it.

- [ ] **Step 1: Write the failing unit tests**

Append to `tests/test_project_scope.py`:

```python
def _foreign(entity_id, what="card"):
    return re.escape(
        f"no {what} with id {entity_id} in this project; "
        f"it belongs to project {OTHER_PROJECT.name} ({OTHER_PROJECT.id})"
    )


def _state(conn):
    return {
        table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2")]
        for table in ("entities", "cards", "issues", "blocked_by", "comments")
    }


REFUSED = [
    pytest.param(
        lambda c: core.update_card(c, P, "q1", title="x"), "q1", "card", id="update_card"
    ),
    pytest.param(
        lambda c: core.update_card(c, P, "q1", status="done"), "q1", "card",
        id="update_card_status",
    ),
    pytest.param(
        lambda c: core.update_card(c, P, "q-child", parent_id=core.CLEAR_PARENT),
        "q-child", "card", id="update_card_clear_parent",
    ),
    pytest.param(
        lambda c: core.update_card(c, P, "p1", title="x", parent_id="q1"), "q1", "card",
        id="update_card_foreign_parent",
    ),
    pytest.param(
        lambda c: core.create_card(c, P, "new", parent_id="q1"), "q1", "card",
        id="create_card_foreign_parent",
    ),
]


@pytest.mark.parametrize(("call", "foreign_id", "what"), REFUSED)
def test_refused_call_names_the_owner_and_writes_nothing(two, call, foreign_id, what):
    before = _state(two)
    with pytest.raises(CardNotFoundError, match=_foreign(foreign_id, what)):
        call(two)
    assert _state(two) == before


def test_require_card_returns_the_projects_card(two):
    assert core.require_card(two, P, "p1").id == "p1"


def test_require_card_on_a_missing_id_is_unchanged(two):
    with pytest.raises(CardNotFoundError, match=r"^no card with id nope$"):
        core.require_card(two, P, "nope")


def test_update_card_on_a_foreign_issue_still_says_no_card(two):
    with pytest.raises(CardNotFoundError, match=r"^no card with id qi$"):
        core.update_card(two, P, "qi", title="x")
```

- [ ] **Step 2: Write the failing CLI tests**

In `tests/test_cli.py`, replace the import lines 7-8:

```python
from brd import paths
from brd.cli import app
```

with:

```python
from brd import db, paths
from brd.cli import app
from tests.cli_helpers import err, invoke, ok
from tests.factories import OTHER_PROJECT, add_project, make_card
```

Append to the end of `tests/test_cli.py`:

```python
FOREIGN = "f0f0f0f0-0000-4000-8000-000000000000"


@pytest.fixture
def foreign(project):
    """Seed another project and its card FOREIGN into the current board file.
    No command can do this until every project shares one database."""
    conn = db.connect(paths.project_db_path(project))
    try:
        add_project(conn, OTHER_PROJECT)
        make_card(conn, FOREIGN, title="Foreign", project_id=OTHER_PROJECT.id)
    finally:
        conn.close()
    return FOREIGN


def _refused(*args) -> None:
    result = invoke(*args)
    assert result.exit_code == 1, result.output
    error = json.loads(result.stdout)["error"]
    assert error["type"] == "CardNotFoundError"
    assert f"belongs to project {OTHER_PROJECT.name} ({OTHER_PROJECT.id})" in error["message"]


def test_update_refuses_a_foreign_card(foreign):
    _refused("update", foreign, "--title", "x")
    assert ok("show", foreign)["title"] == "Foreign"


def test_add_and_update_refuse_a_foreign_parent(foreign):
    _refused("add", "--title", "t", "--parent", foreign)
    mine = ok("add", "--title", "mine")["id"]
    _refused("update", mine, "--parent", foreign)
    assert ok("show", mine)["parent_id"] is None
```

- [ ] **Step 3: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_project_scope.py tests/test_cli.py -k "refused or require_card or foreign" -v`
Expected: FAIL — `TypeError` from `update_card`'s extra positional argument, `AttributeError: module 'brd.core' has no attribute 'require_card'`, and the CLI tests exit 0 instead of 1 (update succeeds) or fail with a raw `sqlite3.IntegrityError` for `--parent`.

- [ ] **Step 4: Implement `require_card` and `_require_in_project` in `src/brd/core.py`**

Directly after the existing `_require_card` function (leave `_require_card` as it is), insert:

```python
def _require_in_project(
    conn: sqlite3.Connection, project_id: str, entity_id: str, what: str
) -> None:
    # Commands act on the current project only. Name the owner, so an id
    # copied from another project's board says where it lives.
    owner = db.owner_of(conn, entity_id)
    if owner is not None and owner.id != project_id:
        raise CardNotFoundError(
            f"no {what} with id {entity_id} in this project; "
            f"it belongs to project {owner.name} ({owner.id})"
        )


def require_card(conn: sqlite3.Connection, project_id: str, card_id: str) -> Card:
    card = db.get_card(conn, card_id)
    if card is None:
        raise CardNotFoundError(f"no card with id {card_id}")
    _require_in_project(conn, project_id, card_id, "card")
    return card
```

- [ ] **Step 5: Scope `create_card`'s parent check**

In `create_card`, replace:

```python
    if parent_id is not None:
        _require_card(conn, parent_id)
```

with:

```python
    if parent_id is not None:
        require_card(conn, project_id, parent_id)
```

- [ ] **Step 6: Replace `update_card` with the scoped version**

Replace the whole `update_card` function with:

```python
def update_card(
    conn: sqlite3.Connection,
    project_id: str,
    card_id: str,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
    parent_id: str | object | None = None,
) -> Card:
    require_card(conn, project_id, card_id)

    if status == "blocked":
        raise InvalidStatusError("status cannot be set to 'blocked' directly; it is derived")

    fields: dict[str, str | None] = {}
    if title is not None:
        fields["title"] = title
    if description is not None:
        fields["description"] = description
    if status is not None:
        if status not in db.CARD_STATUSES:
            raise InvalidStatusError(
                f"invalid card status {status!r}; use one of {', '.join(db.CARD_STATUSES)}"
            )
        fields["status"] = status

    if parent_id is CLEAR_PARENT:
        fields["parent_id"] = None
    elif parent_id is not None:
        require_card(conn, project_id, parent_id)
        if would_create_parent_cycle(conn, card_id, parent_id):
            raise CycleError(f"setting {card_id}'s parent to {parent_id} would create a cycle")
        fields["parent_id"] = parent_id

    if fields:
        fields["updated_at"] = _now()
        db.update_card_fields(conn, card_id, **fields)
        if description is not None:
            refs.reindex(conn, card_id)

    return require_card(conn, project_id, card_id)
```

- [ ] **Step 7: Pass the project from the CLI `update` command**

In `src/brd/cli/cards.py`, inside `update`'s `action`, replace:

```python
        card = core.update_card(
            ctx.conn,
            card_id,
```

with:

```python
        card = core.update_card(
            ctx.conn,
            ctx.project.id,
            card_id,
```

- [ ] **Step 8: Update existing `update_card` call sites in `tests/test_core.py`**

Run:

```bash
sed -i 's/core\.update_card(conn, /core.update_card(conn, PROJECT.id, /g' tests/test_core.py
grep -n "update_card(" tests/test_core.py
```

Expected: every line shows `core.update_card(conn, PROJECT.id, ...` (17 lines, e.g. `core.update_card(conn, PROJECT.id, card.id, title="Updated")`, `core.update_card(conn, PROJECT.id, "nope", title="Updated")`).

- [ ] **Step 9: Run the tests to verify they pass**

Run: `uv run pytest tests/test_project_scope.py tests/test_cli.py tests/test_core.py -v`
Expected: PASS.

- [ ] **Step 10: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass, none failing.

- [ ] **Step 11: Commit**

```bash
git add src/brd/core.py src/brd/cli/cards.py tests/test_core.py tests/test_project_scope.py tests/test_cli.py
git commit -m "Refuse to update a card, or parent one to a card, from another project"
```

---

### Task 3: Scoped `delete_card` and `delete_entity`

**Files:**
- Modify: `src/brd/core.py` (`delete_card`)
- Modify: `src/brd/cli/cards.py` (`delete_entity`, `delete` command)
- Modify: `tests/test_core.py` (delete_card call sites)
- Test: `tests/test_project_scope.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `core.require_card(conn, project_id, card_id)` (Task 2); `REFUSED`, `two`, `P` (Tasks 1-2); `foreign`, `_refused`, `ok` (Task 2).
- Produces:
  - `core.delete_card(conn: sqlite3.Connection, project_id: str, card_id: str, cascade: bool = False) -> list[str]`.
  - `cli.cards.delete_entity(conn: sqlite3.Connection, project_id: str, entity_id: str, cascade: bool) -> list[str]`.
  - (`db.delete_card(conn, card_id)` is a different, unchanged function.)

- [ ] **Step 1: Write the failing unit tests**

In `tests/test_project_scope.py`, add these entries at the end of the `REFUSED` list (before its closing `]`):

```python
    pytest.param(lambda c: core.delete_card(c, P, "q1"), "q1", "card", id="delete_card"),
    pytest.param(
        lambda c: core.delete_card(c, P, "q1", cascade=True), "q1", "card",
        id="delete_card_cascade",
    ),
    pytest.param(
        lambda c: cli_cards.delete_entity(c, P, "q1", True), "q1", "card", id="delete_entity"
    ),
```

- [ ] **Step 2: Write the failing CLI test**

Append to `tests/test_cli.py`:

```python
def test_delete_refuses_a_foreign_card(foreign):
    _refused("delete", foreign)
    _refused("delete", foreign, "--cascade")
    assert ok("show", foreign)["id"] == foreign
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_project_scope.py tests/test_cli.py -k "delete" -v`
Expected: FAIL — the old `delete_card(conn, card_id, cascade)` reads `P` as the card id and raises `no card with id 1111...` (no owner in the message), `delete_entity` raises `TypeError` (4 arguments given, 3 taken), and the CLI `delete` exits 0.

- [ ] **Step 4: Replace `core.delete_card`**

In `src/brd/core.py`, replace the whole `delete_card` function with:

```python
def delete_card(
    conn: sqlite3.Connection, project_id: str, card_id: str, cascade: bool = False
) -> list[str]:
    require_card(conn, project_id, card_id)

    children = db.list_children(conn, card_id)
    if children and not cascade:
        raise CardHasChildrenError(
            f"card {card_id} has children; use --cascade to delete them too"
        )

    deleted: list[str] = []
    for child in children:
        deleted.extend(delete_card(conn, project_id, child.id, cascade=True))

    db.delete_card(conn, card_id)
    deleted.append(card_id)
    return deleted
```

- [ ] **Step 5: Pass the project through `delete_entity` and the `delete` command**

In `src/brd/cli/cards.py`, replace the whole `delete_entity` function with:

```python
def delete_entity(
    conn: sqlite3.Connection, project_id: str, entity_id: str, cascade: bool
) -> list[str]:
    kind = entities.kind_of(conn, entity_id)
    if kind is None:
        raise CardNotFoundError(f"no card, issue, or document with id {entity_id}")
    if kind == "card":
        return core.delete_card(conn, project_id, entity_id, cascade=cascade)
    if kind == "document":
        documents.delete(conn, entity_id)
        return [entity_id]
    entities.delete(conn, entity_id)
    return [entity_id]
```

and in the `delete` command replace:

```python
    run(pretty, lambda ctx: {"deleted": delete_entity(ctx.conn, entity_id, cascade)})
```

with:

```python
    run(
        pretty,
        lambda ctx: {"deleted": delete_entity(ctx.conn, ctx.project.id, entity_id, cascade)},
    )
```

- [ ] **Step 6: Update existing `core.delete_card` call sites in `tests/test_core.py`**

Run:

```bash
sed -i 's/core\.delete_card(conn, /core.delete_card(conn, PROJECT.id, /g' tests/test_core.py
grep -n "delete_card(" tests/test_core.py
```

Expected: every `core.delete_card(` line now reads `core.delete_card(conn, PROJECT.id, ...` (6 lines). `tests/test_db.py` and `tests/test_migration.py` call `db.delete_card`, which is unchanged; leave them.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_project_scope.py tests/test_cli.py tests/test_core.py -v`
Expected: PASS.

- [ ] **Step 8: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add src/brd/core.py src/brd/cli/cards.py tests/test_core.py tests/test_project_scope.py tests/test_cli.py
git commit -m "Refuse to delete a card from another project"
```

---

### Task 4: Scoped blocking: `block_card`, `unblock_card`, blocker targets, `issue open --blocks`

**Files:**
- Modify: `src/brd/core.py` (`_require_blocker`, `create_card`, `block_card`, `unblock_card`)
- Modify: `src/brd/issues.py` (`open_issue`, imports)
- Modify: `src/brd/cli/cards.py` (remove `_require_card`, `block`, `unblock`, imports)
- Modify: `tests/test_core.py`, `tests/test_issues.py` (call sites)
- Test: `tests/test_project_scope.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `core.require_card`, `core._require_in_project` (Task 2); `REFUSED`, `two`, `P`, `foreign`, `_refused`, `ok` (Tasks 1-2).
- Produces:
  - `core._require_blocker(conn: sqlite3.Connection, project_id: str, blocker_id: str) -> None`.
  - `core.block_card(conn: sqlite3.Connection, project_id: str, card_id: str, blocker_id: str) -> None`.
  - `core.unblock_card(conn: sqlite3.Connection, project_id: str, card_id: str, blocker_id: str) -> None`.
  - `issues.open_issue` keeps its signature `(conn, project_id, title, body=None, ref_ids=None, blocks=None)`.

- [ ] **Step 1: Write the failing unit tests**

In `tests/test_project_scope.py`, add these entries at the end of the `REFUSED` list:

```python
    pytest.param(
        lambda c: core.block_card(c, P, "q1", "p1"), "q1", "card", id="block_card_foreign_source"
    ),
    pytest.param(
        lambda c: core.unblock_card(c, P, "q1", "p2"), "q1", "card",
        id="unblock_card_foreign_source",
    ),
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
    pytest.param(
        lambda c: issues.open_issue(c, P, "t", blocks=["p1", "q1"]), "q1", "card",
        id="open_issue_foreign_blocks",
    ),
```

(The fixture's seeded edge `q1 -> p2` is what `unblock_card_foreign_source` would remove if it were not refused; `_state` proves it stays.)

Append to `tests/test_project_scope.py`:

```python
def test_a_document_of_this_project_still_cannot_block(two):
    make_document(two, "pd", "pnotes")
    with pytest.raises(InvalidBlockerError):
        core.block_card(two, P, "p1", "pd")


def test_a_missing_blocker_is_unchanged(two):
    with pytest.raises(CardNotFoundError, match=r"^no card or issue with id nope$"):
        core.block_card(two, P, "p1", "nope")
```

- [ ] **Step 2: Write the failing CLI tests**

Append to `tests/test_cli.py`:

```python
def test_block_and_unblock_refuse_a_foreign_card(foreign):
    mine = ok("add", "--title", "mine")["id"]
    _refused("block", foreign, "--by", mine)
    _refused("unblock", foreign, "--by", mine)
    assert ok("show", foreign)["blocked_by"] == []


def test_blocker_targets_must_be_in_this_project(foreign):
    mine = ok("add", "--title", "mine")["id"]
    _refused("block", mine, "--by", foreign)
    _refused("add", "--title", "t", "--blocked-by", foreign)
    assert ok("show", mine)["blocked_by"] == []


def test_issue_open_refuses_a_foreign_blocks_card(foreign):
    _refused("issue", "open", "--title", "q", "--blocks", foreign)
    assert ok("issue", "list") == []
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_project_scope.py tests/test_cli.py -k "block or issue" -v`
Expected: FAIL — `TypeError` on the 4-argument `block_card`/`unblock_card` calls; `create_card_foreign_blocker` and `open_issue_foreign_blocks` do not raise (a card / an issue is written); the CLI block commands exit 0.

- [ ] **Step 4: Replace `_require_blocker` in `src/brd/core.py`**

Replace the whole `_require_blocker` function with:

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

- [ ] **Step 5: Pass the project to the blocker check in `create_card`**

In `create_card`, replace:

```python
    for blocker_id in blocked_by:
        _require_blocker(conn, blocker_id)
```

with:

```python
    for blocker_id in blocked_by:
        _require_blocker(conn, project_id, blocker_id)
```

- [ ] **Step 6: Replace `block_card` and `unblock_card`**

Replace both functions with:

```python
def block_card(
    conn: sqlite3.Connection, project_id: str, card_id: str, blocker_id: str
) -> None:
    require_card(conn, project_id, card_id)
    _require_blocker(conn, project_id, blocker_id)
    if would_create_block_cycle(conn, card_id, blocker_id):
        raise CycleError(f"blocking {card_id} on {blocker_id} would create a cycle")
    db.add_blocked_by_edge(conn, card_id, blocker_id)


def unblock_card(
    conn: sqlite3.Connection, project_id: str, card_id: str, blocker_id: str
) -> None:
    require_card(conn, project_id, card_id)
    db.remove_blocked_by_edge(conn, card_id, blocker_id)
```

- [ ] **Step 7: Check `--blocks` cards before inserting the issue in `src/brd/issues.py`**

In `open_issue`, replace:

```python
    for card_id in blocks:
        if db.get_card(conn, card_id) is None:
            raise CardNotFoundError(f"no card with id {card_id}")
```

with:

```python
    for card_id in blocks:
        core.require_card(conn, project_id, card_id)
```

and replace:

```python
    for card_id in blocks:
        core.block_card(conn, card_id, issue.id)
```

with:

```python
    for card_id in blocks:
        core.block_card(conn, project_id, card_id, issue.id)
```

Then remove the now-unused `CardNotFoundError,` line from the `from brd.errors import (...)` block at the top of `src/brd/issues.py`, leaving:

```python
from brd.errors import (
    InvalidCloseReasonError,
    InvalidStatusError,
    IssueNotFoundError,
)
```

- [ ] **Step 8: Use `core.require_card` in the CLI `block` / `unblock` and drop the duplicate**

In `src/brd/cli/cards.py`:

1. Delete the whole module-level `_require_card` function (lines 13-17 originally):

```python
def _require_card(conn: sqlite3.Connection, card_id: str) -> Card:
    card = db.get_card(conn, card_id)
    if card is None:
        raise CardNotFoundError(f"no card with id {card_id}")
    return card
```

2. Delete the import line `from brd.models import Card` (no longer used). Keep `sqlite3`, `db` and `CardNotFoundError`: `delete_entity` and `list` still use them.

3. In `block`, replace the `action` body with:

```python
    def action(ctx):
        core.block_card(ctx.conn, ctx.project.id, card_id, by)
        return views.card_detail(ctx.conn, core.require_card(ctx.conn, ctx.project.id, card_id))
```

4. In `unblock`, replace the `action` body with:

```python
    def action(ctx):
        core.unblock_card(ctx.conn, ctx.project.id, card_id, by)
        return views.card_detail(ctx.conn, core.require_card(ctx.conn, ctx.project.id, card_id))
```

- [ ] **Step 9: Update existing call sites**

Run:

```bash
sed -i -E 's/core\.(block_card|unblock_card)\((p?conn), /core.\1(\2, PROJECT.id, /g' tests/test_core.py tests/test_issues.py
grep -nE "core\.(un)?block_card\(" tests/test_core.py tests/test_issues.py
```

Expected: every match reads `core.block_card(conn, PROJECT.id, ...`, `core.unblock_card(conn, PROJECT.id, ...` or `core.block_card(pconn, PROJECT.id, ...` (18 lines across both files). Both files already import `PROJECT`.

- [ ] **Step 10: Run the tests to verify they pass**

Run: `uv run pytest tests/test_project_scope.py tests/test_cli.py tests/test_core.py tests/test_issues.py tests/test_cli_issues.py -v`
Expected: PASS.

- [ ] **Step 11: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 12: Commit**

```bash
git add src/brd/core.py src/brd/issues.py src/brd/cli/cards.py tests/test_core.py tests/test_issues.py tests/test_project_scope.py tests/test_cli.py
git commit -m "Refuse to block or unblock a card, or block on a target, from another project"
```

---

### Task 5: Scoped `comments.add` on cards

**Files:**
- Modify: `src/brd/comments.py` (`add`, imports)
- Modify: `src/brd/cli/comments.py` (`add` command)
- Modify: `tests/test_comments.py` (call sites, import)
- Test: `tests/test_project_scope.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `core.require_card(conn, project_id, card_id)` (Task 2); `REFUSED`, `two`, `P`, `foreign`, `_refused`, `ok` (Tasks 1-2).
- Produces: `comments.add(conn: sqlite3.Connection, project_id: str, entity_id: str, body: str, author: str) -> Comment`.

- [ ] **Step 1: Write the failing unit test**

In `tests/test_project_scope.py`, add this entry at the end of the `REFUSED` list:

```python
    pytest.param(
        lambda c: comments.add(c, P, "q1", "hi", "alice"), "q1", "card",
        id="comments_add_foreign_card",
    ),
```

- [ ] **Step 2: Write the failing CLI test**

Append to `tests/test_cli.py`:

```python
def test_comment_add_refuses_a_foreign_card(foreign):
    _refused("comment", "add", foreign, "hi")
    assert ok("show", foreign)["comments"] == []
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_project_scope.py tests/test_cli.py -k "comment" -v`
Expected: FAIL — `TypeError: add() takes 4 positional arguments but 5 were given`; the CLI `comment add` exits 0.

- [ ] **Step 4: Implement the check in `src/brd/comments.py`**

Change the import line `from brd import entities, refs` to:

```python
from brd import core, entities, refs
```

Replace the start of `add`, from its `def` through the `require_capability` call:

```python
def add(conn: sqlite3.Connection, entity_id: str, body: str, author: str) -> Comment:
    entities.require_capability(
        conn, entity_id, entities.COMMENTABLE, NotCommentableError, "commented on"
    )
```

with:

```python
def add(
    conn: sqlite3.Connection, project_id: str, entity_id: str, body: str, author: str
) -> Comment:
    kind = entities.require_capability(
        conn, entity_id, entities.COMMENTABLE, NotCommentableError, "commented on"
    )
    if kind == "card":
        # Only cards are scoped to the current project so far; issues follow.
        core.require_card(conn, project_id, entity_id)
```

The rest of `add` is unchanged.

- [ ] **Step 5: Pass the project from the CLI**

In `src/brd/cli/comments.py`, in the `add` command, replace:

```python
            comments.add(ctx.conn, entity_id, text, comments.resolve_author(author))
```

with:

```python
            comments.add(
                ctx.conn, ctx.project.id, entity_id, text, comments.resolve_author(author)
            )
```

- [ ] **Step 6: Update existing call sites in `tests/test_comments.py`**

Replace its import line:

```python
from tests.factories import make_card, make_document, make_issue
```

with:

```python
from tests.factories import PROJECT, make_card, make_document, make_issue
```

then run:

```bash
sed -i 's/comments\.add(pconn, /comments.add(pconn, PROJECT.id, /g' tests/test_comments.py
grep -n "comments.add(" tests/test_comments.py
```

Expected: 8 lines, each `comments.add(pconn, PROJECT.id, ...`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_project_scope.py tests/test_cli.py tests/test_comments.py tests/test_cli_social.py -v`
Expected: PASS.

- [ ] **Step 8: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add src/brd/comments.py src/brd/cli/comments.py tests/test_comments.py tests/test_project_scope.py tests/test_cli.py
git commit -m "Refuse to comment on a card from another project"
```

---

### Task 6: Scoped listings: `list_cards`, `next_cards`, `build_tree`, `snapshot.export`

**Files:**
- Modify: `src/brd/db.py` (`list_cards`)
- Modify: `src/brd/core.py` (`next_cards`, `build_tree`, delete `_require_card`)
- Modify: `src/brd/snapshot.py` (`export`)
- Modify: `src/brd/cli/cards.py` (`list`, `tree`, `next` commands)
- Modify: `src/brd/cli/snapshot.py` (`export` command)
- Modify: `tests/test_db.py`, `tests/test_core.py`, `tests/test_issues.py` (call sites)
- Test: `tests/test_project_scope.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `db.in_project(id_column)` (Task 1); `core.require_card` (Task 2); `REFUSED`, `two`, `P`, `Q`, `foreign`, `_refused`, `ok` (Tasks 1-2).
- Produces:
  - `db.list_cards(conn: sqlite3.Connection, project_id: str, status: str | None = None, parent_id: str | None = _UNSET) -> list[Card]`.
  - `core.next_cards(conn: sqlite3.Connection, project_id: str, limit: int | None = None, parent_id: str | None = None) -> list[Card]`.
  - `core.build_tree(conn: sqlite3.Connection, project_id: str, root_id: str | None = None) -> list[dict]`.
  - `snapshot.export(conn: sqlite3.Connection, project_id: str, root: Path) -> dict`.
  - `core._require_card` no longer exists.

- [ ] **Step 1: Write the failing unit tests**

In `tests/test_project_scope.py`, add these entries at the end of the `REFUSED` list:

```python
    pytest.param(
        lambda c: core.next_cards(c, P, parent_id="q1"), "q1", "card",
        id="next_cards_foreign_parent",
    ),
    pytest.param(
        lambda c: core.build_tree(c, P, root_id="q1"), "q1", "card",
        id="build_tree_foreign_root",
    ),
```

Append to `tests/test_project_scope.py`:

```python
def test_list_cards_returns_only_the_projects_cards(two):
    assert {c.id for c in db.list_cards(two, P)} == {"p1", "p2"}
    assert {c.id for c in db.list_cards(two, P, status="todo")} == {"p1", "p2"}
    assert {c.id for c in db.list_cards(two, P, parent_id=None)} == {"p1", "p2"}
    assert {c.id for c in db.list_cards(two, Q, parent_id=None)} == {"q1"}


def test_list_cards_with_a_foreign_parent_is_empty(two):
    assert db.list_cards(two, P, parent_id="q1") == []


def test_next_cards_skips_other_projects_and_follows_edges_across_them(two):
    assert {c.id for c in core.next_cards(two, P)} == {"p1", "p2"}
    make_card(two, "q-blocker", project_id=Q)
    make_card(two, "p-blocked")
    db.add_blocked_by_edge(two, "p-blocked", "q-blocker")
    assert core.resolve_status(two, db.get_card(two, "p-blocked")) == "blocked"
    assert {c.id for c in db.list_cards(two, P)} == {"p1", "p2", "p-blocked"}
    assert {c.id for c in core.next_cards(two, P)} == {"p1", "p2"}
    db.update_card_fields(two, "q-blocker", status="done")
    assert {c.id for c in core.next_cards(two, P)} == {"p1", "p2", "p-blocked"}


def test_build_tree_holds_only_the_projects_roots(two):
    make_card(two, "p-child", parent_id="p1")
    tree = core.build_tree(two, P)
    assert {node["id"] for node in tree} == {"p1", "p2"}
    p1 = next(node for node in tree if node["id"] == "p1")
    assert [child["id"] for child in p1["children"]] == ["p-child"]


def _tree_ids(nodes):
    return [node["id"] for node in nodes] + [
        child_id for node in nodes for child_id in _tree_ids(node["children"])
    ]


def test_export_cards_hold_only_the_projects_cards(two, tmp_path):
    assert set(_tree_ids(snapshot.export(two, P, tmp_path)["cards"])) == {"p1", "p2"}
```

- [ ] **Step 2: Write the failing CLI tests**

Append to `tests/test_cli.py`:

```python
def test_listings_exclude_a_foreign_card(foreign):
    mine = ok("add", "--title", "mine")["id"]
    assert [c["id"] for c in ok("list")] == [mine]
    assert [c["id"] for c in ok("list", "--status", "todo")] == [mine]
    assert ok("list", "--parent", foreign) == []
    assert [c["id"] for c in ok("next")] == [mine]
    assert [node["id"] for node in ok("tree")] == [mine]
    assert [node["id"] for node in ok("export")["cards"]] == [mine]


def test_next_and_tree_refuse_a_foreign_root(foreign):
    _refused("next", "--parent", foreign)
    _refused("tree", foreign)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_project_scope.py tests/test_cli.py -k "list or next or tree or export or foreign_root" -v`
Expected: FAIL — `TypeError` / wrong results from the old signatures (`db.list_cards(two, P)` treats `P` as a status and returns `[]`; `next_cards(two, P)` treats `P` as `limit`), and the CLI listings include `FOREIGN`.

- [ ] **Step 4: Scope `db.list_cards`**

In `src/brd/db.py`, replace the whole `list_cards` function with:

```python
def list_cards(
    conn: sqlite3.Connection,
    project_id: str,
    status: str | None = None,
    parent_id: str | None = _UNSET,
) -> list[Card]:
    # cards.* only: the scope join brings entities' own id column along.
    query = f"SELECT cards.* FROM cards {in_project('cards.id')} WHERE 1=1"
    params: list[str | None] = [project_id]
    if status is not None:
        query += " AND cards.status = ?"
        params.append(status)
    if parent_id is not _UNSET:
        if parent_id is None:
            query += " AND cards.parent_id IS NULL"
        else:
            query += " AND cards.parent_id = ?"
            params.append(parent_id)
    query += " ORDER BY cards.created_at"
    rows = conn.execute(query, params).fetchall()
    return [_row_to_card(row) for row in rows]
```

- [ ] **Step 5: Scope `next_cards` and `build_tree`, delete `_require_card`**

In `src/brd/core.py`, replace the whole `next_cards` function with:

```python
def next_cards(
    conn: sqlite3.Connection,
    project_id: str,
    limit: int | None = None,
    parent_id: str | None = None,
) -> list[Card]:
    if parent_id is not None:
        require_card(conn, project_id, parent_id)
        candidates = db.list_children(conn, parent_id)
        ready = [card for card in candidates if resolve_status(conn, card) == "todo"]
    else:
        todo_cards = db.list_cards(conn, project_id, status="todo")
        ready = [
            card
            for card in todo_cards
            if resolve_status(conn, card) == "todo"
            and not db.list_children(conn, card.id)
        ]
    return ready[:limit] if limit is not None else ready
```

Replace the whole `build_tree` function with:

```python
def build_tree(
    conn: sqlite3.Connection, project_id: str, root_id: str | None = None
) -> list[dict]:
    if root_id is not None:
        card = require_card(conn, project_id, root_id)
        return [_build_node(conn, card)]

    top_level = db.list_cards(conn, project_id, parent_id=None)
    return [_build_node(conn, card) for card in top_level]
```

Delete the old global function entirely:

```python
def _require_card(conn: sqlite3.Connection, card_id: str) -> Card:
    card = db.get_card(conn, card_id)
    if card is None:
        raise CardNotFoundError(f"no card with id {card_id}")
    return card
```

Then confirm nothing still calls it:

Run: `grep -rn "_require_card" src tests`
Expected: no output.

- [ ] **Step 6: Scope `snapshot.export`**

In `src/brd/snapshot.py`, replace:

```python
def export(conn: sqlite3.Connection, root: Path) -> dict:
    results = documents.sync_all(conn, root)
    return {
        "brd_export": FORMAT_VERSION,
        "cards": core.build_tree(conn),
```

with:

```python
def export(conn: sqlite3.Connection, project_id: str, root: Path) -> dict:
    results = documents.sync_all(conn, root)
    return {
        "brd_export": FORMAT_VERSION,
        "cards": core.build_tree(conn, project_id),
```

- [ ] **Step 7: Pass the project from the CLI**

In `src/brd/cli/cards.py`:

In `list_cards_cmd`'s `action`, replace:

```python
        return [views.card_detail(ctx.conn, card) for card in db.list_cards(ctx.conn, **kwargs)]
```

with:

```python
        return [
            views.card_detail(ctx.conn, card)
            for card in db.list_cards(ctx.conn, ctx.project.id, **kwargs)
        ]
```

In `tree`, replace:

```python
        lambda ctx: core.build_tree(ctx.conn, root_id=card_id),
```

with:

```python
        lambda ctx: core.build_tree(ctx.conn, ctx.project.id, root_id=card_id),
```

In `next_cmd`'s `action`, replace:

```python
        cards = core.next_cards(ctx.conn, limit=limit, parent_id=parent)
```

with:

```python
        cards = core.next_cards(ctx.conn, ctx.project.id, limit=limit, parent_id=parent)
```

In `src/brd/cli/snapshot.py`, replace:

```python
    run(pretty, lambda ctx: snapshot.export(ctx.conn, Path(ctx.project.root_path)))
```

with:

```python
    run(
        pretty,
        lambda ctx: snapshot.export(ctx.conn, ctx.project.id, Path(ctx.project.root_path)),
    )
```

- [ ] **Step 8: Update existing call sites**

Run:

```bash
sed -i 's/db\.list_cards(project_conn/db.list_cards(project_conn, PROJECT.id/g' tests/test_db.py
sed -i -E 's/core\.(next_cards|build_tree)\(([a-z_]*conn)/core.\1(\2, PROJECT.id/g' tests/test_core.py tests/test_issues.py
grep -nE "db\.list_cards\(|core\.(next_cards|build_tree)\(" tests/test_db.py tests/test_core.py tests/test_issues.py
```

Expected: every match carries `PROJECT.id` as the second argument, e.g. `db.list_cards(project_conn, PROJECT.id)`, `db.list_cards(project_conn, PROJECT.id, status="done")`, `core.next_cards(conn, PROJECT.id, limit=2)`, `core.build_tree(fresh_conn, PROJECT.id)`, `core.build_tree(conn, PROJECT.id, root_id="nope")`, `core.next_cards(pconn, PROJECT.id)`. All three files already import `PROJECT`.

- [ ] **Step 9: Run the tests to verify they pass**

Run: `uv run pytest tests/test_project_scope.py tests/test_cli.py tests/test_core.py tests/test_db.py tests/test_issues.py tests/test_snapshot.py -v`
Expected: PASS.

- [ ] **Step 10: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 11: Commit**

```bash
git add src/brd/db.py src/brd/core.py src/brd/snapshot.py src/brd/cli/cards.py src/brd/cli/snapshot.py tests/test_db.py tests/test_core.py tests/test_issues.py tests/test_project_scope.py tests/test_cli.py
git commit -m "List, next, tree and export show only the current project's cards"
```

---

### Task 7: `brd show` names the owning project

**Files:**
- Modify: `src/brd/views.py` (`detail`)
- Modify: `tests/test_snapshot.py` (`test_round_trip_into_fresh_project` compares `show` output across two projects)
- Test: `tests/test_project_scope.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `db.owner_of(conn, entity_id) -> Project | None` (Task 1); `two`, `foreign`, `ok`, `err` (Tasks 1-2).
- Produces: `views.detail(conn, root, entity_id) -> dict` whose result has one extra key `"project": {"id": str, "name": str}`. Signature unchanged.

- [ ] **Step 1: Write the failing unit tests**

Append to `tests/test_project_scope.py`:

```python
@pytest.mark.parametrize(
    ("entity_id", "owner", "expected"),
    [
        ("p1", PROJECT, lambda c, root: views.card_detail(c, db.get_card(c, "p1"))),
        ("q1", OTHER_PROJECT, lambda c, root: views.card_detail(c, db.get_card(c, "q1"))),
        ("qi", OTHER_PROJECT, lambda c, root: views.issue_detail(c, issues.require(c, "qi"))),
        (
            "qd",
            OTHER_PROJECT,
            lambda c, root: views.document_detail(
                c, documents.require(c, "qd"), documents.sync(c, root, documents.require(c, "qd"))
            ),
        ),
    ],
    ids=["own_card", "foreign_card", "foreign_issue", "foreign_document"],
)
def test_detail_is_global_and_names_the_owner(two, tmp_path, entity_id, owner, expected):
    shown = views.detail(two, tmp_path, entity_id)
    assert shown.pop("project") == {"id": owner.id, "name": owner.name}
    assert shown == expected(two, tmp_path)


def test_detail_of_a_missing_id_is_unchanged(two, tmp_path):
    with pytest.raises(CardNotFoundError, match=r"^no card, issue, or document with id nope$"):
        views.detail(two, tmp_path, "nope")


def test_card_detail_has_no_project_key(two):
    assert "project" not in views.card_detail(two, db.get_card(two, "p1"))
```

- [ ] **Step 2: Write the failing CLI test**

Append to `tests/test_cli.py`:

```python
def test_show_is_global_and_names_the_owner(foreign):
    mine = ok("add", "--title", "mine")["id"]
    assert ok("show", foreign)["project"] == {
        "id": OTHER_PROJECT.id,
        "name": OTHER_PROJECT.name,
    }
    registered = ok("projects")[0]
    assert ok("show", mine)["project"] == {"id": registered["id"], "name": registered["name"]}
    assert "project" not in ok("list")[0]
    assert err("show", "nope") == "CardNotFoundError"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_project_scope.py tests/test_cli.py -k "detail or show_is_global" -v`
Expected: FAIL with `KeyError: 'project'` (unit) and `KeyError: 'project'` on the CLI show payload.

- [ ] **Step 4: Add the owner to `views.detail`**

In `src/brd/views.py`, replace the whole `detail` function with:

```python
def detail(conn: sqlite3.Connection, root: Path, entity_id: str) -> dict:
    kind = entities.kind_of(conn, entity_id)
    if kind is None:
        raise CardNotFoundError(f"no card, issue, or document with id {entity_id}")
    # show is global: any project's entity, labelled with the project owning it.
    owner = db.owner_of(conn, entity_id)
    # Documents may have been edited on disk; sync them all so backlinks
    # (referenced_by) reflect their current content.
    results = documents.sync_all(conn, root)
    if kind == "document":
        shown = document_detail(conn, documents.require(conn, entity_id), results[entity_id])
    elif kind == "issue":
        shown = issue_detail(conn, issues.require(conn, entity_id))
    else:
        shown = card_detail(conn, db.get_card(conn, entity_id))
    return {**shown, "project": {"id": owner.id, "name": owner.name}}
```

- [ ] **Step 5: Keep the snapshot round-trip test honest about the new key**

`tests/test_snapshot.py::test_round_trip_into_fresh_project` compares `brd show` output before and after importing into a second project; `project` now legitimately differs between the two (verified: this is the only existing test that breaks). In that test, replace:

```python
    for data in (before, after):
        data[populated["doc"]["id"]].pop("source_state")
    assert before == after
```

with:

```python
    for data in (before, after):
        data[populated["doc"]["id"]].pop("source_state")
    # `show` names the owning project, which differs between the two boards.
    assert {s["project"]["id"] for s in before.values()}.isdisjoint(
        {s["project"]["id"] for s in after.values()}
    )
    for data in (before, after):
        for shown in data.values():
            shown.pop("project")
    assert before == after
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_project_scope.py tests/test_cli.py tests/test_snapshot.py tests/test_pretty.py tests/test_cli_docs.py -v`
Expected: PASS (`test_pretty.py` confirms `--pretty` show output is unchanged).

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass (471 original plus the new tests).

- [ ] **Step 8: Commit**

```bash
git add src/brd/views.py tests/test_snapshot.py tests/test_project_scope.py tests/test_cli.py
git commit -m "Show names the project that owns the entity"
```
<!-- task-pipeline: validated -->
