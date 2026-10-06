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


---

# 5.3 Import Replaces a Project's Local State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `brd import <file> [--yes]` replaces a target project that already has entities, after a y/N confirmation on stderr (or `--yes`), keeping incoming edges from other projects; with no TTY and no `--yes` it refuses and writes nothing.

**Architecture:** `src/brd/snapshot.py` stays I/O-free: after placement it computes `Replacement`s (registered targets that own entities), validates the file treating those projects as empty, asks a `confirm` callback the CLI passes in (or refuses if there is none), then wipes each replaced project with `DELETE FROM entities WHERE project_id = ?` inside the existing single import transaction before inserting. Document backups are snapshotted before overwrite so a failed import restores them byte-for-byte, and a successful one removes the replaced projects' stale backups. `src/brd/cli/snapshot.py` adds `--yes`, prints the per-project summary to stderr and prompts with `typer.confirm` when stdin is a TTY.

**Tech Stack:** Python 3, SQLite (`sqlite3`, foreign keys ON), Typer 0.27.2 (vendors click as `typer._click`; there is **no** importable `click` package — use `typer.Abort`), pytest via `uv run pytest`.

**Spec:** `docs/superpowers/specs/5-3-import-replaces-a-7188185d.md` (prepended above).

## Global Constraints

- CLI form is `brd import <file> [--yes]`; `--yes` help text: `Replace target projects that already have entities without asking.`
- Every refusal is a `BrdError` envelope `{"ok": false, "error": {type, message}}`, exit 1, and writes nothing (no project row, entity, edge, comment, tag, or backup file created/changed/removed).
- Validation refusals happen before any summary is printed or any prompt is shown.
- Summary line (stderr only, one per replaced project, file order): `brd: replacing <name> (<root_path>): -<c> cards, -<i> issues, -<d> documents, -<m> comments / +<c'> cards, +<i'> issues, +<d'> documents, +<m'> comments`
- Prompt (stderr): `Replace <n> project(s)? This cannot be undone. [y/N]: ` — default No.
- Declined/EOF/Ctrl-C → envelope type `Aborted`, message `Import cancelled; nothing was written.`
- No TTY and no `--yes` → `ProjectNotEmptyError` naming each replaced project (name and id) with card/issue/document counts and `pass --yes to replace their contents`; the words "not supported yet" appear nowhere.
- Outside-owned id → `EntityAlreadyExistsError` `entity <id> already exists in project <name> (<project id>)`; comment → `comment <id> already exists in project <name> (<project id>)`.
- Wipe is `DELETE FROM entities WHERE project_id = ?` inside `_write`'s `with conn:`. Never call `db.delete_project` or any `brd delete` helper. The project row (id, name, root_path, created_at) is kept.
- Incoming edges (`blocked_by.blocks_on_id`, `refs.dst_id` from outside projects) are never deleted.
- Import never writes, deletes or reads-for-writing any file under a project's `root_path`.
- Report: each `projects` item gains `"removed": {"cards", "issues", "documents", "comments"}` (all zeros when not replaced); `--pretty` appends ` [replaced]` to a replaced project's line; `not_found_edges` counts only edges from the file.
- `snapshot.load(conn, cwd, raw, confirm=None)`; `snapshot.Replacement(project, removed, added)`; new `Aborted(BrdError)` in `src/brd/errors.py`.
- Only `src/brd/snapshot.py`, `src/brd/cli/snapshot.py`, `src/brd/errors.py`, `README.md` and tests change.
- Full suite green: `uv run pytest` (baseline 906 passed).

## Deviations from the spec's test list (verified against the code)

- **`test_import_stem_collision_touches_nothing` stays unchanged.** The spec says it now hits `EntityAlreadyExistsError`, but it uses `_fresh_project`, a *separate install* (own `XDG_DATA_HOME`), where none of the file's ids exist. Validation passes (the target is treated as empty), and with no TTY and no `--yes` it still gets `ProjectNotEmptyError`. The `--yes` success case is added as a new test (Task 5, `test_replacing_a_project_frees_its_document_paths_and_stems`).
- **Test 8 marks `a1` done before exporting.** A card blocked by a `todo` card resolves `blocked` (`core.resolve_status`), so "after reconnecting, `b1` is `todo`" only holds if the blocker is finished. The test sets `a1` to `done` and expects the reconnected blocker status `done` and `b1` `todo`.
- **`typer.Abort`, not `click.exceptions.Abort`:** typer 0.27.2 vendors click; `import click` fails in this environment.
- **Duplicate document path/stem within one incoming entry is checked in `_validate`** (raising `ImportFormatError`, the same type as today), so R1's "a doomed import never asks" holds for a replaced target too. Before, it was caught only by the transaction's integrity check, which for a replaced target would run after the prompt.

## Review Focus

1. A replacing entry with two documents sharing a source path, or a stem differing only in ASCII case → `ImportFormatError` before any summary or prompt, nothing written. (Task 3: `test_duplicate_document_paths_in_a_replacing_entry_refuse_before_the_prompt`.)
2. Typing the word `yes` (not just `y`) at the prompt replaces; an empty answer, `n` or EOF cancels. (Task 2: `test_replace_on_tty_answer_yes_replaces_the_project` parametrised `y`/`yes`; `test_replace_on_tty_answer_no_changes_nothing` parametrised `n`/empty/EOF.)
3. A structurally malformed entity (e.g. an issue missing `title`) in a replacing import, discovered only inside the transaction after the user confirmed → `ImportFormatError` "malformed snapshot", old entities intact, every backup byte-identical. (Task 4: `test_malformed_entity_in_a_replace_leaves_old_state_and_backups_intact`.)
4. Replacing one project never removes another project's document backups. (Task 4: `kept` assertions in `test_replace_removes_old_document_backups_after_commit`.)
5. In `--pretty` mode the replacement summary still goes to stderr and never into stdout's report. (Task 2: assertions in `test_replace_with_yes_skips_the_prompt`.)

## File Structure

- `src/brd/errors.py` — add `Aborted(BrdError)` (envelope type `Aborted`, matching `brd purge`).
- `src/brd/snapshot.py` — `CONTENT_KEYS`, `Replacement`, `load(..., confirm)`, `_replacements`, `_project_counts`, `_confirm`, `_validate(..., replaced)` (owner-naming messages, replaced-project exemptions, within-entry document uniqueness), `_write(..., replaced)` (wipe + backup snapshot/restore/cleanup), `_report(..., replacements)` (`removed`). `_require_empty` is deleted.
- `src/brd/cli/snapshot.py` — `_stdin_is_tty`, `_replacement_line`, `_confirmation`, `--yes` option, `[replaced]` in `_import_text`, new help docstring.
- `README.md:73` — import paragraph.
- `tests/test_snapshot.py` — CLI integration tests (helpers `_board`, `_backups`, `_import_on_tty`).
- `tests/test_project_scope.py` — `test_load_confirm_contract` (library contract).

---

### Task 1: Library replace contract (`Aborted`, `Replacement`, `confirm`, wipe, `removed` in the report)

**Files:**
- Modify: `src/brd/errors.py` (append after `ProjectRootNotFoundError`, line 125-126)
- Modify: `src/brd/snapshot.py:1-20` (imports, constants), `:121-151` (`_Target`, `load`, `_load`), `:285-310` (replace `_require_empty`), `:326-378` (`_validate`, `_write`), `:437-453` (`_report`)
- Test: `tests/test_project_scope.py` (imports at lines 10-22; new test after `test_snapshot_load_records_its_project`, line ~118)
- Test: `tests/test_snapshot.py` (update `test_import_report_shape_and_pretty` ~line 629, rewrite `test_import_refuses_a_non_empty_target` ~line 806, add helpers and `test_replace_without_tty_or_yes_refuses` at end of file)

