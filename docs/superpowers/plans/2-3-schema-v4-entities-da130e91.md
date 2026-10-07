# 2.3 Schema v4: entities and documents record their project — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring each per-project board file to `PRAGMA user_version = 4`: every entity and document records its project, a card's parent must share its project, edge targets lose their FK, and the `*_register_entity` triggers give way to code that writes `entities(id, kind, project_id)` on every insert path.

**Architecture:** Every insert function takes `project_id` as a required parameter placed right after `conn`. `db.migrate_project(conn, project)` gains a `_migrate_to_v4(conn, project)` step that drops the register triggers, writes the board's one `projects` row, and rebuilds `entities`, `documents`, `blocked_by` and `refs`. Same-project rules live in triggers. Since the FK no longer checks edge targets, `brd import` checks them in code. `master.init_project` settles the project before it touches a board, so the board's `projects` row and the registry agree.

**Tech Stack:** Python ≥3.12, stdlib `sqlite3` (SQLite 3.50), Typer CLI, pytest via `uv run pytest`.

**Spec:** `docs/superpowers/specs/2-3-schema-v4-entities-da130e91.md` (the full spec follows this header; read both).

## Global Constraints

- `db.SCHEMA_VERSION == 4`; a migrated board has `PRAGMA user_version = 4`.
- `projects(id TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL, root_path TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL)`: reuse `_PROJECTS_SQL`. A board file holds exactly one `projects` row: its own project.
- `entities(id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('card','issue','document')), project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE)`, plus `CREATE INDEX entities_project ON entities(project_id, kind)`.
- `documents` gains `project_id TEXT NOT NULL` and has `UNIQUE (project_id, source_path)` and `UNIQUE (project_id, stem COLLATE NOCASE)` in place of the global uniques.
- `blocked_by.blocks_on_id TEXT NOT NULL` with no FK, plus `CREATE INDEX blocked_by_target ON blocked_by(blocks_on_id)`. `refs.dst_id TEXT NOT NULL` with no FK, plus `CREATE INDEX refs_target ON refs(dst_id)`. `card_id` / `src_id` keep their FK and cascade.
- No `*_register_entity` trigger exists in a v4 board. `_migrate_to_v1` / `_v2` / `_v3` / `_register_trigger` keep producing the v3 shape unchanged.
- **Convention for this plan:** `project_id: str` is a **required** positional parameter placed right after `conn` in every insert function: `db.insert_entity(conn, project_id, entity_id, kind)`, `db.insert_card(conn, project_id, card)`, `core.create_card(conn, project_id, title, ...)`, `core.import_tree(conn, project_id, nodes)`, `issues.open_issue(conn, project_id, title, ...)`, `documents.add(conn, project_id, root, path, ...)`, `snapshot.load(conn, project_id, root, raw)`. The spec's guidance orders `insert_card(conn, card, project_id)` / `insert_entity(conn, entity_id, kind, project_id)`, but that guidance is non-normative. One order everywhere keeps call sites uniform and lets Task 1 rewrite the test call sites mechanically. Production code never defaults `project_id`. Only `tests/factories.py` defaults it, to `PROJECT.id`.
- `Card`, `Issue`, `Document` and every JSON output stay without a `project_id` field. Command output and error types stay the same.
- `documents._check_unique` stays unscoped (scoping is cards 2.4/2.5).
- Full verification: `uv run pytest`. Baseline is 440 passed. No lint or typecheck is configured.

## Review Focus

1. **Orphan `entities` row when the kind insert fails** (CHECK violation, UNIQUE race past `_check_unique`): the entity row and the kind row must commit together or not at all. Pinned in Task 3 by `test_failed_card_insert_leaves_no_entity_row` and `test_failed_document_insert_leaves_no_entity_row` (`tests/test_project_scope.py`).
2. **The table rename breaking on a leftover register trigger**: `_make_v3` must really carry all three register triggers, or T2 proves nothing. Pinned in Task 3: `_make_v3` asserts the trigger set before it returns.
3. **Legacy v0 board with dangling `blocked_by` / `parent_id`** must still reach v4 cleanly, with no dangling rows coming back. Pinned in Task 3 by the updated `test_dangling_legacy_rows_are_dropped_not_fatal` (asserts `user_version == 4` and an empty `foreign_key_check`).
4. **Case-only stem collision on a migrated (not fresh) board**: after the `documents` rebuild, `Notes` vs `notes` in one project is still rejected. Pinned in Task 3 by `test_migrated_board_still_rejects_case_only_stem_collision`.
5. **`brd import` of an export whose explicit refs point at a document in the same snapshot** must still succeed under the new target check. Pinned in Task 2 by `test_round_trip_keeps_refs_between_snapshot_entities`.

---

## Spec (verbatim from `docs/superpowers/specs/2-3-schema-v4-entities-da130e91.md`)

### 2.3 Schema v4: entities and documents record their project; edge targets lose their FK

