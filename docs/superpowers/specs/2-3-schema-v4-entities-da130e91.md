# 2.3 Schema v4: entities and documents record their project; edge targets lose their FK

Card: `da130e91-691a-4837-8ed3-e000b6d56be3` (subtask of story `54de5e9d` "Project-scoped
schema", milestone `6aa7043a` "Single database and cross-project blocking"). Blocked by
2.2 (`a6a8dd67`, done on this branch's parent: `db.delete_incoming_edges`,
`src/brd/db.py:426-431`).

Parent design spec: `docs/superpowers/specs/2026-10-06-single-db-cross-project-blocking-design.md`
(in the main checkout; not in this branch's history). Cited by section and line as
**[P §n Lx]**.

## Goal

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

## Inherited constraints

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

## Behaviour

### B1. Fresh board

`db.migrate_project(conn, project)` on an empty file creates the v4 schema:

- `user_version` is `4` (`db.SCHEMA_VERSION == 4`).
- Tables: `projects`, `entities`, `cards`, `blocked_by`, `issues`, `documents`, `comments`,
  `tags`, `refs`.
- `projects` holds exactly one row, equal to `project`: `id`, `name`, `root_path`, `created_at`.
- Indexes `entities_project`, `blocked_by_target` and `refs_target` exist.
- No trigger named `*_register_entity` exists in `sqlite_master`.
- `PRAGMA foreign_key_check` is empty.

### B2. v3 board migrates to v4 with its project filled in

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

### B3. `migrate_project` needs the project; a v4 board must belong to it

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

### B4. Every insert path writes the entity row first, with the project

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

### B5. Documents are unique per project and agree with their entity

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

### B6. A card's parent is in the same project

- Inserting a card whose `parent_id` is a card of **another** project is rejected with
  `sqlite3.IntegrityError`. The message says the parent must be in the same project.
- Updating `cards.parent_id` to a card of another project is rejected the same way.
- `parent_id IS NULL` and same-project parents are accepted as today.
- A `parent_id` that is not a card at all still fails through the existing
  `REFERENCES cards(id)` FK. The trigger must not change that path: it only fires
  when the parent's entity exists and is in a different project. `core.create_card` /
  `update_card` still raise `CardNotFoundError` before any SQL runs, as today.

### B7. Edge targets have no FK

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

### B8. Commands still refuse dangling targets (code validation replaces the FK)

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

### B9. Legacy `.brd` marker migration still works

`master._copy_cards` (`src/brd/master.py:22-42`) copies a legacy board's cards and
`blocked_by` into the new board:

- It writes the cards' `entities` rows with the project settled in B3.
- It copies only edges whose both ends are copied cards, the same rule `_migrate_to_v1`
  applies (`src/brd/db.py:194-199`). Today a dangling edge makes `brd init` fail on the FK.
  Without the FK it would be stored silently. Dropping it matches how the v0→v1
  migration already treats legacy boards.
- The existing `tests/test_master.py` legacy-marker tests stay green.

## Implementation guidance (non-normative)

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

## Tests

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

## Review Focus (hand-off to the planner)

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

## Out of scope

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