**Interfaces:**
- Consumes: `db.owner_of(conn, entity_id) -> Project | None` (`src/brd/db.py:574`), `db.in_project(id_column) -> str`.
- Produces:
  - `brd.errors.Aborted(BrdError)`.
  - `snapshot.CONTENT_KEYS = ("cards", "issues", "documents", "comments")`.
  - `@dataclass snapshot.Replacement(project: Project, removed: dict, added: dict)` — count dicts keyed by `CONTENT_KEYS`.
  - `snapshot.load(conn: sqlite3.Connection, cwd: Path, raw, confirm: Callable[[list[Replacement]], bool] | None = None) -> dict`.
  - Each report `projects` item has key `"removed"` (dict keyed by `CONTENT_KEYS`).
  - Test helpers in `tests/test_snapshot.py`: `_board() -> dict`, `_backups() -> dict[str, bytes]`.

- [ ] **Step 1: Write the failing library test**

In `tests/test_project_scope.py`, extend the `from brd.errors import (...)` block (lines 10-22) so it reads:

```python
from brd.errors import (
    Aborted,
    CardNotFoundError,
    CommentNotFoundError,
    CycleError,
    DocumentNotFoundError,
    DuplicatePathError,
    DuplicateStemError,
    EntityNotFoundError,
    ImportFormatError,
    InvalidBlockerError,
    IssueNotFoundError,
    ProjectNotEmptyError,
    SelfReferenceError,
)
```

Then add, directly after `test_snapshot_load_records_its_project` (ends at line ~118, before the `@pytest.fixture def two`):

```python
def test_load_confirm_contract(pconn, tmp_path):
    other = dataclasses.replace(OTHER_PROJECT, root_path=str(tmp_path.resolve()))
    add_project(pconn, other)
    snap = {
        "brd_export": 1,
        "cards": [
            {"id": "e", "title": "E", "description": None, "status": "todo", "blocked_by": [],
             "created_at": NOW, "updated_at": NOW, "children": []}
        ],
        "documents": [
            {"id": "dd", "title": "D", "source_path": "docs/d.md", "content": "x",
             "content_hash": "h", "created_at": NOW, "updated_at": NOW}
        ],
        "comments": [
            {"id": "m", "entity_id": "e", "author": "a", "body": "b", "created_at": NOW}
        ],
    }

    def owned():
        return {
            row[0]
            for row in pconn.execute("SELECT id FROM entities WHERE project_id = ?", (other.id,))
        }

    def never(replacements):
        raise AssertionError("confirm was called for an empty target")

    # A registered but empty target is not replaced: confirm is never called.
    snapshot.load(pconn, tmp_path, snap, confirm=never)
    make_card(pconn, "old", project_id=other.id)

    # The same ids again: owned by the project being replaced, so allowed.
    with pytest.raises(ProjectNotEmptyError, match="pass --yes"):
        snapshot.load(pconn, tmp_path, snap)
    calls = []
    with pytest.raises(Aborted, match="nothing was written"):
        snapshot.load(pconn, tmp_path, snap, confirm=lambda reps: calls.append(reps) or False)
    assert owned() == {"e", "dd", "old"}
    ((replacement,),) = calls
    assert replacement.project.id == other.id
    assert replacement.removed == {"cards": 2, "issues": 0, "documents": 1, "comments": 1}
    assert replacement.added == {"cards": 1, "issues": 0, "documents": 1, "comments": 1}

    result = snapshot.load(pconn, tmp_path, snap, confirm=lambda reps: True)
    assert owned() == {"e", "dd"}
    assert result["projects"][0]["removed"] == replacement.removed
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_project_scope.py::test_load_confirm_contract -v`
Expected: FAIL at collection with `ImportError: cannot import name 'Aborted' from 'brd.errors'`.

- [ ] **Step 3: Write the failing CLI tests**

In `tests/test_snapshot.py`, replace `test_import_refuses_a_non_empty_target` (the whole function, ~lines 805-827) with:

```python
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
    result = invoke("import", snapshot)
    assert result.exit_code == 1, result.output
    error = json.loads(result.stdout)["error"]
    assert error["type"] == "ProjectNotEmptyError"
    assert a["id"] in error["message"] and a["name"] in error["message"]
    assert "--yes" in error["message"]
    assert "not supported yet" not in error["message"]
    assert result.stderr == ""
    assert ok("projects") == [a]
    monkeypatch.chdir(project)
    assert (ok("list"), ok("issue", "list")) == before
```

In `test_import_report_shape_and_pretty` (~line 629), replace the expected `result["projects"]` literal with:

```python
    assert result["projects"] == [
        {
            "project": registered,
            "registered": False,
            "imported": 4,
            "cards": 2,
            "issues": 1,
            "documents": 1,
            "comments": 1,
            "removed": {"cards": 0, "issues": 0, "documents": 0, "comments": 0},
        }
    ]
```

Append at the end of `tests/test_snapshot.py`:

```python
def _board():
    """What a replacing import could change, as the CLI shows it from the cwd."""
    return {
        "projects": ok("projects"),
        "cards": ok("list"),
        "issues": ok("issue", "list"),
        "docs": ok("doc", "list"),
        "export": ok("export"),
    }


def _backups():
    """Every document backup file in this install, with its bytes."""
    docs_dir = paths.docs_dir()
    if not docs_dir.exists():
        return {}
    return {path.name: path.read_bytes() for path in docs_dir.iterdir()}


def test_replace_without_tty_or_yes_refuses(populated, tmp_path):
    snapshot = _snapshot_file(tmp_path, ok("export"))
    (registered,) = ok("projects")
    before, backups = _board(), _backups()
    result = invoke("import", snapshot)
    assert result.exit_code == 1, result.output
    error = json.loads(result.stdout)["error"]
    assert error["type"] == "ProjectNotEmptyError"
    assert registered["name"] in error["message"] and registered["id"] in error["message"]
    assert "--yes" in error["message"]
    assert "not supported yet" not in error["message"]
    assert result.stderr == ""
    assert _board() == before and _backups() == backups
```

- [ ] **Step 4: Run them to verify they fail**

Run: `uv run pytest tests/test_snapshot.py -k "refuses_a_non_empty_target or report_shape_and_pretty or without_tty_or_yes" -v`
Expected: FAIL — `--yes` not in the message (it still says "not supported yet"), and the report item has no `removed` key.

- [ ] **Step 5: Add `Aborted`**

Append to `src/brd/errors.py`:

```python


class Aborted(BrdError):
    """The user declined a confirmation; the class name is the envelope type,
    the same one `brd purge` reports."""
```

- [ ] **Step 6: Implement the contract in `src/brd/snapshot.py`**

Replace lines 1-20 (imports and constants) with:

```python
import dataclasses
import sqlite3
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from brd import core, db, documents, entities, issues, master, refs
from brd.errors import (
    Aborted,
    EntityAlreadyExistsError,
    ImportFormatError,
    ProjectAlreadyExistsError,
    ProjectNotEmptyError,
    ProjectNotFoundError,
    ProjectRootNotFoundError,
)
from brd.models import Project

FORMAT_VERSION = 2
V1_FORMAT_VERSION = 1
ENTRY_BODY_KEYS = ("cards", "issues", "documents", "comments", "tags", "refs")
PROJECT_KEYS = ("id", "name", "root_path", "created_at")
COUNT_KEYS = ("imported", "cards", "issues", "documents", "comments")
CONTENT_KEYS = ("cards", "issues", "documents", "comments")
```

