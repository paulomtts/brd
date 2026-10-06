# 3.3 `brd init --relink` and `brd forget --project`

Card: `91e68a83-1567-463a-8cc2-a2781c1c3ee5`. It is the third subtask of story `4939dac5`
"One database". The milestone is `6aa7043a` "Single database and cross-project blocking".
It is blocked by 3.2 `222a1279` (resolve the project by deepest registered root, no
`.brd` marker), which is merged into this branch, as is 3.1 (everything in `brd.db`).
Sibling that runs after it: 3.4 `9da10121` (leak guard).

Parent design spec: `docs/superpowers/specs/2026-10-06-single-db-cross-project-blocking-design.md`.
It is in the main checkout (`/home/mtts/Code/brd/docs/...`), not in this branch's history.
Citations look like **[P §n Lx]**.

## Goal

A project is now a row in `brd.db` keyed by a UUID, with a `root_path` that commands match
against the cwd (3.2). Two things are missing:

1. **A moved repo loses its board.** After `mv ~/old ~/new`, nothing resolves from `~/new`,
   and `brd init` there would register a second, empty project. `brd init --relink
   <old-root-or-project-id>` points the existing project at the cwd instead.
2. **A project whose directory is gone cannot be forgotten from the cwd**, and `brd forget`
   with no argument only matches the cwd exactly, unlike every other command.
   `brd forget` now takes the cwd project (deepest root, as resolution does) or
   `--project <id>`.

## Inherited constraints

| Constraint | Source |
|---|---|
| The current project is the deepest registered `root_path` that is the cwd or an ancestor. `brd init --relink` handles moved repos. | [P D5 L35] |
| `brd init --relink <old-root-or-project-id>` sets that project's `root_path` to the cwd. Nested projects are allowed; the deepest root wins. | [P §2 L104-107] |
| `brd forget` takes the cwd project, or `--project <id>` for a project whose directory no longer exists. | [P §2 L122-123] |
| `brd forget` deletes the `projects` row, cascading everything owned. | [P §1 L95-96] |
| `projects.root_path` is `UNIQUE`; `projects.id` is a uuid4. | [P §1 L49-54] |
| Doc backups live at `$XDG_DATA_HOME/brd/docs/<doc_id>.md`. | [P §1 L45-46] |
| Edge targets carry no foreign key, so deleting an entity does not cascade to edges that point at it. | [P D6 L36], [P §1 L68-80] |
| Resolution tests include `--relink`. | [P Testing L258] |
| In this phase (single database), edge targets are still validated as same-project by code, and `delete` cleans up incoming edges explicitly "so in-board behaviour is unchanged". | [P Implementation order L276-280] |

### Notes on the parent spec

