# 2.2 Deleting an entity removes edges that point at it

Card: `a6a8dd67-4821-4c10-b8f0-96882f93a3b8` (subtask of story `54de5e9d` "Project-scoped
schema", milestone `6aa7043a` "Single database and cross-project blocking"). Blocked by
2.1 (`5b54e4f6`, done on this branch's parent).

Parent design spec: `docs/superpowers/specs/2026-10-06-single-db-cross-project-blocking-design.md`
(commit `98c42de`; not in this branch's history, cited by section and line number in
that commit). Cited below as **[P §n Lx]**.

## Goal

Make every `brd delete` path remove the edges that point **at** the deleted entity
(`blocked_by` rows whose `blocks_on_id` is the entity, `refs` rows whose `dst_id` is the
entity) with explicit SQL, instead of relying on the `ON DELETE CASCADE` foreign keys on
those two columns. Card 2.3 drops those foreign keys [P §1 L68-80, D6 L36]; once it does,
the cascade no longer happens, and only the explicit deletes keep today's behaviour.

Today this card is **behaviour-preserving**: with `PRAGMA foreign_keys=ON`
(`src/brd/db.py:15`) the cascade on `blocked_by.blocks_on_id` (`src/brd/db.py:105`) and
`refs.dst_id` (`src/brd/db.py:152`) already removes these rows. The new tests prove the
explicit deletes do the work on their own by running with foreign keys switched off.

## Inherited constraints

| Constraint | Source |
|---|---|
| `brd delete` removes edges pointing at the deleted entity (today's behaviour). | [P D8 L38] |
| `core.delete_card`, the issue delete path and `documents.delete` run `DELETE FROM blocked_by WHERE blocks_on_id = ?` and `DELETE FROM refs WHERE dst_id = ?`. | [P §1 L92-94] |
| Deleting an entity still cascades its *own* rows (row in `cards`/`issues`/`documents`, comments, tags, outgoing `blocked_by` and `refs`) through the FKs that stay. | [P §1 L90-91; schema L69, L75] |
| `brd forget` does **not** remove incoming edges from other projects. | [P D8 L38; §1 L95-96] |
| The explicit incoming-edge cleanup lands in phase 2 so in-board behaviour is unchanged when the FKs go. | [P Implementation order L276-279] |
| Test: "`delete` removes incoming edges". | [P Testing L265] |

## Current delete paths

All three end in `DELETE FROM entities WHERE id = ?` and rely on the cascade:

| Entity | Route from `brd delete` (`src/brd/cli/cards.py:117-127`, `delete_entity`) | Function that issues the DELETE |
|---|---|---|
| card | `core.delete_card` (`src/brd/core.py:209-224`, recursive with `cascade=True`) | `db.delete_card` (`src/brd/db.py:426-429`) |
| issue | falls through to `entities.delete` (`cards.py:126`) — there is no `issues.delete` | `entities.delete` (`src/brd/entities.py:57-59`) |
| document | `documents.delete` (`src/brd/documents.py:247-250`) | `entities.delete`, then the backup file is unlinked |

The parent spec names `issues.delete` [P §1 L92]; that function does not exist. The issue
path is `entities.delete`, and this card covers it there. Adding an `issues.delete`
wrapper is not required. A later card can add one if it needs one.

## Behaviour

### B1. Incoming edges are removed on every delete path

After any of the following returns for entity `X`:

- `db.delete_card(conn, X)`
- `core.delete_card(conn, X)` / `core.delete_card(conn, X, cascade=True)` (for `X` and
  for every descendant it deletes)
- `entities.delete(conn, X)` (any kind; this is the issue path)
- `documents.delete(conn, X)`

the database contains:

- no `blocked_by` row with `blocks_on_id = X`, and
- no `refs` row with `dst_id = X` (whatever its `origin`: `explicit` or `link`),

**whether or not `PRAGMA foreign_keys` is on.** The cleanup is unconditional per kind. It
runs for documents in `blocked_by` too, even though documents cannot be blockers
(`entities.BLOCKERS`, `src/brd/entities.py:9`). Deleting an id that has no incoming
edges is a no-op for those tables.

### B2. Only incoming edges of the deleted entity are touched

The explicit deletes match the deleted id exactly. Edges among other entities survive,
and so do edges whose source is another entity and whose target is not `X`. Example:
`c3 → c1`, `c3 → c2` in `blocked_by`; deleting `c1` leaves `c3 → c2`.

### B3. Own-side rows are unchanged in how they go

Outgoing `blocked_by` (`card_id = X`) and `refs` (`src_id = X`), comments, tags and the
kind row keep going through the FK cascade from `entities`. This card adds no explicit
SQL for them. With FKs on, the observable end state is the same as today: the entity
and all its rows in both directions are gone.

### B4. One transaction per delete call

In each function, the two edge deletes and `DELETE FROM entities` run in the same
transaction, before the entity row is deleted, with the single existing `commit()` at
the end. A delete never commits a state where the entity is gone but its incoming edges
remain, or the reverse. `core.delete_card` with `cascade=True` still commits once per
card, as today (each recursive `db.delete_card` commits). Making the whole subtree
atomic is out of scope.

### B5. User-visible results unchanged

- `brd delete <issue>` where the issue blocks card `C`: afterwards `brd show C` has
  `blocked_by: []` and status `todo` (if `C` has no other blockers).
- `brd delete <card>` where the card blocks `C`: same.
- `brd delete <x>` where another entity `S` references `x` (explicitly or by
  `[[link]]`): `S`'s outgoing refs no longer list `x`. Today `refs.outgoing` builds
  each row from `entities.summary`, which returns `None` for a missing entity
  (`src/brd/refs.py:112-121`). A leftover dangling `dst_id` would crash `show`. That is
  why the cleanup must happen once the FK is gone.
- Return values and errors of all delete functions and of `brd delete` are unchanged
  (`CardNotFoundError`, `CardHasChildrenError`, `DocumentNotFoundError` paths untouched).

### Implementation guidance (non-normative)

Put the two DELETEs in one place in `db.py`, a helper that doesn't commit (e.g.
`db.delete_incoming_edges(conn, entity_id)`). Call it from `db.delete_card` and from
`entities.delete` right before their `DELETE FROM entities`. `documents.delete` goes
through `entities.delete` and needs no change of its own. `entities` currently imports
nothing from `brd`. Importing `brd.db` from it is safe, because `db` only imports
`brd.errors` and `brd.models`. Update the comment on `db.delete_card`
(`src/brd/db.py:427`) so it says incoming edges are deleted explicitly.

## Tests

Tiers in this repo: **unit** = module functions against a real temporary SQLite file
(`tests/test_db.py`, `test_core.py`, `test_entities.py`, `test_documents.py`), using the
`pconn`/`conn`/`project_conn` fixtures and `tests/factories.py`. **CLI** = Typer app via
`tests/cli_helpers.ok/err` with the `project` fixture.

**How the FK-off tests work.** Build the edges with FKs on (normal fixtures). Then call
`conn.commit()` and `conn.execute("PRAGMA foreign_keys=OFF")`; the pragma is ignored
inside an open transaction, so commit first. Call the delete function, and assert with
raw `SELECT COUNT(*)` on `blocked_by` / `refs`. With FKs off, only the explicit DELETEs
can remove those rows. This simulates the post-2.3 schema. Each of these tests fails
before the change. Do not assert own-side rows in FK-off tests, because those rely on
the cascade by design (B3).

| # | Test | File | Tier | Why this tier | Proves |
|---|---|---|---|---|---|
| T1 | `test_delete_card_removes_incoming_edges_without_fk_cascade`: cards `c1,c2,c3`, `c3` blocked by `c1` and by `c2`, explicit ref `c2 → c1` and a link ref `c3 → c1` (raw INSERT into `refs` is fine); FK off; `db.delete_card(c1)`. | `tests/test_db.py` | unit | `db.delete_card` is the lowest function that issues the delete; checks the SQL directly. | B1 (blocked_by + both ref origins), B2 (`c3 → c2` edge survives) |
| T2 | `test_delete_card_cascade_removes_incoming_edges_of_every_deleted_card`: parent `P` → child `C` → grandchild `G`; outsider card `O` blocked by `C` and by `G`, explicit refs `O → P`, `O → G`, and `O` also blocked by unrelated card `U`; FK off; `core.delete_card(P, cascade=True)`. | `tests/test_core.py` | unit | Recursion lives in `core.delete_card`; must show each descendant's incoming edges go, not only the root's. | B1 for the subtree, B2 (`O → U` survives) |
| T3 | `test_delete_issue_removes_incoming_edges_without_fk_cascade`: `issues.open_issue(..., blocks=[card])` plus an explicit ref from another card to the issue; FK off; `entities.delete(issue)`. Assert no `blocked_by` with `blocks_on_id = issue`, no `refs` with `dst_id = issue`. | `tests/test_entities.py` | unit | `entities.delete` is the issue path (`cli/cards.py:126`). | B1 for issues |
| T4 | `test_delete_document_removes_incoming_refs_without_fk_cascade`: document added via `documents.add`; a card with an explicit ref to it and a card whose description links it with `[[stem]]` (reindexed); FK off; `documents.delete(doc)`. Assert no `refs.dst_id = doc`; backup file gone; source file kept. | `tests/test_documents.py` | unit | `documents.delete` adds backup handling around `entities.delete`; checks both survive together. | B1 for documents, B5 (backup/source unchanged) |
| T5 | `test_delete_issue_unblocks_card` (CLI): `brd add` card `C`, `brd issue open --blocks C`, `brd delete <issue>`; `brd show C` has `blocked_by == []` and `status == "todo"`. | `tests/test_cli_issues.py` | CLI | Pins the user-visible D8 contract through `delete_entity` routing. Passes before and after (FK on); it is a regression guard that keeps meaning after 2.3. | B5 |
| T6 | `test_delete_card_with_fk_on_removes_edges_both_directions` — **already exists** as `tests/test_db.py:561`, `test_core.py:302`; keep green. Also keep `test_entities.py:42`, `test_documents.py:225`, `test_migration.py:90,120`, `test_cli.py:392-430` green. | existing | unit/CLI | Proves B3: own-side cascade and overall behaviour unchanged with FKs on. | B3, B5 |

`tests/test_issues.py:103` and `tests/test_refs.py:95` delete with raw
`DELETE FROM entities` and so bypass the code under change. Leave them as they are.
They test status/refs reads over a cascaded database, not the delete API.

Full verification: `uv run pytest` (no lint or typecheck configured).

## Out of scope

- **`brd forget`** (`db.delete_project` `src/brd/db.py:322`, `master.forget_project`,
  `cli/project.py`). It must *not* gain incoming-edge cleanup: per D8 it keeps incoming
  edges from other projects as not-found. That change belongs to the cross-project
  phase [P Implementation order L281-283].
- **Dropping the FKs** on `blocked_by.blocks_on_id` / `refs.dst_id`, adding the
  `blocked_by_target` / `refs_target` indexes, `entities.project_id`: card 2.3
  [P §1 L55-80].
- **Import's project replacement** (must keep incoming edges, D8): export/import v2
  phase [P §5 L228-231].
- Making `core.delete_card --cascade` a single transaction.
- Explicit SQL for own-side rows (outgoing edges, comments, tags): they stay on the FK
  cascade.
- Adding an `issues.delete` function or changing `delete_entity` routing.
- Not-found edge reporting and the `blockers` output: cross-project phase.

---

# Deleting an Entity Removes Its Incoming Edges Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every `brd delete` path removes the `blocked_by` rows with `blocks_on_id = X` and the `refs` rows with `dst_id = X` through explicit SQL, so the behaviour holds once card 2.3 drops the `ON DELETE CASCADE` foreign keys on those columns.

**Architecture:** One non-committing helper, `db.delete_incoming_edges(conn, entity_id)`, issues the two DELETEs. `db.delete_card` (card path, used recursively by `core.delete_card`) and `entities.delete` (issue path; also the document path through `documents.delete`) call it right before their `DELETE FROM entities`, and the existing single `commit()` covers all three statements. Own-side rows stay on the FK cascade.

**Tech Stack:** Python 3, stdlib `sqlite3`, Typer CLI, pytest, run with `uv run pytest`.

**Spec:** `docs/superpowers/specs/2-2-deleting-an-entity-a6a8dd67.md` (reproduced above).

## Global Constraints

- The explicit deletes are exactly `DELETE FROM blocked_by WHERE blocks_on_id = ?` and `DELETE FROM refs WHERE dst_id = ?` [P §1 L92-94].
- Run them unconditionally for every kind (documents included), before `DELETE FROM entities`, with no extra `commit()`: the existing single commit at the end of each delete function covers them (B4).
- No explicit SQL for own-side rows (outgoing `blocked_by`/`refs`, comments, tags, kind row): they stay on the FK cascade (B3).
- Do not touch `db.delete_project`, `master.forget_project`, `cli/project.py` (`brd forget`), `delete_entity` routing, or the schema/FKs. Do not add `issues.delete`.
- Return values and errors of every delete function and of `brd delete` stay unchanged.
- FK-off tests: build edges with FKs on, then `conn.commit()` followed by `conn.execute("PRAGMA foreign_keys=OFF")` (the pragma is ignored inside an open transaction), then delete, then assert with raw `SELECT COUNT(*)`. Never assert own-side rows in an FK-off test.
- Leave `tests/test_issues.py:103` and `tests/test_refs.py:95` (raw `DELETE FROM entities`) as they are.
- Full verification: `uv run pytest` (no lint or typecheck configured). Baseline before this work: 434 passed.

## Review Focus

1. **The helper commits on its own (B4).** If `delete_incoming_edges` called `commit()`, a crash between it and `DELETE FROM entities` would leave the entity with its incoming edges gone. Expected: after the helper, the connection is still in a transaction and `rollback()` brings the edges back. Pinned by `test_delete_incoming_edges_does_not_commit` (Task 1).
2. **A dangling `refs.dst_id` crashes `show` (B5).** `refs.outgoing` builds each row from `entities.summary`, which returns `None` for a missing entity, so `{**None}` raises `TypeError`. Expected: after deleting a referenced document with FKs off, `refs.outgoing(src)` of the referencing cards is `[]`. Pinned in `test_delete_document_removes_incoming_refs_without_fk_cascade` (Task 2).
3. **A card blocked only by a deleted issue stays `blocked` (B5).** Expected: with FKs off, after `entities.delete(issue)` the card's resolved status is `todo`. Pinned in `test_delete_issue_removes_incoming_edges_without_fk_cascade` (Task 2), and through the CLI with FKs on in `test_delete_issue_unblocks_card` (Task 2).
4. **Descendants of a cascaded card delete keep their incoming edges.** Cleanup only on the root would leave edges pointing at deleted children. Expected: every deleted card's incoming edges go. Pinned by `test_delete_card_cascade_removes_incoming_edges_of_every_deleted_card` (Task 1).
5. **The DELETE matches more than the deleted id (B2).** E.g. a `card_id = ?` or `src_id = ?` slip removes the blocked card's other edges. Expected: edges among other entities survive (`c3 → c2`, `O → U`). Pinned in `test_delete_card_removes_incoming_edges_without_fk_cascade` and the cascade test (Task 1).

---

### Task 1: `db.delete_incoming_edges` and the card delete path

**Files:**
- Modify: `src/brd/db.py:426-429` (`delete_card`), add `delete_incoming_edges` directly above it
- Test: `tests/test_db.py` (append after `test_delete_card_removes_blocked_by_edges_in_both_directions`, which ends at line 571)
- Test: `tests/test_core.py` (append after `test_delete_card_removes_blocked_by_edges`, which ends at line 309)

**Interfaces:**
- Consumes: nothing new. Existing: `db.insert_card(conn, Card)`, `db.add_blocked_by_edge(conn, card_id, blocks_on_id)`, `db.list_blockers_of(conn, card_id) -> list[str]`, `core.create_card(conn, title, description=None, parent_id=None, blocked_by=None) -> Card`, `core.block_card(conn, card_id, blocker_id)`, `core.delete_card(conn, card_id, cascade=False) -> list[str]`, `refs.add_explicit(conn, src_id, dst_id)` (imported in `test_core.py` as `_refs`).
- Produces: `db.delete_incoming_edges(conn: sqlite3.Connection, entity_id: str) -> None` — deletes `blocked_by` rows with `blocks_on_id = entity_id` and `refs` rows with `dst_id = entity_id`; does **not** commit. Task 2 calls it from `entities.delete`.

- [ ] **Step 1: Write the failing tests in `tests/test_db.py`**

Append after `test_delete_card_removes_blocked_by_edges_in_both_directions` (the `project_conn` fixture and `_sample_card` helper already exist in this file):

```python
def _count(conn, sql, *params):
    return conn.execute(sql, params).fetchone()[0]


def test_delete_card_removes_incoming_edges_without_fk_cascade(project_conn):
    for card_id in ("c1", "c2", "c3"):
        db.insert_card(project_conn, _sample_card(card_id))
    db.add_blocked_by_edge(project_conn, "c3", "c1")
    db.add_blocked_by_edge(project_conn, "c3", "c2")
    project_conn.execute(
        "INSERT INTO refs (src_id, dst_id, origin) VALUES "
        "('c2', 'c1', 'explicit'), ('c3', 'c1', 'link')"
    )
    project_conn.commit()
    project_conn.execute("PRAGMA foreign_keys=OFF")

    db.delete_card(project_conn, "c1")

    assert _count(
        project_conn, "SELECT COUNT(*) FROM blocked_by WHERE blocks_on_id = ?", "c1"
    ) == 0
    assert _count(project_conn, "SELECT COUNT(*) FROM refs WHERE dst_id = ?", "c1") == 0
    assert db.list_blockers_of(project_conn, "c3") == ["c2"]


def test_delete_incoming_edges_does_not_commit(project_conn):
    db.insert_card(project_conn, _sample_card("c1"))
    db.insert_card(project_conn, _sample_card("c2"))
    db.add_blocked_by_edge(project_conn, "c2", "c1")
    project_conn.execute(
        "INSERT INTO refs (src_id, dst_id, origin) VALUES ('c2', 'c1', 'explicit')"
    )
    project_conn.commit()

    db.delete_incoming_edges(project_conn, "c1")
    assert project_conn.in_transaction
    project_conn.rollback()

    assert db.list_blockers_of(project_conn, "c2") == ["c1"]
    assert _count(project_conn, "SELECT COUNT(*) FROM refs WHERE dst_id = ?", "c1") == 1
```

- [ ] **Step 2: Write the failing test in `tests/test_core.py`**

Append after `test_delete_card_removes_blocked_by_edges` (`conn` fixture, `core`, `db` and `_refs` are already imported/defined in this file):

```python
def test_delete_card_cascade_removes_incoming_edges_of_every_deleted_card(conn):
    parent = core.create_card(conn, title="P")
    child = core.create_card(conn, title="C", parent_id=parent.id)
    grandchild = core.create_card(conn, title="G", parent_id=child.id)
    outsider = core.create_card(conn, title="O")
    unrelated = core.create_card(conn, title="U")
    core.block_card(conn, outsider.id, child.id)
    core.block_card(conn, outsider.id, grandchild.id)
    core.block_card(conn, outsider.id, unrelated.id)
    _refs.add_explicit(conn, outsider.id, parent.id)
    _refs.add_explicit(conn, outsider.id, grandchild.id)
    conn.commit()
    conn.execute("PRAGMA foreign_keys=OFF")

    deleted = core.delete_card(conn, parent.id, cascade=True)

    assert set(deleted) == {parent.id, child.id, grandchild.id}
    for card_id in deleted:
        assert conn.execute(
            "SELECT COUNT(*) FROM blocked_by WHERE blocks_on_id = ?", (card_id,)
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM refs WHERE dst_id = ?", (card_id,)
        ).fetchone()[0] == 0
    assert db.list_blockers_of(conn, outsider.id) == [unrelated.id]
```

- [ ] **Step 3: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_db.py::test_delete_card_removes_incoming_edges_without_fk_cascade tests/test_db.py::test_delete_incoming_edges_does_not_commit tests/test_core.py::test_delete_card_cascade_removes_incoming_edges_of_every_deleted_card -v`

Expected: 3 FAILED.
- `test_delete_card_removes_incoming_edges_without_fk_cascade`: `assert 1 == 0` on the `blocked_by` count (FK off, so nothing cascades).
- `test_delete_incoming_edges_does_not_commit`: `AttributeError: module 'brd.db' has no attribute 'delete_incoming_edges'`.
- `test_delete_card_cascade_removes_incoming_edges_of_every_deleted_card`: `assert 1 == 0` on the `blocked_by` count for the first deleted card that has an incoming edge.

- [ ] **Step 4: Implement the helper and call it from `db.delete_card`**

In `src/brd/db.py`, replace the current `delete_card` (lines 426-429):

```python
def delete_card(conn: sqlite3.Connection, card_id: str) -> None:
    # Cascades to the cards row, its block edges, comments, tags, and refs.
    conn.execute("DELETE FROM entities WHERE id = ?", (card_id,))
    conn.commit()
```

with:

```python
def delete_incoming_edges(conn: sqlite3.Connection, entity_id: str) -> None:
    # Edges pointing at entity_id. Explicit rather than an FK cascade so it
    # holds without one; no commit, so callers delete the entity in the same
    # transaction.
    conn.execute("DELETE FROM blocked_by WHERE blocks_on_id = ?", (entity_id,))
    conn.execute("DELETE FROM refs WHERE dst_id = ?", (entity_id,))


def delete_card(conn: sqlite3.Connection, card_id: str) -> None:
    # Incoming edges are deleted explicitly; the entities cascade takes the
    # cards row, its outgoing block edges and refs, comments, and tags.
    delete_incoming_edges(conn, card_id)
    conn.execute("DELETE FROM entities WHERE id = ?", (card_id,))
    conn.commit()
```

`core.delete_card` needs no change: it already calls `db.delete_card` for the root and every descendant.

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `uv run pytest tests/test_db.py::test_delete_card_removes_incoming_edges_without_fk_cascade tests/test_db.py::test_delete_incoming_edges_does_not_commit tests/test_core.py::test_delete_card_cascade_removes_incoming_edges_of_every_deleted_card -v`

Expected: 3 passed.

- [ ] **Step 6: Run the full suite (FK-on regression guard, T6)**

Run: `uv run pytest`

Expected: all pass (437 passed), including the existing `test_delete_card_removes_blocked_by_edges_in_both_directions` (`tests/test_db.py:561`) and `test_delete_card_removes_blocked_by_edges` (`tests/test_core.py:302`).

- [ ] **Step 7: Commit**

```bash
git add src/brd/db.py tests/test_db.py tests/test_core.py
git commit -m "Delete a card's incoming edges explicitly instead of by FK cascade"
```

---

### Task 2: The issue and document delete path (`entities.delete`)

**Files:**
- Modify: `src/brd/entities.py:1-3` (imports), `src/brd/entities.py:57-59` (`delete`)
- Test: `tests/test_entities.py` (imports at lines 1-5; append after `test_delete_cascades`, which ends at line 46)
- Test: `tests/test_documents.py` (imports at lines 1-13; append after `test_delete_removes_backup_keeps_source`, which ends at line 231)
- Test: `tests/test_cli_issues.py` (append after `test_delete_issue`, which ends at line 58)

**Interfaces:**
- Consumes: `db.delete_incoming_edges(conn: sqlite3.Connection, entity_id: str) -> None` from Task 1 (no commit). Existing: `issues.open_issue(conn, title, body=None, ref_ids=None, blocks=None) -> Issue` (`.id`), `refs.add_explicit(conn, src_id, dst_id)`, `refs.outgoing(conn, entity_id) -> list[dict]`, `core.create_card(...) -> Card` (reindexes `[[links]]` in `description`), `core.resolve_status(conn, card) -> str`, `db.get_card(conn, id) -> Card | None`, `documents.add(conn, root, path) -> Document`, `documents.delete(conn, doc_id)`, `documents.backup_path(conn, doc_id) -> Path`, `tests.factories.make_card(conn, id_)`.
- Produces: `entities.delete(conn, entity_id) -> None` with unchanged signature and return; now removes incoming edges before deleting the entity, in the same transaction.

- [ ] **Step 1: Write the failing test in `tests/test_entities.py`**

Change the imports at the top of the file from:

```python
import pytest

from brd import entities
from brd.errors import EntityNotFoundError, NotTaggableError
from tests.factories import make_card, make_document, make_issue
```

to:

```python
import pytest

from brd import core, db, entities, issues, refs
from brd.errors import EntityNotFoundError, NotTaggableError
from tests.factories import make_card, make_document, make_issue
```

Append after `test_delete_cascades`:

```python
def test_delete_issue_removes_incoming_edges_without_fk_cascade(pconn):
    make_card(pconn, "blocked")
    make_card(pconn, "citer")
    issue = issues.open_issue(pconn, "Q", blocks=["blocked"])
    refs.add_explicit(pconn, "citer", issue.id)
    pconn.commit()
    pconn.execute("PRAGMA foreign_keys=OFF")

    entities.delete(pconn, issue.id)

    assert pconn.execute(
        "SELECT COUNT(*) FROM blocked_by WHERE blocks_on_id = ?", (issue.id,)
    ).fetchone()[0] == 0
    assert pconn.execute(
        "SELECT COUNT(*) FROM refs WHERE dst_id = ?", (issue.id,)
    ).fetchone()[0] == 0
    assert core.resolve_status(pconn, db.get_card(pconn, "blocked")) == "todo"
    assert refs.outgoing(pconn, "citer") == []
```

- [ ] **Step 2: Write the failing test in `tests/test_documents.py`**

Append after `test_delete_removes_backup_keeps_source` (`core`, `documents`, `refs` are already imported; `pconn`, `root` and `write` exist):

```python
def test_delete_document_removes_incoming_refs_without_fk_cascade(pconn, root):
    path = write(root, "docs/a.md", "v1")
    doc = documents.add(pconn, root, path)
    explicit = core.create_card(pconn, title="Explicit")
    refs.add_explicit(pconn, explicit.id, doc.id)
    linker = core.create_card(pconn, title="Linker", description="see [[a]]")
    assert pconn.execute(
        "SELECT COUNT(*) FROM refs WHERE dst_id = ?", (doc.id,)
    ).fetchone()[0] == 2
    pconn.commit()
    pconn.execute("PRAGMA foreign_keys=OFF")

    documents.delete(pconn, doc.id)

    assert pconn.execute(
        "SELECT COUNT(*) FROM refs WHERE dst_id = ?", (doc.id,)
    ).fetchone()[0] == 0
    assert refs.outgoing(pconn, explicit.id) == []
    assert refs.outgoing(pconn, linker.id) == []
    assert not documents.backup_path(pconn, doc.id).exists()
    assert path.read_text() == "v1"
```

- [ ] **Step 3: Write the CLI regression guard in `tests/test_cli_issues.py`**

Append after `test_delete_issue`:

```python
def test_delete_issue_unblocks_card(project):
    card = ok("add", "--title", "Work")
    issue = ok("issue", "open", "--title", "Q", "--blocks", card["id"])
    assert ok("show", card["id"])["status"] == "blocked"

    ok("delete", issue["id"])

    shown = ok("show", card["id"])
    assert (shown["blocked_by"], shown["status"]) == ([], "todo")
```

- [ ] **Step 4: Run the new tests to verify the unit tests fail**

Run: `uv run pytest tests/test_entities.py::test_delete_issue_removes_incoming_edges_without_fk_cascade tests/test_documents.py::test_delete_document_removes_incoming_refs_without_fk_cascade tests/test_cli_issues.py::test_delete_issue_unblocks_card -v`

Expected:
- `test_delete_issue_removes_incoming_edges_without_fk_cascade`: FAILED, `assert 1 == 0` on the `blocked_by` count.
- `test_delete_document_removes_incoming_refs_without_fk_cascade`: FAILED, `assert 2 == 0` on the `refs` count.
- `test_delete_issue_unblocks_card`: PASSED. It runs with FKs on, so today's cascade already does the work. It is a regression guard for the user-visible contract that keeps its meaning once 2.3 drops the FKs; it is not expected to fail first.

- [ ] **Step 5: Implement the explicit delete in `entities.delete`**

In `src/brd/entities.py`, change the imports from:

```python
import sqlite3

from brd.errors import BrdError, EntityNotFoundError
```

to:

```python
import sqlite3

from brd import db
from brd.errors import BrdError, EntityNotFoundError
```

(`brd.db` imports only `brd.errors` and `brd.models`, so this adds no import cycle.)

Replace `delete` (lines 57-59):

```python
def delete(conn: sqlite3.Connection, entity_id: str) -> None:
    conn.execute("DELETE FROM entities WHERE id = ?", (entity_id,))
    conn.commit()
```

with:

```python
def delete(conn: sqlite3.Connection, entity_id: str) -> None:
    db.delete_incoming_edges(conn, entity_id)
    conn.execute("DELETE FROM entities WHERE id = ?", (entity_id,))
    conn.commit()
```

`documents.delete` calls `entities.delete` and needs no change.

- [ ] **Step 6: Run the new tests to verify they pass**

Run: `uv run pytest tests/test_entities.py::test_delete_issue_removes_incoming_edges_without_fk_cascade tests/test_documents.py::test_delete_document_removes_incoming_refs_without_fk_cascade tests/test_cli_issues.py::test_delete_issue_unblocks_card -v`

Expected: 3 passed.

- [ ] **Step 7: Run the full suite (T6)**

Run: `uv run pytest`

Expected: all pass (440 passed), including `tests/test_entities.py::test_delete_cascades`, `tests/test_documents.py::test_delete_removes_backup_keeps_source`, the `tests/test_migration.py` and `tests/test_cli.py` delete tests.

- [ ] **Step 8: Commit**

```bash
git add src/brd/entities.py tests/test_entities.py tests/test_documents.py tests/test_cli_issues.py
git commit -m "Delete an issue's or document's incoming edges explicitly"
```

---

## Self-Review

**Spec coverage:**
- B1 card path (`db.delete_card`, `core.delete_card` incl. descendants): Task 1, T1 + T2.
- B1 issue path (`entities.delete`): Task 2, T3. Document path (`documents.delete`): Task 2, T4. Both `refs` origins: T1 (explicit + link), T4 (explicit + link via `[[a]]`).
- B2 exact match: T1 (`c3 → c2` survives), T2 (`O → U` survives).
- B3 own-side unchanged: no own-side SQL added; existing FK-on tests rerun in Task 1 Step 6 and Task 2 Step 7 (T6).
- B4 one transaction: helper has no commit; pinned by `test_delete_incoming_edges_does_not_commit`. Cascade still commits per card (no change to `core.delete_card`).
- B5: T5 (CLI, issue unblocks card); T3/T4 assert `refs.outgoing` no longer lists the deleted entity and the card resolves to `todo`; T4 checks backup gone and source kept. Errors/returns untouched (no change in validation code).
- Implementation guidance: helper in `db.py`, called from `db.delete_card` and `entities.delete`; comment on `db.delete_card` updated.
- Out of scope respected: `brd forget`, schema/FKs, `delete_entity` routing, `issues.delete` not touched.

**Placeholder scan:** none; every code step carries the code.

**Type consistency:** `db.delete_incoming_edges(conn, entity_id) -> None` used identically in Tasks 1 and 2.

**Review Focus:** all five lines have a pinning test in the task that owns the code.
<!-- task-pipeline: validated -->