Card: `da130e91-691a-4837-8ed3-e000b6d56be3` (subtask of story `54de5e9d` "Project-scoped
schema", milestone `6aa7043a` "Single database and cross-project blocking"). Blocked by
2.2 (`a6a8dd67`, done on this branch's parent: `db.delete_incoming_edges`,
`src/brd/db.py:426-431`).

Parent design spec: `docs/superpowers/specs/2026-10-06-single-db-cross-project-blocking-design.md`
(in the main checkout; not in this branch's history). Cited by section and line as
**[P §n Lx]**.

#### Goal

Bring the per-project board file to `PRAGMA user_version = 4`, the section 1 schema
[P §1 L43-96], while there is **still one board file per project**:

- every entity records the project it belongs to (`entities.project_id`, cascading from a
  `projects` row);
- documents carry the project too, and are unique per project, not globally;
- a card's parent must be in the same project as the card;
- `blocked_by.blocks_on_id` and `refs.dst_id` lose their foreign keys and gain indexes;
- the `<table>_register_entity` triggers are gone, so every insert path writes
  `entities(id, kind, project_id)` itself.

The `projects` row the FK needs lives in each board file for now (card text). One board
file holds exactly one `projects` row: the project the board belongs to. `master.db`
stays the registry. Moving everything into one `brd.db` is story S3, not this card.

Apart from the new constraints, user-visible behaviour does not change. The same
commands give the same output and the same errors.

#### Inherited constraints

| Constraint | Source |
|---|---|
| `user_version = 4`. | [P §1 L45] |
| `projects(id TEXT PRIMARY KEY, name TEXT NOT NULL, root_path TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL)`. The existing `_PROJECTS_SQL` (`src/brd/db.py:19-26`) is this shape. | [P §1 L49-54] |
| `entities(id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('card','issue','document')), project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE)`; `CREATE INDEX entities_project ON entities(project_id, kind)`. | [P §1 L55-60], [P D4 L34] |
| cards: columns unchanged; `parent_id REFERENCES cards(id)`; trigger: the parent belongs to the same project as the card. | [P §1 L61-62] |
| issues, comments, tags: unchanged. | [P §1 L63, L67] |
| documents: `+ project_id TEXT NOT NULL`; `UNIQUE(project_id, source_path)`, `UNIQUE(project_id, stem COLLATE NOCASE)`; trigger: `documents.project_id` equals `entities.project_id` for the row. | [P §1 L64-66], [P D4 L34] |
| `blocked_by.blocks_on_id TEXT NOT NULL` with no FK; `CREATE INDEX blocked_by_target ON blocked_by(blocks_on_id)`. `card_id` keeps its FK and cascade. | [P §1 L68-73], [P D6 L36] |
| `refs.dst_id TEXT NOT NULL` with no FK; `CREATE INDEX refs_target ON refs(dst_id)`. `src_id` keeps its FK and cascade; `origin` CHECK unchanged. | [P §1 L74-80], [P D6 L36] |
| The `<table>_register_entity` triggers are removed. Inserts go through code that writes `entities(id, kind, project_id)` first. Raw inserts in tests use a factory that does the same. | [P §1 L83-86] |
| Deleting an entity still cascades its own rows; incoming edges are deleted explicitly (done in 2.2). | [P §1 L88-94] |
| In phase 2, edge targets are still validated as same-project **by code**. Here that means a target must exist in the board. | [P Implementation order L276-280] |
| Commands are scoped to the current project. The scoping helper and the scoped queries belong to cards 2.4 and 2.5. | [P §2 L109-115]; card text |

#### Behaviour

##### B1. Fresh board

`db.migrate_project(conn, project)` on an empty file creates the v4 schema:

- `user_version` is `4` (`db.SCHEMA_VERSION == 4`).
- Tables: `projects`, `entities`, `cards`, `blocked_by`, `issues`, `documents`, `comments`,
  `tags`, `refs`.
- `projects` holds exactly one row, equal to `project`: `id`, `name`, `root_path`, `created_at`.
- Indexes `entities_project`, `blocked_by_target` and `refs_target` exist.
- No trigger named `*_register_entity` exists in `sqlite_master`.
- `PRAGMA foreign_key_check` is empty.

##### B2. v3 board migrates to v4 with its project filled in

`db.migrate_project(conn, project)` on a board at `user_version = 3` produces the B1
schema and keeps every row:

- Every `entities` row keeps its `id` and `kind` and gets `project_id = project.id`.
- `cards`, `issues`, `comments` and `tags` are unchanged, row for row.
- Every `documents` row keeps every column and gets `project_id = project.id`.
- Every `blocked_by` and `refs` row is kept as it was.
- `projects` holds the one row for `project`.
- The `*_register_entity` triggers are gone. The new triggers (B5, B6) and indexes exist.
- `PRAGMA foreign_key_check` is empty, and `user_version` is 4.

The migration runs inside the existing `BEGIN IMMEDIATE` / `foreign_keys=OFF` envelope of
`migrate_project` (`src/brd/db.py:243-276`). If it fails, nothing changes: the board
stays at v3 with its data and triggers intact, and the error propagates. Boards at
v0, v1 or v2 go through the existing v1→v3 steps and then v4, in one transaction.
The legacy v0 fixtures in `tests/test_migration.py` must end at v4 with their cards and
edges kept.

`_migrate_to_v1` / `_v2` / `_v3` and `_register_trigger` keep producing the v3 shape
they do today, register triggers included. v4 is the step that removes those triggers.

##### B3. `migrate_project` needs the project; a v4 board must belong to it

`migrate_project(conn, project: Project)` and `init_project_schema(conn, project)` take
the project (`brd.models.Project`) whose board this is.

- Board below v4: migrate as in B1/B2.
- Board already at v4, with a `projects` row whose `id` is `project.id`: no-op, as today.
- Board already at v4, with no `projects` row for `project.id`: raise `MigrationError`.
  The message names the board's stored project id(s), or says the board has none, and
  names `project.id`. Nothing is written. This only happens when the registry and
  the board disagree (for example, `master.db` was deleted and a different id was
  registered). Without this check, the next insert would fail on the FK with a raw
  `sqlite3.IntegrityError`.

Callers pass the project they already hold:

- `cli/_app.open_project` (`src/brd/cli/_app.py:64-73`) passes the `project` it resolved
  from the registry.
- `master.init_project` (`src/brd/master.py:63-99`) settles the project **before** it
  touches any board file, then uses it for the legacy-marker copy (B9), the schema init
  and the registry upsert:
  1. If `master.db` has a row for this `root_path`, use that row: id, name and
     `created_at` as stored. The name is the new one when `name` is given, as
     `upsert_project` stores it.
  2. Otherwise, if the board file exists, is at v4 and has exactly one `projects` row,
     reuse that row's `id` and `created_at`.
  3. Otherwise, use a new `db.new_project_id()` and `_now()`.

  The `Project` that `init_project` returns has the same `id` as the board's `projects`
  row. Re-running `brd init` keeps the id, as 2.1 established.

The board's `projects.name` / `root_path` are written once, when the row is inserted.
Keeping them in sync with later renames is not required. Nothing reads them in this card.

##### B4. Every insert path writes the entity row first, with the project

No trigger creates `entities` rows any more. Each path below inserts
`entities(id, kind, project_id)` before the kind row, in the same transaction.
`project_id` is the id of the project the command runs in.

| Path | Kind(s) | Where the project comes from |
|---|---|---|
| `core.create_card` → `db.insert_card` | card | `ctx.project.id` from `cli/cards.py` (`brd add`) |
| `issues.open_issue` | issue | `ctx.project.id` from `cli/issues.py` (`brd issue open`) |
| `documents.add` | document (also writes `documents.project_id`) | `ctx.project.id` from `cli/docs.py` (`brd doc add`) |
| `core.import_tree` (legacy `brd tree` snapshot) | card | `snapshot.load` ← `cli/snapshot.py` (`brd import`) |
| `snapshot._load_export` (export v1) | card, issue, document | same |
| `master._copy_cards` (legacy `.brd` marker migration) | card | the project settled in B3 |
| `tests/factories.make_card` / `make_issue` / `make_document` | each | test default project (see Tests) |

These functions take the project id as a **required** parameter, named `project_id: str`.
A missing project id is a `TypeError` at the call site. It must never fall back to "the
board's only project": S3 puts every project in one file, and that fallback would
silently put rows in the wrong project. Return values and JSON output are unchanged.
`Card`, `Issue` and `Document` do not gain a `project_id` field, and `brd show` / `list` /
`export` output does not gain one.

An insert whose kind row fails (for example a duplicate document path that slipped past
`_check_unique`, or a CHECK violation) must not leave an orphan `entities` row. The
entity row and the kind row commit together or not at all.

##### B5. Documents are unique per project and agree with their entity

- Within one project, a second document with the same `source_path`, or the same `stem`
  ignoring case, is rejected by the schema (`sqlite3.IntegrityError`). It was rejected
  before too; only the key changed.
- In two **different** projects in the same file, the same `source_path` and the same
  stem are both accepted. No command can reach this today, so it is tested at the
  schema level.
- A `documents` row whose `project_id` differs from its `entities` row's `project_id`
  is rejected on insert, and on an update of `project_id`, with `sqlite3.IntegrityError`
  (trigger `RAISE(ABORT, …)`). An insert with no `entities` row is rejected too.
- `documents._check_unique` stays as it is: unscoped queries, same
  `DuplicatePathError` / `DuplicateStemError`. Scoping them is card 2.4/2.5.

##### B6. A card's parent is in the same project

- Inserting a card whose `parent_id` is a card of **another** project is rejected with
  `sqlite3.IntegrityError`. The message says the parent must be in the same project.
- Updating `cards.parent_id` to a card of another project is rejected the same way.
- `parent_id IS NULL` and same-project parents are accepted as today.
- A `parent_id` that is not a card at all still fails through the existing
  `REFERENCES cards(id)` FK. The trigger must not change that path: it only fires
  when the parent's entity exists and is in a different project. `core.create_card` /
  `update_card` still raise `CardNotFoundError` before any SQL runs, as today.

##### B7. Edge targets have no FK

- With `foreign_keys=ON`, inserting `blocked_by(card_id=<existing card>, blocks_on_id='<any id>')`
  or `refs(src_id=<existing entity>, dst_id='<any id>', origin=...)` succeeds even when
  the target id is not in `entities`.
- `card_id` and `src_id` keep their FKs and cascades. An edge from a missing source is
  still rejected, and deleting the source still removes its outgoing edges.
- Deleting an entity through the delete paths still removes its incoming edges, through
  `db.delete_incoming_edges` from 2.2.
- Deleting a `projects` row cascades every entity of that project and, from there, its
  cards, issues, documents, comments, tags and outgoing edges. Incoming edges from rows
  that are not deleted stay [P D8 L38]. This card adds no command that deletes the
  board's `projects` row: `brd forget` still deletes the whole file.

##### B8. Commands still refuse dangling targets (code validation replaces the FK)

The FK no longer protects the commands below, so each must check that targets exist.
Every existing check stays:

- `brd block` / `brd add --blocked-by` / `brd issue open --blocks`: unchanged. They
  already check targets with `entities.kind_of` (`core._require_blocker`,
  `src/brd/core.py:109-114`) or `db.get_card`.
- `brd ref add`: unchanged. `refs.add_explicit` calls `entities.require` (`src/brd/refs.py:93`).
- Link refs (`refs.reindex`) only insert resolved ids: unchanged.
- **`brd import`, both formats.** Before anything is written, every `blocked_by` target
  must be an entity id that is in the snapshot or already in the board. For export v1,
  every explicit `refs.dst_id` must be one too. Otherwise the import fails with
  `ImportFormatError` and nothing is written: no rows, and no document backups left
  behind. Today the FK gives this result (`tests/test_snapshot.py`
  `test_old_tree_snapshot_with_unknown_blocker_imports_nothing`); after this card,
  code produces it. The message names the offending id.

##### B9. Legacy `.brd` marker migration still works

`master._copy_cards` (`src/brd/master.py:22-42`) copies a legacy board's cards and
`blocked_by` into the new board:

- It writes the cards' `entities` rows with the project settled in B3.
- It copies only edges whose both ends are copied cards, the same rule `_migrate_to_v1`
  applies (`src/brd/db.py:194-199`). Today a dangling edge makes `brd init` fail on the FK.
  Without the FK it would be stored silently. Dropping it matches how the v0→v1
  migration already treats legacy boards.
- The existing `tests/test_master.py` legacy-marker tests stay green.

#### Implementation guidance (non-normative)

- Add `db.insert_entity(conn, entity_id, kind, project_id)`, a single
  `INSERT INTO entities`, with no commit. Call it from every B4 path before the kind
  row. `db.insert_card(conn, card, project_id)` can call it and keep its single commit.
  The importers already run inside `with conn:`.
- `_migrate_to_v4(conn, project)`, in this order:
  1. `DROP TRIGGER IF EXISTS` the three register triggers. Do this first: SQLite's
     `ALTER TABLE … RENAME` re-parses every trigger, and those triggers'
     `INSERT INTO entities` would break the rebuild.
  2. Create `projects` and insert the row.
  3. Rebuild `entities` as `entities_new` with `project_id` filled from `project.id`,
     then drop and rename. Child FKs refer to `entities` by name, so they keep working,
     as with the `cards` rebuild in `_migrate_to_v1`.
  4. Rebuild `documents`, `blocked_by` and `refs` the same way.
  5. Create the indexes and the two triggers.
- Triggers: `documents_project` (BEFORE INSERT, and BEFORE UPDATE OF `id, project_id`)
  compares `NEW.project_id IS NOT (SELECT project_id FROM entities WHERE id = NEW.id)`.
  `cards_parent_project` (BEFORE INSERT, and BEFORE UPDATE OF `parent_id`) fires
  `WHEN NEW.parent_id IS NOT NULL` and the parent's entity exists and its
  `project_id IS NOT` the card's.
- The column-level `COLLATE NOCASE` on `stem` already applies to a table-level
  `UNIQUE(project_id, stem)`. Writing `stem COLLATE NOCASE` inside the constraint, as the
  parent spec does, is equivalent.
- Keep `PRAGMA foreign_key_check` at the end of `migrate_project`. A v3 board whose
  `blocked_by` / `refs` held only valid targets still passes, and from v4 on those
  columns are not checked.

#### Tests

Tiers in this repo:

- **unit**: module functions against a real temporary SQLite file (`tests/test_db.py`,
  `test_migration.py`, `test_core.py`, `test_documents.py`, `test_issues.py`,
  `test_master.py`, `test_snapshot.py` helpers), using `pconn` / `conn` and
  `tests/factories.py`.
- **CLI**: the Typer app through `tests/cli_helpers.ok/err` with the `project` fixture.

Full verification: `uv run pytest` (baseline 440 passed). No lint or typecheck is
configured.

**Fixture changes, needed by everything below.**

- `tests/factories.py` gains `PROJECT = Project(id="11111111-1111-4111-8111-111111111111",
  name="test", root_path="/test", created_at=NOW)`.
- `make_card` / `make_issue` / `make_document` take `project_id=PROJECT.id` (keyword,
  defaulted) and write the `entities` row first. A test-side default is fine. The
  production functions have no default (B4).
- `pconn` (`tests/conftest.py:6-11`) and every direct `migrate_project` /
  `init_project_schema` call in tests pass `PROJECT`, or an explicit second project
  where a test needs two.
- Raw `INSERT INTO cards/issues/documents` in tests that relied on the register trigger
  go through the factories, or insert the entity row first: `test_master.py:54,101,134`,
  `test_db.py:256,295`, `test_cli_app.py:44`, `test_migration.py:25,205,231`, and any
  others the suite turns up.
- `test_cli_app.py:133`'s `failing_migrate` accepts the new argument.
- The `create_card` / `open_issue` / `documents.add` / `import_tree` / `snapshot.load`
  calls in tests pass `project_id=PROJECT.id`.

A v3 board for tests is built by `_make_v3(path)` in `tests/test_migration.py`. It runs
`db._migrate_to_v1`, `_v2`, `_v3` with `foreign_keys=OFF`, sets `user_version = 3`, and
seeds rows with raw INSERTs, which the v3 register triggers turn into entities. This
reuses the real historical migrations, so the fixture is a faithful v3 board.

| # | Test | File | Tier | Why this tier | Proves |
|---|---|---|---|---|---|
| T1 | `test_fresh_db_gets_current_schema` (update): v4 table set includes `projects`; one `projects` row equal to `PROJECT`; `user_version == 4`; indexes `entities_project`, `blocked_by_target`, `refs_target` in `sqlite_master`; no `%_register_entity` trigger; `foreign_key_check` empty. | `tests/test_migration.py` | unit | Schema shape is only observable through `sqlite_master` / pragmas. | B1 |
| T2 | `test_v3_board_migrates_to_v4_with_project_id`: `_make_v3` with a parent/child card, a blocker edge, an issue blocking a card, a document, a comment, a tag, an explicit ref and a link ref; `migrate_project(conn, PROJECT)`. Every entity has `project_id == PROJECT.id`; the document row has `project_id == PROJECT.id`; row counts and contents of cards, issues, documents, comments, tags, blocked_by and refs are unchanged; no register triggers; `user_version == 4`. | `tests/test_migration.py` | unit | Data-preserving migration; must inspect raw rows. | B2 |
| T3 | `test_v0_board_migrates_to_v4` (update the existing v0 tests at `test_migration.py:62-123`): they pass `PROJECT`, assert `user_version == db.SCHEMA_VERSION` (now 4), and assert that every entity has `project_id == PROJECT.id`. | `tests/test_migration.py` | unit | The chained v0→v4 path through the real legacy fixtures. | B2 |
| T4 | Rewrite `test_v1_db_upgrades_to_v2_and_keeps_entity_trigger` / `test_v2_db_upgrades_to_v3_and_accepts_archived` (`test_migration.py:185-232`). Keep the rollback set-up. After the migration, insert the entity row (`db.insert_entity` or the factory) and then the `archived` card; assert it is accepted and its entity has `project_id == PROJECT.id`. Rename the first test, since it no longer keeps a trigger. | `tests/test_migration.py` | unit | These encoded the old trigger contract and must now encode the new one. | B2, B4 |
| T5 | `test_v4_migration_failure_leaves_v3_board_intact`: `_make_v3` with data; monkeypatch `db._migrate_to_v4` to raise after doing part of its work (for example, wrap it to call the real one, then raise). `migrate_project` raises; `user_version == 3`; `cards_register_entity` still exists; the row counts are unchanged. | `tests/test_migration.py` | unit | Transactional envelope; only checkable at the db level. | B2 |
| T6 | `test_migrate_project_rejects_board_of_other_project`: fresh board migrated with `PROJECT`; `migrate_project(conn, other_project)` raises `MigrationError` whose message contains both ids; the `projects` table is unchanged. Also: `migrate_project(conn, PROJECT)` a second time is a no-op. | `tests/test_migration.py` | unit | Error path of the new parameter. | B3 |
| T7 | `test_entity_insert_paths_record_project`: on `pconn`, `core.create_card`, `issues.open_issue`, `documents.add` (with a real file under `tmp_path`), each with `project_id=PROJECT.id`; each new id's `entities.project_id == PROJECT.id`; the document's `documents.project_id == PROJECT.id`. Parametrize or split per kind. | `tests/test_core.py`, `test_issues.py`, `test_documents.py` | unit | Each insert function is the unit under change. | B4 |
| T8 | `test_no_register_trigger_so_raw_kind_insert_without_entity_fails`: on `pconn`, a raw `INSERT INTO cards` with no `entities` row raises `sqlite3.IntegrityError` (the `cards.id` FK). Same for `issues`; for `documents`, the trigger raises. | `tests/test_db.py` | unit | Proves the triggers are really gone and the FK now guards. | B1, B4, B5 |
| T9 | `test_document_unique_per_project`: one file, `PROJECT` and a second project row (`P2`, inserted directly into `projects`); a doc `docs/a.md` in each project is accepted. In the same project, a second `docs/a.md`, or `docs/A.md` with stem `A`, raises `IntegrityError`. | `tests/test_db.py` | unit | Multi-project rows are unreachable from the CLI before S3. | B5 |
| T10 | `test_document_project_must_match_entity`: entity in `PROJECT`, and a `documents` insert with `project_id = P2.id` raises `IntegrityError`. Then an `UPDATE documents SET project_id = P2.id` on a valid row raises too. | `tests/test_db.py` | unit | Trigger behaviour. | B5 |
| T11 | `test_card_parent_must_be_in_same_project`: parent card in `P2`, and a child in `PROJECT` with `parent_id` = that parent raises `IntegrityError` with "same project" in the message. A valid child in `PROJECT`, then `UPDATE cards SET parent_id = <P2 card>` raises too. A same-project parent is accepted. A raw insert with a missing `parent_id` still raises `IntegrityError` (FK path). | `tests/test_db.py` | unit | Trigger behaviour. | B6 |
| T12 | `test_edge_targets_accept_unknown_ids`: with FKs on, `db.add_blocked_by_edge(card, "not-an-entity")` and a raw `INSERT INTO refs (src_id, dst_id, origin) VALUES (card, 'not-an-entity', 'explicit')` succeed. `add_blocked_by_edge("not-an-entity", card)` still raises `IntegrityError`. | `tests/test_db.py` | unit | Schema-level FK removal; commands never reach it. | B7 |
| T13 | `test_deleting_project_row_cascades_its_entities`: two projects in one file, each with a card (with a comment and a tag), an issue and a document. A card of `P2` is blocked by a `PROJECT` card. `DELETE FROM projects WHERE id = PROJECT.id` leaves no `PROJECT` entities, cards, issues, documents, comments or tags; `P2`'s rows are intact; `P2`'s `blocked_by` row pointing at the deleted card still exists. | `tests/test_db.py` | unit | The cascade chain and D8's "incoming edges stay". | B7 |
| T14 | `test_import_rejects_unknown_blocker_and_ref_target`: export v1 data whose card `blocked_by` names an id in neither the snapshot nor the board → `ImportFormatError`, and nothing is imported (`list`, `issue list`, `doc list` empty; no backup files). Same with an explicit `refs` entry whose `dst_id` is unknown. Keep `test_old_tree_snapshot_with_unknown_blocker_imports_nothing` green: it now passes through the code check. | `tests/test_snapshot.py` | CLI | Pins the user-visible contract the FK used to provide, through `brd import`. | B8 |
| T15 | `test_import_blocker_in_board_is_accepted`: import a snapshot whose card is blocked by an issue already on the target board; it succeeds and `brd show` lists the blocker. | `tests/test_snapshot.py` | CLI | Guards against the new check being too strict ("in the board" counts). | B8 |
| T16 | `test_copy_cards_drops_dangling_legacy_edges`: legacy in-repo `.brd/board.db` (as in the `test_master.py` legacy tests) with a `blocked_by` row whose target is not a card. `brd init` succeeds; the copied cards have `entities.project_id` equal to the returned project's id; the dangling edge is absent and the valid edge is kept. | `tests/test_master.py` | unit | `master.init_project` is the unit; it drives the copy. | B9, B3 |
| T17 | `test_init_project_board_row_matches_registry`: `master.init_project(root)` returns project `p`; the board file's `projects` row id is `p.id`. Re-running `init_project(root, name="x")` returns the same id and keeps the board's row. Deleting `master.db` and re-running `init_project(root)` returns the board's id (B3 step 2), and `open_project` afterwards works. | `tests/test_master.py` | unit | The id-settling order in `init_project`. | B3 |
| T18 | Existing CLI suites (`test_cli*.py`, `test_snapshot.py` round trips, `test_cli_app.py`) stay green with the threaded `ctx.project.id`. In particular, export → import into a fresh project round-trips cards, issues, documents, comments, tags and refs. | existing | CLI | Behaviour preservation (Goal: output unchanged). | B4 |

#### Review Focus (hand-off to the planner)

These are the input classes and failure modes most likely to bite and least covered by
T1-T18. Each needs a test in the task that owns the code:

1. **Orphan entity rows on a failed kind insert.** `documents.add` passing
   `_check_unique` but hitting the UNIQUE constraint in a race, or any CHECK failure,
   must not leave an `entities` row without a kind row. Test: force an `IntegrityError`
   on the kind insert, then assert `SELECT COUNT(*) FROM entities` is unchanged (B4).
2. **The rename breaking on a leftover trigger.** A v3 board migrated in the wrong order
   (trigger drop after the `entities` rename) fails at `ALTER TABLE RENAME`. T2 covers
   this only if `_make_v3` really creates all three register triggers. Assert that in
   the fixture.
3. **A legacy v0 board with dangling `blocked_by` / `parent_id`** still migrates cleanly
   to v4, as T3 does. The v1 step already filters them; v4 must not bring them back.
4. **Case-only stem collisions** across the rebuilt `documents` table: `Notes` and
   `notes` in the same project must still be rejected after the migration copies
   existing rows (T9 against a migrated board, not only a fresh one).
5. **`brd import` of a v1 export whose `refs` point at a document in the same snapshot**
   must still succeed. The new dst check counts snapshot ids, not only board ids.

#### Out of scope

- **Query scoping**: the scoping helper in `db.py`, filtering `list` / `next` / `tree` /
  `issue list` / `doc list` / `sync` / link resolution / `reindex_mentions` /
  `_check_unique` / `export` by `entities.project_id`, and "entity belongs to the
  current project" checks on mutating commands. These are cards **2.4 and 2.5**
  [P §2 L109-115].
- **One `brd.db` for all projects**, removal of `master.db` and per-project files, the
  marker-less resolution, `init --relink`, `forget --project`, and the
  master→`brd.db` migration [P §3]. These belong to story S3. Here the `projects` row
  lives in each board file.
- Syncing the board's `projects.name` / `root_path` with later renames in `master.db`.
- **Cross-project edges**: lifting the "target must exist in this board" checks,
  `not-found` resolution and the `blockers` output [P §4, Implementation order L281-283].
  In this card, targets must still exist (B8).
- `brd forget` behaviour: it still deletes the board file.
- Export/import format v2 and project placement [P §5].
- A guard trigger on `UPDATE entities SET project_id`. No code updates it.
- Adding `project_id` to any JSON output or to the `Card` / `Issue` / `Document` models.

---

## File map

| File | Responsibility | Tasks |
|---|---|---|
| `src/brd/db.py` | Schema v4, `_migrate_to_v4`, `insert_entity`, `insert_card`, `board_projects`, `migrate_project(conn, project)` | 1, 3, 4, 5 |
| `src/brd/core.py` | `create_card` / `import_tree` take `project_id`; `_require_import_target` | 1, 2, 3 |
| `src/brd/issues.py` | `open_issue` takes `project_id`, writes entity + issue in one transaction | 1, 3 |
| `src/brd/documents.py` | `add` takes `project_id`, writes entity + document (with `project_id`) in one transaction | 1, 3 |
| `src/brd/snapshot.py` | `load` takes `project_id`; export import writes entities; target checks | 1, 2, 3 |
| `src/brd/master.py` | `_settle_project`, `_board_project`; `_copy_cards` writes entities and drops dangling edges | 1, 3, 6 |
| `src/brd/cli/{_app,cards,issues,docs,snapshot}.py` | Pass `project` / `ctx.project.id` | 1 |
| `tests/factories.py` | `PROJECT`, `OTHER_PROJECT`, `add_project`, factories write entities | 1, 3 |
| `tests/conftest.py` | `pconn` migrates with `PROJECT` | 1 |
| `tests/test_project_scope.py` (new) | Signature and insert-path project tests | 1, 3 |
| `tests/test_migration.py`, `test_db.py`, `test_core.py`, `test_issues.py`, `test_documents.py`, `test_entities.py`, `test_master.py`, `test_snapshot.py`, `test_cli_app.py` | Call-site updates and the spec's T1–T17 | 1–6 |

---

### Task 1: Thread the project through every insert path and `migrate_project`

Pure plumbing. Signatures change and callers pass the project, but nothing reads it yet. The suite stays at the v3 schema and stays green.

**Files:**
- Create: `tests/test_project_scope.py`
- Modify: `src/brd/db.py:243-280` (`migrate_project`, `init_project_schema`), `src/brd/db.py:339-353` (`insert_card`)
- Modify: `src/brd/core.py:117-141` (`create_card`), `src/brd/core.py:279` (`import_tree`)
- Modify: `src/brd/issues.py:58-64` (`open_issue`)
- Modify: `src/brd/documents.py:129-135` (`add`)
- Modify: `src/brd/snapshot.py:50-70,86` (`load`, `_load`, `_load_export`)
- Modify: `src/brd/master.py:22-99`
- Modify: `src/brd/cli/_app.py:69`, `src/brd/cli/cards.py:35-41`, `src/brd/cli/issues.py:22`, `src/brd/cli/docs.py:23-25`, `src/brd/cli/snapshot.py:31`
- Modify: `tests/factories.py`, `tests/conftest.py`, `tests/test_cli_app.py:129`, and call sites in `tests/test_core.py`, `test_db.py`, `test_documents.py`, `test_issues.py`, `test_entities.py`, `test_master.py`, `test_migration.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `db.migrate_project(conn: sqlite3.Connection, project: Project) -> None`
  - `db.init_project_schema(conn: sqlite3.Connection, project: Project) -> None`
  - `db.insert_card(conn: sqlite3.Connection, project_id: str, card: Card) -> None`
  - `core.create_card(conn, project_id: str, title: str, description=None, parent_id=None, blocked_by=None) -> Card`
  - `core.import_tree(conn, project_id: str, nodes: list[dict]) -> int`
  - `issues.open_issue(conn, project_id: str, title: str, body=None, ref_ids=None, blocks=None) -> Issue`
  - `documents.add(conn, project_id: str, root: Path, path: Path, title=None, tag_list=None) -> Document`
  - `snapshot.load(conn, project_id: str, root: Path, raw) -> dict`; `snapshot._load(conn, project_id, raw)`; `snapshot._load_export(conn, project_id, snap)`
  - `master._settle_project(root_path: Path, name: str | None) -> Project`
  - `master._copy_cards(old_db_path: Path, new_db_path: Path, project: Project) -> None`
  - `tests.factories.PROJECT: Project` (id `11111111-1111-4111-8111-111111111111`); `make_card(..., project_id=PROJECT.id)`

- [ ] **Step 1: Write the failing test**

Create `tests/test_project_scope.py`:

```python
import pytest

from brd import core, db, documents, issues, snapshot
from brd.models import Card
from tests.factories import NOW


def test_migrate_project_requires_the_project(tmp_path):
    conn = db.connect(tmp_path / "p.db")
    try:
        with pytest.raises(TypeError):
            db.migrate_project(conn)
        with pytest.raises(TypeError):
            db.init_project_schema(conn)
    finally:
        conn.close()


@pytest.mark.parametrize(
    "call",
    [
        lambda conn, root, source: db.insert_card(
            conn, Card("c", "c", None, "todo", None, NOW, NOW)
        ),
        lambda conn, root, source: core.create_card(conn, title="c"),
        lambda conn, root, source: core.import_tree(conn, []),
        lambda conn, root, source: issues.open_issue(conn, title="i"),
        lambda conn, root, source: documents.add(conn, root, source),
        lambda conn, root, source: snapshot.load(conn, root, []),
    ],
    ids=["insert_card", "create_card", "import_tree", "open_issue", "documents.add", "snapshot.load"],
)
def test_insert_paths_require_a_project_id(pconn, tmp_path, call):
    root = tmp_path / "repo"
    source = root / "docs" / "a.md"
    source.parent.mkdir(parents=True)
    source.write_text("")
    with pytest.raises(TypeError):
        call(pconn, root, source)
```

Do **not** add this file to the perl rewrite in Step 5. Its calls are deliberately missing the project.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_project_scope.py -v`
Expected: 7 FAIL with `Failed: DID NOT RAISE <class 'TypeError'>`.

- [ ] **Step 3: Change the production signatures**

`src/brd/db.py`: replace `migrate_project`'s and `init_project_schema`'s signatures and `insert_card`:

```python
def migrate_project(conn: sqlite3.Connection, project: Project) -> None:
```

(The body stays the same in this task.)

```python
def init_project_schema(conn: sqlite3.Connection, project: Project) -> None:
    migrate_project(conn, project)
```

```python
def insert_card(conn: sqlite3.Connection, project_id: str, card: Card) -> None:
```

(The body stays the same in this task.)

`src/brd/core.py`: change `create_card`:

```python
def create_card(
    conn: sqlite3.Connection,
    project_id: str,
    title: str,
    description: str | None = None,
    parent_id: str | None = None,
    blocked_by: list[str] | None = None,
) -> Card:
```

Inside `create_card`, change `db.insert_card(conn, card)` to `db.insert_card(conn, project_id, card)`.

Change `import_tree`'s signature line to:

```python
def import_tree(conn: sqlite3.Connection, project_id: str, nodes: list[dict]) -> int:
```

`src/brd/issues.py`: change `open_issue`'s signature:

```python
def open_issue(
    conn: sqlite3.Connection,
    project_id: str,
    title: str,
    body: str | None = None,
    ref_ids: list[str] | None = None,
    blocks: list[str] | None = None,
) -> Issue:
```

`src/brd/documents.py`: change `add`'s signature:

```python
def add(
    conn: sqlite3.Connection,
    project_id: str,
    root: Path,
    path: Path,
    title: str | None = None,
    tag_list: list[str] | None = None,
) -> Document:
```

`src/brd/snapshot.py`:

```python
def load(conn: sqlite3.Connection, project_id: str, root: Path, raw) -> dict:
    try:
        return _load(conn, project_id, raw)
    except (KeyError, TypeError, AttributeError, sqlite3.ProgrammingError) as exc:
        # Missing keys or wrong value types in the snapshot. Any backups the
        # import wrote were already cleaned up by the time this is caught.
        raise ImportFormatError(f"malformed snapshot: {type(exc).__name__}: {exc}") from exc


def _load(conn: sqlite3.Connection, project_id: str, raw) -> dict:
```

Inside `_load`, change `return _load_export(conn, raw)` to `return _load_export(conn, project_id, raw)` and `core.import_tree(conn, nodes)` to `core.import_tree(conn, project_id, nodes)`. Change `_load_export`'s signature to `def _load_export(conn: sqlite3.Connection, project_id: str, snap: dict) -> dict:`.

`src/brd/master.py`: replace lines 22-99 (`_copy_cards` through the end of `init_project`) with:

```python
def _copy_cards(old_db_path: Path, new_db_path: Path, project: Project) -> None:
    old_conn = db.connect(old_db_path)
    new_conn = db.connect(new_db_path)
    try:
        db.init_project_schema(new_conn, project)
        for row in old_conn.execute("SELECT * FROM cards"):
            new_conn.execute(
                "INSERT INTO cards (id, title, description, status, "
                "parent_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                tuple(row),
            )
        for row in old_conn.execute("SELECT * FROM blocked_by"):
            new_conn.execute(
                "INSERT INTO blocked_by (card_id, blocks_on_id) VALUES (?, ?)",
                tuple(row),
            )
        new_conn.commit()
    finally:
        old_conn.close()
        new_conn.close()


def _migrate_in_repo_format(marker_dir: Path, new_db_path: Path, project: Project) -> None:
    """Migrate the in-repo format (.brd/ directory with board.db, committed
    to git) back to central storage."""
    old_db_path = marker_dir / "board.db"
    if old_db_path.is_file():
        _copy_cards(old_db_path, new_db_path, project)
    shutil.rmtree(marker_dir)


def _migrate_legacy_uuid_marker(marker_file: Path, new_db_path: Path, project: Project) -> None:
    """Migrate the original design (.brd file holding a UUID, cards in a
    central per-project db keyed by that UUID)."""
    legacy_id = marker_file.read_text().strip()
    old_db_path = paths.data_dir() / "projects" / f"{legacy_id}.db"
    if old_db_path.is_file() and old_db_path != new_db_path:
        _copy_cards(old_db_path, new_db_path, project)


def _settle_project(root_path: Path, name: str | None) -> Project:
    """The project this root is, settled before any board file is touched so
    the board and the registry agree on its id: the registered row when
    there is one, else a new project."""
    project_name = name or root_path.name
    conn = _master_conn()
    try:
        stored = db.get_project(conn, str(root_path))
    finally:
        conn.close()
    if stored is not None:
        return Project(
            id=stored.id,
            name=project_name,
            root_path=str(root_path),
            created_at=stored.created_at,
        )
    return Project(
        id=db.new_project_id(),
        name=project_name,
        root_path=str(root_path),
        created_at=_now(),
    )


def init_project(root_path: Path, name: str | None = None) -> Project:
    project = _settle_project(root_path, name)
    marker = root_path / MARKER_FILENAME
    db_path = paths.project_db_path(root_path)

    if marker.is_dir():
        _migrate_in_repo_format(marker, db_path, project)
    elif marker.is_file():
        _migrate_legacy_uuid_marker(marker, db_path, project)

    project_conn = db.connect(db_path)
    try:
        db.init_project_schema(project_conn, project)
    finally:
        project_conn.close()

    marker.write_text("")

    gitignore = root_path / ".gitignore"
    existing_lines = gitignore.read_text().splitlines() if gitignore.exists() else []
    if MARKER_FILENAME not in existing_lines:
        with gitignore.open("a") as f:
            if existing_lines and existing_lines[-1] != "":
                f.write("\n")
            f.write(f"{MARKER_FILENAME}\n")

    conn = _master_conn()
    try:
        return db.upsert_project(conn, project)
    finally:
        conn.close()
```

CLI callers:

- `src/brd/cli/_app.py:69`: `db.migrate_project(conn)` → `db.migrate_project(conn, project)`.
- `src/brd/cli/cards.py:35-41`: insert `ctx.project.id,` as the line after `ctx.conn,`:

```python
        card = core.create_card(
            ctx.conn,
            ctx.project.id,
            title=title,
            description=description,
            parent_id=parent,
            blocked_by=list(blocked_by),
        )
```

- `src/brd/cli/issues.py:22`:

```python
        issue = issues.open_issue(
            ctx.conn, ctx.project.id, title, body=body, ref_ids=list(ref), blocks=list(blocks)
        )
```

- `src/brd/cli/docs.py:23-25`:

```python
        doc = documents.add(
            ctx.conn,
            ctx.project.id,
            Path(ctx.project.root_path),
            path,
            title=title,
            tag_list=list(tag_list),
        )
```

- `src/brd/cli/snapshot.py:31`: `return snapshot.load(ctx.conn, ctx.project.id, Path(ctx.project.root_path), raw)`.

- [ ] **Step 4: Update the test fixtures by hand**

Replace `tests/factories.py` with:

```python
from brd import db
from brd.models import Card, Project

NOW = "2026-09-24T00:00:00+00:00"

PROJECT = Project(
    id="11111111-1111-4111-8111-111111111111",
    name="test",
    root_path="/test",
    created_at=NOW,
)


def make_card(
    conn, id_, title=None, description=None, parent_id=None, status="todo", project_id=PROJECT.id
):
    db.insert_card(
        conn, project_id, Card(id_, title or id_, description, status, parent_id, NOW, NOW)
    )
    return id_


def make_issue(conn, id_, title=None, body=None, status="open"):
    conn.execute(
        "INSERT INTO issues (id, title, body, status, close_reason, created_at, "
        "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (id_, title or id_, body, status, "resolved" if status == "closed" else None, NOW, NOW),
    )
    conn.commit()
    return id_


def make_document(conn, id_, stem, content="", title=None):
    conn.execute(
        "INSERT INTO documents (id, title, source_path, stem, content_hash, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (id_, title or stem, f"docs/{stem}.md", stem, "0" * 64, NOW, NOW),
    )
    conn.commit()
    backups = db.docs_dir(conn)
    backups.mkdir(parents=True, exist_ok=True)
    (backups / f"{id_}.md").write_text(content)
    return id_
```

`tests/conftest.py`: add `from tests.factories import PROJECT` after `from brd import db`, and change `db.migrate_project(connection)` to `db.migrate_project(connection, PROJECT)`.

`tests/test_cli_app.py:129`: `def failing_migrate(conn):` → `def failing_migrate(conn, project):`.

- [ ] **Step 5: Rewrite the test call sites mechanically**

Run:

```bash
perl -0pi -e 's/\b(core\.create_card|core\.import_tree|issues\.open_issue|documents\.add|db\.insert_card)\(\s*(\w+),\s*/$1($2, PROJECT.id, /g; s/\bdb\.(migrate_project|init_project_schema)\((\w+)\)/db.$1($2, PROJECT)/g' tests/test_core.py tests/test_db.py tests/test_documents.py tests/test_issues.py tests/test_entities.py tests/test_master.py tests/test_migration.py
```

Then add the import of `PROJECT` to each rewritten file:

- `tests/test_core.py`: after `from brd.models import Card` add `from tests.factories import PROJECT`.
- `tests/test_db.py`: after `from brd.models import Card, Project` add `from tests.factories import PROJECT`.
- `tests/test_documents.py`: after the closing `)` of the `from brd.errors import (...)` block add `from tests.factories import PROJECT`.
- `tests/test_issues.py`: `from tests.factories import make_document` → `from tests.factories import PROJECT, make_document`.
- `tests/test_entities.py`: `from tests.factories import make_card, make_document, make_issue` → `from tests.factories import PROJECT, make_card, make_document, make_issue`.
- `tests/test_master.py`: after `from brd import db, master, paths` add `from tests.factories import PROJECT`.
- `tests/test_migration.py`: after `from brd import db, paths` add `from tests.factories import PROJECT`.

Check that no call site was missed:

Run: `grep -nP "\b(core\.create_card|core\.import_tree|issues\.open_issue|documents\.add|db\.insert_card)\((\w+), (?!PROJECT\.id|project_id)" src tests -r; grep -nE "db\.(migrate_project|init_project_schema)\(\w+\)" -r src tests`
Expected: matches only in `tests/test_project_scope.py` (for example `core.create_card(conn, title="c")`, `core.import_tree(conn, [])`, `documents.add(conn, root, source)`, `db.migrate_project(conn)`; the multi-line `db.insert_card(` lambda is not a line match). Nothing in `src/` and nothing in any other test file. Multi-line calls in `src/` (`cli/cards.py`, `cli/docs.py`, `cli/issues.py`) are covered by their explicit edits above.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: `447 passed` (440 + 7 new).

- [ ] **Step 7: Commit**

```bash
git add src/brd tests
git commit -m "Pass the project to every insert path and to migrate_project"
```

---

### Task 2: `brd import` checks edge targets in code

The FK on `blocked_by.blocks_on_id` / `refs.dst_id` goes away in Task 3. This task adds the code check first, while the schema is still v3, so the user-visible contract never lapses (spec B8).

**Files:**
- Modify: `src/brd/core.py` (new `_require_import_target`; `import_tree`)
- Modify: `src/brd/snapshot.py` (`_load_export`)
- Test: `tests/test_snapshot.py`

**Interfaces:**
- Consumes: `core.import_tree(conn, project_id, nodes)` and `snapshot._load_export(conn, project_id, snap)` from Task 1.
- Produces: `core._require_import_target(conn: sqlite3.Connection, snapshot_ids: set[str], target_id: str, what: str) -> None`. It raises `ImportFormatError` whose message contains `target_id`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_snapshot.py`, change the import line `from tests.cli_helpers import err, ok` to `from tests.cli_helpers import err, invoke, ok`, then append:

```python
GHOST = "0b6f4c1e-dead-4222-8333-444455556666"


def _import_error_into_fresh(tmp_path, monkeypatch, data):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(data))
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    ok("init")
    result = invoke("import", snapshot)
    assert result.exit_code == 1, result.output
    return other, json.loads(result.stdout)["error"]


def _assert_nothing_imported(other):
    assert ok("list") == [] and ok("issue", "list") == [] and ok("doc", "list") == []
    docs_dir = paths.project_docs_dir(other)
    assert not docs_dir.exists() or list(docs_dir.iterdir()) == []


def test_import_rejects_unknown_blocker(populated, tmp_path, monkeypatch):
    data = ok("export")
    data["cards"][0]["blocked_by"].append(GHOST)
    other, error = _import_error_into_fresh(tmp_path, monkeypatch, data)
    assert error["type"] == "ImportFormatError"
    assert GHOST in error["message"]
    _assert_nothing_imported(other)


def test_import_rejects_unknown_ref_target(populated, tmp_path, monkeypatch):
    data = ok("export")
    data["refs"].append({"src_id": populated["card"]["id"], "dst_id": GHOST, "origin": "explicit"})
    other, error = _import_error_into_fresh(tmp_path, monkeypatch, data)
    assert error["type"] == "ImportFormatError"
    assert GHOST in error["message"]
    _assert_nothing_imported(other)


def test_old_tree_snapshot_names_the_unknown_blocker(project, tmp_path, monkeypatch):
    a = ok("add", "--title", "A")
    issue = ok("issue", "open", "--title", "Q", "--blocks", a["id"])
    tree = ok("tree")
    other, error = _import_error_into_fresh(tmp_path, monkeypatch, tree)
    assert error["type"] == "ImportFormatError"
    assert issue["id"] in error["message"]
    assert ok("list") == []


@pytest.mark.parametrize("fmt", ["export", "tree"])
def test_import_blocker_already_on_board_is_accepted(project, tmp_path, fmt):
    issue = ok("issue", "open", "--title", "Q")
    card_id = "5d0f6a52-7c55-4a8e-9d0b-0c1f2e3a4b5c"
    node = {
        "id": card_id,
        "title": "Imported",
        "description": None,
        "status": "todo",
        "blocked_by": [issue["id"]],
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "children": [],
    }
    data = {"brd_export": 1, "cards": [node]} if fmt == "export" else [node]
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(data))
    ok("import", snapshot)
    assert ok("show", card_id)["blocked_by"] == [issue["id"]]


