# 5.3 Import replaces a project's local state after confirmation

Card: `7188185d-84cc-4985-8588-067f16645f54`. Third subtask of story `3d5969ce`
"Export/import v2" (spec section 5, D9-D11), in milestone `6aa7043a` "Single database and
cross-project blocking". Blocked by 5.2 (`2dbf2631`, merged into this branch): import
already places every entry in its project, but refuses any already-registered target that
owns entities (`ProjectNotEmptyError`, "replacing a project's contents is not supported
yet", `src/brd/snapshot.py:285-310`). This card turns that refusal into
confirm-and-replace.

Parent design spec: `docs/superpowers/specs/2026-10-06-single-db-cross-project-blocking-design.md`.
It is in the main checkout (`/home/mtts/Code/brd/docs/...`), not in this branch's history.
Citations look like **[P §n Lx]** or **[P Dn Lx]**. Sibling spec cited:
`docs/superpowers/specs/5-2-import-places-each-2dbf2631.md` (**[5.2 Bn]**).

## Goal

`brd import <file> [--yes]` may target a project that already has entities. Such a
project is **replaced**: after validation, the user sees per-project `-`/`+` counts on
stderr and confirms (or passed `--yes`); then, in the import's one transaction, every
entity of that project is deleted the way `brd forget` deletes them (incoming edges from
other projects survive) and the entry's contents are inserted. Without a TTY and without
`--yes`, import refuses and writes nothing. This makes `brd export --all` on one machine
followed by `brd import --yes` on another a full round trip, and makes re-importing a
project's own export idempotent.

## Inherited constraints

| Constraint | Source |
|---|---|
| Import of a project that has local state replaces that whole project, after confirmation; `--yes` skips it; no TTY and no `--yes` refuses. | [P D10 L40] |
| `brd forget` and import's project replacement do **not** remove incoming edges from other projects; they become `not-found` and reconnect if the ids return. Only `brd delete` removes incoming edges. | [P D8 L38] |
| Edge targets carry no foreign key; a not-found edge is kept and reported; a not-found blocker blocks. | [P D6 L36], [P D7 L37] |
| CLI form is `brd import <file> [--yes]`. | [P §5 L211] |
| Validate: duplicate ids within the file; ids already in the database **outside the projects being replaced** (refuse, naming the owner); document paths and stems as today. | [P §5 L222-L224] |
| Confirm: if any target project has entities, print per-project counts to stderr (`brd: -42 cards, -3 issues, … / +40 cards, +3 issues, …`) and ask y/N on a TTY. `--yes` skips the prompt; no TTY and no `--yes` → refuse. | [P §5 L225-L227] |
| One transaction: wipe each target project's entities (same deletion as `forget`), insert all entities of all entries, then all edges, comments, tags and refs. Backups written before and removed on failure, as today. | [P §5 L228-L231] |
| Reindex link refs; report per-project counts plus the number of still-not-found edges. | [P §5 L232-L233] |
| `export --all` on machine 1, `import --yes` on machine 2 restores every project whose root exists, with ids, hierarchy and edges intact. | [P §5 L235-L237] |
| Placement (D11), normalization, the B7 report shape and all 5.2 refusals stay as built. | [5.2 B1-B3, B5-B7] |
| Owned files: `src/brd/snapshot.py`, `src/brd/cli/snapshot.py` (plus their tests). | story card `3d5969ce` |

## Definitions

- **Target**: the project an entry lands in after placement [5.2 B2-B3].
- **Replaced project**: a target that was already registered before this import and owns
  at least one entity when the import starts. A target this import registers, or a
  registered target with no entities, is not replaced: no wipe, no confirmation, exactly
  5.2 behaviour.
- **Outside project**: any registered project that is not a replaced project.

## Behavior

All refusals below are `BrdError` envelopes (`{"ok": false, "error": {type, message}}`,
exit 1) and write **nothing**: no project row, no entity deleted or inserted, no edge,
comment or tag changed, no document backup file created, changed or removed.

### R1. Order of steps

1. Normalize and place, unchanged [5.2 B1-B3].
2. Validate the whole file (R2). Every validation refusal happens **before** any summary
   is printed or any prompt is shown: a doomed import never asks.
3. If there is at least one replaced project, confirm (R3).
4. Write (R4), reindex, report (R5).

### R2. Validation with replacement

Unchanged from 5.2 except where ids or documents of a replaced project are involved:

- An entity id (card, issue, document) appearing twice in the file → `ImportFormatError`
  "snapshot contains duplicate ids" (unchanged).
- An entity id already in the database:
  - owned by a replaced project (any replaced project of this import, not necessarily the
    entry's own target) → allowed; that entity is wiped and the incoming one inserted
    with the id;
  - owned by an outside project → `EntityAlreadyExistsError` (type unchanged). The
    message names the id **and the owner** project's name and id, e.g.
    `entity <id> already exists in project <name> (<project id>)`.
- A comment id already in the database: allowed if the comment is on an entity owned by
  a replaced project (it is wiped with that entity); otherwise `EntityAlreadyExistsError`
  naming the comment id and the owner project's name and id.
- Document `source_path` rules unchanged. Per-project path/stem uniqueness for an entry
  whose target is a replaced project is checked as if the project were already empty:
  the project's current documents never collide with incoming ones. A path or stem
  duplicated **within** the incoming entry is still refused, nothing written (today:
  `ImportFormatError` via the integrity check, or a `Duplicate*Error`).

### R3. Confirmation

When at least one replaced project exists:

- **Summary on stderr.** Unless refusing for lack of a TTY (below), print one line per
  replaced project, in file order, to **stderr** (never stdout, so JSON mode's stdout
  stays a single envelope):

  ```
  brd: replacing <name> (<root_path>): -<c> cards, -<i> issues, -<d> documents, -<m> comments / +<c'> cards, +<i'> issues, +<d'> documents, +<m'> comments
  ```

  `-` counts are what the project holds now (comments = comments on its entities); `+`
  counts are the entry's counts as in the report. Printed in JSON and `--pretty` modes
  alike, and also when `--yes` is given.
- **`--yes`** → no prompt; proceed to R4.
- **No `--yes`, stdin is a TTY** → after the summary, ask on stderr
  `Replace <n> project(s)? This cannot be undone. [y/N]: ` (default No).
  - `y`/`yes` → proceed to R4.
  - Anything else, an empty answer, EOF or Ctrl-C → envelope type **`Aborted`**
    (same type `brd purge` uses), message `Import cancelled; nothing was written.`,
    exit 1, nothing written.
- **No `--yes`, stdin is not a TTY** → no summary, no prompt: `ProjectNotEmptyError`
  (type kept from 5.2). The message names each replaced project (name and id) with its
  card, issue and document counts, and says to pass `--yes` to replace it (e.g.
  `... ; pass --yes to replace their contents`). The words "not supported yet" no longer
  appear anywhere.

When no project is replaced: no summary, no prompt, `--yes` is accepted and ignored.

### R4. Writing with replacement

Inside the one import transaction [P §5 L228-L231], in this order: register new projects;
for each replaced project delete **all its entities** (the project row itself, its id,
name, `root_path` and `created_at`, is kept unchanged — the entry's recorded name and
`created_at` are not applied to an existing project, as in 5.2); then insert every
entry's entities, then every entry's edges, comments, tags and refs, as in 5.2 B6.

Observable consequences:

- After a replacing import, the project holds exactly the entry's contents: an entity of
  the old state whose id is not in the file is gone (`show <id>` from another project →
  not found); its comments, tags, outgoing `blocked_by` rows and outgoing refs are gone.
- **Incoming edges survive** [P D8 L38]: a `blocked_by` row or ref whose source is in an
  outside project and whose target was in the replaced project is kept, untouched.
  If the file brings that id back, the edge is found again (`show` on the outside card
  lists the blocker with its real status); if not, it is `not-found` and the outside
  card resolves `blocked` [P D7 L37]; a later import that brings the id back reconnects
  it. Import never deletes rows owned by outside projects.
- **Document backups.** Backups for incoming documents are written before the
  transaction, as today. On success, the backup file of every old document of a replaced
  project is removed unless this import just wrote a backup with that id (an incoming
  document with the same id and content). So after success the replaced project's
  backups are exactly the ones this import wrote, as if it had been imported into an
  empty database.
- **Failure leaves the old state intact.** If the transaction fails (e.g. a comment on an
  id in no entry → `ImportFormatError` "snapshot is internally inconsistent"), nothing
  is deleted or inserted, and every backup file that existed before the import is
  **byte-identical** afterwards — including one whose id an incoming document shares
  (its pre-import bytes are restored, not unlinked). Backups created by this import for
  new ids are removed, as today.
- **Doc source files are never touched**: import neither writes, deletes nor reads for
  writing any file under a project's `root_path`. A repo file at an old or incoming
  document's `source_path` is byte-identical after the import (and stays absent if it
  was absent); `brd doc restore` remains the only way to write it.
- Link refs are reindexed after commit for every imported entity, as today.

### R5. Report

Additive to [5.2 B7]; every existing key keeps its meaning:

- Each `projects` item gains `"removed": {"cards": c, "issues": i, "documents": d,
  "comments": m}` — what the import deleted from that project; all zeros for a project
  that was not replaced.
- `--pretty` / `--human`: a replaced project's line ends with ` [replaced]` (after the
  `+` counts, in the same place `[registered]` goes for new projects; a project is never
  both).