- **Incoming edges on `forget`.** [P D8 L38] and [P §1 L95-96] say `forget` does **not**
  remove incoming edges from other projects. That is the end state of phase 3 ("`forget`
  keeping incoming edges", [P L281-283]). The card says the opposite for now: "Incoming
  edges from other projects are still removed here as today; S4 changes that." This spec
  follows the card. Note that "as today" does not hold for the code on this branch: the
  `projects → entities` cascade only removes edges whose *source* is in the forgotten
  project (schema v4 has no FK on `blocked_by.blocks_on_id` / `refs.dst_id`), and
  `master.forget_project` (`src/brd/master.py:107-128`) never calls
  `db.delete_incoming_edges` (`src/brd/db.py:657-662`). B4 adds that cleanup. Through
  brd's own commands no cross-project edge can exist yet (same-project check, [P L279-280]),
  so this only matters for rows written outside those commands (tests, hand edits); it
  keeps `forget` consistent with `delete`.
- [P §2 L123] says `--project <id>` is "for a project whose directory no longer exists".
  That is the motivating case, not a precondition: `--project` works for any registered
  id, whether its directory exists or not, and from any cwd.

## Terms

- **cwd**: `Path.cwd()`, stored as `str(Path.cwd())`, the same form `brd init` stores
  (`src/brd/cli/project.py:26`).
- **old-root-or-project-id** (the `--relink` value, written *REF* below): either a project
  id, or a root path as it is stored in `projects.root_path`.
- **path-normalised REF**: `os.path.abspath(REF)` — made absolute against the cwd, `..`
  and trailing `/` removed, symlinks **not** followed (the old directory usually no longer
  exists, and stored roots are not symlink-resolved either).
- **owned entity**: a row of `entities` whose `project_id` is the project.

## Behaviour

### B1. `brd init --relink REF [--name NAME]`

Looks up the target project, in this order:

1. the project whose `id` equals REF exactly;
2. else the project whose `root_path` equals the path-normalised REF.

Then:

| Situation | Result |
|---|---|
| No project matches REF. | `ProjectNotFoundError`. Message contains REF and the hint `brd projects`. Nothing changes. |
| The target's `root_path` already equals the cwd. | Success, no change except `--name` if given. |
| Another project (different `id`) has `root_path` equal to the cwd. | `ProjectAlreadyExistsError` (new, B5). Message names the cwd and the other project's name and id. Nothing changes. |
| Otherwise. | The target's `root_path` becomes the cwd. |

On success:

- `id` and `created_at` are unchanged. Every owned entity (cards, issues, documents,
  comments, tags, edges) stays with the project; nothing is copied or re-keyed.
- `name` stays the same unless `--name NAME` is given, in which case it becomes `NAME`.
  (Plain `brd init` defaults the name to the cwd basename; `--relink` does not, because the
  project already has a name the user chose.)
- Output: the same envelope as `brd init` — `ok_envelope(dataclasses.asdict(project))`
  with the stored row after the change; `--pretty` renders as `brd init --pretty` does.
- Afterwards every command run at or below the cwd resolves to the target project (3.2
  rules), and the old root no longer resolves to it.
- Nesting is not a conflict. A cwd *below* another project's root, or *above* one, is
  fine; only an exact `root_path` match with a different project refuses. The UNIQUE
  constraint is the backstop: if the update hits it anyway (a concurrent `brd init` in the
  cwd), the result is the same `ProjectAlreadyExistsError`, never an `sqlite3.IntegrityError`
  traceback.
- The old directory may or may not still exist; `--relink` does not look at it.
- Lookup, conflict check and update happen on one connection in one transaction.

Without `--relink`, `brd init` is unchanged.

### B2. `brd forget` (no argument, no `--project`)

Forgets the **current project**: the one `master.resolve_project(conn, Path.cwd())`
returns (`src/brd/master.py:88-96`), i.e. the deepest registered root at or above the cwd.
This changes today's exact-match lookup: running `brd forget` in `repo/sub` of a project
registered at `repo` now forgets that project (today it fails with `ProjectNotFoundError`).
In a nested setup, from inside the inner project it forgets the inner one only.

No registered root at or above the cwd → `ProjectNotFoundError` with the message
`resolve_project` produces (contains the cwd and `brd init`).

### B3. `brd forget --project ID`

Forgets the project whose `id` equals ID exactly, from any cwd (registered or not), whether
or not its `root_path` still exists on disk.

Unknown ID → `ProjectNotFoundError`; the message contains ID and the hint `brd projects`.
Nothing changes.

### B4. What forgetting does (all three forms)

Applies to B2, B3 and the positional form (B6):

1. Deletes every `blocked_by` row whose `blocks_on_id` is an owned entity, and every
   `refs` row whose `dst_id` is an owned entity — including rows whose source is in
   another project (card text; see Notes).
2. Deletes the `projects` row, which cascades to every owned entity and their rows
   (cards, issues, documents, comments, tags, outgoing edges).
3. Steps 1 and 2 commit together, in one transaction. If either fails, nothing is deleted.
4. After the commit, deletes `$XDG_DATA_HOME/brd/docs/<doc_id>.md` for every document the
   project owned (ids read before the delete). A missing backup file is not an error.
   Backups of other projects' documents are untouched.
5. Other projects' rows are otherwise untouched. A card in another project that was
   blocked by an entity of the forgotten project loses that `blocked_by` row and so is no
   longer blocked by it.
6. Output: `ok_envelope(dataclasses.asdict(project))` of the forgotten project, as today.

### B5. New error

`ProjectAlreadyExistsError(BrdError)` in `src/brd/errors.py`, one-line `pass` body like the
others (`CardAlreadyExistsError`, `EntityAlreadyExistsError`). The CLI turns it into an
error envelope with exit 1 through `fail()` (`src/brd/cli/_app.py:60-62`).

### B6. Positional path and option conflicts

- `brd forget PATH` keeps today's behaviour: exact match of `str(PATH)` against
  `root_path` (`tests/test_cli.py:144` keeps passing), with B4's effects.
- `brd forget PATH --project ID` is refused before anything is looked up: error envelope
  with type `UsageError` and a message saying to give either a path or `--project`, exit 1.
  This follows `purge`'s precedent of building an envelope directly
  (`src/brd/cli/project.py:75-78`). Nothing changes.
- `--relink` and `--name` combine (B1). There is no other new flag combination.

### B7. Help text and README

- `brd init --help` documents `--relink` as pointing an existing project (by id or old
  root path) at the current directory.
- `brd forget --help` documents `--project` as forgetting a project by id, e.g. one whose
  directory is gone; the command docstring says it forgets the current project by default.
- `README.md` "Storage" (`README.md:38-50`) gains one or two sentences: after moving a
  repo, run `brd init --relink <old-path-or-id>` in the new location; `brd forget
  --project <id>` removes a project whose directory is gone (ids from `brd projects`).

## Error paths

| Condition | Result |
|---|---|
| `init --relink REF`, REF matches no id and no path-normalised root | `ProjectNotFoundError` envelope, exit 1, message has REF and `brd projects`; `projects` unchanged. |
| `init --relink REF`, cwd is the root of a different project | `ProjectAlreadyExistsError` envelope, exit 1, message has cwd, other project's name and id; `projects` unchanged. |
| `init --relink ""` | Matches nothing → `ProjectNotFoundError` (no crash). |
| `forget` with no registered root at or above cwd | `ProjectNotFoundError` envelope, exit 1. |
| `forget --project ID`, unknown ID | `ProjectNotFoundError` envelope, exit 1, message has ID; nothing deleted. |
| `forget PATH --project ID` | `UsageError` envelope, exit 1; nothing deleted. |
| Unmigrated install with a failing migration | Unchanged from 3.1: `MigrationError` envelope from `connect()` before any lookup. |

## Interfaces the plan should produce

SQL stays in `src/brd/db.py`; `src/brd/master.py` orchestrates (3.2 convention). Suggested
shapes, which the planner may adjust as long as behaviour holds:

- `db.get_project_by_id(conn, project_id: str) -> Project | None`
- `db.relink_project(conn, project_id: str, root_path: str, name: str | None) -> Project`
  (no commit, or commit — but the conflict check and update must be one transaction)
- `db.delete_project` keyed by project id, deleting incoming edges of owned entities and
  the row in one transaction (today it takes `root_path` and commits by itself,
  `src/brd/db.py:524-526`).
- `master.relink_project(root_path: Path, ref: str, name: str | None = None) -> Project`
- `master.forget_project(root_path: Path) -> Project` (exact match, unchanged signature),
  `master.forget_current_project(cwd: Path) -> Project`,
  `master.forget_project_by_id(project_id: str) -> Project`, all sharing one private
  helper that does B4.

## Tests

Run with `uv run pytest`. Tests are flat in `tests/`; there are three tiers by file:

- **DB unit** (`tests/test_db.py`): a `brd.db` connection and the `db` helpers directly.
  Right for SQL-level guarantees (atomicity, cascade, edge cleanup) because a failure
  points at one statement.
- **Domain** (`tests/test_master.py`): `master.*` against a real `brd.db` under `tmp_path`
  (`XDG_DATA_HOME` monkeypatched), seeding with `tests/factories.py` (`make_card`,
  `make_issue`, `make_document`, `add_project`, `OTHER_PROJECT`). Right for behaviour rules
  that don't depend on argument parsing: lookup order, conflict rules, what is deleted.
- **CLI** (`tests/test_cli.py`, `isolated_env` fixture and `tests/cli_helpers.py`
  `ok`/`err`/`invoke`): right for what a user sees — option wiring, envelopes, exit codes,
  and resolution after a relink through `open_project`.

### New

| # | Test | Tier | Why this tier |
|---|---|---|---|
| T1 | `relink_project` by old root: project at `old/` with a card; relink from `new/` → returned project has `root_path == str(new)`, same `id`, `created_at`, `name`; the card's `entities.project_id` is unchanged; one `projects` row. | Domain | B1 core rule (card) |
| T2 | `relink_project` by project id (old directory deleted with `shutil.rmtree`) → same result as T1. | Domain | B1 lookup step 1 (card: "old-root-or-project-id") |
| T3 | Relink by old root written with a trailing `/` and with a `..` segment still finds the project. | Domain | Path normalisation of REF |
| T4 | Relink with `name="renamed"` changes the name; without it the old name is kept even though `new/`'s basename differs. | Domain | B1 name rule |
| T5 | Relink when the target's root already equals the cwd → returns the project unchanged, no error. | Domain | B1 no-op row |
| T6 | Relink unknown REF (random uuid, and a path never registered) → `ProjectNotFoundError` whose message contains REF; `projects` rows unchanged. | Domain | B1 error row (card: "unknown id") |
| T7 | Relink when the cwd is the root of a different registered project → `ProjectAlreadyExistsError`, message contains the other project's id; both rows unchanged. | Domain | B1 refusal (card) |
| T8 | Relink to a cwd nested inside another project's root (`outer/` registered, relink target into `outer/inner/`) succeeds; `resolve_project` from `outer/inner/x` gives the relinked project, from `outer/y` gives the outer one. | Domain | Nesting is not a conflict [P L107] |
| T9 | `db.relink_project` hitting the UNIQUE constraint (call it directly with a root another row has, bypassing the pre-check if the shape allows, or simulate with a second connection inserting first) raises `ProjectAlreadyExistsError`, not `sqlite3.IntegrityError`; rows unchanged. | DB unit | Race backstop in B1 |
| T10 | `forget_project_by_id` removes the row, its cards/issues/documents/comments/tags, and its doc backups; another project's rows and backups remain. | Domain | B3 + B4 (card) |
| T11 | `forget_project_by_id` works after the root directory is deleted and from a cwd that is not registered. | Domain | [P L122-123] motivating case |
| T12 | `forget_project_by_id` with an unknown id → `ProjectNotFoundError` with the id in the message; nothing deleted. | Domain | B3 error (card: "unknown id") |
| T13 | Incoming edges: project B's card `b1` blocked by A's card `a1` and with an explicit ref to `a1` (raw rows via factories / `INSERT`); forget A → no `blocked_by` row with `blocks_on_id = 'a1'` and no `refs` row with `dst_id = 'a1'`; `b1` itself and its other edges remain; `b1` resolves to `todo`. | Domain | B4 step 1 (card). Fails on the current code. |
| T14 | `forget_current_project` from `repo/sub/deeper` forgets the project at `repo`; from inside a nested `repo/inner` forgets only `inner`. | Domain | B2 deepest-root rule |
| T15 | Edge cleanup and project delete are atomic: make the project delete fail after edge deletion (e.g. a temporary `BEFORE DELETE ON projects` trigger that raises) → the incoming edges are still there afterwards. | DB unit | B4 step 3 |
| T16 | CLI: `init` in `old/`, `add` a card, rename `old/` → `new/`, `chdir(new)`, `brd init --relink <old>` → ok envelope with `root_path == str(new)` and same id; `brd list` in `new/` shows the card. Repeat via id. | CLI | User-visible relink and resolution through `open_project` [P L258] |
| T17 | CLI: `brd init --relink <unknown-uuid>` → `err(...) == "ProjectNotFoundError"`. | CLI | Envelope type for unknown id (card) |
| T18 | CLI: two projects `a/` and `b/`; in `b/`, `brd init --relink <a's id>` → `err(...) == "ProjectAlreadyExistsError"`; `brd projects` unchanged. | CLI | Envelope type for the refusal |
| T19 | CLI: `brd forget --project <id>` from an unregistered `tmp_path` after deleting the repo dir → ok envelope with that id; `brd projects` is empty. | CLI | B3 wiring |
| T20 | CLI: `brd forget --project <unknown-uuid>` → `err(...) == "ProjectNotFoundError"`. | CLI | B3 error envelope (card) |
| T21 | CLI: `brd forget` from `repo/sub` forgets the project at `repo`. | CLI | B2 as the user sees it |
| T22 | CLI: `brd forget <path> --project <id>` → `err(...) == "UsageError"`; the project is still registered. | CLI | B6 conflict |
| T23 | CLI: `brd init --help` mentions `--relink`; `brd forget --help` mentions `--project`. | CLI | B7 |

### Kept unchanged

`test_forget_removes_current_project`, `test_forget_accepts_explicit_path_argument`,
`test_forget_errors_when_not_registered`, `test_forget_pretty_flag_switches_off_json`
(`tests/test_cli.py:126-171`) and the `forget_project` / init tests in
`tests/test_master.py` (`:89-168`, `:212-231`, `:321-330`, `:500-530`) must keep passing.
`test_forget_errors_when_not_registered` only checks the error type, so the changed
message from B2 does not affect it.

## Out of scope

- `forget` keeping incoming edges as `not-found`, cross-project edge targets, `blockers`
  output — phase 3 ("S4" in the card) [P L281-283].
- The leak guard — sibling 3.4 `9da10121`.
- Export/import placement, `--all`, replacement — phase 4 [P §5].
- A confirmation prompt for `forget`; changing `purge`.
- Relinking automatically (detecting a moved repo without `--relink`), or relinking from
  a subdirectory of the new root to its ancestor.
- Changing how `brd projects` or plain `brd init` behave.

---

# 3.3 `brd init --relink` and `brd forget --project` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a moved repo get its board back with `brd init --relink <old-root-or-id>`, and let `brd forget` take the cwd project (deepest root) or `--project <id>`, removing incoming edges of the forgotten project's entities.

**Architecture:** SQL lives in `src/brd/db.py` (`get_project_by_id`, `relink_project`, `delete_project` keyed by id with incoming-edge cleanup in one transaction). `src/brd/master.py` orchestrates: `relink_project` runs lookup + update inside one `BEGIN IMMEDIATE` transaction; the three forget entry points share one private `_forget` helper. The CLI (`src/brd/cli/project.py`) wires `--relink` on `init` and `--project` on `forget`.

**Tech Stack:** Python ≥3.12, stdlib `sqlite3`, Typer, pytest (run with `uv run pytest`).

**Spec:** `docs/superpowers/specs/3-3-brd-init-relink-and-91e68a83.md` (reproduced in full above).

## Global Constraints

- SQL stays in `src/brd/db.py`; `src/brd/master.py` orchestrates (3.2 convention).
- `projects.root_path` is `UNIQUE`; `projects.id` is a uuid4; `id` and `created_at` never change on relink.
- Path-normalised REF = `os.path.abspath(REF)` semantics (absolute against the cwd, `..` and trailing `/` removed, symlinks **not** followed).
- `ProjectAlreadyExistsError(BrdError)` in `src/brd/errors.py`, one-line `pass` body.
- Forget = delete incoming `blocked_by`/`refs` rows of owned entities + delete the `projects` row, in **one transaction**; doc backups `$XDG_DATA_HOME/brd/docs/<doc_id>.md` removed after the commit, missing file is not an error.
- Output envelopes: `ok_envelope(dataclasses.asdict(project))` for both `init --relink` and `forget`; errors go through `fail()` (exit 1); `forget PATH --project ID` → `UsageError` envelope built directly, exit 1.
- Plain `brd init`, `brd projects`, `brd purge` and `brd forget PATH` behave as before.

## Review Focus

1. `brd init --relink ""` — `os.path.abspath("")` is the cwd, so a naive lookup would "relink" the cwd's own project; a person expects `ProjectNotFoundError`. Pinned in Task 2 (`test_relink_project_with_empty_ref_is_not_found`).
2. A relative REF such as `../old` typed from the new directory — a person expects it to be read against the cwd. Pinned in Task 2 (`test_relink_project_accepts_a_relative_old_root`).
3. A refused relink (conflict) must leave no write transaction or half-applied update behind, so the very next command works. Pinned in Task 2 (`test_relink_project_refusal_leaves_the_database_writable`).
4. `brd init --relink X --pretty` — a person expects the same human-readable output as `brd init --pretty`, not JSON. Pinned in Task 4 (`test_init_relink_pretty_flag_switches_off_json`).
5. `brd forget --project <root-path>` (a path passed where an id is expected) — a person expects "not found" and nothing deleted, not a path match. Pinned in Task 3 (`test_forget_project_by_id_does_not_match_a_root_path`).

## File Structure

- `src/brd/errors.py` — add `ProjectAlreadyExistsError`.
- `src/brd/db.py` — add `get_project_by_id`, `relink_project`; change `delete_project` to take a project id and clean up incoming edges in one transaction.
- `src/brd/master.py` — add `relink_project`, `_find_relink_target`, `_forget`, `forget_current_project`, `forget_project_by_id`; rewrite `forget_project` on `_forget`.
- `src/brd/cli/project.py` — `init --relink`, `forget --project`, default `forget` via deepest root, path/`--project` conflict.
- `README.md` — two sentences in "Storage".
- Tests: `tests/test_db.py`, `tests/test_master.py`, `tests/test_cli.py`.

---

### Task 1: DB layer — error type, `get_project_by_id`, `relink_project`, `delete_project` by id

**Files:**
- Modify: `src/brd/errors.py` (after `ProjectNotFoundError`, line 5-6)
- Modify: `src/brd/db.py:1-7` (imports), `src/brd/db.py:505-526` (`get_project` … `delete_project`)
- Modify: `src/brd/master.py:121` (the one caller of `db.delete_project`)
- Test: `tests/test_db.py` (replace the three `test_delete_project_*` tests at lines 420-445; add new tests after them)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `brd.errors.ProjectAlreadyExistsError(BrdError)`
  - `db.get_project_by_id(conn: sqlite3.Connection, project_id: str) -> Project | None`
  - `db.relink_project(conn: sqlite3.Connection, project_id: str, root_path: str, name: str | None) -> Project` — no commit; raises `ProjectAlreadyExistsError` (message has `root_path`, the other project's name and id) when another project is at `root_path`.
  - `db.delete_project(conn: sqlite3.Connection, project_id: str) -> None` — commits; deletes incoming `blocked_by`/`refs` rows of the project's entities and the `projects` row in one transaction.

- [ ] **Step 1: Write the failing tests**

In `tests/test_db.py`, add `ProjectAlreadyExistsError` to the imports at the top:

```python
from brd import db
from brd.errors import ProjectAlreadyExistsError
from brd.models import Card, Project
```

Then **delete** these three existing tests (lines 420-445): `test_delete_project_removes_matching_row`, `test_delete_project_is_a_noop_when_absent`, `test_delete_project_commits_so_another_connection_sees_it` (they call `delete_project` with a root path on a projects-only schema; the new signature takes an id and needs the full schema). The `project_conn` fixture they are replaced by is defined further down the file (line 448), which pytest resolves fine, so put the new tests **after** the `project_conn` fixture definition, i.e. right after it and before `_sample_card`:

```python
def _project_ids(conn):
    return {row["id"] for row in conn.execute("SELECT id FROM projects")}


def _blocked_by_rows(conn):
    return set(map(tuple, conn.execute("SELECT card_id, blocks_on_id FROM blocked_by")))


def _ref_rows(conn):
    return set(map(tuple, conn.execute("SELECT src_id, dst_id FROM refs")))


def _add_ref(conn, src_id, dst_id):
    conn.execute(
        "INSERT INTO refs (src_id, dst_id, origin) VALUES (?, ?, 'explicit')", (src_id, dst_id)
    )
    conn.commit()


def test_get_project_by_id_returns_matching_project(project_conn):
    add_project(project_conn, OTHER_PROJECT)
    assert db.get_project_by_id(project_conn, OTHER_PROJECT.id) == OTHER_PROJECT


def test_get_project_by_id_returns_none_when_absent(project_conn):
    assert db.get_project_by_id(project_conn, "nope") is None
    assert db.get_project_by_id(project_conn, PROJECT.root_path) is None


def test_relink_project_moves_the_root_and_keeps_id_name_and_created_at(project_conn):
    relinked = db.relink_project(project_conn, PROJECT.id, "/moved", None)
    assert relinked == Project(PROJECT.id, PROJECT.name, "/moved", PROJECT.created_at)
    assert db.get_project(project_conn, PROJECT.root_path) is None


def test_relink_project_renames_when_name_given(project_conn):
    relinked = db.relink_project(project_conn, PROJECT.id, "/moved", "renamed")
    assert relinked.name == "renamed"


def test_relink_project_does_not_commit(project_conn):
    db.relink_project(project_conn, PROJECT.id, "/moved", None)
    assert project_conn.in_transaction
    project_conn.rollback()
    assert db.get_project_by_id(project_conn, PROJECT.id) == PROJECT


def test_relink_project_onto_another_projects_root_raises_already_exists(project_conn):
    add_project(project_conn, OTHER_PROJECT)

    with pytest.raises(ProjectAlreadyExistsError) as excinfo:
        db.relink_project(project_conn, PROJECT.id, OTHER_PROJECT.root_path, None)

    message = str(excinfo.value)
    assert OTHER_PROJECT.root_path in message
    assert OTHER_PROJECT.name in message
    assert OTHER_PROJECT.id in message
    project_conn.rollback()
    assert sorted(db.list_projects(project_conn), key=lambda p: p.id) == [
        PROJECT,
        OTHER_PROJECT,
    ]


def test_delete_project_removes_the_row_and_everything_it_owns(project_conn):
    add_project(project_conn, OTHER_PROJECT)
    make_card(project_conn, "c1")
    make_card(project_conn, "o1", project_id=OTHER_PROJECT.id)

    db.delete_project(project_conn, PROJECT.id)

    assert _project_ids(project_conn) == {OTHER_PROJECT.id}
    assert [row["id"] for row in project_conn.execute("SELECT id FROM cards")] == ["o1"]
    assert [row["id"] for row in project_conn.execute("SELECT id FROM entities")] == ["o1"]


def test_delete_project_removes_incoming_edges_from_other_projects(project_conn):
    add_project(project_conn, OTHER_PROJECT)
    make_card(project_conn, "a1")
    make_card(project_conn, "b1", project_id=OTHER_PROJECT.id)
    make_card(project_conn, "b2", project_id=OTHER_PROJECT.id)
    db.add_blocked_by_edge(project_conn, "b1", "a1")
    db.add_blocked_by_edge(project_conn, "b1", "b2")
    _add_ref(project_conn, "b1", "a1")
    _add_ref(project_conn, "b1", "b2")

    db.delete_project(project_conn, PROJECT.id)

    assert _blocked_by_rows(project_conn) == {("b1", "b2")}
    assert _ref_rows(project_conn) == {("b1", "b2")}


def test_delete_project_is_a_noop_when_absent(project_conn):
    db.delete_project(project_conn, "nope")
    assert _project_ids(project_conn) == {PROJECT.id}


def test_delete_project_commits_so_another_connection_sees_it(tmp_path, project_conn):
    db.delete_project(project_conn, PROJECT.id)
    reader = db.connect(tmp_path / "project.db")
    try:
        assert db.list_projects(reader) == []
    finally:
        reader.close()


def test_delete_project_keeps_incoming_edges_when_the_project_delete_fails(project_conn):
    add_project(project_conn, OTHER_PROJECT)
    make_card(project_conn, "a1")
    make_card(project_conn, "b1", project_id=OTHER_PROJECT.id)
    db.add_blocked_by_edge(project_conn, "b1", "a1")
    _add_ref(project_conn, "b1", "a1")
    project_conn.execute(
        "CREATE TEMP TRIGGER refuse_project_delete BEFORE DELETE ON projects "
        "BEGIN SELECT RAISE(ABORT, 'refused'); END"
    )

    with pytest.raises(sqlite3.DatabaseError):
        db.delete_project(project_conn, PROJECT.id)

    assert not project_conn.in_transaction
    assert _blocked_by_rows(project_conn) == {("b1", "a1")}
    assert _ref_rows(project_conn) == {("b1", "a1")}
    assert _project_ids(project_conn) == {PROJECT.id, OTHER_PROJECT.id}
```

(`Project` is a plain `@dataclass`, not hashable, so compare sorted lists; `PROJECT.id` `1111…` sorts before `OTHER_PROJECT.id` `2222…`.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_db.py -q`
Expected: collection error `ImportError: cannot import name 'ProjectAlreadyExistsError' from 'brd.errors'`.

- [ ] **Step 3: Add the error type**

In `src/brd/errors.py`, right after `ProjectNotFoundError`:

```python
class ProjectAlreadyExistsError(BrdError):
    pass
```

- [ ] **Step 4: Run the tests again**

Run: `uv run pytest tests/test_db.py -q`
Expected: FAIL — `AttributeError: module 'brd.db' has no attribute 'get_project_by_id'` / `'relink_project'`, and the delete tests fail (old `delete_project` matches `root_path`, so passing an id deletes nothing; the incoming-edge test keeps `("b1", "a1")`).

- [ ] **Step 5: Implement the db functions**

In `src/brd/db.py`, change the errors import (line 6):

```python
from brd.errors import MigrationError, ProjectAlreadyExistsError
```

Add after `get_project` (currently ending at line 509):

```python
def get_project_by_id(conn: sqlite3.Connection, project_id: str) -> Project | None:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return _row_to_project(row) if row else None


def relink_project(
    conn: sqlite3.Connection, project_id: str, root_path: str, name: str | None
) -> Project:
    """Point project_id at root_path, renaming it when name is given; id and
    created_at stay. No commit: the caller's transaction covers its lookup
    and this update. The UNIQUE root_path is the conflict check."""
    try:
        conn.execute(
            "UPDATE projects SET root_path = ?, name = COALESCE(?, name) WHERE id = ?",
            (root_path, name, project_id),
        )
    except sqlite3.IntegrityError:
        other = get_project(conn, root_path)
        if other is None:
            raise
        raise ProjectAlreadyExistsError(
            f"{root_path} is already the root of project {other.name} ({other.id})"
        ) from None
    return get_project_by_id(conn, project_id)
```

Replace `delete_project` (lines 524-526) with:

```python
def delete_project(conn: sqlite3.Connection, project_id: str) -> None:
    """Delete the project and, through the cascade, everything it owns. Edges
    from other projects that point at its entities have no foreign key to
    cascade through, so they go explicitly, in the same transaction."""
    owned = "SELECT id FROM entities WHERE project_id = ?"
    with conn:
        conn.execute(f"DELETE FROM blocked_by WHERE blocks_on_id IN ({owned})", (project_id,))
        conn.execute(f"DELETE FROM refs WHERE dst_id IN ({owned})", (project_id,))
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
```

In `src/brd/master.py` line 121, change the caller:

```python
        db.delete_project(conn, project.id)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_db.py tests/test_master.py tests/test_cli.py -q`
Expected: PASS (all).

- [ ] **Step 7: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS (all).

- [ ] **Step 8: Commit**

```bash
git add src/brd/errors.py src/brd/db.py src/brd/master.py tests/test_db.py
git commit -m "Key project deletion by id and remove incoming edges with it"
```

---

### Task 2: `master.relink_project`

**Files:**
- Modify: `src/brd/master.py` (imports at top; new functions after `resolve_project`, line 96)
- Test: `tests/test_master.py` (imports at top; new tests appended at the end of the file)

**Interfaces:**
- Consumes: `db.get_project_by_id(conn, project_id) -> Project | None`, `db.get_project(conn, root_path: str) -> Project | None`, `db.relink_project(conn, project_id, root_path: str, name: str | None) -> Project` (no commit; raises `ProjectAlreadyExistsError`), `brd.errors.ProjectAlreadyExistsError`.
- Produces: `master.relink_project(root_path: Path, ref: str, name: str | None = None) -> Project` — raises `ProjectNotFoundError` (message contains `ref` and `brd projects`) or `ProjectAlreadyExistsError`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_master.py`, extend the imports at the top so they read:

```python
import shutil
import uuid

import pytest

from brd import db, master, paths
from brd.errors import ProjectAlreadyExistsError, ProjectNotFoundError
from brd.models import Project
from tests.factories import PROJECT, make_card, make_document
```

Append at the end of the file (it already defines `_brd`, `_card_owner`, `_resolve`, `_not_found`):

```python
def _moved_repo(tmp_path, monkeypatch):
    """A project registered at old/ with one card, and an empty new/."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    project = master.init_project(old)
    conn = _brd()
    try:
        make_card(conn, "c1", title="Moved card", project_id=project.id)
    finally:
        conn.close()
    return project, old, new


def test_relink_project_by_old_root_points_the_project_at_the_new_root(
    tmp_path, monkeypatch
):
    project, old, new = _moved_repo(tmp_path, monkeypatch)

    relinked = master.relink_project(new, str(old))

    assert relinked == Project(project.id, project.name, str(new), project.created_at)
    assert master.list_all_projects() == [relinked]
    assert _card_owner("c1") == ("Moved card", project.id)
    assert _resolve(new / "sub") == relinked
    with pytest.raises(ProjectNotFoundError):
        _resolve(old)


def test_relink_project_by_id_after_the_old_directory_is_gone(tmp_path, monkeypatch):
    project, old, new = _moved_repo(tmp_path, monkeypatch)
    shutil.rmtree(old)

    relinked = master.relink_project(new, project.id)

    assert relinked == Project(project.id, project.name, str(new), project.created_at)
    assert master.list_all_projects() == [relinked]
    assert _card_owner("c1") == ("Moved card", project.id)


@pytest.mark.parametrize("spelling", ["{old}/", "{old}/../old", "{old}/./"])
def test_relink_project_normalises_the_old_root(tmp_path, monkeypatch, spelling):
    project, old, new = _moved_repo(tmp_path, monkeypatch)

    relinked = master.relink_project(new, spelling.format(old=old))

    assert (relinked.id, relinked.root_path) == (project.id, str(new))


def test_relink_project_accepts_a_relative_old_root(tmp_path, monkeypatch):
    project, old, new = _moved_repo(tmp_path, monkeypatch)

    relinked = master.relink_project(new, "../old")

    assert (relinked.id, relinked.root_path) == (project.id, str(new))


def test_relink_project_keeps_the_name_unless_one_is_given(tmp_path, monkeypatch):
    project, old, new = _moved_repo(tmp_path, monkeypatch)

    kept = master.relink_project(new, str(old))
    assert kept.name == "old"

    renamed = master.relink_project(new, project.id, name="renamed")
    assert renamed.name == "renamed"
    assert renamed.root_path == str(new)


def test_relink_project_already_at_the_cwd_changes_nothing(tmp_path, monkeypatch):
    project, old, new = _moved_repo(tmp_path, monkeypatch)

    assert master.relink_project(old, str(old)) == project
    assert master.relink_project(old, project.id) == project
    assert master.list_all_projects() == [project]


@pytest.mark.parametrize("ref", [str(uuid.uuid4()), "/never/registered"])
def test_relink_project_with_an_unknown_ref_is_not_found(tmp_path, monkeypatch, ref):
    project, old, new = _moved_repo(tmp_path, monkeypatch)

    with pytest.raises(ProjectNotFoundError) as excinfo:
        master.relink_project(new, ref)

    assert ref in str(excinfo.value)
    assert "brd projects" in str(excinfo.value)
    assert master.list_all_projects() == [project]


def test_relink_project_with_empty_ref_is_not_found(tmp_path, monkeypatch):
    # "" normalises to the cwd itself; it must not match the cwd's project.
    project, old, new = _moved_repo(tmp_path, monkeypatch)

    with pytest.raises(ProjectNotFoundError):
        master.relink_project(old, "")

    assert master.list_all_projects() == [project]


def test_relink_project_onto_another_projects_root_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    project_a = master.init_project(a)
    project_b = master.init_project(b)

    with pytest.raises(ProjectAlreadyExistsError) as excinfo:
        master.relink_project(b, project_a.id)

    message = str(excinfo.value)
    assert str(b) in message
    assert project_b.name in message
    assert project_b.id in message
    assert sorted(master.list_all_projects(), key=lambda p: p.id) == sorted(
        [project_a, project_b], key=lambda p: p.id
    )


def test_relink_project_refusal_leaves_the_database_writable(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    a = tmp_path / "a"
    b = tmp_path / "b"
    c = tmp_path / "c"
    for d in (a, b, c):
        d.mkdir()
    project_a = master.init_project(a)
    master.init_project(b)
    with pytest.raises(ProjectAlreadyExistsError):
        master.relink_project(b, project_a.id)

    # A lock or a half-applied update left behind would show up here.
    project_c = master.init_project(c)

    assert {p.root_path for p in master.list_all_projects()} == {str(a), str(b), str(c)}
    assert _resolve(c) == project_c
    assert _resolve(a) == project_a


def test_relink_project_into_another_projects_tree_nests_it(tmp_path, monkeypatch):
    project, old, new = _moved_repo(tmp_path, monkeypatch)
    outer = tmp_path / "outer"
    inner = outer / "inner"
    (inner / "x").mkdir(parents=True)
    (outer / "y").mkdir()
    outer_project = master.init_project(outer)

    relinked = master.relink_project(inner, str(old))

    assert relinked.id == project.id
    assert _resolve(inner / "x") == relinked
    assert _resolve(outer / "y") == outer_project
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_master.py -q -k relink`
Expected: FAIL — `AttributeError: module 'brd.master' has no attribute 'relink_project'`.

- [ ] **Step 3: Implement**

In `src/brd/master.py`, add `import os` to the top imports (alphabetical, before `import shutil`):

```python
import os
import shutil
import sqlite3
```

Add right after `resolve_project` (after line 96):

```python
def relink_project(root_path: Path, ref: str, name: str | None = None) -> Project:
    """Point the project whose id or old root is ref at root_path, e.g. after
    the repo moved. Its id, created_at and board stay; the name changes only
    when name is given."""
    conn = connect()
    try:
        # IMMEDIATE takes the write lock up front, so the lookup and the
        # update see one state of projects.
        conn.execute("BEGIN IMMEDIATE")
        try:
            project = _find_relink_target(conn, root_path, ref)
            relinked = db.relink_project(conn, project.id, str(root_path), name or None)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        return relinked
    finally:
        conn.close()


def _find_relink_target(conn: sqlite3.Connection, root_path: Path, ref: str) -> Project:
    project = db.get_project_by_id(conn, ref)
    # An empty ref would normalise to root_path itself.
    if project is None and ref:
        # Not resolve(): the old directory is usually gone, and stored roots
        # do not follow symlinks either.
        old_root = os.path.normpath(os.path.join(root_path, ref))
        project = db.get_project(conn, old_root)
    if project is None:
        raise ProjectNotFoundError(
            f"no project with id or root path {ref}; see `brd projects`"
        )
    return project
```

(`os.path.join(root_path, ref)` returns `ref` unchanged when it is absolute, and reads it against `root_path` — the cwd the CLI passes — when it is relative; `normpath` drops `..`, `.` and a trailing `/`. Together that is `os.path.abspath(ref)` evaluated in `root_path`.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_master.py -q`
Expected: PASS (all, including the pre-existing ones).

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/brd/master.py tests/test_master.py
git commit -m "Relink a moved project to a new root by id or old root"
```

---

### Task 3: forget by deepest root and by id, sharing one helper

**Files:**
- Modify: `src/brd/master.py:107-128` (`forget_project`)
- Test: `tests/test_master.py` (imports; new tests appended at the end)

**Interfaces:**
- Consumes: `db.delete_project(conn, project_id: str) -> None` (Task 1), `db.get_project_by_id` (Task 1), `master.resolve_project(conn, start: Path) -> Project` (exists).
- Produces:
  - `master.forget_project(root_path: Path) -> Project` — unchanged signature and behaviour (exact `root_path` match, message `no registered project at {root_path}`).
  - `master.forget_current_project(cwd: Path) -> Project` — deepest registered root at or above `cwd`; not found → `resolve_project`'s `ProjectNotFoundError`.
  - `master.forget_project_by_id(project_id: str) -> Project` — exact id; not found → `ProjectNotFoundError` whose message contains the id and `brd projects`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_master.py`, extend the imports so they read:

```python
from brd import core, db, master, paths
from brd.errors import ProjectAlreadyExistsError, ProjectNotFoundError
from brd.models import Project
from tests.factories import PROJECT, make_card, make_document, make_issue
```

Append at the end of the file:

```python
def _two_projects(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    return master.init_project(a), master.init_project(b)


def _count(sql, *params):
    conn = _brd()
    try:
        return conn.execute(sql, params).fetchone()[0]
    finally:
        conn.close()


def test_forget_project_by_id_removes_what_it_owns_and_nothing_else(tmp_path, monkeypatch):
    project_a, project_b = _two_projects(tmp_path, monkeypatch)
    conn = _brd()
    try:
        make_card(conn, "ca", project_id=project_a.id)
        make_issue(conn, "ia", project_id=project_a.id)
        make_document(conn, "da", "a-notes", content="a", project_id=project_a.id)
        make_card(conn, "cb", project_id=project_b.id)
        make_document(conn, "db", "b-notes", content="b", project_id=project_b.id)
        with conn:
            for entity_id in ("ca", "cb"):
                conn.execute(
                    "INSERT INTO comments (id, entity_id, author, body, created_at) "
                    "VALUES (?, ?, 'me', 'hi', 'now')",
                    (f"cm-{entity_id}", entity_id),
                )
                conn.execute(
                    "INSERT INTO tags (entity_id, tag) VALUES (?, 'x')", (entity_id,)
                )
    finally:
        conn.close()

    assert master.forget_project_by_id(project_a.id) == project_a

    assert master.list_all_projects() == [project_b]
    assert _count("SELECT COUNT(*) FROM entities WHERE project_id = ?", project_a.id) == 0
    for table in ("cards", "issues", "documents"):
        assert _count(f"SELECT COUNT(*) FROM {table} WHERE id IN ('ca', 'ia', 'da')") == 0
    assert _count("SELECT COUNT(*) FROM comments WHERE entity_id = 'ca'") == 0
    assert _count("SELECT COUNT(*) FROM tags WHERE entity_id = 'ca'") == 0
    assert not (paths.docs_dir() / "da.md").exists()
    assert _count("SELECT COUNT(*) FROM entities WHERE project_id = ?", project_b.id) == 2
    assert _count("SELECT COUNT(*) FROM comments WHERE entity_id = 'cb'") == 1
    assert _count("SELECT COUNT(*) FROM tags WHERE entity_id = 'cb'") == 1
    assert (paths.docs_dir() / "db.md").read_text() == "b"


def test_forget_project_by_id_works_when_the_root_is_gone_and_cwd_is_unregistered(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    elsewhere = tmp_path / "elsewhere"
    repo.mkdir()
    elsewhere.mkdir()
    project = master.init_project(repo)
    shutil.rmtree(repo)
    monkeypatch.chdir(elsewhere)

    assert master.forget_project_by_id(project.id) == project
    assert master.list_all_projects() == []


def test_forget_project_by_id_with_an_unknown_id_is_not_found(tmp_path, monkeypatch):
    project_a, project_b = _two_projects(tmp_path, monkeypatch)
    unknown = str(uuid.uuid4())

    with pytest.raises(ProjectNotFoundError) as excinfo:
        master.forget_project_by_id(unknown)

    assert unknown in str(excinfo.value)
    assert "brd projects" in str(excinfo.value)
    assert len(master.list_all_projects()) == 2


def test_forget_project_by_id_does_not_match_a_root_path(tmp_path, monkeypatch):
    project_a, project_b = _two_projects(tmp_path, monkeypatch)

    with pytest.raises(ProjectNotFoundError):
        master.forget_project_by_id(project_a.root_path)

    assert len(master.list_all_projects()) == 2


def test_forgetting_a_project_removes_edges_other_projects_point_at_it(
    tmp_path, monkeypatch
):
    project_a, project_b = _two_projects(tmp_path, monkeypatch)
    conn = _brd()
    try:
        make_card(conn, "a1", project_id=project_a.id)
        make_card(conn, "b1", project_id=project_b.id)
        make_card(conn, "b2", status="done", project_id=project_b.id)
        db.add_blocked_by_edge(conn, "b1", "a1")
        db.add_blocked_by_edge(conn, "b1", "b2")
        with conn:
            for dst in ("a1", "b2"):
                conn.execute(
                    "INSERT INTO refs (src_id, dst_id, origin) VALUES ('b1', ?, 'explicit')",
                    (dst,),
                )
        assert core.resolve_status(conn, db.get_card(conn, "b1")) == "blocked"
    finally:
        conn.close()

    master.forget_project_by_id(project_a.id)

    conn = _brd()
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM blocked_by WHERE blocks_on_id = 'a1'"
        ).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM refs WHERE dst_id = 'a1'").fetchone()[0] == 0
        assert db.list_blockers_of(conn, "b1") == ["b2"]
        assert [r["dst_id"] for r in conn.execute("SELECT dst_id FROM refs")] == ["b2"]
        assert core.resolve_status(conn, db.get_card(conn, "b1")) == "todo"
    finally:
        conn.close()


def test_forget_current_project_forgets_the_deepest_root_above_the_cwd(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    deeper = repo / "sub" / "deeper"
    deeper.mkdir(parents=True)
    project = master.init_project(repo)

    assert master.forget_current_project(deeper) == project
    assert master.list_all_projects() == []


def test_forget_current_project_inside_a_nested_project_forgets_only_it(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    outer = tmp_path / "repo"
    inner = outer / "inner"
    (inner / "x").mkdir(parents=True)
    outer_project = master.init_project(outer)
    inner_project = master.init_project(inner)

    assert master.forget_current_project(inner / "x") == inner_project
    assert master.list_all_projects() == [outer_project]


def test_forget_current_project_outside_any_project_is_not_found(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    nowhere = tmp_path / "nowhere"
    nowhere.mkdir()

    with pytest.raises(ProjectNotFoundError) as excinfo:
        master.forget_current_project(nowhere)

    assert str(excinfo.value) == _not_found(nowhere)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_master.py -q -k "forget"`
Expected: FAIL — `AttributeError: module 'brd.master' has no attribute 'forget_project_by_id'` / `'forget_current_project'`. The pre-existing `forget_project` tests still pass.

- [ ] **Step 3: Implement**

In `src/brd/master.py`, replace the whole `forget_project` function (lines 107-128) with:

```python
def forget_project(root_path: Path) -> Project:
    """Forget the project registered exactly at root_path."""

    def find(conn: sqlite3.Connection) -> Project:
        project = db.get_project(conn, str(root_path))
        if project is None:
            raise ProjectNotFoundError(f"no registered project at {root_path}")
        return project

    return _forget(find)


def forget_current_project(cwd: Path) -> Project:
    """Forget the project cwd belongs to: the deepest registered root at or
    above it, as every other command resolves it."""
    return _forget(lambda conn: resolve_project(conn, cwd))


def forget_project_by_id(project_id: str) -> Project:
    """Forget a project by id, from anywhere, e.g. one whose directory is gone."""

    def find(conn: sqlite3.Connection) -> Project:
        project = db.get_project_by_id(conn, project_id)
        if project is None:
            raise ProjectNotFoundError(
                f"no project with id {project_id}; see `brd projects`"
            )
        return project

    return _forget(find)


def _forget(find: Callable[[sqlite3.Connection], Project]) -> Project:
    """Delete the project find returns, the edges pointing at its entities,
    and its document backups."""
    conn = connect()
    try:
        project = find(conn)
        # Read before the delete: the cascade through entities removes them.
        doc_ids = [
            row["id"]
            for row in conn.execute(
                "SELECT id FROM entities WHERE project_id = ? AND kind = 'document'",
                (project.id,),
            )
        ]
        db.delete_project(conn, project.id)
    finally:
        conn.close()

    for doc_id in doc_ids:
        (paths.docs_dir() / f"{doc_id}.md").unlink(missing_ok=True)

    return project
```

(`Callable` is already imported from `collections.abc` at the top of `master.py`.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_master.py -q`
Expected: PASS (all, including `test_forget_project_*`, `test_forget_removes_the_projects_document_backups`, `test_forgetting_a_nested_project_hands_its_tree_back_to_the_outer_one`).

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/brd/master.py tests/test_master.py
git commit -m "Forget the current project by deepest root, or any project by id"
```

---

### Task 4: CLI `brd init --relink`

**Files:**
- Modify: `src/brd/cli/project.py:17-29` (`init`)
- Test: `tests/test_cli.py` (imports at top; new tests after `test_init_pretty_flag_switches_off_json`, which ends around line 97)

**Interfaces:**
- Consumes: `master.relink_project(root_path: Path, ref: str, name: str | None = None) -> Project` (Task 2); `master.init_project` (exists).
- Produces: `brd init [--name NAME] [--relink OLD-ROOT-OR-ID] [--pretty]`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_cli.py`, add `import shutil` to the imports at the top:

```python
import json
import shutil
import uuid
```

Add after `test_init_pretty_flag_switches_off_json`:

```python
def _moved(tmp_path, monkeypatch):
    """init + one card in old/, then old/ renamed to new/ and the cwd moved there."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    monkeypatch.chdir(old)
    project = ok("init")
    ok("add", "--title", "Moved card")
    old.rename(new)
    monkeypatch.chdir(new)
    return project, old, new


def test_init_relink_by_old_root_brings_the_board_along(tmp_path, monkeypatch):
    project, old, new = _moved(tmp_path, monkeypatch)
    assert err("list") == "ProjectNotFoundError"

    relinked = ok("init", "--relink", old)

    assert relinked == {**project, "root_path": str(new)}
    assert [card["title"] for card in ok("list")] == ["Moved card"]


def test_init_relink_by_id_brings_the_board_along(tmp_path, monkeypatch):
    project, old, new = _moved(tmp_path, monkeypatch)

    relinked = ok("init", "--relink", project["id"], "--name", "renamed")

    assert relinked == {**project, "root_path": str(new), "name": "renamed"}
    assert [card["title"] for card in ok("list")] == ["Moved card"]
    assert ok("projects") == [relinked]


def test_init_relink_with_an_unknown_id_is_not_found(tmp_path, monkeypatch):
    project, old, new = _moved(tmp_path, monkeypatch)

    assert err("init", "--relink", str(uuid.uuid4())) == "ProjectNotFoundError"
    assert ok("projects") == [project]


def test_init_relink_onto_another_projects_root_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    monkeypatch.chdir(a)
    project_a = ok("init")
    monkeypatch.chdir(b)
    ok("init")
    before = ok("projects")

    assert err("init", "--relink", project_a["id"]) == "ProjectAlreadyExistsError"
    assert ok("projects") == before


def test_init_relink_pretty_flag_switches_off_json(tmp_path, monkeypatch):
    project, old, new = _moved(tmp_path, monkeypatch)

    result = invoke("init", "--relink", old, "--pretty")

    assert result.exit_code == 0, result.output
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)
    assert str(new) in result.stdout


def test_init_help_mentions_relink():
    result = invoke("init", "--help")
    assert result.exit_code == 0
    assert "--relink" in result.output
```

(`ok("projects")` returns a list of dicts; `ok("init")` returns the project dict. Each test creates its own projects, so `ok("projects")` comparisons are deterministic.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -q -k relink`
Expected: FAIL — Typer usage error `No such option: --relink` (exit code 2, so `ok`/`err` assertions fail).

- [ ] **Step 3: Implement**

In `src/brd/cli/project.py`, replace `init` with:

```python
@app.command()
def init(
    name: str | None = typer.Option(
        None, "--name", help="Override the default project name."
    ),
    relink: str | None = typer.Option(
        None,
        "--relink",
        metavar="OLD-ROOT-OR-ID",
        help="Point an existing project (by id or old root path) at the current "
        "directory instead of registering a new one, e.g. after moving the repo.",
    ),
    pretty: bool = pretty_option(),
) -> None:
    """Register the current directory as a brd project."""
    try:
        if relink is not None:
            project = master.relink_project(Path.cwd(), relink, name=name)
        else:
            project = master.init_project(Path.cwd(), name=name)
    except BrdError as exc:
        fail(exc, pretty)
    output.print_result(output.ok_envelope(dataclasses.asdict(project)), pretty)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -q`
Expected: PASS (all).

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/brd/cli/project.py tests/test_cli.py
git commit -m "Add brd init --relink to point a project at a moved repo"
```

---

### Task 5: CLI `brd forget` by deepest root and `--project`, plus README

**Files:**
- Modify: `src/brd/cli/project.py:43-57` (`forget`)
- Modify: `README.md:38-46` (first "Storage" paragraph)
- Test: `tests/test_cli.py` (new tests after `test_forget_pretty_flag_switches_off_json`, around line 171)

**Interfaces:**
- Consumes: `master.forget_project(root_path: Path) -> Project`, `master.forget_current_project(cwd: Path) -> Project`, `master.forget_project_by_id(project_id: str) -> Project` (Task 3); `output.error_envelope(type: str, message: str)`, `output.print_result`.
- Produces: `brd forget [PATH] [--project ID] [--pretty]`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_cli.py`, add after `test_forget_pretty_flag_switches_off_json`:

```python
def test_forget_project_option_works_after_the_repo_is_deleted(
    isolated_env, tmp_path, monkeypatch
):
    project = ok("init")
    monkeypatch.chdir(tmp_path)
    shutil.rmtree(isolated_env)

    assert ok("forget", "--project", project["id"]) == project
    assert ok("projects") == []


def test_forget_project_option_with_an_unknown_id_is_not_found(isolated_env):
    project = ok("init")

    assert err("forget", "--project", str(uuid.uuid4())) == "ProjectNotFoundError"
    assert ok("projects") == [project]


def test_forget_from_a_subdirectory_forgets_the_enclosing_project(
    isolated_env, monkeypatch
):
    project = ok("init")
    sub = isolated_env / "sub"
    sub.mkdir()
    monkeypatch.chdir(sub)

    assert ok("forget") == project
    assert ok("projects") == []


def test_forget_refuses_both_a_path_and_project(isolated_env):
    project = ok("init")

    assert err("forget", isolated_env, "--project", project["id"]) == "UsageError"
    assert ok("projects") == [project]


def test_forget_help_mentions_project_option():
    result = invoke("forget", "--help")
    assert result.exit_code == 0
    assert "--project" in result.output
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -q -k forget`
Expected: FAIL — `No such option: --project` for the `--project` tests; `test_forget_from_a_subdirectory_forgets_the_enclosing_project` fails with exit code 1 / `ProjectNotFoundError` (today's exact-match lookup). The four pre-existing forget tests still pass.

- [ ] **Step 3: Implement the command**

In `src/brd/cli/project.py`, replace `forget` with:

```python
@app.command()
def forget(
    path: Path | None = typer.Argument(
        None,
        help="Root path of the project to forget, matched exactly (defaults to "
        "the project the current directory belongs to).",
    ),
    project_id: str | None = typer.Option(
        None,
        "--project",
        help="Id of the project to forget (see `brd projects`), e.g. one whose "
        "directory is gone.",
    ),
    pretty: bool = pretty_option(),
) -> None:
    """Un-register a project and delete its stored data. Forgets the current
    project unless a path or --project is given."""
    if path is not None and project_id is not None:
        output.print_result(
            output.error_envelope(
                "UsageError", "give either a path or --project, not both"
            ),
            pretty,
        )
        raise typer.Exit(code=1)
    try:
        if project_id is not None:
            project = master.forget_project_by_id(project_id)
        elif path is not None:
            project = master.forget_project(path)
        else:
            project = master.forget_current_project(Path.cwd())
    except BrdError as exc:
        fail(exc, pretty)
    output.print_result(output.ok_envelope(dataclasses.asdict(project)), pretty)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -q`
Expected: PASS (all, including `test_forget_removes_current_project`, `test_forget_accepts_explicit_path_argument`, `test_forget_errors_when_not_registered`, `test_forget_pretty_flag_switches_off_json`).

- [ ] **Step 5: Update the README**

In `README.md`, the first "Storage" paragraph ends with "…a board doesn't automatically travel with a clone to another machine." Insert a new paragraph right after it (before "Older versions of brd wrote a `.brd` marker…"):

```markdown
If you move a repo, run `brd init --relink <old-path-or-id>` in its new
location: the existing project, with its id and board, now lives at the
current directory. `brd forget --project <id>` removes a project whose
directory is gone; `brd projects` lists the ids.
```

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/brd/cli/project.py tests/test_cli.py README.md
git commit -m "Let brd forget take the current project or --project <id>"
```

---

## Spec coverage check

| Spec item | Task / test |
|---|---|
| B1 lookup by id, then path-normalised root | Task 2 `_find_relink_target`; T1, T2, T3 (`normalises_the_old_root`), relative REF |
| B1 not found (REF + `brd projects` in message) | Task 2 `unknown_ref_is_not_found`; T17 Task 4 |
| B1 no-op when already at cwd | Task 2 `already_at_the_cwd_changes_nothing` (T5) |
| B1 refusal `ProjectAlreadyExistsError` (cwd, name, id) | Task 1 db test, Task 2 `onto_another_projects_root_is_refused` (T7), Task 4 (T18) |
| B1 UNIQUE backstop, never `IntegrityError` | Task 1 `db.relink_project` catches `IntegrityError` (T9) |
| B1 name kept / `--name` | Task 1, Task 2 `keeps_the_name_unless_one_is_given` (T4), Task 4 by-id test |
| B1 id, created_at, owned entities unchanged; old root no longer resolves | Task 2 T1 |
| B1 nesting not a conflict | Task 2 `into_another_projects_tree_nests_it` (T8) |
| B1 one transaction | Task 2 `BEGIN IMMEDIATE` … `commit`/`rollback`; refusal-leaves-writable test |
| B1 output envelope + `--pretty` | Task 4 tests |
| B2 forget current project by deepest root | Task 3 (T14 + not-found), Task 5 (T21) |
| B3 forget `--project ID` any cwd, dir gone | Task 3 (T10, T11, T12), Task 5 (T19, T20) |
| B4.1 incoming edges removed | Task 1 db test, Task 3 (T13) |
| B4.2 cascade of owned rows | Task 1, Task 3 T10 |
| B4.3 atomic | Task 1 trigger test (T15) |
| B4.4 doc backups after commit, others untouched | Task 3 `_forget`, T10 |
| B4.6 output envelope | Task 5 tests compare `== project` |
| B5 new error | Task 1 Step 3 |
| B6 `forget PATH` unchanged; `PATH --project` → `UsageError` | Task 3 keeps `forget_project`; Task 5 (T22) |
| B7 help text, README | Task 4/5 help tests (T23), Task 5 Step 5 |
| `init --relink ""` → not found | Task 2 `empty_ref_is_not_found` |
| Kept-unchanged tests | Run in each task's full-suite step |
<!-- task-pipeline: validated -->