def test_round_trip_keeps_refs_between_snapshot_entities(populated, tmp_path, monkeypatch):
    data = ok("export")
    assert data["refs"], "populated has an explicit issue -> document ref"
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(data))
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    ok("init")
    ok("import", snapshot)
    assert ok("export")["refs"] == data["refs"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_snapshot.py -v -k "unknown or already_on_board or keeps_refs"`
Expected: `test_import_rejects_unknown_blocker`, `test_import_rejects_unknown_ref_target` and `test_old_tree_snapshot_names_the_unknown_blocker` FAIL on `assert GHOST in error["message"]` / `assert issue["id"] in error["message"]`, because today's message is the FK's `FOREIGN KEY constraint failed`. The `already_on_board` and `keeps_refs` tests PASS. They guard against the new check being too strict.

- [ ] **Step 3: Implement the check**

In `src/brd/core.py`, add after `_require_blocker`:

```python
def _require_import_target(
    conn: sqlite3.Connection, snapshot_ids: set[str], target_id: str, what: str
) -> None:
    # Edge targets carry no foreign key, so an import checks them itself:
    # each must be in the snapshot or already on this board.
    if target_id not in snapshot_ids and entities.kind_of(conn, target_id) is None:
        raise ImportFormatError(
            f"snapshot {what} {target_id} is neither in the snapshot nor on this board"
        )
```

In `core.import_tree`, directly after the `for node, _ in flattened:` loop that raises `CardAlreadyExistsError` and before `try:`, add:

```python
    snapshot_ids = {node["id"] for node, _ in flattened}
    for node, _ in flattened:
        for blocker_id in node.get("blocked_by", []):
            _require_import_target(conn, snapshot_ids, blocker_id, "blocker")
```

In `snapshot._load_export`, directly after the `for doc in doc_rows: documents._check_unique(...)` loop and before `contents = {...}`, add:

```python
    snapshot_ids = set(entity_ids)
    for node, _ in flattened:
        for blocker_id in node.get("blocked_by", []):
            core._require_import_target(conn, snapshot_ids, blocker_id, "blocker")
    for r in snap.get("refs", []):
        if r.get("origin", "explicit") == "explicit":
            core._require_import_target(conn, snapshot_ids, r["dst_id"], "ref target")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_snapshot.py -v`
Expected: all PASS, including the existing `test_old_tree_snapshot_with_unknown_blocker_imports_nothing`.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: `453 passed`.

- [ ] **Step 6: Commit**

```bash
git add src/brd/core.py src/brd/snapshot.py tests/test_snapshot.py
git commit -m "Check imported edge targets in code instead of relying on the FK"
```

---

### Task 3: Schema v4 — entities and documents record their project, edge targets lose their FK

The switch. The register triggers go away, so every insert path writes its `entities` row in the same transaction as its kind row.

**Files:**
- Modify: `src/brd/db.py` (`SCHEMA_VERSION`, new schema constants, `_rebuild_table`, `_migrate_to_v4`, `migrate_project`, `insert_entity`, `insert_card`)
- Modify: `src/brd/issues.py` (`open_issue`), `src/brd/documents.py` (`add`), `src/brd/core.py` (`import_tree`), `src/brd/snapshot.py` (`_load_export`, import `db`), `src/brd/master.py` (`_copy_cards`)
- Modify: `tests/factories.py`, `tests/test_migration.py`, `tests/test_db.py`, `tests/test_master.py`, `tests/test_core.py`, `tests/test_issues.py`, `tests/test_documents.py`, `tests/test_refs.py`, `tests/test_project_scope.py`

**Interfaces:**
- Consumes: the Task 1 signatures.
- Produces:
  - `db.SCHEMA_VERSION = 4`
  - `db.insert_entity(conn: sqlite3.Connection, project_id: str, entity_id: str, kind: str) -> None` (does not commit)
  - `db._migrate_to_v4(conn: sqlite3.Connection, project: Project) -> None` (Task 4 appends triggers to it; Task 3's T5 monkeypatches it)
  - `tests.factories.OTHER_PROJECT: Project` (id `22222222-2222-4222-8222-222222222222`), `add_project(conn, project) -> str`, `make_issue(..., project_id=PROJECT.id)`, `make_document(..., project_id=PROJECT.id)`

- [ ] **Step 1: Extend the factories**

Replace `tests/factories.py` with:

```python
from brd import db
from brd.models import Card, Project

NOW = "2026-09-24T00:00:00+00:00"

PROJECT = Project(
    id="11111111-1111-4111-8111-111111111111",
    name="test",
    root_path="/test",
    created_at=NOW,
)
OTHER_PROJECT = Project(
    id="22222222-2222-4222-8222-222222222222",
    name="other",
    root_path="/other",
    created_at=NOW,
)


def add_project(conn, project):
    """A second projects row in one board file: no command reaches this
    before story S3, so multi-project tests insert it directly."""
    conn.execute(
        "INSERT INTO projects (id, name, root_path, created_at) VALUES (?, ?, ?, ?)",
        (project.id, project.name, project.root_path, project.created_at),
    )
    conn.commit()
    return project.id


def make_card(
    conn, id_, title=None, description=None, parent_id=None, status="todo", project_id=PROJECT.id
):
    db.insert_card(
        conn, project_id, Card(id_, title or id_, description, status, parent_id, NOW, NOW)
    )
    return id_


def make_issue(conn, id_, title=None, body=None, status="open", project_id=PROJECT.id):
    with conn:
        db.insert_entity(conn, project_id, id_, "issue")
        conn.execute(
            "INSERT INTO issues (id, title, body, status, close_reason, created_at, "
            "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (id_, title or id_, body, status, "resolved" if status == "closed" else None, NOW, NOW),
        )
    return id_


def make_document(conn, id_, stem, content="", title=None, project_id=PROJECT.id):
    with conn:
        db.insert_entity(conn, project_id, id_, "document")
        conn.execute(
            "INSERT INTO documents (id, project_id, title, source_path, stem, content_hash, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (id_, project_id, title or stem, f"docs/{stem}.md", stem, "0" * 64, NOW, NOW),
        )
    backups = db.docs_dir(conn)
    backups.mkdir(parents=True, exist_ok=True)
    (backups / f"{id_}.md").write_text(content)
    return id_
```

- [ ] **Step 2: Write the migration tests (T1–T5, Review Focus 2–4)**

In `tests/test_migration.py`:

(a) Change the import line `from tests.factories import PROJECT` to:

```python
from tests.factories import PROJECT, make_card, make_document
```

(b) After the existing `_tables` helper, add:

```python
def _names(conn, type_):
    return {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = ?", (type_,))
    }


def _rows(conn, table, columns="*"):
    return sorted(tuple(r) for r in conn.execute(f"SELECT {columns} FROM {table}"))


REGISTER_TRIGGERS = {"cards_register_entity", "issues_register_entity", "documents_register_entity"}
V4_INDEXES = {"entities_project", "blocked_by_target", "refs_target"}
PROJECT_ROW = (PROJECT.id, PROJECT.name, PROJECT.root_path, PROJECT.created_at)


def _make_v3(path):
    # A faithful v3 board: the real historical migrations, then raw inserts
    # that the v3 register triggers turn into entities rows.
    conn = sqlite3.connect(path)  # foreign keys OFF, like the migrations run
    db._migrate_to_v1(conn)
    db._migrate_to_v2(conn)
    db._migrate_to_v3(conn)
    conn.execute("PRAGMA user_version = 3")
    conn.execute(INSERT_CARD, ("p", "p", None))
    conn.execute(INSERT_CARD, ("c", "c", "p"))
    conn.execute(
        "INSERT INTO issues (id, title, body, status, close_reason, created_at, updated_at) "
        "VALUES ('i', 'Q', 'body', 'open', NULL, 'now', 'now')"
    )
    conn.execute(
        "INSERT INTO documents (id, title, source_path, stem, content_hash, created_at, "
        "updated_at) VALUES ('d', 'Notes', 'docs/notes.md', 'notes', 'h', 'now', 'now')"
    )
    conn.execute("INSERT INTO blocked_by (card_id, blocks_on_id) VALUES ('c', 'p')")
    conn.execute("INSERT INTO blocked_by (card_id, blocks_on_id) VALUES ('p', 'i')")
    conn.execute(
        "INSERT INTO comments (id, entity_id, author, body, created_at) "
        "VALUES ('k', 'c', 'me', 'hi', 'now')"
    )
    conn.execute("INSERT INTO tags (entity_id, tag) VALUES ('d', 'design')")
    conn.execute("INSERT INTO refs (src_id, dst_id, origin) VALUES ('c', 'd', 'explicit')")
    conn.execute("INSERT INTO refs (src_id, dst_id, origin) VALUES ('i', 'c', 'link')")
    conn.commit()
    # The v4 rename only works if the trigger drop really comes first; that
    # is only exercised if the fixture really carries every register trigger.
    assert _names(conn, "trigger") == REGISTER_TRIGGERS
    conn.close()


V3_UNCHANGED_TABLES = ("cards", "issues", "comments", "tags", "blocked_by", "refs")
DOC_COLUMNS = "id, title, source_path, stem, content_hash, created_at, updated_at"
```

(c) Replace `test_fresh_db_gets_current_schema` with:

```python
def test_fresh_db_gets_current_schema(tmp_path):
    conn = db.connect(tmp_path / "p.db")
    db.migrate_project(conn, PROJECT)
    assert db.SCHEMA_VERSION == 4
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
    assert _tables(conn) == {
        "projects", "entities", "cards", "blocked_by", "issues", "documents",
        "comments", "tags", "refs",
    }
    assert _rows(conn, "projects") == [PROJECT_ROW]
    assert V4_INDEXES <= _names(conn, "index")
    assert not {name for name in _names(conn, "trigger") if name.endswith("_register_entity")}
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
```

(d) Replace `test_v0_cards_are_backfilled_into_entities` with:

```python
def test_v0_cards_are_backfilled_into_entities(v0_path):
    conn = db.connect(v0_path)
    db.migrate_project(conn, PROJECT)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    assert _rows(conn, "entities", "id, kind, project_id") == [
        ("c", "card", PROJECT.id), ("o", "card", PROJECT.id), ("p", "card", PROJECT.id),
    ]
```

(e) Delete `test_inserting_a_card_registers_its_entity` entirely. It encoded the trigger contract that v4 removes, and T8 in `tests/test_db.py` replaces it.

(f) In `test_dangling_legacy_rows_are_dropped_not_fatal`, append these lines at the end of the function:

```python
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert _rows(conn, "entities", "id, project_id") == [("a", PROJECT.id)]
```

(g) Replace `test_v1_db_upgrades_to_v2_and_keeps_entity_trigger` and `test_v2_db_upgrades_to_v3_and_accepts_archived` with the following. The old tests rolled a freshly migrated board back to an older shape. A fresh board is now v4, and rolling v4 back that way leaves a v4 `entities`/`projects`, so the boards are now built from the real historical migrations:

```python
def _make_v1(path):
    conn = sqlite3.connect(path)
    db._migrate_to_v1(conn)
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()


def _make_v2_without_archived(path):
    conn = sqlite3.connect(path)
    db._migrate_to_v1(conn)
    # The v2 shape: the pre-archived CHECK.
    conn.execute("DROP TRIGGER cards_register_entity")
    conn.execute("DROP TABLE cards")
    conn.execute(db._cards_sql("cards", ("todo", "in_progress", "done", "merged", "canceled")))
    conn.execute(db._register_trigger("cards", "card"))
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()


@pytest.mark.parametrize("make_board", [_make_v1, _make_v2_without_archived])
def test_v1_and_v2_boards_upgrade_to_v4_and_accept_archived(tmp_path, make_board):
    path = tmp_path / "p.db"
    make_board(path)

    conn = db.connect(path)
    db.migrate_project(conn, PROJECT)

    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    make_card(conn, "x", status="archived")
    row = conn.execute("SELECT kind, project_id FROM entities WHERE id = 'x'").fetchone()
    assert tuple(row) == ("card", PROJECT.id)
```

(h) Append:

```python
def test_v3_board_migrates_to_v4_with_project_id(tmp_path):
    path = tmp_path / "project.db"
    _make_v3(path)
    v3 = sqlite3.connect(path)
    before = {table: _rows(v3, table) for table in V3_UNCHANGED_TABLES}
    before_documents = _rows(v3, "documents", DOC_COLUMNS)
    before_entities = _rows(v3, "entities", "id, kind")
    v3.close()

    conn = db.connect(path)
    db.migrate_project(conn, PROJECT)

    assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
    assert {table: _rows(conn, table) for table in V3_UNCHANGED_TABLES} == before
    assert _rows(conn, "documents", DOC_COLUMNS) == before_documents
    assert _rows(conn, "entities", "id, kind") == before_entities
    assert _rows(conn, "entities", "DISTINCT project_id") == [(PROJECT.id,)]
    assert _rows(conn, "documents", "DISTINCT project_id") == [(PROJECT.id,)]
    assert _rows(conn, "projects") == [PROJECT_ROW]
    assert not _names(conn, "trigger") & REGISTER_TRIGGERS
    assert V4_INDEXES <= _names(conn, "index")
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_v4_migration_failure_leaves_v3_board_intact(tmp_path, monkeypatch):
    path = tmp_path / "project.db"
    _make_v3(path)
    real_migrate_to_v4 = db._migrate_to_v4

    def migrate_then_fail(conn, project):
        real_migrate_to_v4(conn, project)
        raise RuntimeError("boom")

    monkeypatch.setattr(db, "_migrate_to_v4", migrate_then_fail)
    conn = db.connect(path)
    with pytest.raises(RuntimeError, match="boom"):
        db.migrate_project(conn, PROJECT)

    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    assert REGISTER_TRIGGERS <= _names(conn, "trigger")
    assert "projects" not in _tables(conn)
    assert _rows(conn, "entities", "id, kind") == [
        ("c", "card"), ("d", "document"), ("i", "issue"), ("p", "card"),
    ]
    assert len(_rows(conn, "cards")) == 2
    assert len(_rows(conn, "documents")) == 1


def test_migrated_board_still_rejects_case_only_stem_collision(tmp_path):
    path = tmp_path / "project.db"
    _make_v3(path)
    conn = db.connect(path)
    db.migrate_project(conn, PROJECT)
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        make_document(conn, "d2", "Notes")  # docs/Notes.md vs the copied docs/notes.md
```

- [ ] **Step 3: Write the schema tests in `tests/test_db.py` (T8, T9, T12, T13) and fix its raw inserts**

(a) Change `from tests.factories import PROJECT` to:

```python
from tests.factories import (
    OTHER_PROJECT,
    PROJECT,
    add_project,
    make_card,
    make_document,
    make_issue,
)
```

(b) In `test_cards_status_check_constraint_rejects_blocked`, add as the line after `db.init_project_schema(conn, PROJECT)`:

```python
    db.insert_entity(conn, PROJECT.id, "c1", "card")
```

(c) Replace the `_insert_card` helper with:

```python
def _insert_card(conn, card_id, parent_id=None):
    db.insert_entity(conn, PROJECT.id, card_id, "card")
    conn.execute(
        "INSERT INTO cards (id, title, description, status, parent_id, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (card_id, "t", None, "todo", parent_id, "now", "now"),
    )
```

(d) Replace `test_blocked_by_foreign_keys_are_enforced` (the `ghost` target is now accepted by the schema) with:

```python
def test_edge_targets_accept_unknown_ids(pconn):
    make_card(pconn, "c1")
    db.add_blocked_by_edge(pconn, "c1", "not-an-entity")
    pconn.execute(
        "INSERT INTO refs (src_id, dst_id, origin) VALUES ('c1', 'not-an-entity', 'explicit')"
    )
    pconn.commit()
    assert db.list_blockers_of(pconn, "c1") == ["not-an-entity"]
    with pytest.raises(sqlite3.IntegrityError):
        db.add_blocked_by_edge(pconn, "not-an-entity", "c1")
    with pytest.raises(sqlite3.IntegrityError):
        pconn.execute(
            "INSERT INTO refs (src_id, dst_id, origin) VALUES ('not-an-entity', 'c1', 'explicit')"
        )
```

(e) Append:

```python
def _ids(conn, sql):
    return [row[0] for row in conn.execute(sql)]


def test_no_register_trigger_so_raw_kind_insert_without_entity_fails(pconn):
    with pytest.raises(sqlite3.IntegrityError):
        pconn.execute(
            "INSERT INTO cards (id, title, status, created_at, updated_at) "
            "VALUES ('c', 'c', 'todo', 'now', 'now')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        pconn.execute(
            "INSERT INTO issues (id, title, status, created_at, updated_at) "
            "VALUES ('i', 'i', 'open', 'now', 'now')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        pconn.execute(
            "INSERT INTO documents (id, project_id, title, source_path, stem, content_hash, "
            "created_at, updated_at) VALUES ('d', ?, 'd', 'docs/d.md', 'd', 'h', 'now', 'now')",
            (PROJECT.id,),
        )
    pconn.rollback()
    assert _count(pconn, "SELECT COUNT(*) FROM entities") == 0


def test_document_unique_per_project(pconn):
    add_project(pconn, OTHER_PROJECT)
    make_document(pconn, "d1", "a")
    make_document(pconn, "d2", "a", project_id=OTHER_PROJECT.id)
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        make_document(pconn, "d3", "a")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        make_document(pconn, "d4", "A")
    assert _ids(pconn, "SELECT id FROM documents ORDER BY id") == ["d1", "d2"]
    assert _ids(pconn, "SELECT id FROM entities ORDER BY id") == ["d1", "d2"]


def test_deleting_project_row_cascades_its_entities(pconn):
    add_project(pconn, OTHER_PROJECT)
    for project, n in ((PROJECT, "1"), (OTHER_PROJECT, "2")):
        make_card(pconn, f"c{n}", project_id=project.id)
        make_issue(pconn, f"i{n}", project_id=project.id)
        make_document(pconn, f"d{n}", f"notes{n}", project_id=project.id)
        pconn.execute(
            "INSERT INTO comments (id, entity_id, author, body, created_at) "
            "VALUES (?, ?, 'me', 'hi', 'now')",
            (f"k{n}", f"c{n}"),
        )
        pconn.execute("INSERT INTO tags (entity_id, tag) VALUES (?, 'design')", (f"d{n}",))
    db.add_blocked_by_edge(pconn, "c2", "c1")

    pconn.execute("DELETE FROM projects WHERE id = ?", (PROJECT.id,))
    pconn.commit()

    assert _ids(pconn, "SELECT id FROM entities ORDER BY id") == ["c2", "d2", "i2"]
    assert _ids(pconn, "SELECT id FROM cards") == ["c2"]
    assert _ids(pconn, "SELECT id FROM issues") == ["i2"]
    assert _ids(pconn, "SELECT id FROM documents") == ["d2"]
    assert _ids(pconn, "SELECT id FROM comments") == ["k2"]
    assert _ids(pconn, "SELECT entity_id FROM tags") == ["d2"]
    # D8: an incoming edge from a row that survives stays.
    assert db.list_blockers_of(pconn, "c2") == ["c1"]
```

(`_count` already exists in `tests/test_db.py`. It is defined above `test_delete_card_removes_incoming_edges_without_fk_cascade`. The new functions are appended after it, so they can use it.)

- [ ] **Step 4: Write the insert-path tests (T7, Review Focus 1)**

`tests/test_core.py`: change `from tests.factories import PROJECT` to `from tests.factories import OTHER_PROJECT, PROJECT, add_project` and append:

```python
def _entity_project(conn, entity_id):
    return conn.execute(
        "SELECT project_id FROM entities WHERE id = ?", (entity_id,)
    ).fetchone()[0]


def test_create_card_records_its_project(conn):
    add_project(conn, OTHER_PROJECT)
    card = core.create_card(conn, OTHER_PROJECT.id, "Card")
    assert _entity_project(conn, card.id) == OTHER_PROJECT.id


def test_import_tree_records_its_project(conn):
    parent = core.create_card(conn, PROJECT.id, "Parent")
    core.create_card(conn, PROJECT.id, "Child", parent_id=parent.id)
    tree = core.build_tree(conn)

    fresh_conn = db.connect(":memory:")
    db.init_project_schema(fresh_conn, OTHER_PROJECT)
    core.import_tree(fresh_conn, OTHER_PROJECT.id, tree)

    projects = {r[0] for r in fresh_conn.execute("SELECT project_id FROM entities")}
    assert projects == {OTHER_PROJECT.id}
```

`tests/test_issues.py`: change `from tests.factories import PROJECT, make_document` to `from tests.factories import OTHER_PROJECT, PROJECT, add_project, make_document` and append:

```python
def test_open_issue_records_its_project(pconn):
    add_project(pconn, OTHER_PROJECT)
    issue = issues.open_issue(pconn, OTHER_PROJECT.id, "Q")
    row = pconn.execute("SELECT kind, project_id FROM entities WHERE id = ?", (issue.id,)).fetchone()
    assert tuple(row) == ("issue", OTHER_PROJECT.id)
```

`tests/test_documents.py`: change `from tests.factories import PROJECT` to `from tests.factories import OTHER_PROJECT, PROJECT, add_project` and append:

```python
def test_add_records_its_project(pconn, root):
    add_project(pconn, OTHER_PROJECT)
    doc = documents.add(pconn, OTHER_PROJECT.id, root, write(root, "docs/a.md", "x"))
    entity = pconn.execute(
        "SELECT kind, project_id FROM entities WHERE id = ?", (doc.id,)
    ).fetchone()
    assert tuple(entity) == ("document", OTHER_PROJECT.id)
    stored = pconn.execute("SELECT project_id FROM documents WHERE id = ?", (doc.id,)).fetchone()
    assert stored[0] == OTHER_PROJECT.id
```

`tests/test_project_scope.py`: replace the import block at the top with:

```python
import sqlite3

import pytest

from brd import core, db, documents, issues, snapshot
from brd.models import Card
from tests.factories import NOW, OTHER_PROJECT, PROJECT, add_project, make_card
```

and append:

```python
def _entity_count(conn):
    return conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]


