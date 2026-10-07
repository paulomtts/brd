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
