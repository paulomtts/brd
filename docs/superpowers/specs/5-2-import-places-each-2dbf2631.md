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