def test_failed_card_insert_leaves_no_entity_row(pconn):
    with pytest.raises(sqlite3.IntegrityError):
        make_card(pconn, "bad", status="blocked")  # CHECK violation on the cards row
    pconn.commit()
    assert _entity_count(pconn) == 0


def test_failed_document_insert_leaves_no_entity_row(pconn, tmp_path, monkeypatch):
    root = tmp_path / "repo"
    source = root / "docs" / "a.md"
    source.parent.mkdir(parents=True)
    source.write_text("")
    documents.add(pconn, PROJECT.id, root, source)
    # A concurrent writer got past the pre-check: the UNIQUE constraint fires.
    monkeypatch.setattr(documents, "_check_unique", lambda *args, **kwargs: None)
    with pytest.raises(sqlite3.IntegrityError):
        documents.add(pconn, PROJECT.id, root, source)
    pconn.commit()
    assert _entity_count(pconn) == 1


def test_snapshot_load_records_its_project(pconn, tmp_path):
    add_project(pconn, OTHER_PROJECT)
    snap = {
        "brd_export": 1,
        "cards": [
            {"id": "c", "title": "C", "description": None, "status": "todo", "blocked_by": [],
             "created_at": NOW, "updated_at": NOW, "children": []}
        ],
        "issues": [
            {"id": "i", "title": "I", "body": None, "status": "open", "close_reason": None,
             "created_at": NOW, "updated_at": NOW}
        ],
        "documents": [
            {"id": "d", "title": "D", "source_path": "docs/d.md", "content": "x",
             "content_hash": "h", "created_at": NOW, "updated_at": NOW}
        ],
    }
    snapshot.load(pconn, OTHER_PROJECT.id, tmp_path, snap)
    rows = {r[0]: r[1] for r in pconn.execute("SELECT id, project_id FROM entities")}
    assert rows == {"c": OTHER_PROJECT.id, "i": OTHER_PROJECT.id, "d": OTHER_PROJECT.id}
    stored = pconn.execute("SELECT project_id FROM documents WHERE id = 'd'").fetchone()
    assert stored[0] == OTHER_PROJECT.id
