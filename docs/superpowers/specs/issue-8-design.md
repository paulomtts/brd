# Issue #8 — 1.7 Master project registration and `.brd` marker resolution

Subtask of story #1 (`Implement brd CLI v1`), milestone `brd CLI v1`. This narrows the agreed milestone design (`docs/superpowers/specs/2026-09-17-brd-cli-design.md`, `docs/superpowers/plans/2026-09-17-brd-cli.md` Task 7, lines 864–1113) to one module. No new design decisions.

## Scope

Create `src/brd/master.py` and `tests/test_master.py`. That is the whole deliverable.

`master.py` is the project-registration tier: it sits above `paths.py`/`db.py`/`models.py` and below `core.py`/`output.py`/`cli.py`. It owns the `.brd` marker file convention, the `.gitignore` append, per-project DB creation, and lookup of "the current project" from a directory.

### Out of scope (owned by siblings)

- Any SQL or schema work — `db.connect`, `db.init_master_schema`, `db.init_project_schema`, `db.insert_project`, `db.get_project_by_id`, `db.get_project_by_name`, `db.list_projects` belong to #5/#6/#7 and are consumed as-is. Do not reimplement or vary their behavior.
- Status derivation, cycle validation, card create/update/block/unblock (#9, #10, #11).
- The JSON/pretty envelope and any rendering (#12). `master.py` raises typed exceptions and returns dataclasses only; it never formats output, prints, or sets exit codes.
- Every `typer` command including `brd init` and `brd projects` (#13–#16). `init_project` takes an optional `name` parameter; the `--name` flag itself is CLI-layer work.

### Prerequisite (already satisfied)

`insert_project`, `get_project_by_id`, `get_project_by_name`, `list_projects` (and the card/`blocked_by` query functions from #7) already exist, fully implemented and tested, in this worktree's `src/brd/db.py` — this branch's `HEAD` is `origin/m1/task-7` (commit `497dc54`). No rebase or branch action is needed; implementation starts directly from the current worktree state and consumes those functions as-is.

## Public interface

- `MARKER_FILENAME = ".brd"`
- `ProjectAlreadyExistsError(Exception)`
- `ProjectNotFoundError(Exception)`
- `init_project(root_path: Path, name: str | None = None) -> Project`
- `find_marker(start: Path) -> Path | None`
- `resolve_current_project(start: Path) -> Project`
- `list_all_projects() -> list[Project]`

`Project` is `brd.models.Project` as-is (fields `id`, `name`, `root_path`, `db_path`, `created_at`, in that order); `master.py` constructs it but does not redefine or extend it.

## Observable behavior

**`init_project(root_path, name=None)`**

1. Project name is `name` if given, else `root_path.name`.
2. If a project with that name is already registered (checked via `db.get_project_by_name` against the master DB), raise `ProjectAlreadyExistsError` and make no filesystem or DB changes.
3. Otherwise generate a fresh `uuid.uuid4()` string id, derive the per-project DB path via `paths.project_db_path(project_id)`, open that DB and apply `db.init_project_schema`, closing it before continuing.
4. Insert the `Project` row into the master DB via `db.insert_project`, with `root_path` and `db_path` stored as strings and `created_at` an ISO-8601 UTC timestamp.
5. Write `root_path/.brd` containing the project id (trailing newline; readers `.strip()`).
6. Append `.brd` to `root_path/.gitignore`, creating that file when absent. The append is idempotent: if `.brd` is already a line in the file, nothing is written. When appending to a file whose last line is non-empty, insert a separating newline first so the entry lands on its own line and existing entries are preserved verbatim.
7. Return the `Project`.

Both DB tiers live only under the XDG data dir (`master.db`, `projects/<id>.db`); nothing but the `.brd` marker and the `.gitignore` line is ever written inside the repo.

**`find_marker(start)`** — resolves `start`, then walks upward testing `<dir>/.brd` as a file; returns the first hit as a `Path`, or `None` on reaching the filesystem root. Pure filesystem; touches no DB.

**`resolve_current_project(start)`** — `find_marker(start)`; if `None`, raise `ProjectNotFoundError` naming the search start. Otherwise read and strip the id from the marker and look it up via `db.get_project_by_id`; if unregistered, raise `ProjectNotFoundError` naming the marker path and the orphan id. Returns the `Project`.

**`list_all_projects()`** — returns `db.list_projects` results from the master DB; empty list when none registered.

## Connection discipline

Per the Concurrency section of the design spec and Global Constraint line 21: plain stdlib `sqlite3`, no ORM, no daemon. Every `master.py` entry point that needs the master DB opens a connection via `db.connect(paths.master_db_path())`, applies `db.init_master_schema` (idempotent, so first use bootstraps the DB), does its work, and closes it in a `finally` block. The per-project connection opened inside `init_project` is likewise closed in its own `finally`.

## Error paths

| Condition | Result |
|---|---|
| Name (explicit or defaulted) already registered | `ProjectAlreadyExistsError` |
| `resolve_current_project` finds no `.brd` above `start` | `ProjectNotFoundError` |
| Marker holds an id absent from the master DB | `ProjectNotFoundError` |
| `find_marker` finds nothing | `None` (not an error) |

Exceptions propagate uncaught out of `master.py`; they are caught exactly once at the `cli.py` boundary (#13) and turned into the error envelope there.

## Tests

Test-placement rule for this repo is the design spec's `Testing` section (lines 183–192) plus the plan's flat File Structure (lines 26–43): one flat test file per source module, no `unit/`/`integration/`/`e2e/` subdirectories. `master.py` sits at the same layer as `core.py`/`db.py`, so it gets **direct-call tests against a real temp filesystem and a real temp SQLite file, with no mocking of SQLite or the filesystem**. The end-to-end tier is reserved for `cli.py` (#17) and is not used here — none of the tests below drive the CLI.

All of the following go in **`tests/test_master.py`** (module-tier, direct-call), scaffolded with `tmp_path` and `monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))` so both DB tiers land in the temp dir:

1. `test_init_project_creates_marker_and_gitignore_entry` — marker exists, contains the returned project id, `.gitignore` is created containing a `.brd` line, name defaults to the repo folder name.
2. `test_init_project_appends_to_existing_gitignore_once` — pre-existing `.gitignore` keeps its entries and ends up with exactly one `.brd` line.
3. `test_init_project_rejects_duplicate_name` — second `init_project` with the same explicit `name` raises `ProjectAlreadyExistsError`.
4. `test_find_marker_walks_up_from_nested_dir` — from `repo/a/b`, returns `repo/.brd`.
5. `test_find_marker_returns_none_when_absent` — unmarked directory returns `None` (no XDG monkeypatch needed; no DB involved).
6. `test_resolve_current_project_from_nested_dir` — resolved `Project` equals the one returned by `init_project`.
7. `test_resolve_current_project_raises_when_no_marker` — raises `ProjectNotFoundError`.
8. `test_list_all_projects` — two inits, both names present in the result.

The plan's reference test file (lines 883–980) is the verbatim expected content; implement against it rather than re-deriving assertions.

## Done when

`uv run pytest tests/test_master.py -v` passes, and the change is committed as `src/brd/master.py` + `tests/test_master.py` with message `Add project registration and .brd marker resolution`.
