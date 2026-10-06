# 5.2 Import places each entry in its project

Card: `2dbf2631-f98c-43bc-802b-bec55cc9879b`. Second subtask of story `3d5969ce`
"Export/import v2" (spec section 5, D9-D11), in milestone `6aa7043a` "Single database and
cross-project blocking". Blocked by 5.1 (`a8e090a7`, merged into this branch): export
already writes v2, and import has a stopgap that accepts only a one-entry v2 file.

Parent design spec: `docs/superpowers/specs/2026-10-06-single-db-cross-project-blocking-design.md`.
It is in the main checkout (`/home/mtts/Code/brd/docs/...`), not in this branch's history.
Citations look like **[P §n Lx]** or **[P Dn Lx]**. Sibling spec cited:
`docs/superpowers/specs/5-1-export-is-a-list-of-a8e090a7.md` (**[5.1]**).

## Goal

Today `brd import` resolves the cwd project first (failing outside one), accepts only a
one-entry v2 file, puts that entry's body into the cwd project, and refuses any blocker or
ref whose target is neither in the file nor already in the database. This card makes
import read any v2 file and place each entry in its own project per D11, registering
projects where needed, inserting every entry in one transaction (all entities before any
edge), keeping edges to ids that do not exist (they are reported, not refused), and
reporting per-project counts plus how many imported edges still point at not-found ids.

## Inherited constraints

| Constraint | Source |
|---|---|
| A v1 export or legacy `brd tree` snapshot is wrapped as one entry with no project metadata. | [P §5 L213-L214] |
| One entry lands in the cwd project. If the cwd is not registered, register it, reusing the entry's project id when present and unused. | [P D11 L41], [P §5 L216-L217] |
| Several entries: the registered project with the same id; else register at the recorded `root_path` if that directory exists; else refuse, listing the paths. | [P D11 L41], [P §5 L218-L219] |
| A recorded `root_path` already registered under a different id is refused with a hint to import that entry alone from its directory. | [P §5 L220-L221] |
| Validate duplicate ids within the file, ids already in the database, document paths and stems as today. | [P §5 L222-L224] |
| One transaction: insert all entities of all entries, then all edges, comments, tags and refs. Backups are written before and removed on failure, as today. | [P §5 L228-L231] |
| Reindex link refs; report per-project counts plus the number of edges whose targets are still not-found. | [P §5 L232-L233] |
| Edge targets carry no foreign key; an edge whose target is not in the database is kept and reported as `not-found`. A not-found blocker blocks. | [P D6 L36], [P D7 L37] |
| Importing B after A reconnects A's not-found edges automatically. | [P §5 L237] |
| Current project = deepest registered `root_path` that is the cwd or an ancestor; `brd init` registers the cwd. | [P D5 L35], [P §2 L101-L106] |
| A target project that already has entities is refused; replacement, confirmation and `--yes` are 5.3. | card `2dbf2631`; [P D10 L40] belongs to card `7188185d` |
| Owned files: `src/brd/snapshot.py`, `src/brd/cli/snapshot.py`. | story card `3d5969ce` |

## Behavior

All refusals below are `BrdError` envelopes (`{"ok": false, "error": {type, message}}`,
exit 1) and write **nothing**: no project row, no entity, no edge, no comment, no tag, no
document backup file.

### B1. Reading and normalizing the file

Unchanged from today: unreadable file or invalid JSON → `ImportReadError`; the
`{"ok": true, "data": …}` envelope is unwrapped; `brd_export` other than 1 or 2 →
`ImportFormatError` "unsupported brd_export version …"; an object without `brd_export`
that is not a tree list → `ImportFormatError`; wrong shapes or types anywhere →
`ImportFormatError` whose message starts with `malformed snapshot: `.

The file becomes a list of entries:

- **v2** (`brd_export: 2`): `projects` must be a list (else malformed). Each entry must be
  an object with `project` and all six body keys (`cards`, `issues`, `documents`,
  `comments`, `tags`, `refs`) (else malformed). `project` must be an object whose `id`,
  `name`, `root_path` and `created_at` are strings (else malformed).
- `projects: []` → `ImportFormatError` saying the snapshot has no project entries.
- Two entries with the same `project.id`, or the same `project.root_path` →
  `ImportFormatError` naming the duplicated value.
- **v1** (`brd_export: 1`) → one entry, body as in the file, no project.
- **legacy tree** (a list of card nodes, bare or in a `data` envelope) → one entry whose
  `cards` are the nodes and whose other lists are empty, no project. The derived
  `blockers` key on tree nodes is ignored, as today.

No message mentions "not supported yet" any more.

### B2. Placing a one-entry file (v2 with one entry, v1, legacy tree)

- If a project resolves from the cwd exactly as for every scoped command (the deepest
  registered root at or above the cwd), the entry lands in it. The entry's own
  `project` is ignored, whatever its id or `root_path`.
- If none resolves, the cwd itself is registered (the same `root_path` string `brd init`
  run there would store) and the entry lands in that new project:
  - `id`: the entry's `project.id` if no registered project has it; otherwise (or when
    the entry has no project) a new id, as `brd init` mints.
  - `name`: the entry's `project.name` when present, else the cwd's directory name.
  - `created_at`: the entry's `project.created_at` when present, else now.
- So `brd import` no longer fails with `ProjectNotFoundError` outside a project, and no
  prior `brd init` is needed.

### B3. Placing a multi-entry file (v2 with two or more entries)

The cwd plays no part; the command works from any directory, registered or not. For each
entry, in file order:

1. A registered project whose id equals `project.id` → that project (even if its
   `root_path` differs from the recorded one).
2. Else, if `project.root_path` is already the `root_path` of a registered project (which
   by step 1 has a different id) → refuse with `ProjectAlreadyExistsError`: the message
   names the path, the registered project (name and id) and the entry's id, and hints to
   import that entry alone from its directory (a one-entry file lands in the cwd project,
   B2).
3. Else, if `project.root_path` is an absolute path to an existing directory → register a
   project with the entry's `id`, `name`, `root_path` and `created_at`.
4. Else the entry is unplaceable.

The first root conflict (step 2) refuses at once. Otherwise, if any entry is unplaceable,
refuse with `ProjectRootNotFoundError` (new) whose message lists **every** unplaceable
`root_path` (and its entry's project name), not just the first.

### B4. Target projects must be empty

After placement, if any target that was already registered owns at least one entity,
refuse with `ProjectNotEmptyError` (new). The message names each such project (name and
id) with its card, issue and document counts and says replacing a project's contents is
not supported yet. Newly registered targets are empty by construction.

This replaces today's partial-merge behaviour (importing new ids into a non-empty board
used to succeed): it is the condition 5.3 will turn into confirm-and-replace, so the
refusal keeps one rule for "target has entities" across both cards. As a result,
re-importing a snapshot into the project it came from now fails with
`ProjectNotEmptyError` (before: `EntityAlreadyExistsError`, or `CardAlreadyExistsError`
for tree snapshots).

### B5. Validation across all entries

Checked after placement and before anything is written, over the whole file:

- An entity id (card, issue, document) appearing twice anywhere in the file, within or
  across entries → `ImportFormatError` "snapshot contains duplicate ids".
- An entity id already in the database (necessarily owned by a project outside the
  targets, since targets are empty) → `EntityAlreadyExistsError` naming the id. Same for
  a comment id already in the database. This applies to tree snapshots too (no more
  `CardAlreadyExistsError` from import).
- Document `source_path` rules and per-project path/stem uniqueness, as today, each
  checked against the entry's target project.
- **No check on edge targets.** A `blocked_by` id or explicit ref `dst_id` that is neither
  in the file nor in the database is accepted and imported as stored (D6).

### B6. Writing

One transaction covers: registering every new project; then inserting every entity
(cards, issues, documents) of every entry, each owned by its entry's target project;
then every entry's `blocked_by` edges, comments, tags and explicit refs. Consequences
a user can observe:

- A card in entry A blocked by (or ref'd to) an entity in entry B of the same file is
  connected after import, whichever order the entries appear in.
- A comment or tag referencing an id that is in no entry and not in the database still
  fails the transaction → `ImportFormatError` "snapshot is internally inconsistent",
  nothing written, the backups written for this import removed (today's behaviour,
  now across all entries).
- Stored status `blocked` is imported as `todo`, as today.
- Document backups for every entry are written before the transaction and removed if it
  fails, as today.

After commit, link refs are reindexed for every imported entity (so `[[stem]]` and
`[[uuid]]` links in imported text resolve against the whole import).

### B7. Report

Success data (JSON mode):

```json
{
  "imported": 5, "cards": 2, "issues": 1, "documents": 1, "comments": 1,
  "projects": [
    {
      "project": {"id": "…", "name": "…", "root_path": "…", "created_at": "…"},
      "registered": true,
      "imported": 5, "cards": 2, "issues": 1, "documents": 1, "comments": 1
    }
  ],
  "not_found_edges": 0
}
```

- Top-level `imported` (entities), `cards`, `issues`, `documents`, `comments` are totals
  over all entries; the keys and meaning existing callers read stay the same for a
  one-project v1/v2 import. Tree imports now return this shape too (was
  `{"imported": n}`).
- `projects` has one item per entry in file order: the target project's row as stored
  after import, `registered: true` when this import registered it, and that entry's
  counts.
- `not_found_edges`: the number of imported edges (`blocked_by` rows plus explicit refs
  from the file) whose target id is not in the database once the import has committed.
  Edges into another entry of the file, or into an entity already in the database, are
  found.
- `--pretty` / `--human`: one line per project,
  `<name> (<root_path>): +<c> cards, +<i> issues, +<d> documents, +<m> comments`, with
  ` [registered]` appended for a newly registered project, then
  `not-found edge targets: <n>`.

### B8. Docs

- `brd import --help`: a snapshot of one project lands in the current project (registering
  the cwd if needed); a multi-project snapshot places each entry by id or recorded root;
  refuses when a target project already has entities; nothing is written on refusal.
- README import paragraph (after the export paragraph 5.1 wrote): the same rules in a few
  sentences, plus "edges to ids that are not in the database are kept and counted as
  not-found; importing the missing project later reconnects them". Drop the claim that
  import needs `brd init` first.
- `GUIDE` in `src/brd/cli/_app.py` stays as is.

## Interface for the planner

- `snapshot.load(conn, cwd: Path, raw) -> dict` replaces `load(conn, project_id, root,
  raw)`: import resolves or registers projects itself, so it no longer takes a project.
  It keeps the `malformed snapshot: …` mapping of `KeyError`/`TypeError`/
  `AttributeError`/`sqlite3.ProgrammingError`.
- Keep the steps visible as functions in `snapshot.py`: normalize → list of entries
  (`project: dict | None`, body); place → per entry a target (existing `Project`, or a
  `Project` to register); validate (B4, B5); write (B6); report (B7).
- Registration inside the import transaction needs a non-committing insert of a
  `Project` with a given id (`db.upsert_project` commits and upserts by root; it is not
  usable). Add a small helper to `src/brd/db.py` next to `upsert_project` (outside the
  story's owned files: reason is that `projects` SQL lives only in `db.py`). New error
  classes `ProjectRootNotFoundError`, `ProjectNotEmptyError` go in `src/brd/errors.py`
  (same reason).
- Cwd resolution: `master.resolve_project(conn, cwd)`, treating `ProjectNotFoundError` as
  "register the cwd". Registered root string: `str(cwd)` as `cli/project.py` passes to
  `init_project`.
- CLI: `import_cmd` must not go through `run()` (which fails outside a project). Use the
  module's `_run_global` style (connect, run, `fail` on `BrdError`), extended with an
  optional text renderer for B7's `--pretty` (export `--all` keeps its indented JSON).
- `core._require_import_target` loses its last callers in `snapshot.py`; `core.import_tree`
  is no longer called by import. Both live in `core.py` (not owned): leave them and their
  `tests/test_core.py` tests alone.

## Tests

Tier: **CLI integration** in `tests/test_snapshot.py` for every behaviour above, because
each is the observable outcome of `brd import` (envelope, exit code, what `list`, `show`,
`projects`, `export` see afterwards) and the existing import tests live there. Use the
`project` fixture and the file's helpers (`_fresh_project` = separate install,
`_another_project` = same install, `_import_error_into_fresh`, `_assert_nothing_imported`).
A refusal test also asserts `ok("projects")` is unchanged (no project row written).

Unregistered directory helper (new): `chdir` into a new dir under `tmp_path` without
`brd init`, optionally under a fresh `XDG_DATA_HOME`.

### New

1. `test_one_entry_import_registers_an_unregistered_cwd_with_the_entry_id` — export from
   `populated`; fresh install, unregistered dir: import succeeds; `brd projects` has one
   project at that dir with the entry's id, name and `created_at`; report has
   `registered: true`; `list` from the dir shows the cards.
2. `test_one_entry_import_mints_an_id_when_the_entry_id_is_taken` — same install with
   project A: from an unregistered dir, import a hand-built one-entry v2 file whose
   `project.id` is A's id and whose cards have new ids: succeeds, the new project's id
   differs from A's, A is unchanged.
3. `test_v1_and_tree_import_register_an_unregistered_cwd` — parametrised over a v1 file
   and a tree file: fresh install, unregistered dir named `restored`: succeeds, the
   registered project is named `restored` with a new id.
4. `test_one_entry_import_lands_in_the_cwd_project_from_a_subdirectory` — import from a
   subdirectory of an empty registered project: lands in it, no new project, the entry's
   different id and `root_path` ignored.
5. `test_multi_entry_import_matches_registered_projects_by_id` — same install with an
   empty project A. Hand-built two-entry file: entry 1 has A's id but a `root_path` that
   does not exist, and one card; entry 2 has a new id, the `root_path` of an existing
   unregistered dir, and one card. Import from an unrelated unregistered dir: entry 1
   lands in A (`registered: false`, A's root unchanged, missing recorded root ignored),
   entry 2 registers a project at its root (`registered: true`); per-project counts are
   1 card each.
6. `test_multi_entry_import_registers_at_recorded_roots` — `export --all` of A and B,
   then in a fresh install (dirs at the recorded paths still exist) import from an
   unregistered dir: `brd projects` lists A and B with their exported ids, names,
   roots and `created_at`; `registered: true` for both; `list` from each root shows that
   project's cards only.
7. `test_multi_entry_import_lists_every_missing_root` — hand-built two-entry file whose
   roots do not exist: `ProjectRootNotFoundError`, message contains both paths; nothing
   written.
8. `test_multi_entry_import_refuses_a_root_registered_under_another_id` — `export --all`;
   fresh install with a project `brd init`ed at A's recorded root (new id):
   `ProjectAlreadyExistsError`, message contains the root, the other project's id and
   the word "alone"; nothing written (B not registered either).
9. `test_import_refuses_a_non_empty_target` — parametrised: one-entry file into a project
   that has a card; multi-entry file whose entry matches by id a project that has an
   issue: `ProjectNotEmptyError` naming the project; nothing written.
10. `test_cross_entry_edges_connect_in_either_order` — A has card `a1` blocked by B's card
    `b1` and ref'd to B's issue; B's card blocked by A's issue. `export --all`, reverse
    the `projects` list, import into a fresh install at the recorded roots: `show a1`
    has blocker `b1` with `status` not `not-found`, refs present, `not_found_edges == 0`.
11. `test_unknown_edge_targets_are_kept_and_counted` — replaces
    `test_import_rejects_unknown_blocker`, `test_import_rejects_unknown_ref_target`,
    `test_old_tree_snapshot_with_unknown_blocker_imports_nothing` and
    `test_old_tree_snapshot_names_the_unknown_blocker`: append `GHOST` as a blocker and
    as a ref target (v2) / tree with an issue blocker absent from the tree: import
    succeeds, `not_found_edges` equals the number of such edges, `show` lists the
    blocker as `not-found` and the card resolves `blocked`.
12. `test_importing_the_missing_project_later_reconnects_edges` — A blocked on B's card;
    export A alone and B alone; fresh install: import A (from A's root) →
    `not_found_edges == 1`; import B (from B's root) → `not_found_edges == 0` and A's
    card's blocker is now found.
13. `test_duplicate_ids_across_entries_are_refused` — two entries sharing a card id:
    `ImportFormatError` "duplicate ids"; nothing written. Same file with two entries
    sharing `project.id`, and sharing `root_path`: `ImportFormatError`.
14. `test_id_owned_by_another_project_is_refused` — same install: export project A,
    create an empty project B, import A's file in B: `EntityAlreadyExistsError` naming the
    id; B still empty.
15. `test_import_report_shape_and_pretty` — one-project import report has the B7 keys and
    one `projects` item; `--pretty` prints the project line and the
    `not-found edge targets: 0` line.
16. `test_import_help_describes_placement` — `import --help` mentions the current project
    and multi-project placement.
17. Malformed v2 project objects added to `test_malformed_v2_snapshot_says_malformed`:
    `project` missing, `project: 5`, `project` lacking `root_path`.

### Updated

- `test_import_refuses_a_multi_entry_export` → only the `count == 0` case remains
  (no-entries `ImportFormatError`); the two-entry case is covered by new tests 5-8.
- `test_import_collision_touches_nothing` → re-import into the same project is now
  `ProjectNotEmptyError` (B4); keep "touches nothing".
- `test_old_tree_snapshot_still_imports` → result has the B7 shape with `imported == 2`;
  re-import is `ProjectNotEmptyError`.
- `test_import_stem_collision_touches_nothing` → the target already has a document, so
  `ProjectNotEmptyError`; a within-file path/stem duplicate is still refused
  (`ImportFormatError` or `Duplicate*Error`, nothing written).
- `test_import_blocker_already_on_board_is_accepted` → the issue lives in another
  project of the same install and the import goes into an empty project; blocker found,
  `not_found_edges == 0`.
- `tests/test_project_scope.py` calls `snapshot.load(conn, project_id, root, raw)` in three
  places; all must move to the new signature (they are unit tests of the owned module):
  - `test_insert_paths_require_a_project_id`: drop the `snapshot.load` case (load no longer
    takes a project id; it places entries itself).
  - `test_snapshot_load_records_its_project`: register a project whose `root_path` is
    `str(tmp_path)`, call `snapshot.load(pconn, tmp_path, snap)`, and assert every
    imported entity (and the document row) is owned by that project.
  - `test_import_checks_document_uniqueness_per_project`: the target project must now be
    empty, so the second import into the same project is `ProjectNotEmptyError`.
    Rewrite: importing a document whose path and stem Q's `qd` already uses into an empty
    project succeeds (uniqueness is per project); a snapshot with two documents sharing
    a path is refused and writes nothing.
- Every other existing import test keeps passing unchanged (round trip, wrapped envelope,
  unsafe source path, backup rollback, refs round trip, malformed cases).

### Verification

`uv run pytest` — full suite green.

## Out of scope

- Replacing a target project that has entities, the stderr `-/+` summary, the y/N prompt,
  `--yes`, no-TTY refusal, and naming the owner of a colliding id — card 5.3
  (`7188185d`).
- Any change to the export format or `brd export` (5.1).
- `core.import_tree` / `core._require_import_target` and their unit tests.
- Reindexing other projects' `[[uuid]]` links that point at newly imported ids.
- Changing `run()` / project resolution for other commands, or `brd init`.

---

# 5.2 Import places each entry in its project — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `brd import` reads any v2/v1/tree snapshot, places each entry in its own project (registering projects where needed), writes everything in one transaction with edges to unknown ids kept as not-found, and reports per-project counts.

**Architecture:** `snapshot.load(conn, cwd, raw)` becomes a visible pipeline in `src/brd/snapshot.py`: `_entries` (normalize to `_Entry` objects) → `_place` (one `_Target` per entry: an existing `Project` or one to register) → `_require_empty` (B4) → `_validate` (B5) → `_write` (B6, one transaction: projects, then all entities, then all links) → `_report` (B7). The CLI's `import` stops going through `run()` and uses the module's `_run_global` (connect, run, fail on `BrdError`), extended with a text renderer for `--pretty`.

**Tech Stack:** Python 3, sqlite3, Typer CLI, pytest (via `uv run pytest`).

**Spec:** `docs/superpowers/specs/5-2-import-places-each-2dbf2631.md` (prepended above).

## Global Constraints

- Owned files: `src/brd/snapshot.py`, `src/brd/cli/snapshot.py`. Allowed outside them, with reasons: `src/brd/db.py` (new `insert_project` — `projects` SQL lives only in `db.py`), `src/brd/errors.py` (new `ProjectRootNotFoundError`, `ProjectNotEmptyError`), tests, `README.md`.
- Every refusal is a `BrdError` envelope `{"ok": false, "error": {type, message}}`, exit 1, and writes **nothing**: no project row, no entity, no edge, no comment, no tag, no document backup file.
- `ImportFormatError` messages for shape problems start with `malformed snapshot: `.
- No message mentions "not supported yet" for snapshot format/entry-count problems (B4's "replacing a project's contents is not supported yet" is the one intended use).
- Registered root string for the cwd: `str(cwd)` exactly as `brd init` stores it (the CLI passes `Path.cwd()`).
- Do not touch `core.import_tree`, `core._require_import_target` or their tests in `tests/test_core.py`. Do not change `run()`, `brd init`, or the export format. `GUIDE` in `src/brd/cli/_app.py` stays as is.
- Verification: `uv run pytest` — full suite green (885 tests pass at the start of this plan).

## Review Focus

1. A transaction failure (e.g. a comment on an unknown entity) during an import that registers the cwd must leave no project row and no backup behind — the user retries in the same directory and must not find a half-registered empty project. Test: `test_failed_import_registers_no_project` (Task 1).
2. Two documents in one entry with the same `source_path` into an empty/new target: the per-project pre-check sees an empty project, so only the UNIQUE constraint catches it — must be `ImportFormatError`, nothing written, backups removed, no project registered. Test: `test_import_refuses_two_documents_with_one_path` (Task 1).
3. A recorded `root_path` that is relative, or names a regular file rather than a directory, is unplaceable and must be listed with the other missing roots, not registered. Test: extension of `test_multi_entry_import_lists_every_missing_root` (Task 2).
4. After a `ProjectRootNotFoundError`, creating the missing directories and re-running the same import must succeed (the refusal left no stale project rows that would now collide). Test: `test_multi_entry_import_succeeds_once_the_roots_exist` (Task 2).
5. Running a multi-entry import from inside a registered (empty) project must not put anything in that project: the cwd plays no part. Test: `test_multi_entry_import_ignores_the_cwd_project` (Task 2).

---

## File Structure

- `src/brd/snapshot.py` — import pipeline (`load`, `_Entry`, `_Target`, `_entries`, `_v2_entries`, `_v2_entry`, `_entry`, `_place`, `_place_in_cwd`, `_place_by_record`, `_require_empty`, `_validate`, `_write`, `_insert_entities`, `_insert_links`, `_report`). Export half unchanged.
- `src/brd/cli/snapshot.py` — `import_cmd` via `_run_global`; `_run_global` gains a `render` argument; `_import_text` renders B7 for `--pretty`.
- `src/brd/db.py` — `insert_project(conn, project)`: non-committing insert with a given id.
- `src/brd/errors.py` — `ProjectNotEmptyError`, `ProjectRootNotFoundError`.
- `tests/test_snapshot.py` — CLI integration tests for every behaviour.
- `tests/test_project_scope.py` — three unit tests moved to the new `load` signature.
- `tests/test_cli.py` — `test_import_rejects_colliding_ids` expects `ProjectNotEmptyError`.
- `README.md` — import paragraph.

---

### Task 1: One-entry import pipeline (B1, B2, B4, B5, B6, B7 JSON)

Rewrites `snapshot.load` as the pipeline, places a one-entry file in the cwd project or registers the cwd, refuses non-empty targets, drops the edge-target check, writes in one transaction, returns the B7 report. A multi-entry file is temporarily refused (Task 2 replaces that).

**Files:**
- Modify: `src/brd/errors.py` (append class)
- Modify: `src/brd/db.py:488-497` (add `insert_project` after `upsert_project`)
- Modify: `src/brd/snapshot.py:1-11` (imports, constants) and `src/brd/snapshot.py:73-241` (replace the whole import half)
- Modify: `src/brd/cli/snapshot.py:58-74` (`import_cmd`)
- Test: `tests/test_snapshot.py`, `tests/test_project_scope.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `master.resolve_project(conn, start: Path) -> Project` (raises `ProjectNotFoundError`), `db.get_project_by_id`, `db.get_project`, `db.new_project_id() -> str`, `core._now() -> str`, `core._flatten_tree(nodes) -> list[tuple[dict, str | None]]`, `documents._check_unique`, `documents._write_backup`, `documents.backup_path`, `documents._hash`, `entities.kind_of`, `refs.reindex`.
- Produces:
  - `db.insert_project(conn: sqlite3.Connection, project: Project) -> None` (no commit).
  - `errors.ProjectNotEmptyError(BrdError)`.
  - `snapshot.load(conn: sqlite3.Connection, cwd: Path, raw) -> dict` returning `{"imported", "cards", "issues", "documents", "comments": int, "projects": list[dict], "not_found_edges": int}`; each `projects` item is `{"project": {id, name, root_path, created_at}, "registered": bool, "imported", "cards", "issues", "documents", "comments": int}`.
  - In `snapshot.py`: `PROJECT_KEYS = ("id", "name", "root_path", "created_at")`, dataclasses `_Entry(project: dict | None, cards, issues, documents, comments, tags, refs)` with `entity_ids()`, `explicit_refs()`, `edge_targets()`, `counts()`; `_Target(project: Project, registered: bool)`; `_place(conn, cwd, entries) -> list[_Target]`; `_v2_entries(snap) -> list[_Entry]`.
  - In `tests/test_snapshot.py`: constants `T`, `CARD_1`, `CARD_2`, `PROJECT_X`, `PROJECT_Y`; helpers `_unregistered_dir(tmp_path, monkeypatch, name, data_home=None) -> Path` (resolved), `_snapshot_file(tmp_path, data, name="snapshot.json") -> Path`, `_import_error(snapshot) -> dict`, `_card_node(card_id, blocked_by=()) -> dict`, `_hand_entry(project_id, root_path, name="hand", cards=(), issues=(), refs=()) -> dict`, `_v2(*entries) -> dict`.

- [ ] **Step 1: Add the test helpers to `tests/test_snapshot.py`**

Insert right after the `_another_project` function (after its `return root, ok("init")` line):

```python
T = "2026-01-01T00:00:00+00:00"
CARD_1 = "c1000000-0000-4000-8000-000000000001"
CARD_2 = "c2000000-0000-4000-8000-000000000002"
PROJECT_X = "aaaaaaaa-0000-4000-8000-00000000000a"
PROJECT_Y = "bbbbbbbb-0000-4000-8000-00000000000b"


def _unregistered_dir(tmp_path, monkeypatch, name, data_home=None):
    """chdir into a new directory that no `brd init` registered; with
    data_home, on a fresh install whose data lives there. Returns the
    resolved path, the string `brd init` would store for it."""
    if data_home is not None:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / data_home))
    path = tmp_path / name
    path.mkdir(parents=True)
    monkeypatch.chdir(path)
    return path.resolve()


def _snapshot_file(tmp_path, data, name="snapshot.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return path


def _import_error(snapshot):
    result = invoke("import", snapshot)
    assert result.exit_code == 1, result.output
    return json.loads(result.stdout)["error"]


def _card_node(card_id, blocked_by=()):
    return {
        "id": card_id,
        "title": f"card {card_id[:2]}",
        "description": None,
        "status": "todo",
        "blocked_by": list(blocked_by),
        "created_at": T,
        "updated_at": T,
        "children": [],
    }


def _hand_entry(project_id, root_path, name="hand", cards=(), issues=(), refs=()):
    """A v2 project entry built by hand: a recorded project plus its body."""
    return {
        "project": {"id": project_id, "name": name, "root_path": str(root_path), "created_at": T},
        "cards": list(cards),
        "issues": list(issues),
        "documents": [],
        "comments": [],
        "tags": [],
        "refs": list(refs),
    }


def _v2(*entries):
    return {"brd_export": 2, "projects": list(entries)}
```

- [ ] **Step 2: Write the new failing tests in `tests/test_snapshot.py`**

Append at the end of the file:

```python
def test_one_entry_import_registers_an_unregistered_cwd_with_the_entry_id(
    populated, tmp_path, monkeypatch
):
    data = ok("export")
    recorded = _entry(data)["project"]
    snapshot = _snapshot_file(tmp_path, data)
    restored = _unregistered_dir(tmp_path, monkeypatch, "restored", data_home="other-data")
    result = ok("import", snapshot)
    (registered,) = ok("projects")
    assert registered == {
        "id": recorded["id"],
        "name": recorded["name"],
        "root_path": str(restored),
        "created_at": recorded["created_at"],
    }
    (item,) = result["projects"]
    assert item["registered"] is True
    assert item["project"] == registered
    assert populated["card"]["id"] in {c["id"] for c in ok("list")}


def test_one_entry_import_mints_an_id_when_the_entry_id_is_taken(project, tmp_path, monkeypatch):
    (a,) = ok("projects")
    snapshot = _snapshot_file(
        tmp_path, _v2(_hand_entry(a["id"], tmp_path / "nowhere", cards=[_card_node(CARD_1)]))
    )
    restored = _unregistered_dir(tmp_path, monkeypatch, "restored")
    result = ok("import", snapshot)
    (item,) = result["projects"]
    assert item["registered"] is True
    assert item["project"]["id"] != a["id"]
    assert item["project"]["root_path"] == str(restored)
    assert item["project"]["name"] == "hand"
    projects = {p["id"]: p for p in ok("projects")}
    assert projects == {a["id"]: a, item["project"]["id"]: item["project"]}
    assert [c["id"] for c in ok("list")] == [CARD_1]


@pytest.mark.parametrize("fmt", ["v1", "tree"])
def test_v1_and_tree_import_register_an_unregistered_cwd(tmp_path, monkeypatch, fmt):
    node = _card_node(CARD_1)
    data = {"brd_export": 1, "cards": [node]} if fmt == "v1" else [node]
    snapshot = _snapshot_file(tmp_path, data)
    restored = _unregistered_dir(tmp_path, monkeypatch, "restored", data_home="data")
    result = ok("import", snapshot)
    (registered,) = ok("projects")
    assert registered["name"] == "restored"
    assert registered["root_path"] == str(restored)
    assert registered["id"]
    (item,) = result["projects"]
    assert item["project"] == registered and item["registered"] is True
    assert [c["id"] for c in ok("list")] == [CARD_1]


def test_one_entry_import_lands_in_the_cwd_project_from_a_subdirectory(
    project, tmp_path, monkeypatch
):
    (a,) = ok("projects")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()  # an existing directory, still ignored for a one-entry file
    snapshot = _snapshot_file(
        tmp_path, _v2(_hand_entry(PROJECT_X, elsewhere, cards=[_card_node(CARD_1)]))
    )
    sub = project / "src" / "deep"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    result = ok("import", snapshot)
    assert ok("projects") == [a]
    (item,) = result["projects"]
    assert item["project"] == a and item["registered"] is False
    assert [c["id"] for c in ok("list")] == [CARD_1]


@pytest.mark.parametrize("fmt", ["export", "tree"])
def test_unknown_edge_targets_are_kept_and_counted(tmp_path, monkeypatch, fmt):
    node = _card_node(CARD_1, blocked_by=[GHOST])
    if fmt == "export":
        ghost_ref = {"src_id": CARD_1, "dst_id": GHOST, "origin": "explicit"}
        data = _v2(_hand_entry(PROJECT_X, tmp_path / "x", cards=[node], refs=[ghost_ref]))
        expected = 2
    else:
        data = [node]
        expected = 1
    snapshot = _snapshot_file(tmp_path, data)
    _unregistered_dir(tmp_path, monkeypatch, "restored", data_home="data")
    assert ok("import", snapshot)["not_found_edges"] == expected
    shown = ok("show", CARD_1)
    assert [(b["id"], b["status"]) for b in shown["blockers"]] == [(GHOST, "not-found")]
    assert shown["status"] == "blocked"
    if fmt == "export":
        assert [r["id"] for r in shown["refs"] if r["origin"] == "explicit"] == [GHOST]


def test_importing_the_missing_project_later_reconnects_edges(project, tmp_path, monkeypatch):
    a1 = ok("add", "--title", "a1")["id"]
    second, _ = _another_project(tmp_path, monkeypatch, "second")
    b1 = ok("add", "--title", "b1")["id"]
    b_snapshot = _snapshot_file(tmp_path, ok("export"), "b.json")
    monkeypatch.chdir(project)
    ok("block", a1, "--by", b1)
    a_snapshot = _snapshot_file(tmp_path, ok("export"), "a.json")

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "other-data"))
    assert ok("import", a_snapshot)["not_found_edges"] == 1
    assert [(b["id"], b["status"]) for b in ok("show", a1)["blockers"]] == [(b1, "not-found")]
    monkeypatch.chdir(second)
    assert ok("import", b_snapshot)["not_found_edges"] == 0
    monkeypatch.chdir(project)
    assert [(b["id"], b["status"]) for b in ok("show", a1)["blockers"]] == [(b1, "todo")]


def test_id_owned_by_another_project_is_refused(populated, tmp_path, monkeypatch):
    snapshot = _snapshot_file(tmp_path, ok("export"))
    _another_project(tmp_path, monkeypatch, "second")
    error = _import_error(snapshot)
    assert error["type"] == "EntityAlreadyExistsError"
    assert populated["card"]["id"] in error["message"]
    assert ok("list") == [] and ok("issue", "list") == [] and ok("doc", "list") == []
    assert len(ok("projects")) == 2


def test_import_report_shape_and_pretty(populated, tmp_path, monkeypatch):
    snapshot = _snapshot_file(tmp_path, ok("export"))
    _fresh_project(tmp_path, monkeypatch)
    result = ok("import", snapshot)
    assert set(result) == {
        "imported", "cards", "issues", "documents", "comments", "projects", "not_found_edges"
    }
    assert (
        result["imported"], result["cards"], result["issues"], result["documents"],
        result["comments"],
    ) == (4, 2, 1, 1, 1)
    (registered,) = ok("projects")
    assert result["projects"] == [
        {
            "project": registered,
            "registered": False,
            "imported": 4,
            "cards": 2,
            "issues": 1,
            "documents": 1,
            "comments": 1,
        }
    ]
    assert result["not_found_edges"] == 0


def test_failed_import_registers_no_project(populated, tmp_path, monkeypatch):
    data = ok("export")
    _entry(data)["comments"].append(
        {
            "id": "00000000-0000-0000-0000-000000000000",
            "entity_id": "does-not-exist",
            "author": "x",
            "body": "y",
            "created_at": T,
        }
    )
    snapshot = _snapshot_file(tmp_path, data)
    _unregistered_dir(tmp_path, monkeypatch, "restored", data_home="other-data")
    error = _import_error(snapshot)
    assert error["type"] == "ImportFormatError"
    assert "internally inconsistent" in error["message"]
    assert ok("projects") == []
    docs_dir = paths.docs_dir()
    assert not docs_dir.exists() or list(docs_dir.iterdir()) == []


def test_import_refuses_two_documents_with_one_path(populated, tmp_path, monkeypatch):
    data = ok("export")
    docs = _entry(data)["documents"]
    docs.append({**docs[0], "id": "d0c00000-0000-4000-8000-000000000001"})
    snapshot = _snapshot_file(tmp_path, data)
    _unregistered_dir(tmp_path, monkeypatch, "restored", data_home="other-data")
    error = _import_error(snapshot)
    assert error["type"] == "ImportFormatError"
    assert ok("projects") == []
    docs_dir = paths.docs_dir()
    assert not docs_dir.exists() or list(docs_dir.iterdir()) == []


def test_import_refuses_a_snapshot_with_no_entries(project, tmp_path, monkeypatch):
    other, error = _import_error_into_fresh(tmp_path, monkeypatch, _v2())
    assert error["type"] == "ImportFormatError"
    assert "no project entries" in error["message"]
    _assert_nothing_imported(other)
```

- [ ] **Step 3: Update and remove existing tests in `tests/test_snapshot.py`**

3a. Replace `test_import_collision_touches_nothing` with:

```python
def test_import_collision_touches_nothing(populated, tmp_path):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(ok("export")))
    before = len(ok("list"))
    assert err("import", snapshot) == "ProjectNotEmptyError"
    assert len(ok("list")) == before
    assert len(ok("projects")) == 1
```

3b. Replace `test_old_tree_snapshot_still_imports` with:

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
    result = ok("import", snapshot)
    assert (result["imported"], result["cards"]) == (2, 2)
    assert len(result["projects"]) == 1 and result["not_found_edges"] == 0
    assert err("import", snapshot) == "ProjectNotEmptyError"
```

3c. Replace `test_import_stem_collision_touches_nothing` with:

```python
def test_import_stem_collision_touches_nothing(populated, tmp_path, monkeypatch):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(ok("export")))
    other = _fresh_project(tmp_path, monkeypatch)
    write(other, "docs/notes.md", "local")
    ok("doc", "add", "docs/notes.md")
    assert err("import", snapshot) == "ProjectNotEmptyError"
    assert ok("list") == [] and ok("issue", "list") == []
    assert len(ok("doc", "list")) == 1
    assert len(ok("projects")) == 1
```

3d. Delete these four tests entirely (replaced by `test_unknown_edge_targets_are_kept_and_counted`): `test_old_tree_snapshot_with_unknown_blocker_imports_nothing`, `test_import_rejects_unknown_blocker`, `test_import_rejects_unknown_ref_target`, `test_old_tree_snapshot_names_the_unknown_blocker`.

3e. Replace `test_import_blocker_already_on_board_is_accepted` with:

```python
@pytest.mark.parametrize("fmt", ["export", "tree"])
def test_import_blocker_already_on_board_is_accepted(project, tmp_path, monkeypatch, fmt):
    issue = ok("issue", "open", "--title", "Q")
    node = _card_node(CARD_1, blocked_by=[issue["id"]])
    data = {"brd_export": 1, "cards": [node]} if fmt == "export" else [node]
    snapshot = _snapshot_file(tmp_path, data)
    # The issue lives in another project of this install; the target is empty.
    _another_project(tmp_path, monkeypatch, "second")
    result = ok("import", snapshot)
    assert result["not_found_edges"] == 0
    shown = ok("show", CARD_1)
    assert shown["blocked_by"] == [issue["id"]]
    assert [b["status"] for b in shown["blockers"]] == ["open"]
```

3f. Delete `test_import_refuses_a_multi_entry_export` (its zero-entry case is now `test_import_refuses_a_snapshot_with_no_entries`; the two-entry case moves to Task 2's tests).

3g. Add the malformed project-object cases to the parametrize list of `test_malformed_v2_snapshot_says_malformed`. Just above that test's `@pytest.mark.parametrize`, add:

```python
_EMPTY_BODY = {key: [] for key in ("cards", "issues", "documents", "comments", "tags", "refs")}
```

and append these three items to its `raw` list (after `{"brd_export": 2, "projects": [{"project": {}, "cards": []}]},`):

```python
        {"brd_export": 2, "projects": [dict(_EMPTY_BODY)]},
        {"brd_export": 2, "projects": [{"project": 5, **_EMPTY_BODY}]},
        {"brd_export": 2, "projects": [
            {"project": {"id": "x", "name": "n", "created_at": "t"}, **_EMPTY_BODY}
        ]},
```

- [ ] **Step 4: Update `tests/test_project_scope.py`**

4a. In the `test_insert_paths_require_a_project_id` parametrize list, delete the line
`        lambda conn, root, source: snapshot.load(conn, root, []),`
and change the `ids` line to:

```python
    ids=["insert_card", "create_card", "import_tree", "open_issue", "documents.add"],
```

4b. Replace `test_snapshot_load_records_its_project` with:

```python
def test_snapshot_load_records_its_project(pconn, tmp_path):
    other = dataclasses.replace(OTHER_PROJECT, root_path=str(tmp_path.resolve()))
    add_project(pconn, other)
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
    snapshot.load(pconn, tmp_path, snap)
    rows = {r[0]: r[1] for r in pconn.execute("SELECT id, project_id FROM entities")}
    assert rows == {"c": other.id, "i": other.id, "d": other.id}
    stored = pconn.execute("SELECT project_id FROM documents WHERE id = 'd'").fetchone()
    assert stored[0] == other.id
```

4c. Replace `test_import_checks_document_uniqueness_per_project` with:

```python
def test_import_checks_document_uniqueness_per_project(two, root):
    def doc(doc_id):
        return {"id": doc_id, "title": "N", "source_path": "docs/qnotes.md", "content": "x",
                "content_hash": "h", "created_at": NOW, "updated_at": NOW}

    third = Project(
        id="33333333-3333-4333-8333-333333333333",
        name="third",
        root_path=str(root.resolve()),
        created_at=NOW,
    )
    add_project(two, third)
    before = _state(two)
    with pytest.raises(ImportFormatError):
        snapshot.load(two, root, {"brd_export": 1, "documents": [doc("pn"), doc("pn2")]})
    assert _state(two) == before
    # Q's qd has this path and stem; uniqueness is per project.
    snapshot.load(two, root, {"brd_export": 1, "documents": [doc("pn")]})
    assert [d.id for d in documents.list_all(two, third.id)] == ["pn"]
```

4d. At the top of `tests/test_project_scope.py`, add `ImportFormatError,` to the `from brd.errors import (...)` list (alphabetical, after `EntityNotFoundError,`), and change `from brd.models import Card` to `from brd.models import Card, Project`.

- [ ] **Step 5: Update `tests/test_cli.py`**

In `test_import_rejects_colliding_ids`, change
`    assert payload["error"]["type"] == "CardAlreadyExistsError"`
to
`    assert payload["error"]["type"] == "ProjectNotEmptyError"`.

- [ ] **Step 6: Run the tests to verify they fail**

Run: `uv run pytest tests/test_snapshot.py tests/test_project_scope.py tests/test_cli.py -q`
Expected: FAIL — among others, `test_one_entry_import_registers_an_unregistered_cwd_with_the_entry_id` fails with `ProjectNotFoundError` (exit 1), `test_import_collision_touches_nothing` gets `EntityAlreadyExistsError` instead of `ProjectNotEmptyError`, `test_snapshot_load_records_its_project` fails with `TypeError` (missing argument `raw`), `test_unknown_edge_targets_are_kept_and_counted` fails with `ImportFormatError`.

- [ ] **Step 7: Add the error class**

Append to `src/brd/errors.py`:

```python


class ProjectNotEmptyError(BrdError):
    pass
```

- [ ] **Step 8: Add `db.insert_project`**

In `src/brd/db.py`, insert right after the `upsert_project` function (after its `return get_project(conn, project.root_path)` line):

```python


def insert_project(conn: sqlite3.Connection, project: Project) -> None:
    """Register project with its own id. No commit: import registers projects
    in the same transaction as their entities, so a failed import leaves
    no project behind."""
    conn.execute(
        "INSERT INTO projects (id, name, root_path, created_at) VALUES (?, ?, ?, ?)",
        (project.id, project.name, project.root_path, project.created_at),
    )
```

- [ ] **Step 9: Rewrite the import half of `src/brd/snapshot.py`**

9a. Replace lines 1-11 (imports and constants) with:

```python
import dataclasses
import sqlite3
from pathlib import Path, PurePosixPath

from brd import core, db, documents, entities, issues, master, refs
from brd.errors import (
    EntityAlreadyExistsError,
    ImportFormatError,
    ProjectNotEmptyError,
    ProjectNotFoundError,
)
from brd.models import Project

FORMAT_VERSION = 2
V1_FORMAT_VERSION = 1
ENTRY_BODY_KEYS = ("cards", "issues", "documents", "comments", "tags", "refs")
PROJECT_KEYS = ("id", "name", "root_path", "created_at")
COUNT_KEYS = ("imported", "cards", "issues", "documents", "comments")
```

9b. Replace everything from `def load(conn: sqlite3.Connection, project_id: str, root: Path, raw) -> dict:` (line 73) to the end of the file with:

```python
@dataclasses.dataclass
class _Entry:
    """One project's part of a snapshot, whatever format it came in. A v1
    export or a `brd tree` list has no recorded project."""

    project: dict | None
    cards: list[tuple[dict, str | None]]  # flattened (node, parent id), parents first
    issues: list[dict]
    documents: list[dict]
    comments: list[dict]
    tags: list[dict]
    refs: list[dict]

    def entity_ids(self) -> list[str]:
        return (
            [node["id"] for node, _ in self.cards]
            + [i["id"] for i in self.issues]
            + [d["id"] for d in self.documents]
        )

    def explicit_refs(self) -> list[dict]:
        return [r for r in self.refs if r.get("origin", "explicit") == "explicit"]

    def edge_targets(self) -> list[str]:
        """Every imported edge's target: blocked_by rows, then explicit refs."""
        return [
            blocker_id for node, _ in self.cards for blocker_id in node.get("blocked_by", [])
        ] + [r["dst_id"] for r in self.explicit_refs()]

    def counts(self) -> dict:
        return {
            "imported": len(self.entity_ids()),
            "cards": len(self.cards),
            "issues": len(self.issues),
            "documents": len(self.documents),
            "comments": len(self.comments),
        }


@dataclasses.dataclass
class _Target:
    """Where an entry lands: a registered project, or one this import registers."""

    project: Project
    registered: bool


def load(conn: sqlite3.Connection, cwd: Path, raw) -> dict:
    """Import a snapshot: place each entry in its project (registering
    projects where needed), check the whole file, then write it in one
    transaction. cwd matters only for a one-entry snapshot."""
    try:
        return _load(conn, cwd, raw)
    except (KeyError, TypeError, AttributeError, sqlite3.ProgrammingError) as exc:
        # Missing keys or wrong value types in the snapshot. Any backups the
        # import wrote were already cleaned up by the time this is caught.
        raise ImportFormatError(f"malformed snapshot: {type(exc).__name__}: {exc}") from exc


def _load(conn: sqlite3.Connection, cwd: Path, raw) -> dict:
    entries = _entries(raw)
    targets = _place(conn, cwd, entries)
    _require_empty(conn, targets)
    _validate(conn, entries, targets)
    _write(conn, entries, targets)
    # After commit, so [[stem]] and [[uuid]] links resolve against the whole import.
    for entry in entries:
        for entity_id in entry.entity_ids():
            refs.reindex(conn, entity_id)
    return _report(conn, entries, targets)


def _entries(raw) -> list[_Entry]:
    """The snapshot as a list of entries: v2 has one per project; a v1
    export or a `brd tree` list is one entry with no recorded project."""
    # `brd export > file` writes the whole envelope; accept it unwrapped too.
    if isinstance(raw, dict) and isinstance(raw.get("data"), dict):
        raw = raw["data"]
    if isinstance(raw, dict) and "brd_export" in raw:
        if raw["brd_export"] == FORMAT_VERSION:
            return _v2_entries(raw)
        if raw["brd_export"] != V1_FORMAT_VERSION:
            raise ImportFormatError(f"unsupported brd_export version {raw['brd_export']!r}")
        return [_entry(None, raw)]
    nodes = raw["data"] if isinstance(raw, dict) and "data" in raw else raw
    if not isinstance(nodes, list):
        raise ImportFormatError("expected a `brd export` object or a `brd tree` snapshot list")
    # Tree nodes carry a derived `blockers` key; nothing below reads it.
    return [_entry(None, {"cards": nodes})]


def _entry(project: dict | None, body: dict) -> _Entry:
    return _Entry(
        project=project,
        cards=core._flatten_tree(body.get("cards", [])),
        issues=body.get("issues", []),
        documents=body.get("documents", []),
        comments=body.get("comments", []),
        tags=body.get("tags", []),
        refs=body.get("refs", []),
    )


def _v2_entries(snap: dict) -> list[_Entry]:
    items = snap.get("projects")
    if not isinstance(items, list):
        raise ImportFormatError(
            f"malformed snapshot: `projects` must be a list, got {type(items).__name__}"
        )
    entries = [_v2_entry(item) for item in items]
    if not entries:
        raise ImportFormatError("snapshot has no project entries")
    return entries


def _v2_entry(item) -> _Entry:
    if not isinstance(item, dict) or not all(key in item for key in ("project", *ENTRY_BODY_KEYS)):
        raise ImportFormatError(
            "malformed snapshot: a project entry must be an object with project, "
            + ", ".join(ENTRY_BODY_KEYS)
        )
    project = item["project"]
    if not isinstance(project, dict) or not all(
        isinstance(project.get(key), str) for key in PROJECT_KEYS
    ):
        raise ImportFormatError(
            "malformed snapshot: an entry's project must be an object with string "
            + ", ".join(PROJECT_KEYS)
        )
    return _entry(project, item)


def _place(conn: sqlite3.Connection, cwd: Path, entries: list[_Entry]) -> list[_Target]:
    if len(entries) == 1:
        return [_place_in_cwd(conn, cwd, entries[0].project)]
    raise ImportFormatError(
        f"snapshot has {len(entries)} project entries; importing more than one "
        "project is not supported yet"
    )


def _place_in_cwd(conn: sqlite3.Connection, cwd: Path, recorded: dict | None) -> _Target:
    """A one-entry snapshot lands in the cwd project, whatever it records.
    Outside one, the cwd is registered as `brd init` would, keeping the
    recorded id when no project has it."""
    try:
        return _Target(master.resolve_project(conn, cwd), registered=False)
    except ProjectNotFoundError:
        pass
    if recorded is None:
        project = Project(
            id=db.new_project_id(), name=cwd.name, root_path=str(cwd), created_at=core._now()
        )
        return _Target(project, registered=True)
    project_id = recorded["id"]
    if db.get_project_by_id(conn, project_id) is not None:
        project_id = db.new_project_id()
    project = Project(
        id=project_id,
        name=recorded["name"],
        root_path=str(cwd),
        created_at=recorded["created_at"],
    )
    return _Target(project, registered=True)


def _require_empty(conn: sqlite3.Connection, targets: list[_Target]) -> None:
    """A registered target that already owns entities is refused: replacing
    its contents is not supported yet. New targets are empty."""
    busy = []
    for target in targets:
        if target.registered:
            continue
        counts = {
            row["kind"]: row["n"]
            for row in conn.execute(
                "SELECT kind, COUNT(*) AS n FROM entities WHERE project_id = ? GROUP BY kind",
                (target.project.id,),
            )
        }
        if counts:
            project = target.project
            busy.append(
                f"{project.name} ({project.id}) has {counts.get('card', 0)} cards, "
                f"{counts.get('issue', 0)} issues and {counts.get('document', 0)} documents"
            )
    if busy:
        raise ProjectNotEmptyError(
            "target project already has entities: "
            + "; ".join(busy)
            + "; replacing a project's contents is not supported yet"
        )


def _check_source_path(source_path) -> None:
    """A snapshot's source_path must stay inside the project: `doc restore`
    writes to it and sync/export read from it."""
    if not isinstance(source_path, str):
        raise ImportFormatError(f"document source_path must be a string, got {source_path!r}")
    path = PurePosixPath(source_path)
    if path.is_absolute() or ".." in path.parts or path.suffix.lower() != ".md":
        raise ImportFormatError(
            f"document source_path {source_path!r} must be a relative .md path "
            "inside the project"
        )


def _validate(conn: sqlite3.Connection, entries: list[_Entry], targets: list[_Target]) -> None:
    """Every check before anything is written, over the whole file. Edge
    targets are not checked: one that is not in the database is kept and
    reported as not-found."""
    entity_ids = [entity_id for entry in entries for entity_id in entry.entity_ids()]
    if len(set(entity_ids)) != len(entity_ids):
        raise ImportFormatError("snapshot contains duplicate ids")
    for entity_id in entity_ids:
        if entities.kind_of(conn, entity_id) is not None:
            raise EntityAlreadyExistsError(f"entity {entity_id} already exists in another project")
    for entry in entries:
        for comment in entry.comments:
            if conn.execute("SELECT 1 FROM comments WHERE id = ?", (comment["id"],)).fetchone():
                raise EntityAlreadyExistsError(f"comment {comment['id']} already exists")
    for entry, target in zip(entries, targets):
        for doc in entry.documents:
            _check_source_path(doc["source_path"])
        for doc in entry.documents:
            documents._check_unique(
                conn, target.project.id, doc["source_path"], PurePosixPath(doc["source_path"]).stem
            )


def _write(conn: sqlite3.Connection, entries: list[_Entry], targets: list[_Target]) -> None:
    """One transaction: new projects, then every entry's entities, then every
    entry's edges, comments, tags and refs, so an edge or comment into another
    entry finds its target whatever the entry order."""
    contents = {
        d["id"]: d["content"].encode("utf-8")
        for entry in entries
        for d in entry.documents
        if d.get("content") is not None
    }
    # Write backups before touching the DB, so a DB failure never leaves a
    # document row with no backup: if the transaction below fails, we delete
    # exactly the backups we just wrote.
    for doc_id, data in contents.items():
        documents._write_backup(conn, doc_id, data)
    try:
        with conn:  # one transaction: commits on success, rolls back on error
            for target in targets:
                if target.registered:
                    db.insert_project(conn, target.project)
            for entry, target in zip(entries, targets):
                _insert_entities(conn, target.project.id, entry, contents)
            for entry in entries:
                _insert_links(conn, entry)
    except BaseException as exc:
        for doc_id in contents:
            documents.backup_path(conn, doc_id).unlink(missing_ok=True)
        if isinstance(exc, sqlite3.IntegrityError):
            raise ImportFormatError(f"snapshot is internally inconsistent: {exc}") from exc
        raise


def _insert_entities(
    conn: sqlite3.Connection, project_id: str, entry: _Entry, contents: dict[str, bytes]
) -> None:
    for node, parent_id in entry.cards:
        status = "todo" if node["status"] == "blocked" else node["status"]
        db.insert_entity(conn, project_id, node["id"], "card")
        conn.execute(
            "INSERT INTO cards (id, title, description, status, parent_id, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (node["id"], node["title"], node.get("description"), status,
             parent_id, node["created_at"], node["updated_at"]),
        )
    for i in entry.issues:
        db.insert_entity(conn, project_id, i["id"], "issue")
        conn.execute(
            "INSERT INTO issues (id, title, body, status, close_reason, created_at, "
            "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (i["id"], i["title"], i.get("body"), i["status"], i.get("close_reason"),
             i["created_at"], i["updated_at"]),
        )
    for d in entry.documents:
        digest = documents._hash(contents[d["id"]]) if d["id"] in contents else d["content_hash"]
        db.insert_entity(conn, project_id, d["id"], "document")
        conn.execute(
            "INSERT INTO documents (id, project_id, title, source_path, stem, "
            "content_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (d["id"], project_id, d["title"], d["source_path"],
             PurePosixPath(d["source_path"]).stem, digest, d["created_at"],
             d["updated_at"]),
        )


def _insert_links(conn: sqlite3.Connection, entry: _Entry) -> None:
    for node, _ in entry.cards:
        for blocker_id in node.get("blocked_by", []):
            conn.execute(
                "INSERT INTO blocked_by (card_id, blocks_on_id) VALUES (?, ?)",
                (node["id"], blocker_id),
            )
    for c in entry.comments:
        conn.execute(
            "INSERT INTO comments (id, entity_id, author, body, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (c["id"], c["entity_id"], c["author"], c["body"], c["created_at"]),
        )
    for t in entry.tags:
        conn.execute(
            "INSERT INTO tags (entity_id, tag) VALUES (?, ?)", (t["entity_id"], t["tag"])
        )
    for r in entry.explicit_refs():
        conn.execute(
            "INSERT INTO refs (src_id, dst_id, origin) VALUES (?, ?, 'explicit')",
            (r["src_id"], r["dst_id"]),
        )


def _report(conn: sqlite3.Connection, entries: list[_Entry], targets: list[_Target]) -> dict:
    per_project = [
        {
            "project": dataclasses.asdict(db.get_project_by_id(conn, target.project.id)),
            "registered": target.registered,
            **entry.counts(),
        }
        for entry, target in zip(entries, targets)
    ]
    totals = {key: sum(item[key] for item in per_project) for key in COUNT_KEYS}
    not_found = sum(
        1
        for entry in entries
        for target_id in entry.edge_targets()
        if entities.kind_of(conn, target_id) is None
    )
    return {**totals, "projects": per_project, "not_found_edges": not_found}
```

- [ ] **Step 10: Route `brd import` through `_run_global`**

In `src/brd/cli/snapshot.py`, replace the body of `import_cmd` (from `    def action(ctx):` to `    run(pretty, action)`) with:

```python
    def action(conn: sqlite3.Connection) -> dict:
        try:
            raw = json.loads(file.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ImportReadError(f"could not read a JSON snapshot from {file}: {exc}") from exc
        return snapshot.load(conn, Path.cwd(), raw)

    _run_global(pretty, action)
```

(`run` stays imported: `export_cmd` still uses it.)

- [ ] **Step 11: Run the tests to verify they pass**

Run: `uv run pytest tests/test_snapshot.py tests/test_project_scope.py tests/test_cli.py -q`
Expected: PASS. Note `test_export_all_lists_every_project_in_creation_order` still passes here: its two-entry import is refused by `_place`'s temporary `ImportFormatError` (Task 2 changes that).

- [ ] **Step 12: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS (all tests).

- [ ] **Step 13: Commit**

```bash
git add src/brd/errors.py src/brd/db.py src/brd/snapshot.py src/brd/cli/snapshot.py tests/test_snapshot.py tests/test_project_scope.py tests/test_cli.py
git commit -m "Import a one-entry snapshot into the cwd project, registering the cwd if needed

Edges to ids not in the database are kept and counted as not-found; a
target project that already has entities is refused."
```

---

### Task 2: Multi-entry placement (B1 duplicate projects, B3, B4/B5/B6 across entries)

**Files:**
- Modify: `src/brd/errors.py` (append class)
- Modify: `src/brd/snapshot.py` (imports; `_v2_entries`; `_place`; new `_place_by_record`)
- Test: `tests/test_snapshot.py`

**Interfaces:**
- Consumes (from Task 1): `_Entry`, `_Target`, `PROJECT_KEYS`, `_place(conn, cwd, entries)`, `_v2_entries(snap)`; test helpers `_unregistered_dir`, `_snapshot_file`, `_import_error`, `_card_node`, `_hand_entry`, `_v2`, constants `T`, `CARD_1`, `CARD_2`, `PROJECT_X`, `PROJECT_Y`.
- Produces: `errors.ProjectRootNotFoundError(BrdError)`; `snapshot._place_by_record(conn, recorded: list[dict]) -> list[_Target]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_snapshot.py`:

```python
def test_multi_entry_import_matches_registered_projects_by_id(project, tmp_path, monkeypatch):
    (a,) = ok("projects")
    new_root = tmp_path / "new-root"
    new_root.mkdir()
    snapshot = _snapshot_file(tmp_path, _v2(
        _hand_entry(a["id"], tmp_path / "gone", name="a", cards=[_card_node(CARD_1)]),
        _hand_entry(PROJECT_X, new_root.resolve(), name="x", cards=[_card_node(CARD_2)]),
    ))
    _unregistered_dir(tmp_path, monkeypatch, "elsewhere")
    result = ok("import", snapshot)
    first, second = result["projects"]
    assert first["project"] == a and first["registered"] is False and first["cards"] == 1
    assert second["project"] == {
        "id": PROJECT_X, "name": "x", "root_path": str(new_root.resolve()), "created_at": T
    }
    assert second["registered"] is True and second["cards"] == 1
    assert {p["id"]: p for p in ok("projects")} == {a["id"]: a, PROJECT_X: second["project"]}
    monkeypatch.chdir(project)
    assert [c["id"] for c in ok("list")] == [CARD_1]
    monkeypatch.chdir(new_root)
    assert [c["id"] for c in ok("list")] == [CARD_2]


def test_multi_entry_import_registers_at_recorded_roots(project, tmp_path, monkeypatch):
    a_card = ok("add", "--title", "A card")["id"]
    second, _ = _another_project(tmp_path, monkeypatch, "second")
    b_card = ok("add", "--title", "B card")["id"]
    data = ok("export", "--all")
    snapshot = _snapshot_file(tmp_path, data)
    _unregistered_dir(tmp_path, monkeypatch, "elsewhere", data_home="other-data")
    result = ok("import", snapshot)
    recorded = [e["project"] for e in data["projects"]]
    assert ok("projects") == recorded
    assert [item["project"] for item in result["projects"]] == recorded
    assert [item["registered"] for item in result["projects"]] == [True, True]
    monkeypatch.chdir(project)
    assert [c["id"] for c in ok("list")] == [a_card]
    monkeypatch.chdir(second)
    assert [c["id"] for c in ok("list")] == [b_card]


def test_multi_entry_import_lists_every_missing_root(tmp_path, monkeypatch):
    gone_a, gone_b = tmp_path / "gone-a", tmp_path / "gone-b"
    a_file = tmp_path / "a-file"
    a_file.write_text("not a directory")
    snapshot = _snapshot_file(tmp_path, _v2(
        _hand_entry(PROJECT_X, gone_a, name="x", cards=[_card_node(CARD_1)]),
        _hand_entry(PROJECT_Y, gone_b, name="y", cards=[_card_node(CARD_2)]),
        _hand_entry("cccccccc-0000-4000-8000-00000000000c", a_file, name="f"),
        _hand_entry("dddddddd-0000-4000-8000-00000000000d", "relative/dir", name="r"),
    ))
    _unregistered_dir(tmp_path, monkeypatch, "elsewhere", data_home="data")
    error = _import_error(snapshot)
    assert error["type"] == "ProjectRootNotFoundError"
    for root in (str(gone_a), str(gone_b), str(a_file), "relative/dir"):
        assert root in error["message"]
    assert ok("projects") == []


def test_multi_entry_import_succeeds_once_the_roots_exist(tmp_path, monkeypatch):
    gone_a, gone_b = tmp_path / "gone-a", tmp_path / "gone-b"
    snapshot = _snapshot_file(tmp_path, _v2(
        _hand_entry(PROJECT_X, gone_a, name="x", cards=[_card_node(CARD_1)]),
        _hand_entry(PROJECT_Y, gone_b, name="y", cards=[_card_node(CARD_2)]),
    ))
    _unregistered_dir(tmp_path, monkeypatch, "elsewhere", data_home="data")
    assert _import_error(snapshot)["type"] == "ProjectRootNotFoundError"
    gone_a.mkdir()
    gone_b.mkdir()
    result = ok("import", snapshot)
    assert [item["registered"] for item in result["projects"]] == [True, True]
    assert {p["id"] for p in ok("projects")} == {PROJECT_X, PROJECT_Y}


def test_multi_entry_import_ignores_the_cwd_project(project, tmp_path, monkeypatch):
    (a,) = ok("projects")
    root_x, root_y = tmp_path / "x", tmp_path / "y"
    root_x.mkdir()
    root_y.mkdir()
    snapshot = _snapshot_file(tmp_path, _v2(
        _hand_entry(PROJECT_X, root_x.resolve(), name="x", cards=[_card_node(CARD_1)]),
        _hand_entry(PROJECT_Y, root_y.resolve(), name="y", cards=[_card_node(CARD_2)]),
    ))
    result = ok("import", snapshot)  # cwd is project's root
    assert [item["project"]["id"] for item in result["projects"]] == [PROJECT_X, PROJECT_Y]
    assert ok("list") == []
    assert {p["id"] for p in ok("projects")} == {a["id"], PROJECT_X, PROJECT_Y}


def test_multi_entry_import_refuses_a_root_registered_under_another_id(
    project, tmp_path, monkeypatch
):
    ok("add", "--title", "A")
    _another_project(tmp_path, monkeypatch, "second")
    ok("add", "--title", "B")
    data = ok("export", "--all")
    snapshot = _snapshot_file(tmp_path, data)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "other-data"))
    monkeypatch.chdir(project)
    squatter = ok("init")
    error = _import_error(snapshot)
    assert error["type"] == "ProjectAlreadyExistsError"
    assert data["projects"][0]["project"]["root_path"] in error["message"]
    assert squatter["id"] in error["message"]
    assert "alone" in error["message"]
    assert ok("projects") == [squatter]
    assert ok("list") == []


@pytest.mark.parametrize("entries", [1, 2])
def test_import_refuses_a_non_empty_target(project, tmp_path, monkeypatch, entries):
    (a,) = ok("projects")
    if entries == 1:
        ok("add", "--title", "existing")
    else:
        ok("issue", "open", "--title", "existing")
    before = (ok("list"), ok("issue", "list"))
    new_root = tmp_path / "new-root"
    new_root.mkdir()
    hand = [
        _hand_entry(a["id"], project, cards=[_card_node(CARD_1)]),
        _hand_entry(PROJECT_X, new_root.resolve(), cards=[_card_node(CARD_2)]),
    ]
    snapshot = _snapshot_file(tmp_path, _v2(*hand[:entries]))
    if entries == 2:
        _unregistered_dir(tmp_path, monkeypatch, "elsewhere")
    error = _import_error(snapshot)
    assert error["type"] == "ProjectNotEmptyError"
    assert a["id"] in error["message"] and a["name"] in error["message"]
    assert ok("projects") == [a]
    monkeypatch.chdir(project)
    assert (ok("list"), ok("issue", "list")) == before


def test_cross_entry_edges_connect_in_either_order(project, tmp_path, monkeypatch):
    a_issue = ok("issue", "open", "--title", "A issue")["id"]
    a1 = ok("add", "--title", "a1")["id"]
    second, _ = _another_project(tmp_path, monkeypatch, "second")
    b1 = ok("add", "--title", "b1")["id"]
    b_issue = ok("issue", "open", "--title", "B issue")["id"]
    ok("block", b1, "--by", a_issue)
    monkeypatch.chdir(project)
    ok("block", a1, "--by", b1)
    ok("ref", "add", a1, b_issue)
    data = ok("export", "--all")
    data["projects"].reverse()
    snapshot = _snapshot_file(tmp_path, data)
    _unregistered_dir(tmp_path, monkeypatch, "elsewhere", data_home="other-data")
    assert ok("import", snapshot)["not_found_edges"] == 0
    monkeypatch.chdir(project)
    shown = ok("show", a1)
    assert [(b["id"], b["status"]) for b in shown["blockers"]] == [(b1, "todo")]
    explicit = [r for r in shown["refs"] if r["origin"] == "explicit"]
    assert [(r["id"], r["kind"]) for r in explicit] == [(b_issue, "issue")]
    monkeypatch.chdir(second)
    assert [(b["id"], b["status"]) for b in ok("show", b1)["blockers"]] == [(a_issue, "open")]


def test_duplicate_ids_across_entries_are_refused(tmp_path, monkeypatch):
    root_x, root_y = tmp_path / "x", tmp_path / "y"
    root_x.mkdir()
    root_y.mkdir()
    x = _hand_entry(PROJECT_X, root_x.resolve(), name="x", cards=[_card_node(CARD_1)])
    y = _hand_entry(PROJECT_Y, root_y.resolve(), name="y", cards=[_card_node(CARD_2)])
    same_card = _hand_entry(PROJECT_Y, root_y.resolve(), name="y", cards=[_card_node(CARD_1)])
    same_id = {**y, "project": {**y["project"], "id": PROJECT_X}}
    same_root = {**y, "project": {**y["project"], "root_path": x["project"]["root_path"]}}
    _unregistered_dir(tmp_path, monkeypatch, "elsewhere", data_home="data")
    for second, words in [
        (same_card, "duplicate ids"),
        (same_id, PROJECT_X),
        (same_root, x["project"]["root_path"]),
    ]:
        snapshot = _snapshot_file(tmp_path, _v2(x, second))
        error = _import_error(snapshot)
        assert error["type"] == "ImportFormatError"
        assert words in error["message"]
        assert ok("projects") == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_snapshot.py -q -k "multi_entry or non_empty_target or cross_entry or duplicate_ids_across"`
Expected: FAIL — the multi-entry tests get `ImportFormatError` ("importing more than one project is not supported yet") instead of success / `ProjectRootNotFoundError` / `ProjectAlreadyExistsError` / `ProjectNotEmptyError`; the `same_id`/`same_root` cases of `test_duplicate_ids_across_entries_are_refused` fail on the message check. `test_import_refuses_a_non_empty_target[1]` already passes (B4 for one-entry files landed in Task 1).

- [ ] **Step 3: Add the error class**

Append to `src/brd/errors.py`:

```python


class ProjectRootNotFoundError(BrdError):
    pass
```

- [ ] **Step 4: Refuse duplicate recorded projects in `_v2_entries`**

In `src/brd/snapshot.py`, replace `_v2_entries` with:

```python
def _v2_entries(snap: dict) -> list[_Entry]:
    items = snap.get("projects")
    if not isinstance(items, list):
        raise ImportFormatError(
            f"malformed snapshot: `projects` must be a list, got {type(items).__name__}"
        )
    entries = [_v2_entry(item) for item in items]
    if not entries:
        raise ImportFormatError("snapshot has no project entries")
    for key in ("id", "root_path"):
        seen: set[str] = set()
        for entry in entries:
            value = entry.project[key]
            if value in seen:
                raise ImportFormatError(f"snapshot has two project entries with {key} {value}")
            seen.add(value)
    return entries
```

- [ ] **Step 5: Place multi-entry files by recorded id or root**

5a. In `src/brd/snapshot.py`, change the errors import to:

```python
from brd.errors import (
    EntityAlreadyExistsError,
    ImportFormatError,
    ProjectAlreadyExistsError,
    ProjectNotEmptyError,
    ProjectNotFoundError,
    ProjectRootNotFoundError,
)
```

5b. Replace `_place` with:

```python
def _place(conn: sqlite3.Connection, cwd: Path, entries: list[_Entry]) -> list[_Target]:
    if len(entries) == 1:
        return [_place_in_cwd(conn, cwd, entries[0].project)]
    return _place_by_record(conn, [entry.project for entry in entries])
```

5c. Insert right after `_place_in_cwd`:

```python
def _place_by_record(conn: sqlite3.Connection, recorded: list[dict]) -> list[_Target]:
    """A multi-entry snapshot ignores the cwd: each entry goes to the project
    with its id, else to a new project at its recorded root. A root held by
    another id refuses at once; otherwise every missing root is listed."""
    targets: list[_Target] = []
    missing: list[dict] = []
    for project in recorded:
        existing = db.get_project_by_id(conn, project["id"])
        if existing is not None:
            targets.append(_Target(existing, registered=False))
            continue
        holder = db.get_project(conn, project["root_path"])
        if holder is not None:
            raise ProjectAlreadyExistsError(
                f"{project['root_path']} is already the root of project {holder.name} "
                f"({holder.id}), not of the snapshot's {project['name']} ({project['id']}); "
                "import that entry alone from its directory"
            )
        root = Path(project["root_path"])
        if not (root.is_absolute() and root.is_dir()):
            missing.append(project)
            continue
        new = Project(**{key: project[key] for key in PROJECT_KEYS})
        targets.append(_Target(new, registered=True))
    if missing:
        raise ProjectRootNotFoundError(
            "no directory at the recorded root of "
            + ", ".join(f"{p['name']} ({p['root_path']})" for p in missing)
            + "; create those directories, or import each entry alone from its directory"
        )
    return targets
```

- [ ] **Step 6: Update the `export --all` test's import tail**

In `tests/test_snapshot.py`, `test_export_all_lists_every_project_in_creation_order`, replace its last block:

```python
    # A two-project snapshot does not import yet (5.2), and writes nothing.
    snapshot = tmp_path / "all.json"
    snapshot.write_text(json.dumps(from_a))
    assert err("import", snapshot) == "ImportFormatError"
    assert [c["id"] for c in ok("list")] == [a_card]
```

with:

```python
    # Re-importing places both entries back in their (non-empty) projects:
    # refused, and nothing is written.
    snapshot = tmp_path / "all.json"
    snapshot.write_text(json.dumps(from_a))
    assert err("import", snapshot) == "ProjectNotEmptyError"
    assert [c["id"] for c in ok("list")] == [a_card]
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_snapshot.py -q`
Expected: PASS.

- [ ] **Step 8: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/brd/errors.py src/brd/snapshot.py tests/test_snapshot.py
git commit -m "Import a multi-project snapshot, placing each entry by id or recorded root"
```

---

### Task 3: `--pretty` report, help text and README (B7 text, B8)

**Files:**
- Modify: `src/brd/cli/snapshot.py:17-33` (`_run_global`), `src/brd/cli/snapshot.py:58-74` (`import_cmd` docstring and call)
- Modify: `README.md:65` and `README.md:73`
- Test: `tests/test_snapshot.py`

**Interfaces:**
- Consumes (from Task 1): the `snapshot.load` report dict (`projects[*].project.name`, `.root_path`, `registered`, `cards`, `issues`, `documents`, `comments`, top-level `not_found_edges`); `_run_global(pretty, fn)`.
- Produces: `_run_global(pretty, fn, render: Callable[[dict], str] = _indented)`; `_import_text(data: dict) -> str`.

- [ ] **Step 1: Write the failing tests**

1a. In `tests/test_snapshot.py`, append to the end of `test_import_report_shape_and_pretty` (after `assert result["not_found_edges"] == 0`):

```python

    restored = _unregistered_dir(tmp_path, monkeypatch, "restored", data_home="third-data")
    text = human("import", snapshot)
    assert text.splitlines() == [
        f"repo ({restored}): +2 cards, +1 issues, +1 documents, +1 comments [registered]",
        "not-found edge targets: 0",
    ]
```

(`repo` is the recorded project name: the `project` fixture's directory.)

1b. Append to `tests/test_snapshot.py`:

```python
def test_import_help_describes_placement():
    result = invoke("import", "--help")
    assert result.exit_code == 0, result.output
    # Rich wraps help inside a bordered panel; compare with borders and
    # line breaks folded away.
    text = " ".join(result.stdout.replace("│", " ").split())
    assert "current project" in text
    assert "multi-project" in text
    assert "already has entities" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_snapshot.py -q -k "report_shape_and_pretty or help_describes_placement"`
Expected: FAIL — `--pretty` prints indented JSON, so `splitlines()` differs; help text lacks "current project".

- [ ] **Step 3: Implement the renderer, help and `_run_global` render argument**

3a. In `src/brd/cli/snapshot.py`, replace `_run_global` with:

```python
def _run_global(
    pretty: bool,
    fn: Callable[[sqlite3.Connection], dict],
    render: Callable[[dict], str] = _indented,
) -> None:
    """Like run(), but never resolves the cwd project: for a command that
    works from any directory. --pretty prints render's text."""
    try:
        conn = master.connect()
    except BrdError as exc:
        fail(exc, pretty)
    try:
        data = fn(conn)
    except BrdError as exc:
        fail(exc, pretty)
    finally:
        conn.close()
    if pretty:
        print(render(data))
    else:
        output.print_result(output.ok_envelope(data), pretty)


def _import_text(data: dict) -> str:
    lines = []
    for item in data["projects"]:
        project = item["project"]
        line = (
            f"{project['name']} ({project['root_path']}): +{item['cards']} cards, "
            f"+{item['issues']} issues, +{item['documents']} documents, "
            f"+{item['comments']} comments"
        )
        if item["registered"]:
            line += " [registered]"
        lines.append(line)
    lines.append(f"not-found edge targets: {data['not_found_edges']}")
    return "\n".join(lines)
```

3b. Replace `import_cmd`'s docstring line
`    """Restore a board from a snapshot; touches nothing if any id already exists."""`
with:

```python
    """Restore a snapshot. A one-project snapshot lands in the current project,
    registering the current directory if it is not in one. A multi-project
    snapshot places each entry in the registered project with its id, else
    registers it at its recorded root; it works from any directory. Refuses,
    writing nothing, if a target project already has entities."""
```

3c. In `import_cmd`, change `    _run_global(pretty, action)` to:

```python
    _run_global(pretty, action, _import_text)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_snapshot.py -q`
Expected: PASS (including `test_export_pretty_is_indented_json`, which still uses the default `_indented` renderer).

- [ ] **Step 5: Update the README**

5a. In `README.md`, change the line
`brd import docs/board/snapshot.json     # on another machine/clone, after brd init`
to
`brd import docs/board/snapshot.json     # on another machine/clone`

5b. Replace the paragraph starting `` `import` restores a one-project snapshot into the current project. `` (line 73) with:

```markdown
`brd import` restores a snapshot, preserving the original ids, content, and timestamps — including document backups (restore a missing file with `brd doc restore <id>`). A one-project snapshot lands in the current project; outside any project, the current directory is registered first (keeping the snapshot's project id when no project has it), so no `brd init` is needed. A multi-project snapshot (from `brd export --all`) places each entry in the registered project with the same id, else registers it at its recorded root path if that directory exists, and works from any directory. Import refuses, touching nothing, when a target project already has entities, when an id in the snapshot already exists, or when an entry cannot be placed. Edges to ids that are not in the database are kept and counted as not-found; importing the missing project later reconnects them. Older one-object `brd export` snapshots and `brd tree` snapshots still import.
```

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/brd/cli/snapshot.py tests/test_snapshot.py README.md
git commit -m "Print brd import --pretty as one line per project; document placement rules"
```
<!-- task-pipeline: validated -->