After the `_Target` dataclass (ends line 126), add:

```python


@dataclasses.dataclass
class Replacement:
    """A registered target that already owns entities: the import wipes it
    and loads its entry instead. removed is what it holds now, added what
    the entry brings; both keyed by CONTENT_KEYS."""

    project: Project
    removed: dict
    added: dict
```

Replace `load` and `_load` (lines 129-151) with:

```python
def load(
    conn: sqlite3.Connection,
    cwd: Path,
    raw,
    confirm: Callable[[list[Replacement]], bool] | None = None,
) -> dict:
    """Import a snapshot: place each entry in its project (registering
    projects where needed), check the whole file, then write it in one
    transaction. cwd matters only for a one-entry snapshot. A target that
    already has entities is replaced only if confirm, called once with every
    replacement, returns True; with no confirm, import refuses."""
    try:
        return _load(conn, cwd, raw, confirm)
    except (KeyError, TypeError, AttributeError, sqlite3.ProgrammingError) as exc:
        # Missing keys or wrong value types in the snapshot. Any backups the
        # import wrote were already cleaned up by the time this is caught.
        raise ImportFormatError(f"malformed snapshot: {type(exc).__name__}: {exc}") from exc


def _load(conn: sqlite3.Connection, cwd: Path, raw, confirm) -> dict:
    entries = _entries(raw)
    targets = _place(conn, cwd, entries)
    replacements = _replacements(conn, entries, targets)
    replaced = {replacement.project.id for replacement in replacements}
    _validate(conn, entries, targets, replaced)
    if replacements:
        _confirm(replacements, confirm)
    _write(conn, entries, targets, replaced)
    # After commit, so [[stem]] and [[uuid]] links resolve against the whole import.
    for entry in entries:
        for entity_id in entry.entity_ids():
            refs.reindex(conn, entity_id)
    return _report(conn, entries, targets, replacements)
```

Replace `_require_empty` (lines 285-310) with:

```python
def _replacements(
    conn: sqlite3.Connection, entries: list[_Entry], targets: list[_Target]
) -> list[Replacement]:
    """Every registered target that already owns entities, in file order.
    New targets are empty."""
    replacements = []
    for entry, target in zip(entries, targets):
        if target.registered:
            continue
        removed = _project_counts(conn, target.project.id)
        if any(removed.values()):
            counts = entry.counts()
            added = {key: counts[key] for key in CONTENT_KEYS}
            replacements.append(Replacement(target.project, removed, added))
    return replacements


def _project_counts(conn: sqlite3.Connection, project_id: str) -> dict:
    kinds = {
        row["kind"]: row["n"]
        for row in conn.execute(
            "SELECT kind, COUNT(*) AS n FROM entities WHERE project_id = ? GROUP BY kind",
            (project_id,),
        )
    }
    comments = conn.execute(
        f"SELECT COUNT(*) FROM comments {db.in_project('comments.entity_id')}", (project_id,)
    ).fetchone()[0]
    return {
        "cards": kinds.get("card", 0),
        "issues": kinds.get("issue", 0),
        "documents": kinds.get("document", 0),
        "comments": comments,
    }


def _confirm(
    replacements: list[Replacement], confirm: Callable[[list[Replacement]], bool] | None
) -> None:
    if confirm is None:
        raise ProjectNotEmptyError(
            "target project already has entities: "
            + "; ".join(
                f"{r.project.name} ({r.project.id}) has {r.removed['cards']} cards, "
                f"{r.removed['issues']} issues and {r.removed['documents']} documents"
                for r in replacements
            )
            + "; pass --yes to replace their contents"
        )
    if not confirm(replacements):
        raise Aborted("Import cancelled; nothing was written.")
```

Replace `_validate` (lines 326-346) with:

```python
def _validate(
    conn: sqlite3.Connection, entries: list[_Entry], targets: list[_Target], replaced: set[str]
) -> None:
    """Every check before anything is written, over the whole file. A
    replaced project counts as already empty: its ids may come back, in any
    entry, and its documents never collide with incoming ones. Edge targets
    are not checked: one that is not in the database is kept and reported
    as not-found."""
    entity_ids = [entity_id for entry in entries for entity_id in entry.entity_ids()]
    if len(set(entity_ids)) != len(entity_ids):
        raise ImportFormatError("snapshot contains duplicate ids")
    for entity_id in entity_ids:
        owner = db.owner_of(conn, entity_id)
        if owner is not None and owner.id not in replaced:
            raise EntityAlreadyExistsError(f"entity {entity_id} already exists in another project")
    for entry in entries:
        for comment in entry.comments:
            row = conn.execute(
                "SELECT entity_id FROM comments WHERE id = ?", (comment["id"],)
            ).fetchone()
            if row is None:
                continue
            owner = db.owner_of(conn, row["entity_id"])
            if owner is None or owner.id not in replaced:
                raise EntityAlreadyExistsError(f"comment {comment['id']} already exists")
    for entry, target in zip(entries, targets):
        for doc in entry.documents:
            _check_source_path(doc["source_path"])
        if target.project.id in replaced:
            continue
        for doc in entry.documents:
            documents._check_unique(
                conn, target.project.id, doc["source_path"], PurePosixPath(doc["source_path"]).stem
            )
```

In `_write` (lines 349-378), change the signature, docstring and transaction body so the function reads:

```python
def _write(
    conn: sqlite3.Connection, entries: list[_Entry], targets: list[_Target], replaced: set[str]
) -> None:
    """One transaction: new projects, then the replaced projects' wipe, then
    every entry's entities, then every entry's edges, comments, tags and
    refs, so an edge or comment into another entry finds its target whatever
    the entry order."""
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
            for project_id in replaced:
                # The deletion `brd forget` does, keeping the project row: the
                # cascades take cards, issues, documents, comments, tags and
                # outgoing edges. Incoming edges have no foreign key and stay.
                conn.execute("DELETE FROM entities WHERE project_id = ?", (project_id,))
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
```

Replace `_report` (lines 437-453) with:

```python
def _report(
    conn: sqlite3.Connection,
    entries: list[_Entry],
    targets: list[_Target],
    replacements: list[Replacement],
) -> dict:
    removed = {replacement.project.id: replacement.removed for replacement in replacements}
    per_project = [
        {
            "project": dataclasses.asdict(db.get_project_by_id(conn, target.project.id)),
            "registered": target.registered,
            **entry.counts(),
            "removed": removed.get(target.project.id, dict.fromkeys(CONTENT_KEYS, 0)),
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

- [ ] **Step 7: Run the new and updated tests**

Run: `uv run pytest tests/test_project_scope.py::test_load_confirm_contract tests/test_snapshot.py -k "load_confirm_contract or refuses_a_non_empty_target or report_shape_and_pretty or without_tty_or_yes" -v`
Expected: PASS.

- [ ] **Step 8: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass (906 + the new ones). `test_import_collision_touches_nothing`, `test_old_tree_snapshot_still_imports`, `test_import_stem_collision_touches_nothing`, `test_export_all_lists_every_project_in_creation_order` and `tests/test_cli.py::test_import_rejects_colliding_ids` still get `ProjectNotEmptyError` (no confirm is passed yet).

- [ ] **Step 9: Commit**

```bash
git add src/brd/errors.py src/brd/snapshot.py tests/test_project_scope.py tests/test_snapshot.py
git commit -m "Let snapshot.load replace a non-empty target when a confirm callback agrees"
```

---

### Task 2: `brd import --yes`, the stderr summary and the TTY prompt

**Files:**
- Modify: `src/brd/cli/snapshot.py:1-10` (imports), `:40-53` (`_import_text`), `:78-98` (`import_cmd`)
- Test: `tests/test_snapshot.py` (add `import copy` at the top; append helper and tests at the end)

**Interfaces:**
- Consumes: `snapshot.load(conn, cwd, raw, confirm)`, `snapshot.Replacement`, `snapshot.CONTENT_KEYS` (Task 1); test helpers `_board()`, `_backups()` (Task 1).
- Produces:
  - `brd.cli.snapshot._stdin_is_tty() -> bool` (module-level; tests monkeypatch it).
  - `brd.cli.snapshot._replacement_line(replacement: snapshot.Replacement) -> str`.
  - `brd.cli.snapshot._confirmation(yes: bool) -> Callable[[list[snapshot.Replacement]], bool] | None`.
  - `--yes` option on `brd import`.
  - Test helper `_import_on_tty(monkeypatch, snapshot, answer, *args) -> tuple[int, dict, str]` (exit code, envelope, stderr).

- [ ] **Step 1: Write the failing tests**

At the top of `tests/test_snapshot.py`, change the first import line block to:

```python
import copy
import json
import shutil
```

Append at the end of `tests/test_snapshot.py`:

```python
def _import_on_tty(monkeypatch, snapshot, answer, *args):
    """`brd import` as if stdin were a terminal, typing answer. The runner
    echoes the typed answer into stdout before the envelope, so the
    envelope is parsed from its first `{`."""
    monkeypatch.setattr("brd.cli.snapshot._stdin_is_tty", lambda: True)
    result = invoke("import", snapshot, *args, input=answer)
    out = result.stdout
    return result.exit_code, json.loads(out[out.index("{"):]), result.stderr


@pytest.mark.parametrize("answer", ["y\n", "yes\n"])
def test_replace_on_tty_answer_yes_replaces_the_project(populated, tmp_path, monkeypatch, answer):
    data = ok("export")
    snapshot = _snapshot_file(tmp_path, data)
    extra = ok("add", "--title", "extra")["id"]
    ok("update", populated["card"]["id"], "--title", "Renamed")
    (registered,) = ok("projects")

    code, envelope, stderr = _import_on_tty(monkeypatch, snapshot, answer)
    assert code == 0 and envelope["ok"] is True
    assert (
        f"brd: replacing {registered['name']} ({registered['root_path']}): "
        "-3 cards, -1 issues, -1 documents, -1 comments / "
        "+2 cards, +1 issues, +1 documents, +1 comments"
    ) in stderr
    assert "Replace 1 project(s)? This cannot be undone. [y/N]" in stderr
    (item,) = envelope["data"]["projects"]
    assert item["registered"] is False
    assert item["removed"] == {"cards": 3, "issues": 1, "documents": 1, "comments": 1}
    assert extra not in {card["id"] for card in ok("list")}
    assert ok("show", populated["card"]["id"])["title"] == "Parser"
    assert ok("export") == data


@pytest.mark.parametrize("answer", ["n\n", "\n", ""], ids=["no", "empty", "eof"])
def test_replace_on_tty_answer_no_changes_nothing(populated, tmp_path, monkeypatch, answer):
    snapshot = _snapshot_file(tmp_path, ok("export"))
    ok("add", "--title", "extra")
    before, backups = _board(), _backups()
    code, envelope, stderr = _import_on_tty(monkeypatch, snapshot, answer)
    assert code == 1
    assert envelope["error"]["type"] == "Aborted"
    assert "cancelled" in envelope["error"]["message"]
    assert "brd: replacing " in stderr
    assert _board() == before and _backups() == backups


def test_replace_with_yes_skips_the_prompt(populated, tmp_path):
    data = ok("export")
    snapshot = _snapshot_file(tmp_path, data)
    extra = ok("add", "--title", "extra")["id"]
    result = invoke("import", snapshot, "--yes")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["ok"] is True
    assert "brd: replacing " in result.stderr
    assert "[y/N]" not in result.stderr
    assert extra not in {card["id"] for card in ok("list")}
    assert ok("export") == data

    ok("add", "--title", "extra again")
    result = invoke("import", snapshot, "--yes", "--pretty")
    assert result.exit_code == 0, result.output
    project_line, _ = result.stdout.splitlines()
    assert project_line.endswith(" [replaced]")
    # The summary is stderr's, never part of the pretty report.
    assert "brd: replacing " in result.stderr
    assert "brd: replacing " not in result.stdout


def test_validation_refusals_come_before_the_prompt(populated, tmp_path, monkeypatch):
    data = ok("export")
    entry = _entry(data)
    entry["cards"].append(copy.deepcopy(entry["cards"][0]))
    snapshot = _snapshot_file(tmp_path, data)
    before, backups = _board(), _backups()
    code, envelope, stderr = _import_on_tty(monkeypatch, snapshot, "y\n")
    assert code == 1
    assert envelope["error"]["type"] == "ImportFormatError"
    assert "duplicate ids" in envelope["error"]["message"]
    assert stderr == ""
    assert _board() == before and _backups() == backups


def test_ids_may_move_between_two_replaced_projects(project, tmp_path, monkeypatch):
    a1 = ok("add", "--title", "a1")["id"]
    b_root, _ = _another_project(tmp_path, monkeypatch, "bproj")
    b1 = ok("add", "--title", "b1")["id"]
    data = ok("export", "--all")
    a_entry, b_entry = data["projects"]
    a_entry["cards"], b_entry["cards"] = b_entry["cards"], a_entry["cards"]
    snapshot = _snapshot_file(tmp_path, data)
    _unregistered_dir(tmp_path, monkeypatch, "elsewhere")
    result = ok("import", snapshot, "--yes")
    assert [item["removed"]["cards"] for item in result["projects"]] == [1, 1]
    monkeypatch.chdir(project)
    assert [card["id"] for card in ok("list")] == [b1]
    monkeypatch.chdir(b_root)
    assert [card["id"] for card in ok("list")] == [a1]


def test_replace_of_a_registered_but_empty_target_does_not_ask(project, tmp_path, monkeypatch):
    snapshot = _snapshot_file(tmp_path, [_card_node(CARD_1)])
    code, envelope, stderr = _import_on_tty(monkeypatch, snapshot, "")
    assert code == 0 and envelope["ok"] is True
    assert stderr == ""
    (item,) = envelope["data"]["projects"]
    assert item["registered"] is False
    assert item["removed"] == {"cards": 0, "issues": 0, "documents": 0, "comments": 0}

    _another_project(tmp_path, monkeypatch, "second")
    text = human("import", _snapshot_file(tmp_path, [_card_node(CARD_2)], "second.json"))
    assert "[replaced]" not in text
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_snapshot.py -k "answer_yes or answer_no or with_yes_skips or come_before_the_prompt or move_between or empty_target_does_not_ask" -v`
Expected: FAIL — `AttributeError: <module 'brd.cli.snapshot'> has no attribute '_stdin_is_tty'` for the TTY tests, and exit code 2 ("No such option: --yes") for the `--yes` tests.

- [ ] **Step 3: Implement the CLI**

In `src/brd/cli/snapshot.py`, replace lines 1-10 with:

```python
import json
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path