```

- [ ] **Step 5: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_migration.py tests/test_db.py tests/test_project_scope.py -q`
Expected: many FAIL / ERROR with `AttributeError: module 'brd.db' has no attribute 'insert_entity'` (factories) or `'_migrate_to_v4'`, and `user_version` `3 != 4`.

- [ ] **Step 6: Implement schema v4 in `src/brd/db.py`**

(a) Change `SCHEMA_VERSION = 3` to `SCHEMA_VERSION = 4`.

(b) After the `_ENTITY_KINDS` / `_register_trigger` definitions and before `_migrate_to_v1`, add:

```python
_ENTITIES_SQL = """
CREATE TABLE {name} (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('card', 'issue', 'document')),
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE
)
"""

_DOCUMENTS_SQL = """
CREATE TABLE {name} (
    id TEXT PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL,
    title TEXT NOT NULL,
    source_path TEXT NOT NULL,
    stem TEXT NOT NULL COLLATE NOCASE,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (project_id, source_path),
    UNIQUE (project_id, stem COLLATE NOCASE)
)
"""

# From v4 on, edge targets have no foreign key: a target may live in another
# project, and deleting an entity removes its incoming edges explicitly.
_V4_BLOCKED_BY_SQL = """
CREATE TABLE {name} (
    card_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    blocks_on_id TEXT NOT NULL,
    PRIMARY KEY (card_id, blocks_on_id)
)
"""

_V4_REFS_SQL = """
CREATE TABLE {name} (
    src_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    dst_id TEXT NOT NULL,
    origin TEXT NOT NULL CHECK (origin IN ('explicit', 'link')),
    PRIMARY KEY (src_id, dst_id, origin)
)
"""

_V4_INDEXES = [
    "CREATE INDEX entities_project ON entities(project_id, kind)",
    "CREATE INDEX blocked_by_target ON blocked_by(blocks_on_id)",
    "CREATE INDEX refs_target ON refs(dst_id)",
]

_DOCUMENT_COLUMNS = "title, source_path, stem, content_hash, created_at, updated_at"
```

