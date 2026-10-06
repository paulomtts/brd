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