- `not_found_edges` is unchanged in meaning: it counts only edges **from the file**.
  Incoming edges from outside projects that became not-found are not counted (the
  summary and `show` make them visible).

### R6. Docs

- `brd import --help`: replace "Refuses, writing nothing, if a target project already
  has entities" with: a target project that already has entities is replaced after a
  y/N confirmation; `--yes` skips it; without a terminal and without `--yes` it refuses.
  `--yes` option help: `Replace target projects that already have entities without
  asking.`
- README import paragraph (`README.md:73`): same change, plus: edges from other
  projects into a replaced project are kept and reconnect when their ids return; doc
  source files are never touched (use `brd doc restore`). Mention the round trip
  `brd export --all` → `brd import --yes`.

## Interface for the planner

- `snapshot.load(conn, cwd: Path, raw, confirm: Callable[[list[Replacement]], bool] | None
  = None) -> dict`. `snapshot.py` stays I/O-free:
  - no replaced project → `confirm` is never called;
  - `confirm is None` → `ProjectNotEmptyError` (R3 no-TTY message, built in `snapshot.py`);
  - `confirm(...)` returns `False` → raise `Aborted("Import cancelled; nothing was
    written.")`; returns `True` → write.
  - `confirm` is called after placement and validation and before `_write`.
- `Replacement`: a small dataclass in `snapshot.py` carrying `project: Project`,
  `removed: dict` and `added: dict` (count dicts keyed `cards`, `issues`, `documents`,
  `comments`), in file order. The CLI formats the stderr line from it.