(c) After `_migrate_to_v3`, add:

```python
def _rebuild_table(
    conn: sqlite3.Connection,
    table: str,
    create_sql: str,
    columns: str,
    values: str,
    params: tuple = (),
) -> None:
    # SQLite's usual rebuild: create the new shape, copy, drop, rename.
    # Child foreign keys name the table, so they follow the rename.
    conn.execute(create_sql.format(name=f"{table}_new"))
    conn.execute(f"INSERT INTO {table}_new ({columns}) SELECT {values} FROM {table}", params)
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE {table}_new RENAME TO {table}")


def _migrate_to_v4(conn: sqlite3.Connection, project: Project) -> None:
    # Drop the register triggers first: ALTER TABLE RENAME re-parses every
    # trigger, and their INSERT INTO entities would break the rebuilds.
    for table, _ in _ENTITY_KINDS:
        conn.execute(f"DROP TRIGGER IF EXISTS {table}_register_entity")
    # A legacy board may carry a stray projects table; the board's own row
    # replaces it.
    conn.execute("DROP TABLE IF EXISTS projects")
    conn.execute(_PROJECTS_SQL.format(name="projects"))
    conn.execute(
        "INSERT INTO projects (id, name, root_path, created_at) VALUES (?, ?, ?, ?)",
        (project.id, project.name, project.root_path, project.created_at),
    )
    _rebuild_table(
        conn, "entities", _ENTITIES_SQL, "id, kind, project_id", "id, kind, ?", (project.id,)
    )
    _rebuild_table(
        conn,
        "documents",
        _DOCUMENTS_SQL,
        f"id, project_id, {_DOCUMENT_COLUMNS}",
        f"id, ?, {_DOCUMENT_COLUMNS}",
        (project.id,),
    )
    _rebuild_table(
        conn, "blocked_by", _V4_BLOCKED_BY_SQL, "card_id, blocks_on_id", "card_id, blocks_on_id"
    )
    _rebuild_table(
        conn, "refs", _V4_REFS_SQL, "src_id, dst_id, origin", "src_id, dst_id, origin"
    )
    for statement in _V4_INDEXES:
        conn.execute(statement)
```