import typer

from brd import db, master, output, snapshot
from brd.cli._app import app, fail, pretty_option, run
from brd.errors import BrdError, ImportReadError
```

Replace `_import_text` (lines 40-53) with:

```python
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
        elif any(item["removed"].values()):
            line += " [replaced]"
        lines.append(line)
    lines.append(f"not-found edge targets: {data['not_found_edges']}")
    return "\n".join(lines)


def _stdin_is_tty() -> bool:
    # A function so tests can stand in for a terminal: CliRunner swaps
    # sys.stdin for a non-TTY stream.
    return sys.stdin.isatty()


def _replacement_line(replacement: snapshot.Replacement) -> str:
    project = replacement.project
    removed = ", ".join(f"-{replacement.removed[key]} {key}" for key in snapshot.CONTENT_KEYS)
    added = ", ".join(f"+{replacement.added[key]} {key}" for key in snapshot.CONTENT_KEYS)
    return f"brd: replacing {project.name} ({project.root_path}): {removed} / {added}"


def _confirmation(yes: bool) -> Callable[[list[snapshot.Replacement]], bool] | None:
    """How import confirms replacing projects that have entities: not at all
    (refuse) without a terminal and without --yes; otherwise print what
    each replacement removes and adds on stderr, then ask unless --yes."""
    if not yes and not _stdin_is_tty():
        return None

    def confirm(replacements: list[snapshot.Replacement]) -> bool:
        for replacement in replacements:
            typer.echo(_replacement_line(replacement), err=True)
        if yes:
            return True
        try:
            return typer.confirm(
                f"Replace {len(replacements)} project(s)? This cannot be undone.",
                default=False,
                err=True,
            )
        except typer.Abort:  # EOF or Ctrl-C at the prompt
            return False

    return confirm