- New error class `Aborted(BrdError)` in `src/brd/errors.py` (outside the owned files;
  reason: every `BrdError` lives there, and its class name is the envelope type, chosen
  to match `brd purge`'s `Aborted`, `src/brd/cli/project.py:104-106`). No other file
  outside the owned ones changes except `errors.py`, `README.md` and tests.
- Replace `_require_empty` with a step that computes the replacements (same per-kind
  count query, plus the comment count) and a set of replaced project ids that
  `_validate` and `_write` take.
- Ownership lookup for messages: `db.owner_of(conn, entity_id)` (returns `Project | None`).
- Wipe: `DELETE FROM entities WHERE project_id = ?` inside `_write`'s `with conn:`.
  Do **not** call `db.delete_project` (commits on its own and unregisters the project)
  or any `brd delete` helper (removes incoming edges, violating D8). FK cascades from
  `entities` remove cards/issues/documents/comments/tags/outgoing edges; `blocked_by.
  blocks_on_id` and `refs.dst_id` have no FK so incoming rows remain.
- Backups: collect the replaced projects' old document ids before the transaction; for
  every id in the incoming `contents`, read the existing backup bytes (if any) before
  overwriting; on failure restore those bytes (and unlink only the ones that did not
  exist); on success unlink old ids not in `contents`.
- CLI (`src/brd/cli/snapshot.py`): `--yes` option as in `purge`
  (`typer.Option(False, "--yes", help=...)`). Build `confirm` as: if not `yes` and
  `not _stdin_is_tty()` → `None`; else a callback that prints the R3 summary with
  `typer.echo(..., err=True)` and returns `True` if `yes`, else
  `typer.confirm(prompt, default=False, err=True)`, treating `typer.Abort` /
  `click.exceptions.Abort` (EOF, Ctrl-C) as `False`. `_stdin_is_tty()` is a module-level
  function returning `sys.stdin.isatty()`, so tests can monkeypatch it
  (`monkeypatch.setattr("brd.cli.snapshot._stdin_is_tty", lambda: True)`): Typer's
  `CliRunner` replaces `sys.stdin` with a non-TTY stream during `invoke`.
- `_import_text` appends ` [replaced]` when any `removed` count is non-zero.

## Tests

Tier: **CLI integration** in `tests/test_snapshot.py` unless stated, because every
behaviour here is the observable outcome of `brd import` (envelope, exit code, stderr
text, and what `list`, `show`, `projects`, `export`, the backup directory and the repo
see afterwards), and the existing import tests and helpers live there (`project`,
`populated`, `_fresh_project`, `_another_project`, `_unregistered_dir`, `_snapshot_file`,
`_import_error`, `_hand_entry`, `_card_node`, `_v2`, `CARD_1`, `CARD_2`, `PROJECT_X`).

Facts the tests rely on (verified with typer 0.27.2): `CliRunner` keeps `result.stdout`
and `result.stderr` separate; `sys.stdin.isatty()` is `False` under `invoke`; with
`input="y\n"` the runner echoes the typed answer into `result.stdout` **before** the
envelope, so a test that answers a prompt parses the envelope from the first `{`
(`json.loads(out[out.index("{"):])`). New helper `_import_on_tty(monkeypatch, snapshot,
answer, *args)`: monkeypatches `_stdin_is_tty` to `True`, invokes
`import <snapshot> *args` with `input=answer`, returns `(exit_code, envelope, stderr)`.
"Nothing changed" assertions compare `ok("projects")`, `list`, `issue list`, `doc list`
(and `show` of edge-bearing cards) before and after, and the set and bytes of files in
`paths.docs_dir()`.

### New

1. `test_replace_on_tty_answer_yes_replaces_the_project` — `populated`; export; then add
   a card `extra` and edit the card's title. TTY, answer `y`: exit 0; stderr has the
   `brd: replacing <name> (<root>): -3 cards, -1 issues, -1 documents, -1 comments /
   +2 cards, +1 issues, +1 documents, +1 comments` line and the `[y/N]` prompt; stdout
   envelope ok; `extra` is gone, the title is the exported one, ids, hierarchy, tags,
   comment and refs match the export (`export` after == the file's entry); report item
   has `registered: false` and `removed` with those `-` counts.
2. `test_replace_on_tty_answer_no_changes_nothing` — parametrised answers `n\n`, `\n`,
   and EOF (`input=""`): exit 1, envelope type `Aborted`, message contains "cancelled";
   stderr has the summary; state and backup files unchanged.
3. `test_replace_with_yes_skips_the_prompt` — non-TTY (default runner) with `--yes`:
   exit 0, stderr has the summary line and no `[y/N]`; project replaced as in 1. Also
   `--yes --pretty`: stdout's project line ends with ` [replaced]`.
4. `test_replace_without_tty_or_yes_refuses` — non-TTY, no `--yes`:
   `ProjectNotEmptyError`; message names the project's name and id and contains
   `--yes`, and not "not supported yet"; stderr is empty; nothing changed.
5. `test_validation_refusals_come_before_the_prompt` — a replacing import (TTY) whose
   file also holds a duplicated id: `ImportFormatError`, stderr has no summary and no
   prompt (the runner's `input` is unused), nothing changed.
6. `test_id_owned_by_a_project_not_being_replaced_is_refused_naming_the_owner` — same
   install: project A has card `a1`; project C has card `c1`. One-entry file for A
   (from A's export) with `c1`'s node appended; import from A with `--yes`:
   `EntityAlreadyExistsError`; message has `c1`'s id, C's name and C's id; A and C
   unchanged. Same for a comment id owned by C (hand-added to the entry's `comments`).
7. `test_ids_may_move_between_two_replaced_projects` — same install, A has `a1`, B has
   `b1`. `export --all`, then edit the file so `a1`'s node sits in B's entry and `b1`'s
   in A's. Import with `--yes` from an unregistered dir: exit 0; `list` in A shows `b1`,
   in B shows `a1`.
8. `test_incoming_edges_survive_replacement_and_reconnect` — same install: A has `a1`;
   B has `b1` blocked by `a1` and an explicit ref to `a1`
   (`ok("block", b1, "--by", a1)` and `ok("ref", "add", b1, a1)` from B). Export A (`full`). Build `without` = `full` with `a1` removed. From A, import
   `without` `--yes`: `show b1` lists blocker `a1` as `not-found`, `b1` resolves
   `blocked`, the ref row from `b1` still exists; report `not_found_edges == 0` (the
   edge is not from the file). Import `full` `--yes`: blocker `a1` has status `todo`,
   `b1` is `todo`, ref resolves.
9. `test_replace_keeps_the_project_row` — project's id, name, `root_path`, `created_at`
   unchanged after replacing with an entry whose recorded `name` and `created_at`
   differ; `ok("projects")` has the same single row.
10. `test_replace_removes_old_document_backups_after_commit` — `populated` (doc `d1`).
    Add a second doc `d2`; export (has both); delete nothing; build a file without
    `d2`. Import `--yes`: `d2`'s backup file is gone, `d1`'s backup holds the file's
    content. Then a file whose `d1` entry has no `content`: after import `d1`'s
    backup is gone (only backups this import wrote remain).
11. `test_failed_replace_leaves_old_state_and_backups_intact` — `populated`; record
    every file in `paths.docs_dir()` with its bytes. Build a file from the export that
    keeps doc `d1`'s id with **different** content, adds a new doc `d9`, and adds a
    comment on a nonexistent id. Import `--yes`: `ImportFormatError` "internally
    inconsistent"; all old entities, comments, tags still present; docs dir has exactly
    the recorded files with identical bytes (`d1` restored, no `d9`).
12. `test_replace_never_touches_doc_source_files` — `populated` (`docs/notes.md` in the
    repo). Overwrite `docs/notes.md` with `local edits`, create `docs/other.md` with
    `keep`. Import the export (whose `notes` content differs) `--yes`: both repo files
    byte-identical; a doc entry whose `source_path` is absent from the repo leaves it
    absent.
13. `test_round_trip_across_two_machines` — machine 1 (`project` fixture install): A
    = `populated`; B with a card blocked by A's card and an issue ref'd from A's card.
    `export --all` from anywhere → file. Machine 2: `monkeypatch.setenv` a new
    `XDG_DATA_HOME` (empty `brd.db`), chdir to an unregistered dir; the recorded roots
    still exist. `import --yes`: exit 0, both `registered: true`, `removed` all zero,
    `not_found_edges == 0`, stderr has no `replacing` line. `export --all` on machine 2
    equals machine 1's file (`projects` compared as a list sorted by project id).
    Import the same file again with `--yes`: both projects replaced (`removed` equals
    the `+` counts), `export --all` still equal — re-import is idempotent.
14. `test_replace_of_a_registered_but_empty_target_does_not_ask` — empty registered
    project; TTY with `input=""`: exit 0, stderr empty, `removed` all zeros, no
    ` [replaced]` in `--pretty`.
15. `test_import_help_mentions_yes` — extends `test_import_help_describes_placement`:
    help contains `--yes` and "replace"/"replaced", not "Refuses, writing nothing, if a
    target".

Unit tier, `tests/test_project_scope.py` (the module already holds direct
`snapshot.load` tests; this tier pins the library contract the CLI relies on, which no
CLI test can observe — e.g. that `confirm` is not called when nothing is replaced):

16. `test_load_confirm_contract` — `confirm=None` with a non-empty target →
    `ProjectNotEmptyError`; a recording `confirm` returning `False` → `Aborted`, called
    once with one `Replacement` whose `project.id`, `removed` and `added` match;
    returning `True` → replaced; an empty target → `confirm` never called.

### Updated

- `test_import_refuses_a_non_empty_target` (`tests/test_snapshot.py:806`) — keep as the
  non-TTY refusal; additionally assert `--yes` in the message and that stderr is empty.
- `test_id_owned_by_another_project_is_refused` (`:608`) and
  `test_tree_id_owned_by_another_project_is_refused` (`:618`) — additionally assert the
  owner project's name and id appear in the message.
- `test_import_collision_touches_nothing` (`:115`), `test_old_tree_snapshot_still_imports`
  (`:131`), the `export --all` test at `:322-350`, and `tests/test_cli.py:711`
  `test_import_rejects_colliding_ids` — unchanged: under `CliRunner` stdin is not a TTY and
  every id in the file is owned by the replaced target, so they still get
  `ProjectNotEmptyError`. `test_old_tree_snapshot_still_imports` gains: re-import with
  `--yes` succeeds with `removed.cards == 2`.
- `test_import_stem_collision_touches_nothing` (`:180`) **changes**: it imports `populated`'s
  export into a *different* registered project (`other`) that holds a document at the same
  path and stem. The file's ids are owned by `populated`'s project, which is not being
  replaced, so validation now refuses with `EntityAlreadyExistsError` (naming that owner)
  before the non-empty check; assert that type, and that nothing changed. The stem/path
  collision case moves to a new test: from `populated`'s own project, `--yes`
  re-importing its own export (same path and stem as the existing document) succeeds —
  the old document does not collide with the incoming one.
- `test_import_report_shape_and_pretty` — expect the `removed` key (all zeros) in each
  `projects` item; pretty output unchanged for a fresh import.

### Verification

`uv run pytest` — full suite green (baseline 906 passed).

## Out of scope

- Placement, normalization, the not-found edge rules and the rest of 5.2's behaviour
  (card `2dbf2631`), and anything in export / the v2 format (5.1, `a8e090a7`).
- Merging an entry into a non-empty project (keeping entities absent from the file):
  replacement is whole-project only [P D10 L40].
- Changing `brd forget`, `brd delete`, `brd purge` or `db.delete_project`.
- Writing, deleting or reconciling doc source files in the repo (that is `brd doc
  restore`), and reindexing outside projects' `[[uuid]]` links to returning ids.
- Counting outside projects' incoming edges in `not_found_edges`.
- A `--no-input`/`--force` flag, or prompting anywhere other than stdin's TTY.
- The `brd --help` / `brd prompt` consumer-contract text [P §6] — another story.