(d) In `migrate_project`, after `if version < 3: _migrate_to_v3(conn)` add:

```python
        if version < 4:
            _migrate_to_v4(conn, project)
```

(e) Replace `insert_card` with the following, and add `insert_entity` directly above it:

```python
def insert_entity(
    conn: sqlite3.Connection, project_id: str, entity_id: str, kind: str
) -> None:
    # No commit: callers insert the kind row in the same transaction, so the
    # two land together or not at all.
    conn.execute(
        "INSERT INTO entities (id, kind, project_id) VALUES (?, ?, ?)",
        (entity_id, kind, project_id),
    )


def insert_card(conn: sqlite3.Connection, project_id: str, card: Card) -> None:
    with conn:
        insert_entity(conn, project_id, card.id, "card")
        conn.execute(
            "INSERT INTO cards (id, title, description, status, parent_id, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                card.id,
                card.title,
                card.description,
                card.status,
                card.parent_id,
                card.created_at,
                card.updated_at,
            ),
        )
```

- [ ] **Step 7: Write the entity row on every other insert path**

`src/brd/issues.py`, in `open_issue`: replace

```python
    conn.execute(
        "INSERT INTO issues (id, title, body, status, close_reason, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (issue.id, issue.title, issue.body, issue.status, None, now, now),
    )
    conn.commit()
```

with

```python
    with conn:
        db.insert_entity(conn, project_id, issue.id, "issue")
        conn.execute(
            "INSERT INTO issues (id, title, body, status, close_reason, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (issue.id, issue.title, issue.body, issue.status, None, now, now),
        )
```

`src/brd/documents.py`, in `add`: replace

```python
    conn.execute(
        "INSERT INTO documents (id, title, source_path, stem, content_hash, created_at, "
        "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (doc.id, doc.title, doc.source_path, doc.stem, doc.content_hash, doc.created_at, doc.updated_at),
    )
    conn.commit()
```

with

```python
    with conn:
        db.insert_entity(conn, project_id, doc.id, "document")
        conn.execute(
            "INSERT INTO documents (id, project_id, title, source_path, stem, content_hash, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (doc.id, project_id, doc.title, doc.source_path, doc.stem, doc.content_hash,
             doc.created_at, doc.updated_at),
        )
```

`src/brd/core.py`, in `import_tree`'s `with conn:` block, add as the first statement inside `for node, parent_id in flattened:`, directly after the `status = ...` line:

```python
                db.insert_entity(conn, project_id, node["id"], "card")
```

`src/brd/snapshot.py`: change `from brd import core, documents, entities, issues, refs` to `from brd import core, db, documents, entities, issues, refs`. In `_load_export`'s `with conn:` block:

- In the cards loop, add `db.insert_entity(conn, project_id, node["id"], "card")` directly after the `status = ...` line.
- In the issues loop, add `db.insert_entity(conn, project_id, i["id"], "issue")` as the first statement.
- Replace the documents loop with:

```python
            for d in doc_rows:
                digest = documents._hash(contents[d["id"]]) if d["id"] in contents else d["content_hash"]
                db.insert_entity(conn, project_id, d["id"], "document")
                conn.execute(
                    "INSERT INTO documents (id, project_id, title, source_path, stem, "
                    "content_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (d["id"], project_id, d["title"], d["source_path"],
                     PurePosixPath(d["source_path"]).stem, digest, d["created_at"],
                     d["updated_at"]),
                )
```

`src/brd/master.py`, in `_copy_cards`: replace the cards loop with

```python
        for row in old_conn.execute("SELECT * FROM cards"):
            db.insert_entity(new_conn, project.id, row["id"], "card")
            new_conn.execute(
                "INSERT INTO cards (id, title, description, status, "
                "parent_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                tuple(row),
            )
```

- [ ] **Step 8: Replace the raw card inserts in `tests/test_master.py`**

Change `from tests.factories import PROJECT` to `from tests.factories import PROJECT, make_card`.

In `test_init_project_twice_preserves_existing_cards`, replace `master.init_project(repo)` (the first call) with `project = master.init_project(repo)`, and replace the `conn.execute("INSERT INTO cards ...", (...))` + `conn.commit()` pair with:

```python
        make_card(conn, "c1", title="Existing card", project_id=project.id)
```

In `test_init_project_migrates_legacy_uuid_marker_preserving_cards`, replace the `old_conn.execute("INSERT INTO cards ...", (...))` + `old_conn.commit()` pair with:

```python
    make_card(old_conn, "c1", title="Old card")
```

In `test_init_project_migrates_in_repo_format_preserving_cards`, replace the `old_conn.execute("INSERT INTO cards ...", (...))` + `old_conn.commit()` pair with:

```python
    make_card(old_conn, "c1", title="In-repo card")
```

- [ ] **Step 8a: Route raw `DELETE FROM entities` tests through the delete paths**

Without the FK, a raw `DELETE FROM entities` no longer removes the rows that point at the entity (spec B7: incoming edges go through `db.delete_incoming_edges`, which `entities.delete` and `db.delete_card` call). Three existing tests relied on the old cascade and break or go vacuous at v4:

- `tests/test_migration.py`, `test_deleting_entity_cascades_to_card_and_edges`: replace `conn.execute("DELETE FROM entities WHERE id = 'o'")` + `conn.commit()` with `db.delete_card(conn, "o")`. (Its `list_blockers_of(conn, "c") == []` assertion fails otherwise.)
- `tests/test_refs.py`, `test_deleted_target_disappears_from_refs`: change `from brd import refs` to `from brd import entities, refs` and replace `pconn.execute("DELETE FROM entities WHERE id = ?", (B,))` with `entities.delete(pconn, B)`. (Otherwise the dangling `refs` row makes `refs.outgoing` call `{**None, ...}` and raise `TypeError`.)
- `tests/test_issues.py`, `test_deleting_issue_unblocks`: change `from brd import core, issues, refs` to `from brd import core, entities, issues, refs` and replace `pconn.execute("DELETE FROM entities WHERE id = ?", (issue.id,))` with `entities.delete(pconn, issue.id)`. (It would still pass on the leftover edge, but would no longer test that deleting the issue removes the edge.)

`tests/test_comments.py::test_comments_cascade_with_entity` stays as it is: `comments.entity_id` keeps its FK and cascade.

- [ ] **Step 9: Run the targeted tests**

Run: `uv run pytest tests/test_migration.py tests/test_db.py tests/test_project_scope.py tests/test_core.py tests/test_issues.py tests/test_documents.py tests/test_master.py tests/test_refs.py -q`
Expected: all PASS.

- [ ] **Step 10: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass. The CLI suites (`test_cli*.py`, `test_snapshot.py`) cover T18: export → import into a fresh project round-trips. If a test still does a raw `INSERT INTO cards|issues|documents` that relied on the register trigger, `grep -rn "INSERT INTO \(cards\|issues\|documents\)" tests/` finds it. Route it through `make_card` / `make_issue` / `make_document`, or put `db.insert_entity(...)` before it. The `INSERT INTO cards` lines in `tests/test_migration.py`'s `_make_v0` / `_make_v3` and in `tests/test_cli_app.py:44` build pre-v4 boards and are correct as they are.

- [ ] **Step 11: Commit**

```bash
git add src/brd tests
git commit -m "Schema v4: entities and documents record their project, edge targets lose their FK"
```

---

### Task 4: Same-project triggers for documents and card parents

**Files:**
- Modify: `src/brd/db.py` (`_V4_TRIGGERS`, end of `_migrate_to_v4`)
- Test: `tests/test_db.py`, `tests/test_migration.py`

**Interfaces:**
- Consumes: `db._migrate_to_v4(conn, project)`, `db.insert_entity`, factories from Task 3.
- Produces: triggers `documents_project_insert`, `documents_project_update`, `cards_parent_project_insert`, `cards_parent_project_update`. Their `RAISE(ABORT, ...)` messages contain `same project`.

- [ ] **Step 1: Write the failing tests (T10, T11, trigger presence)**

Append to `tests/test_db.py`:

```python
_INSERT_DOCUMENT = (
    "INSERT INTO documents (id, project_id, title, source_path, stem, content_hash, "
    "created_at, updated_at) VALUES (?, ?, 'T', ?, ?, 'h', 'now', 'now')"
)


def test_document_project_must_match_entity(pconn):
    add_project(pconn, OTHER_PROJECT)
    db.insert_entity(pconn, PROJECT.id, "d", "document")
    with pytest.raises(sqlite3.IntegrityError, match="same project"):
        pconn.execute(_INSERT_DOCUMENT, ("d", OTHER_PROJECT.id, "docs/d.md", "d"))
    pconn.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="same project"):
        pconn.execute(_INSERT_DOCUMENT, ("ghost", PROJECT.id, "docs/g.md", "g"))
    pconn.rollback()

    make_document(pconn, "ok", "fine")
    with pytest.raises(sqlite3.IntegrityError, match="same project"):
        pconn.execute("UPDATE documents SET project_id = ? WHERE id = 'ok'", (OTHER_PROJECT.id,))
    pconn.rollback()
    stored = pconn.execute("SELECT project_id FROM documents WHERE id = 'ok'").fetchone()
    assert stored[0] == PROJECT.id


def test_card_parent_must_be_in_same_project(pconn):
    add_project(pconn, OTHER_PROJECT)
    make_card(pconn, "foreign", project_id=OTHER_PROJECT.id)
    make_card(pconn, "home")

    with pytest.raises(sqlite3.IntegrityError, match="same project"):
        make_card(pconn, "child", parent_id="foreign")
    assert db.get_card(pconn, "child") is None

    with pytest.raises(sqlite3.IntegrityError, match="same project"):
        pconn.execute("UPDATE cards SET parent_id = 'foreign' WHERE id = 'home'")
    pconn.rollback()
    assert db.get_card(pconn, "home").parent_id is None

    make_card(pconn, "kid", parent_id="home")
    assert db.get_card(pconn, "kid").parent_id == "home"

    # A parent that is not a card at all still fails on the FK, not the trigger.
    db.insert_entity(pconn, PROJECT.id, "orphan", "card")
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        pconn.execute(
            "INSERT INTO cards (id, title, status, parent_id, created_at, updated_at) "
            "VALUES ('orphan', 'o', 'todo', 'ghost', 'now', 'now')"
        )
    pconn.rollback()
```

In `tests/test_migration.py`, add after `V4_INDEXES = ...`:

```python
V4_TRIGGERS = {
    "documents_project_insert",
    "documents_project_update",
    "cards_parent_project_insert",
    "cards_parent_project_update",
}
```