```

Replace `import_cmd` (lines 78-98) with (docstring unchanged here; Task 6 rewrites it):

```python
@app.command(name="import")
def import_cmd(
    file: Path = typer.Argument(
        ..., help="Path to a `brd export` file (or an older `brd tree` snapshot)."
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Replace target projects that already have entities without asking.",
    ),
    pretty: bool = pretty_option(),
) -> None:
    """Restore a snapshot. A one-project snapshot lands in the current project,
    registering the current directory if it is not in one. A multi-project
    snapshot places each entry in the registered project with its id, else
    registers it at its recorded root; it works from any directory. Refuses,
    writing nothing, if a target project already has entities."""

    def action(conn: sqlite3.Connection) -> dict:
        try:
            raw = json.loads(file.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ImportReadError(f"could not read a JSON snapshot from {file}: {exc}") from exc
        return snapshot.load(conn, Path.cwd(), raw, _confirmation(yes))

    _run_global(pretty, action, _import_text)
```

- [ ] **Step 4: Run the new tests**

Run: `uv run pytest tests/test_snapshot.py -k "answer_yes or answer_no or with_yes_skips or come_before_the_prompt or move_between or empty_target_does_not_ask" -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/brd/cli/snapshot.py tests/test_snapshot.py
git commit -m "Add brd import --yes; confirm replacing non-empty projects on a terminal"
```

---

### Task 3: Validation names the owner and refuses duplicate document paths before asking

**Files:**
- Modify: `src/brd/snapshot.py` — `_validate` (from Task 1) and a new helper `_check_distinct_documents` placed right after `_check_source_path`
- Test: `tests/test_snapshot.py` — update `test_id_owned_by_another_project_is_refused` (~line 608) and `test_tree_id_owned_by_another_project_is_refused` (~line 618); append two tests

**Interfaces:**
- Consumes: `_validate(conn, entries, targets, replaced)` (Task 1), `_import_on_tty`, `_board`, `_backups` (Tasks 1-2), `db.owner_of`.
- Produces: `snapshot._check_distinct_documents(docs: list[dict]) -> None`; `snapshot._nocase(text: str) -> str`. Messages `entity <id> already exists in project <name> (<project id>)` and `comment <id> already exists in project <name> (<project id>)`.

- [ ] **Step 1: Write the failing tests**

Replace `test_id_owned_by_another_project_is_refused` and `test_tree_id_owned_by_another_project_is_refused` with:

```python
def test_id_owned_by_another_project_is_refused(populated, tmp_path, monkeypatch):
    (owner,) = ok("projects")
    snapshot = _snapshot_file(tmp_path, ok("export"))
    _another_project(tmp_path, monkeypatch, "second")
    error = _import_error(snapshot)
    assert error["type"] == "EntityAlreadyExistsError"
    assert populated["card"]["id"] in error["message"]
    assert f"in project {owner['name']} ({owner['id']})" in error["message"]
    assert ok("list") == [] and ok("issue", "list") == [] and ok("doc", "list") == []
    assert len(ok("projects")) == 2


def test_tree_id_owned_by_another_project_is_refused(project, tmp_path, monkeypatch):
    (owner,) = ok("projects")
    card_id = ok("add", "--title", "A")["id"]
    snapshot = _snapshot_file(tmp_path, ok("tree"))
    _another_project(tmp_path, monkeypatch, "second")
    error = _import_error(snapshot)
    assert error["type"] == "EntityAlreadyExistsError"
    assert card_id in error["message"]
    assert f"in project {owner['name']} ({owner['id']})" in error["message"]
    assert ok("list") == []
```

Append at the end of `tests/test_snapshot.py`:

```python
def test_id_owned_by_a_project_not_being_replaced_is_refused_naming_the_owner(
    project, tmp_path, monkeypatch
):
    a1 = ok("add", "--title", "a1")["id"]
    a_entry = _entry(ok("export"))
    c_root, c = _another_project(tmp_path, monkeypatch, "cproj")
    c1 = ok("add", "--title", "c1")["id"]
    ok("comment", "add", c1, "c note")
    c_entry = _entry(ok("export"))
    before_c, backups = _board(), _backups()
    monkeypatch.chdir(project)
    before_a = _board()

    with_card = copy.deepcopy(a_entry)
    with_card["cards"].append(c_entry["cards"][0])
    c_comment = c_entry["comments"][0]
    with_comment = copy.deepcopy(a_entry)
    with_comment["comments"].append({**c_comment, "entity_id": a1})
    for entry, owned_id, what in (
        (with_card, c1, "entity"),
        (with_comment, c_comment["id"], "comment"),
    ):
        snapshot = _snapshot_file(tmp_path, _v2(entry))
        result = invoke("import", snapshot, "--yes")
        assert result.exit_code == 1, result.output
        error = json.loads(result.stdout)["error"]
        assert error["type"] == "EntityAlreadyExistsError"
        assert f"{what} {owned_id} already exists in project {c['name']} ({c['id']})" in (
            error["message"]
        )
        assert result.stderr == ""
        assert _board() == before_a and _backups() == backups
    monkeypatch.chdir(c_root)
    assert _board() == before_c


@pytest.mark.parametrize("clash", ["path", "stem"])
def test_duplicate_document_paths_in_a_replacing_entry_refuse_before_the_prompt(
    populated, tmp_path, monkeypatch, clash
):
    data = ok("export")
    docs = _entry(data)["documents"]
    twin = {**docs[0], "id": "d0c00000-0000-4000-8000-000000000001"}
    if clash == "stem":
        twin["source_path"] = "other/NOTES.md"  # stem `NOTES`, same as `notes` ignoring case
    docs.append(twin)
    snapshot = _snapshot_file(tmp_path, data)
    before, backups = _board(), _backups()
    code, envelope, stderr = _import_on_tty(monkeypatch, snapshot, "y\n")
    assert code == 1
    assert envelope["error"]["type"] == "ImportFormatError"
    assert clash in envelope["error"]["message"]
    assert stderr == ""
    assert _board() == before and _backups() == backups
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_snapshot.py -k "owned_by_another_project or naming_the_owner or refuse_before_the_prompt" -v`
Expected: FAIL — messages say "already exists in another project" / "comment ... already exists" with no owner; the duplicate-document test shows the `brd: replacing` summary on stderr (the clash is caught only inside the transaction, after the prompt) and its message is "snapshot is internally inconsistent".

- [ ] **Step 3: Implement**

In `src/brd/snapshot.py`, add right after `_check_source_path`:

```python
def _nocase(text: str) -> str:
    """Fold text the way SQLite's NOCASE does: ASCII letters only."""
    return "".join(c.lower() if c.isascii() else c for c in text)


def _check_distinct_documents(docs: list[dict]) -> None:
    """Two documents of one entry can't share a path or a stem: they land in
    one project, whose schema keeps both unique. Checked here so a doomed
    import never reaches the confirmation."""
    paths: set[str] = set()
    stems: set[str] = set()
    for doc in docs:
        path = doc["source_path"]
        stem = PurePosixPath(path).stem
        if path in paths:
            raise ImportFormatError(f"snapshot has two documents with path {path}")
        if _nocase(stem) in stems:
            raise ImportFormatError(f"snapshot has two documents with stem {stem}")
        paths.add(path)
        stems.add(_nocase(stem))
```

Replace `_validate` with:

```python
def _validate(
    conn: sqlite3.Connection, entries: list[_Entry], targets: list[_Target], replaced: set[str]
) -> None:
    """Every check before anything is written, over the whole file. A
    replaced project counts as already empty: its ids may come back, in any
    entry, and its documents never collide with incoming ones. Edge targets
    are not checked: one that is not in the database is kept and reported
    as not-found."""
    entity_ids = [entity_id for entry in entries for entity_id in entry.entity_ids()]
    if len(set(entity_ids)) != len(entity_ids):
        raise ImportFormatError("snapshot contains duplicate ids")
    for entity_id in entity_ids:
        owner = db.owner_of(conn, entity_id)
        if owner is not None and owner.id not in replaced:
            raise EntityAlreadyExistsError(
                f"entity {entity_id} already exists in project {owner.name} ({owner.id})"
            )
    for entry in entries:
        for comment in entry.comments:
            row = conn.execute(
                "SELECT entity_id FROM comments WHERE id = ?", (comment["id"],)
            ).fetchone()
            if row is None:
                continue
            owner = db.owner_of(conn, row["entity_id"])
            if owner is None or owner.id not in replaced:
                where = f" in project {owner.name} ({owner.id})" if owner else ""
                raise EntityAlreadyExistsError(f"comment {comment['id']} already exists{where}")
    for entry, target in zip(entries, targets):
        for doc in entry.documents:
            _check_source_path(doc["source_path"])
        _check_distinct_documents(entry.documents)
        if target.project.id in replaced:
            continue
        for doc in entry.documents:
            documents._check_unique(
                conn, target.project.id, doc["source_path"], PurePosixPath(doc["source_path"]).stem
            )
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_snapshot.py -k "owned_by_another_project or naming_the_owner or refuse_before_the_prompt or two_documents_with_one_path" -v && uv run pytest tests/test_project_scope.py::test_import_checks_document_uniqueness_per_project -v` (two invocations: `-k` would deselect the node id given in the same command)
Expected: PASS (`two_documents_with_one_path` and the project-scope test pin that two documents with one path in a non-replaced target still give `ImportFormatError`).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/brd/snapshot.py tests/test_snapshot.py
git commit -m "Name the owning project when import refuses an id; refuse duplicate doc paths before asking"
```

---

### Task 4: Document backups survive a failed replace and are pruned after a successful one

**Files:**
- Modify: `src/brd/snapshot.py` — `_write` (from Task 1)
- Test: `tests/test_snapshot.py` — append three tests

**Interfaces:**
- Consumes: `_write(conn, entries, targets, replaced)` (Task 1), `documents.backup_path(conn, doc_id) -> Path`, `documents._write_backup(conn, doc_id, data: bytes) -> None`, `_board()`, `_backups()`.
- Produces: no new names; `_write` behaviour only.

- [ ] **Step 1: Write the failing tests**

Append at the end of `tests/test_snapshot.py`:

```python
def test_replace_removes_old_document_backups_after_commit(
    project, populated, tmp_path, monkeypatch
):
    d1 = populated["doc"]["id"]
    write(project, "docs/second.md", "# Second")
    d2 = ok("doc", "add", "docs/second.md")["id"]
    data = ok("export")
    entry = _entry(data)
    entry["documents"] = [d for d in entry["documents"] if d["id"] != d2]
    (d1_doc,) = entry["documents"]
    snapshot = _snapshot_file(tmp_path, data)
    keeper_root, _ = _another_project(tmp_path, monkeypatch, "keeper")
    write(keeper_root, "docs/kept.md", "# Kept")
    kept = ok("doc", "add", "docs/kept.md")["id"]
    monkeypatch.chdir(project)
    docs_dir = paths.docs_dir()

    ok("import", snapshot, "--yes")
    assert not (docs_dir / f"{d2}.md").exists()
    assert (docs_dir / f"{d1}.md").read_text() == d1_doc["content"]
    assert (docs_dir / f"{kept}.md").read_bytes() == b"# Kept"

    # An entry with no content writes no backup, so d1's old one goes too.
    del d1_doc["content"]
    ok("import", _snapshot_file(tmp_path, data, "no-content.json"), "--yes")
    assert not (docs_dir / f"{d1}.md").exists()
    assert (docs_dir / f"{kept}.md").read_bytes() == b"# Kept"


def test_failed_replace_leaves_old_state_and_backups_intact(populated, tmp_path):
    data = ok("export")
    entry = _entry(data)
    d1 = populated["doc"]["id"]
    next(d for d in entry["documents"] if d["id"] == d1)["content"] = "# Notes\nchanged"
    d9 = "d9000000-0000-4000-8000-000000000009"
    entry["documents"].append(
        {"id": d9, "title": "Nine", "source_path": "docs/nine.md", "content": "nine",
         "content_hash": "h", "created_at": T, "updated_at": T}
    )
    entry["comments"].append(
        {"id": "00000000-0000-0000-0000-000000000000", "entity_id": "does-not-exist",
         "author": "x", "body": "y", "created_at": T}
    )
    snapshot = _snapshot_file(tmp_path, data)
    before, backups = _board(), _backups()
    assert f"{d1}.md" in backups
    result = invoke("import", snapshot, "--yes")
    assert result.exit_code == 1, result.output
    error = json.loads(result.stdout)["error"]
    assert error["type"] == "ImportFormatError"
    assert "internally inconsistent" in error["message"]
    assert _backups() == backups
    assert _board() == before


def test_malformed_entity_in_a_replace_leaves_old_state_and_backups_intact(populated, tmp_path):
    data = ok("export")
    entry = _entry(data)
    next(d for d in entry["documents"])["content"] = "# Notes\nchanged"
    del entry["issues"][0]["title"]  # only the insert inside the transaction reads it
    snapshot = _snapshot_file(tmp_path, data)
    before, backups = _board(), _backups()
    result = invoke("import", snapshot, "--yes")
    assert result.exit_code == 1, result.output
    error = json.loads(result.stdout)["error"]
    assert error["type"] == "ImportFormatError"
    assert error["message"].startswith("malformed snapshot: ")
    assert _backups() == backups
    assert _board() == before
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_snapshot.py -k "old_document_backups or failed_replace_leaves or malformed_entity_in_a_replace" -v`
Expected: FAIL — `d2`'s backup still exists after the first import; in the two failure tests `d1`'s backup is missing (`_write` unlinks every backup it wrote, including the pre-existing one it overwrote).

- [ ] **Step 3: Implement**

Replace `_write` in `src/brd/snapshot.py` with:

```python
def _write(
    conn: sqlite3.Connection, entries: list[_Entry], targets: list[_Target], replaced: set[str]
) -> None:
    """One transaction: new projects, then the replaced projects' wipe, then
    every entry's entities, then every entry's edges, comments, tags and
    refs, so an edge or comment into another entry finds its target whatever
    the entry order."""
    contents = {
        d["id"]: d["content"].encode("utf-8")
        for entry in entries
        for d in entry.documents
        if d.get("content") is not None
    }
    old_doc_ids = [
        row["id"]
        for project_id in replaced
        for row in conn.execute(
            "SELECT id FROM entities WHERE project_id = ? AND kind = 'document'", (project_id,)
        )
    ]
    # Backups go first, so a DB failure never leaves a document row with no
    # backup. An incoming document may share a replaced one's id and so
    # overwrite its backup: keep those bytes to put back if anything fails.
    previous = {}
    for doc_id in contents:
        path = documents.backup_path(conn, doc_id)
        if path.exists():
            previous[doc_id] = path.read_bytes()
    try:
        for doc_id, data in contents.items():
            documents._write_backup(conn, doc_id, data)
        with conn:  # one transaction: commits on success, rolls back on error
            for target in targets:
                if target.registered:
                    db.insert_project(conn, target.project)
            for project_id in replaced:
                # The deletion `brd forget` does, keeping the project row: the
                # cascades take cards, issues, documents, comments, tags and
                # outgoing edges. Incoming edges have no foreign key and stay.
                conn.execute("DELETE FROM entities WHERE project_id = ?", (project_id,))
            for entry, target in zip(entries, targets):
                _insert_entities(conn, target.project.id, entry, contents)
            for entry in entries:
                _insert_links(conn, entry)
    except BaseException as exc:
        for doc_id in contents:
            if doc_id in previous:
                documents._write_backup(conn, doc_id, previous[doc_id])
            else:
                documents.backup_path(conn, doc_id).unlink(missing_ok=True)
        if isinstance(exc, sqlite3.IntegrityError):
            raise ImportFormatError(f"snapshot is internally inconsistent: {exc}") from exc
        raise
    # Committed: the replaced projects' old backups go, except the ones this
    # import just wrote, as if it had imported into an empty database.
    for doc_id in old_doc_ids:
        if doc_id not in contents:
            documents.backup_path(conn, doc_id).unlink(missing_ok=True)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_snapshot.py -k "old_document_backups or failed_replace_leaves or malformed_entity_in_a_replace or rolls_back_document_backup or failed_import_registers_no_project" -v`
Expected: PASS (the last two pin that backups for new ids are still removed on failure).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/brd/snapshot.py tests/test_snapshot.py
git commit -m "Restore overwritten document backups when a replacing import fails; prune stale ones after"
```

---

### Task 5: Acceptance pins — incoming edges, the project row, repo files, round trip

These tests pin spec behaviour that Tasks 1-4 already implement (D8 incoming edges, the kept project row, untouched source files, the two-machine round trip and idempotent re-import). **Expected result on first run is PASS.** If one fails, it is a bug in the Task 1-4 code it exercises: fix it there (in `src/brd/snapshot.py` or `src/brd/cli/snapshot.py`), not in the test.

**Files:**
- Test: `tests/test_snapshot.py` — extend `test_old_tree_snapshot_still_imports` (~line 131); append five tests

**Interfaces:**
- Consumes: `brd import --yes` (Task 2), report `removed` (Task 1), `_board`, `_backups` helpers, `write`, `_entry`, `_snapshot_file`, `_another_project`, `_unregistered_dir`, `_fresh_project`, `T`.
- Produces: tests only.

- [ ] **Step 1: Write the tests**

At the end of `test_old_tree_snapshot_still_imports`, after `assert err("import", snapshot) == "ProjectNotEmptyError"`, add:

```python
    assert ok("import", snapshot, "--yes")["projects"][0]["removed"]["cards"] == 2
```

Append at the end of `tests/test_snapshot.py`:

```python
def test_incoming_edges_survive_replacement_and_reconnect(project, tmp_path, monkeypatch):
    a1 = ok("add", "--title", "a1")["id"]
    b_root, _ = _another_project(tmp_path, monkeypatch, "bproj")
    b1 = ok("add", "--title", "b1")["id"]
    ok("block", b1, "--by", a1)
    ok("ref", "add", b1, a1)
    monkeypatch.chdir(project)
    ok("update", a1, "--status", "done")  # a finished blocker: b1 resolves todo
    full = ok("export")
    without = copy.deepcopy(full)
    _entry(without)["cards"] = []
    full_file = _snapshot_file(tmp_path, full, "full.json")
    without_file = _snapshot_file(tmp_path, without, "without.json")

    def b1_view():
        monkeypatch.chdir(b_root)
        shown = ok("show", b1)
        monkeypatch.chdir(project)
        return (
            [(b["id"], b["status"]) for b in shown["blockers"]],
            shown["status"],
            [r["id"] for r in shown["refs"] if r["origin"] == "explicit"],
        )

    assert b1_view() == ([(a1, "done")], "todo", [a1])
    result = ok("import", without_file, "--yes")
    assert result["projects"][0]["removed"]["cards"] == 1
    assert result["not_found_edges"] == 0  # b1's edge is not from the file
    assert b1_view() == ([(a1, "not-found")], "blocked", [a1])

    ok("import", full_file, "--yes")
    assert b1_view() == ([(a1, "done")], "todo", [a1])


def test_replace_keeps_the_project_row(populated, tmp_path):
    data = ok("export")
    _entry(data)["project"].update(name="renamed", created_at=T)
    snapshot = _snapshot_file(tmp_path, data)
    before = ok("projects")
    result = ok("import", snapshot, "--yes")
    assert ok("projects") == before
    assert result["projects"][0]["project"] == before[0]


def test_replace_never_touches_doc_source_files(project, populated, tmp_path):
    data = ok("export")
    _entry(data)["documents"].append(
        {"id": "d9000000-0000-4000-8000-000000000009", "title": "Absent",
         "source_path": "docs/absent.md", "content": "absent", "content_hash": "h",
         "created_at": T, "updated_at": T}
    )
    snapshot = _snapshot_file(tmp_path, data)
    write(project, "docs/notes.md", "local edits")
    write(project, "docs/other.md", "keep")
    ok("import", snapshot, "--yes")
    assert (project / "docs" / "notes.md").read_bytes() == b"local edits"
    assert (project / "docs" / "other.md").read_bytes() == b"keep"
    assert not (project / "docs" / "absent.md").exists()


def test_replacing_a_project_frees_its_document_paths_and_stems(populated, tmp_path, monkeypatch):
    snapshot = _snapshot_file(tmp_path, ok("export"))
    other = _fresh_project(tmp_path, monkeypatch)
    write(other, "docs/notes.md", "local")
    ok("doc", "add", "docs/notes.md")
    result = ok("import", snapshot, "--yes")
    assert result["projects"][0]["removed"]["documents"] == 1
    assert [d["id"] for d in ok("doc", "list")] == [populated["doc"]["id"]]
    assert (other / "docs" / "notes.md").read_text() == "local"


def test_round_trip_across_two_machines(project, populated, tmp_path, monkeypatch):
    a_card = populated["card"]["id"]
    _another_project(tmp_path, monkeypatch, "bproj")
    b_card = ok("add", "--title", "B card")["id"]
    b_issue = ok("issue", "open", "--title", "B issue")["id"]
    ok("block", b_card, "--by", a_card)
    monkeypatch.chdir(project)
    ok("ref", "add", a_card, b_issue)
    machine1 = ok("export", "--all")
    snapshot = _snapshot_file(tmp_path, machine1, "all.json")

    def by_id(data):
        return sorted(data["projects"], key=lambda entry: entry["project"]["id"])

    # Machine 2: an empty install; the recorded roots exist on this disk.
    _unregistered_dir(tmp_path, monkeypatch, "elsewhere", data_home="machine2")
    result = invoke("import", snapshot, "--yes")
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)["data"]
    assert [item["registered"] for item in report["projects"]] == [True, True]
    assert all(not any(item["removed"].values()) for item in report["projects"])
    assert report["not_found_edges"] == 0
    assert "replacing" not in result.stderr
    assert by_id(ok("export", "--all")) == by_id(machine1)

    # Re-importing the same file replaces both projects with themselves.
    again = ok("import", snapshot, "--yes")
    for item in again["projects"]:
        assert item["registered"] is False
        assert item["removed"] == {key: item[key] for key in ("cards", "issues", "documents", "comments")}
    assert by_id(ok("export", "--all")) == by_id(machine1)
```

- [ ] **Step 2: Run them**

Run: `uv run pytest tests/test_snapshot.py -k "old_tree_snapshot_still_imports or incoming_edges_survive or keeps_the_project_row or never_touches_doc_source or frees_its_document_paths or round_trip_across_two_machines" -v`
Expected: PASS. On a failure, debug the Task 1-4 code it exercises (superpowers:systematic-debugging), fix it there, and re-run.

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_snapshot.py
git commit -m "Pin replace behaviour: incoming edges, the project row, repo files, two-machine round trip"
```

(If Step 2 required a source fix, add that file to `git add` too.)

---

### Task 6: Help text and README

**Files:**
- Modify: `src/brd/cli/snapshot.py` — `import_cmd` docstring (from Task 2)
- Modify: `README.md:73` (the paragraph beginning "`brd import` restores a snapshot")
- Test: `tests/test_snapshot.py` — `test_import_help_describes_placement` (~line 878)

**Interfaces:**
- Consumes: `import_cmd` with `--yes` (Task 2).
- Produces: docs only.

- [ ] **Step 1: Write the failing test**

Replace `test_import_help_describes_placement` with:

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
    assert "--yes" in text
    assert "is replaced" in text
    assert "without asking" in text
    assert "Refuses, writing nothing, if a target" not in text
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_snapshot.py::test_import_help_describes_placement -v`
Expected: FAIL — `"is replaced"` is not in the help, and the old "Refuses, writing nothing, if a target" sentence is.

- [ ] **Step 3: Rewrite the help docstring**

In `src/brd/cli/snapshot.py`, replace the `import_cmd` docstring with:

```python
    """Restore a snapshot. A one-project snapshot lands in the current project,
    registering the current directory if it is not in one. A multi-project
    snapshot places each entry in the registered project with its id, else
    registers it at its recorded root; it works from any directory. A target
    project that already has entities is replaced after a y/N confirmation;
    --yes skips it, and without a terminal and without --yes import refuses,
    writing nothing."""