Append `assert _names(conn, "trigger") == V4_TRIGGERS` as the last line of both `test_fresh_db_gets_current_schema` and `test_v3_board_migrates_to_v4_with_project_id`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_db.py::test_document_project_must_match_entity tests/test_db.py::test_card_parent_must_be_in_same_project tests/test_migration.py::test_fresh_db_gets_current_schema tests/test_migration.py::test_v3_board_migrates_to_v4_with_project_id -v`
Expected: the two `test_db` tests FAIL with `DID NOT RAISE` (or, for the `ghost` document, with a regex mismatch against `FOREIGN KEY constraint failed`). The two migration tests FAIL with `set() == {...}`.

- [ ] **Step 3: Implement the triggers**

In `src/brd/db.py`, after `_V4_INDEXES`, add:

```python
_SAME_PROJECT_DOCUMENT = (
    "WHEN NEW.project_id IS NOT (SELECT project_id FROM entities WHERE id = NEW.id) "
    "BEGIN SELECT RAISE(ABORT, 'a document must be in the same project as its entity'); END"
)

# Fires only when the parent's entity exists and sits in another project; a
# parent that is not a card at all is left to the parent_id foreign key.
_SAME_PROJECT_PARENT = (
    "WHEN NEW.parent_id IS NOT NULL "
    "AND (SELECT project_id FROM entities WHERE id = NEW.parent_id) IS NOT NULL "
    "AND (SELECT project_id FROM entities WHERE id = NEW.parent_id) "
    "IS NOT (SELECT project_id FROM entities WHERE id = NEW.id) "
    "BEGIN SELECT RAISE(ABORT, 'a card''s parent must be in the same project as the card'); END"
)

_V4_TRIGGERS = [
    f"CREATE TRIGGER documents_project_insert BEFORE INSERT ON documents {_SAME_PROJECT_DOCUMENT}",
    "CREATE TRIGGER documents_project_update BEFORE UPDATE OF id, project_id ON documents "
    f"{_SAME_PROJECT_DOCUMENT}",
    f"CREATE TRIGGER cards_parent_project_insert BEFORE INSERT ON cards {_SAME_PROJECT_PARENT}",
    "CREATE TRIGGER cards_parent_project_update BEFORE UPDATE OF parent_id ON cards "
    f"{_SAME_PROJECT_PARENT}",
]
```

At the end of `_migrate_to_v4`, after the `_V4_INDEXES` loop, add:

```python
    for statement in _V4_TRIGGERS:
        conn.execute(statement)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: the same command as Step 2.
Expected: 4 PASS.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass. `core.create_card` / `update_card` still raise `CardNotFoundError` for a missing parent before any SQL runs, so `tests/test_core.py`'s missing-parent tests are unaffected.

- [ ] **Step 6: Commit**

```bash
git add src/brd/db.py tests/test_db.py tests/test_migration.py
git commit -m "Reject documents and card parents that cross projects"
```

---

### Task 5: A v4 board must belong to the project that opens it

**Files:**
- Modify: `src/brd/db.py` (`board_projects`, `_require_board_project`, `migrate_project`)
- Test: `tests/test_migration.py`

**Interfaces:**
- Consumes: v4 schema from Task 3.
- Produces: `db.board_projects(conn: sqlite3.Connection) -> list[Project]`. It returns the board's `projects` rows ordered by `created_at`, or `[]` when the board is below v4. Task 6 uses it.

- [ ] **Step 1: Write the failing test (T6)**

In `tests/test_migration.py`, change the factories import to `from tests.factories import OTHER_PROJECT, PROJECT, make_card, make_document`, add `from brd.errors import MigrationError` after `from brd import db, paths`, and append:

```python
def test_migrate_project_rejects_board_of_other_project(tmp_path):
    conn = db.connect(tmp_path / "p.db")
    db.migrate_project(conn, PROJECT)
    db.migrate_project(conn, PROJECT)  # same project: a no-op
    assert _rows(conn, "projects") == [PROJECT_ROW]

    with pytest.raises(MigrationError) as excinfo:
        db.migrate_project(conn, OTHER_PROJECT)
    assert PROJECT.id in str(excinfo.value)
    assert OTHER_PROJECT.id in str(excinfo.value)
    assert _rows(conn, "projects") == [PROJECT_ROW]


def test_migrate_project_rejects_v4_board_with_no_project(tmp_path):
    conn = db.connect(tmp_path / "p.db")
    db.migrate_project(conn, PROJECT)
    conn.execute("DELETE FROM projects")
    conn.commit()

    with pytest.raises(MigrationError, match="no project") as excinfo:
        db.migrate_project(conn, PROJECT)
    assert PROJECT.id in str(excinfo.value)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_migration.py -v -k "rejects"`
Expected: both FAIL with `DID NOT RAISE <class 'brd.errors.MigrationError'>`.

- [ ] **Step 3: Implement the check**

In `src/brd/db.py`, add directly above `migrate_project`:

```python
def board_projects(conn: sqlite3.Connection) -> list[Project]:
    """The projects rows a board records; [] below v4, where a projects
    table, if any, is a legacy leftover."""
    if conn.execute("PRAGMA user_version").fetchone()[0] < 4:
        return []
    rows = conn.execute("SELECT * FROM projects ORDER BY created_at").fetchall()
    return [_row_to_project(row) for row in rows]


def _require_board_project(conn: sqlite3.Connection, project: Project) -> None:
    # Without this, a registry/board mismatch surfaces later as a raw FK
    # error on the first insert.
    stored = [row.id for row in board_projects(conn)]
    if project.id in stored:
        return
    held = f"project {', '.join(stored)}" if stored else "no project"
    raise MigrationError(
        f"this board records {held}, not project {project.id}; "
        "the registry and the board disagree"
    )
```

In `migrate_project`, replace the fast path

```python
    if version >= SCHEMA_VERSION:
        return
```

with

```python
    if version >= SCHEMA_VERSION:
        _require_board_project(conn, project)
        return
```

and replace the re-check inside the lock

```python
        if version >= SCHEMA_VERSION:
            conn.rollback()
            return
```

with

```python
        if version >= SCHEMA_VERSION:
            conn.rollback()
            _require_board_project(conn, project)
            return
```

The re-check's `return` sits inside the `try:` whose `finally:` turns `foreign_keys` back on. Raising from there goes through `except BaseException: conn.rollback(); raise`, and a second rollback is harmless.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_migration.py -v`
Expected: all PASS, including `test_concurrent_first_run_migrations_all_succeed`. Every thread passes `PROJECT`.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/brd/db.py tests/test_migration.py
git commit -m "Refuse to open a v4 board that belongs to another project"
```

---

### Task 6: `brd init` reuses the board's project id; legacy copy drops dangling edges

**Files:**
- Modify: `src/brd/master.py` (`_board_project`, `_settle_project`, `_copy_cards`)
- Test: `tests/test_master.py`

**Interfaces:**
- Consumes: `db.board_projects(conn)` from Task 5; `master._settle_project` / `_copy_cards(old, new, project)` from Task 1; `db.insert_entity` from Task 3.
- Produces: `master._board_project(db_path: Path) -> Project | None`.

- [ ] **Step 1: Write the failing tests (T16, T17)**

In `tests/test_master.py`, add `from brd.cli import _app` after `from brd import db, master, paths`, and append:

```python
def test_copy_cards_drops_dangling_legacy_edges(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    brd_dir = repo / ".brd"
    brd_dir.mkdir(parents=True)
    old_conn = db.connect(brd_dir / "board.db")
    db.init_project_schema(old_conn, PROJECT)
    make_card(old_conn, "c1")
    make_card(old_conn, "c2")
    db.add_blocked_by_edge(old_conn, "c2", "c1")
    db.add_blocked_by_edge(old_conn, "c1", "ghost")  # the legacy board's dangling edge
    old_conn.close()

    project = master.init_project(repo)

    conn = db.connect(paths.project_db_path(repo))
    try:
        entities = conn.execute("SELECT id, project_id FROM entities ORDER BY id").fetchall()
        edges = conn.execute("SELECT card_id, blocks_on_id FROM blocked_by").fetchall()
    finally:
        conn.close()
    assert [tuple(r) for r in entities] == [("c1", project.id), ("c2", project.id)]
    assert [tuple(r) for r in edges] == [("c2", "c1")]


def _board_project_ids(repo):
    conn = db.connect(paths.project_db_path(repo))
    try:
        return [row[0] for row in conn.execute("SELECT id FROM projects")]
    finally:
        conn.close()


def test_init_project_board_row_matches_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    first = master.init_project(repo)
    assert _board_project_ids(repo) == [first.id]

    renamed = master.init_project(repo, name="x")
    assert renamed.id == first.id
    assert _board_project_ids(repo) == [first.id]

    # The registry is lost; the board still knows its project.
    for suffix in ("", "-wal", "-shm"):
        paths.master_db_path().with_name(f"master.db{suffix}").unlink(missing_ok=True)
    again = master.init_project(repo)
    assert again.id == first.id
    assert again.created_at == first.created_at
    assert master.list_all_projects() == [again]

    monkeypatch.chdir(repo)
    ctx = _app.open_project()
    try:
        assert ctx.project.id == first.id
    finally:
        ctx.conn.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_master.py -v -k "dangling or matches_registry"`
Expected: `test_copy_cards_drops_dangling_legacy_edges` FAILS because `edges` also holds `("c1", "ghost")`. `test_init_project_board_row_matches_registry` FAILS with `MigrationError: this board records project <first.id>, not project <new id>` at `again = master.init_project(repo)`.

- [ ] **Step 3: Implement**

In `src/brd/master.py`, replace `_copy_cards` with:

```python
def _copy_cards(old_db_path: Path, new_db_path: Path, project: Project) -> None:
    old_conn = db.connect(old_db_path)
    new_conn = db.connect(new_db_path)
    try:
        db.init_project_schema(new_conn, project)
        copied: set[str] = set()
        for row in old_conn.execute("SELECT * FROM cards"):
            db.insert_entity(new_conn, project.id, row["id"], "card")
            new_conn.execute(
                "INSERT INTO cards (id, title, description, status, "
                "parent_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                tuple(row),
            )
            copied.add(row["id"])
        for row in old_conn.execute("SELECT card_id, blocks_on_id FROM blocked_by"):
            # Same rule as _migrate_to_v1: keep only edges between copied
            # cards. Edge targets have no FK, so nothing else would stop one.
            if row["card_id"] in copied and row["blocks_on_id"] in copied:
                new_conn.execute(
                    "INSERT INTO blocked_by (card_id, blocks_on_id) VALUES (?, ?)",
                    tuple(row),
                )
        new_conn.commit()
    finally:
        old_conn.close()
        new_conn.close()
```

Add `_board_project` directly above `_settle_project`:

```python
def _board_project(db_path: Path) -> Project | None:
    """The project a board file records, when it records exactly one."""
    if not db_path.is_file():
        return None
    conn = db.connect(db_path)
    try:
        rows = db.board_projects(conn)
    finally:
        conn.close()
    return rows[0] if len(rows) == 1 else None
```

Replace `_settle_project` with:

```python
def _settle_project(root_path: Path, name: str | None) -> Project:
    """The project this root is, settled before any board file is touched so
    the board and the registry agree on its id: the registered row, else the
    one project the board already records, else a new project."""
    project_name = name or root_path.name
    conn = _master_conn()
    try:
        stored = db.get_project(conn, str(root_path))
    finally:
        conn.close()
    known = stored or _board_project(paths.project_db_path(root_path))
    if known is not None:
        return Project(
            id=known.id,
            name=project_name,
            root_path=str(root_path),
            created_at=known.created_at,
        )
    return Project(
        id=db.new_project_id(),
        name=project_name,
        root_path=str(root_path),
        created_at=_now(),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_master.py -v`
Expected: all PASS, including the three legacy-marker tests.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/brd/master.py tests/test_master.py
git commit -m "Reuse the board's project id on init and drop dangling legacy edges"
```

---

## Spec coverage check

| Spec | Task(s) | Tests |
|---|---|---|
| B1 fresh board | 3, 4 | T1 `test_fresh_db_gets_current_schema` |
| B2 v3 → v4, v0/v1/v2 chains, atomic failure | 3, 4 | T2, T3 (`test_v0_*`, `test_dangling_*`), T4 (`test_v1_and_v2_boards_upgrade_to_v4_and_accept_archived`), T5, RF2, RF3, RF4 |
| B3 `migrate_project(conn, project)`, mismatch error, `init_project` settling | 1, 5, 6 | `test_migrate_project_requires_the_project`, T6, T17 |
| B4 insert paths write entity first, required `project_id`, no orphans | 1, 3 | `test_insert_paths_require_a_project_id`, T7 (core/issues/documents/import_tree/snapshot.load), T8, RF1 |
| B5 documents unique per project, project matches entity | 3, 4 | T9, T10, RF4 |
| B6 parent in same project | 4 | T11 |
| B7 edge targets have no FK, project cascade | 3 | T12, T13 |
| B8 import refuses dangling targets | 2 | T14 (3 tests), T15, RF5 |
| B9 legacy marker copy | 3, 6 | T16, existing legacy-marker tests |
| T18 CLI behaviour preserved | every task | full `uv run pytest` |
<!-- task-pipeline: validated -->