```

- [ ] **Step 4: Rewrite the README paragraph**

In `README.md`, replace the whole line 73 (the paragraph starting "`brd import` restores a snapshot, preserving the original ids") with:

```markdown
`brd import` restores a snapshot, preserving the original ids, content, and timestamps — including document backups (restore a missing file with `brd doc restore <id>`). A one-project snapshot lands in the current project; outside any project, the current directory is registered first (keeping the snapshot's project id when no project has it), so no `brd init` is needed. A multi-project snapshot (from `brd export --all`) places each entry in the registered project with the same id, else registers it at its recorded root path if that directory exists, and works from any directory. A target project that already has entities is replaced: import prints what it will remove and add, asks y/N, then deletes that project's cards, issues, documents and comments and loads the snapshot's in their place. `--yes` skips the question; without a terminal and without `--yes`, import refuses. Edges from other projects into a replaced project are kept: they show as not-found until their ids return, and reconnect when they do. Import never writes or deletes documents' source files in the repo; use `brd doc restore <id>` for that. So `brd export --all > board.json` on one machine and `brd import --yes board.json` on another restores every project whose root exists, with ids, hierarchy and edges intact, and re-importing a project's own export changes nothing. Import refuses, touching nothing, when an id in the snapshot belongs to a project it is not replacing, or when an entry cannot be placed. Edges to ids that are not in the database are kept and counted as not-found; importing the missing project later reconnects them. Older one-object `brd export` snapshots and `brd tree` snapshots still import.
```

- [ ] **Step 5: Run the test and the full suite**

Run: `uv run pytest tests/test_snapshot.py::test_import_help_describes_placement -v && uv run pytest -q`
Expected: PASS; full suite green.

- [ ] **Step 6: Commit**

```bash
git add src/brd/cli/snapshot.py README.md tests/test_snapshot.py
git commit -m "Document brd import --yes and project replacement in the help and README"
```

---

## Spec coverage check

| Spec item | Task |
|---|---|
| R1 order (place → validate → confirm → write) | 1 (`_load`), 2 (test 5), 3 (dup docs before prompt) |
| R2 ids of replaced projects allowed, any entry | 1 (`_validate`), 2 (test 7) |
| R2 outside ids/comments refused naming owner | 3 (test 6, updated :608/:618) |
| R2 document paths as if empty; in-entry duplicates refused | 1 (skip `_check_unique`), 3, 5 (`frees_its_document_paths`) |
| R3 summary on stderr, all modes, also with `--yes` | 2 (tests 1, 3) |
| R3 TTY prompt, y/yes, no/empty/EOF → `Aborted` | 2 (tests 1, 2) |
| R3 no TTY & no `--yes` → `ProjectNotEmptyError` with `--yes`, no "not supported yet" | 1 (test 4, updated non-empty test) |
| R3 nothing replaced → no summary, no prompt | 2 (test 14), 5 (round trip first import) |
| R4 wipe keeps project row | 1, 5 (test 9) |
| R4 incoming edges survive and reconnect | 5 (test 8) |
| R4 backups pruned on success, restored on failure | 4 (tests 10, 11, malformed) |
| R4 doc source files never touched | 5 (test 12) |
| R5 `removed`, `[replaced]`, `not_found_edges` from file only | 1 (report), 2 (test 3), 5 (test 8) |
| R6 help and README | 6 |
| Interface: `load(confirm)`, `Replacement`, `Aborted`, `_stdin_is_tty` | 1, 2 (unit test 16) |
| Round trip + idempotent re-import | 5 (test 13) |
| Verification `uv run pytest` | every task's last run step |
<!-- task-pipeline: validated -->
