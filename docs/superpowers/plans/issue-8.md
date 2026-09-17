<!-- task-pipeline: validated -->
# Spec (verbatim)

<!-- Verbatim copy of docs/superpowers/specs/issue-8-design.md -->

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

---

# Master Project Registration and `.brd` Marker Resolution — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `src/brd/master.py` — the project-registration tier that registers a repo as a `brd` project (`.brd` marker + `.gitignore` entry + master-DB row + per-project DB) and resolves "the current project" from any directory inside it.

**Architecture:** `master.py` is a thin, stateless module sitting above `paths.py`/`db.py`/`models.py` and below `core.py`/`cli.py`. It consumes the already-implemented `db` query functions as-is, opens one short-lived `sqlite3` connection per call and closes it in a `finally`, returns `brd.models.Project` dataclasses, and raises typed exceptions (`ProjectAlreadyExistsError`, `ProjectNotFoundError`) that propagate uncaught to the future `cli.py` boundary. It never prints, formats an envelope, or sets an exit code.

**Tech Stack:** Python 3.12, stdlib `sqlite3`/`uuid`/`pathlib`/`datetime`, `pytest`, `uv`.

**Spec:** `docs/superpowers/specs/issue-8-design.md` (reproduced verbatim above). Parent design: `docs/superpowers/specs/2026-09-17-brd-cli-design.md`; parent plan Task 7: `docs/superpowers/plans/2026-09-17-brd-cli.md:864-1113`.

## Global Constraints

- No ORM — plain stdlib `sqlite3` with a light wrapper.
- Both DB tiers live under the XDG data dir (`~/.local/share/brd/`), never inside project repos. The only things written inside a repo are the `.brd` marker and one `.gitignore` line.
- `.brd` marker file must be added to the repo's `.gitignore` by project initialization, idempotently.
- SQLite WAL mode; one connection opened/closed per call, no daemon.
- Card IDs and project IDs are UUID4 strings.
- `master.py` raises typed exceptions and returns dataclasses only; no output formatting, no printing, no exit codes (that is `#12`/`#13`).
- Tests are flat, one file per source module (`tests/test_master.py`), direct-call, against a real temp filesystem and real temp SQLite files — no mocking of SQLite or the filesystem, and no driving the CLI.

---

## Starting state (verified on this worktree)

Branch `m1/task-8`, worktree `/home/paulomtts/Code/brd/.claude/worktrees/m1/task-8`, cut from `origin/m1/task-7`.

Already present and consumed as-is (do not modify):

- `src/brd/models.py:4-10` — `Project(id: str, name: str, root_path: str, db_path: str, created_at: str)`, a plain `@dataclass` (so `==` is field-wise).
- `src/brd/paths.py:5-20` — `data_dir() -> Path` (honours `XDG_DATA_HOME`, `mkdir(parents=True, exist_ok=True)`), `master_db_path() -> Path`, `project_db_path(project_id: str) -> Path` (creates `<data_dir>/projects/`).
- `src/brd/db.py:7-93` — `connect(db_path: Path) -> sqlite3.Connection` (WAL, `foreign_keys=ON`, `sqlite3.Row`), `init_master_schema(conn) -> None`, `init_project_schema(conn) -> None`, `insert_project(conn, project: Project) -> None`, `get_project_by_id(conn, project_id: str) -> Project | None`, `get_project_by_name(conn, name: str) -> Project | None`, `list_projects(conn) -> list[Project]`.

Absent (this plan creates them): `src/brd/master.py`, `tests/test_master.py`.

Existing test files for style reference: `tests/test_db.py`, `tests/test_paths.py` (flat, `tmp_path`-based, `from brd import db`).

## File Structure

- `src/brd/master.py` (create) — the whole public interface: `MARKER_FILENAME`, `ProjectAlreadyExistsError`, `ProjectNotFoundError`, `_now`, `_master_conn`, `init_project`, `find_marker`, `resolve_current_project`, `list_all_projects`. Single responsibility: project registration + marker resolution. Small enough (~90 lines) that no split is warranted.
- `tests/test_master.py` (create) — the eight module-tier tests from the spec's Tests section, in spec order.

Task decomposition: Task 1 = registration (`init_project`, tests 1–3); Task 2 = resolution (`find_marker`, `resolve_current_project`, tests 4–7); Task 3 = enumeration (`list_all_projects`, test 8). Each ends with an independently testable deliverable and its own commit.

**Note on the spec's "Done when" commit message:** the spec names one commit, `Add project registration and .brd marker resolution`. This plan lands the same two files across three TDD commits (one per review gate); their combined effect is exactly that commit's content. Reviewers should read the branch, not a single SHA.

---

### Task 1: `init_project` — marker file, `.gitignore` entry, master registration

**Files:**
- Create: `src/brd/master.py`
- Test: `tests/test_master.py`

**Interfaces:**
- Consumes: `brd.paths.master_db_path() -> Path`, `brd.paths.project_db_path(project_id: str) -> Path`, `brd.db.connect(db_path: Path) -> sqlite3.Connection`, `brd.db.init_master_schema(conn) -> None`, `brd.db.init_project_schema(conn) -> None`, `brd.db.insert_project(conn, project: Project) -> None`, `brd.db.get_project_by_name(conn, name: str) -> Project | None`, `brd.models.Project`.
- Produces:
  - `master.MARKER_FILENAME: str = ".brd"`
  - `master.ProjectAlreadyExistsError(Exception)`
  - `master._now() -> str` (ISO-8601 UTC timestamp; module-private)
  - `master._master_conn() -> sqlite3.Connection` (connected master DB with schema applied; caller must close; module-private)
  - `master.init_project(root_path: Path, name: str | None = None) -> Project`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_master.py` with exactly this content:

```python
import pytest

from brd import master


def test_init_project_creates_marker_and_gitignore_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    project = master.init_project(repo)

    marker = repo / ".brd"
    assert marker.exists()
    assert marker.read_text().strip() == project.id

    gitignore = repo / ".gitignore"
    assert gitignore.exists()
    assert ".brd" in gitignore.read_text().splitlines()
    assert project.name == "myrepo"


def test_init_project_appends_to_existing_gitignore_once(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    (repo / ".gitignore").write_text("__pycache__/\n")

    master.init_project(repo)

    lines = (repo / ".gitignore").read_text().splitlines()
    assert lines.count(".brd") == 1
    assert "__pycache__/" in lines


def test_init_project_rejects_duplicate_name(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo1 = tmp_path / "repo1"
    repo1.mkdir()
    repo2 = tmp_path / "repo2"
    repo2.mkdir()

    master.init_project(repo1, name="shared")
    with pytest.raises(master.ProjectAlreadyExistsError):
        master.init_project(repo2, name="shared")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_master.py -v`

Expected: collection error — `ModuleNotFoundError: No module named 'brd.master'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/brd/master.py`:

```python
import uuid
from datetime import datetime, timezone
from pathlib import Path

from brd import db, paths
from brd.models import Project

MARKER_FILENAME = ".brd"


class ProjectAlreadyExistsError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _master_conn():
    conn = db.connect(paths.master_db_path())
    db.init_master_schema(conn)
    return conn


def init_project(root_path: Path, name: str | None = None) -> Project:
    project_name = name or root_path.name
    conn = _master_conn()
    try:
        if db.get_project_by_name(conn, project_name) is not None:
            raise ProjectAlreadyExistsError(
                f"a project named '{project_name}' is already registered"
            )

        project_id = str(uuid.uuid4())
        project_db_path = paths.project_db_path(project_id)

        project_conn = db.connect(project_db_path)
        try:
            db.init_project_schema(project_conn)
        finally:
            project_conn.close()

        project = Project(
            id=project_id,
            name=project_name,
            root_path=str(root_path),
            db_path=str(project_db_path),
            created_at=_now(),
        )
        db.insert_project(conn, project)

        marker = root_path / MARKER_FILENAME
        marker.write_text(project_id + "\n")

        gitignore = root_path / ".gitignore"
        existing_lines = (
            gitignore.read_text().splitlines() if gitignore.exists() else []
        )
        if MARKER_FILENAME not in existing_lines:
            with gitignore.open("a") as f:
                if existing_lines and existing_lines[-1] != "":
                    f.write("\n")
                f.write(f"{MARKER_FILENAME}\n")

        return project
    finally:
        conn.close()
```

Notes for the implementer:
- The duplicate-name check happens **before** any UUID generation, per-project DB creation, or file write, so a rejected `init_project` leaves no trace (spec, Observable behavior step 2).
- `gitignore.open("a")` creates the file when absent, satisfying "creating that file when absent".
- The separating-newline guard handles a pre-existing `.gitignore` that does not end in a newline: `"a\nb"` splits to `["a", "b"]`, last element non-empty, so a `\n` is written first and `b` is preserved verbatim. A file ending in `\n` splits to `[..., "b"]` too — writing the extra `\n` would create a blank line, which `git` ignores and the test tolerates (`lines.count(".brd") == 1`, `"__pycache__/" in lines`); do not "fix" this by dropping the guard, that would corrupt no-trailing-newline files.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_master.py -v`

Expected: 3 passed.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`

Expected: all tests pass (the pre-existing `tests/test_paths.py`, `tests/test_db.py`, `tests/test_models.py`, `tests/test_cli.py` are untouched).

- [ ] **Step 6: Commit**

```bash
git add src/brd/master.py tests/test_master.py
git commit -m "Add project registration with .brd marker and gitignore entry"
```

---

### Task 2: `find_marker` and `resolve_current_project`

**Files:**
- Modify: `src/brd/master.py` (add `ProjectNotFoundError` below `ProjectAlreadyExistsError`; append `find_marker` and `resolve_current_project` after `init_project`)
- Test: `tests/test_master.py` (append)

**Interfaces:**
- Consumes: `master.MARKER_FILENAME`, `master._master_conn()`, `master.init_project(root_path: Path, name: str | None = None) -> Project` (Task 1); `brd.db.get_project_by_id(conn, project_id: str) -> Project | None`; `brd.models.Project`.
- Produces:
  - `master.ProjectNotFoundError(Exception)`
  - `master.find_marker(start: Path) -> Path | None`
  - `master.resolve_current_project(start: Path) -> Project`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_master.py`:

```python
def test_find_marker_walks_up_from_nested_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    nested = repo / "a" / "b"
    nested.mkdir(parents=True)
    master.init_project(repo)

    found = master.find_marker(nested)
    assert found == repo / ".brd"


def test_find_marker_returns_none_when_absent(tmp_path):
    somewhere = tmp_path / "nowhere"
    somewhere.mkdir()
    assert master.find_marker(somewhere) is None


def test_resolve_current_project_from_nested_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    nested = repo / "a"
    nested.mkdir(parents=True)
    created = master.init_project(repo)

    resolved = master.resolve_current_project(nested)
    assert resolved == created


def test_resolve_current_project_raises_when_no_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    somewhere = tmp_path / "nowhere"
    somewhere.mkdir()
    with pytest.raises(master.ProjectNotFoundError):
        master.resolve_current_project(somewhere)
```

Note on `test_find_marker_returns_none_when_absent`: `tmp_path` sits under the system temp dir, which contains no `.brd`, so the upward walk reaches `/` and returns `None`. Deliberately no `XDG_DATA_HOME` monkeypatch here — no DB is touched.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_master.py -v`

Expected: the three Task 1 tests pass; the four new ones fail with `AttributeError: module 'brd.master' has no attribute 'find_marker'` / `... 'resolve_current_project'` / `... 'ProjectNotFoundError'`.

- [ ] **Step 3: Write the minimal implementation**

In `src/brd/master.py`, add the second exception class immediately after `ProjectAlreadyExistsError`:

```python
class ProjectNotFoundError(Exception):
    pass
```

and append these two functions after `init_project`:

```python
def find_marker(start: Path) -> Path | None:
    current = start.resolve()
    while True:
        candidate = current / MARKER_FILENAME
        if candidate.is_file():
            return candidate
        if current.parent == current:
            return None
        current = current.parent


def resolve_current_project(start: Path) -> Project:
    marker = find_marker(start)
    if marker is None:
        raise ProjectNotFoundError(f"no {MARKER_FILENAME} marker found above {start}")

    project_id = marker.read_text().strip()
    conn = _master_conn()
    try:
        project = db.get_project_by_id(conn, project_id)
    finally:
        conn.close()

    if project is None:
        raise ProjectNotFoundError(
            f"marker at {marker} references unknown project id {project_id}"
        )
    return project
```

Notes for the implementer:
- The `current.parent == current` test is the filesystem-root sentinel — `Path("/").parent == Path("/")`.
- `is_file()` (not `exists()`) so a stray `.brd` *directory* is skipped rather than treated as a marker.
- The `db.get_project_by_id` lookup is done inside the `try` and the `None` check *after* the `finally` closes the connection, so the connection is never left open while an exception unwinds.
- `resolve_current_project` returns the `Project` dataclass straight from `db`; because `Project` is a plain `@dataclass`, `resolved == created` compares field-wise and passes only if `root_path`/`db_path`/`created_at` round-tripped through SQLite unchanged.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_master.py -v`

Expected: 7 passed.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/brd/master.py tests/test_master.py
git commit -m "Add .brd marker resolution to the current project"
```

---

### Task 3: `list_all_projects`

**Files:**
- Modify: `src/brd/master.py` (append `list_all_projects` at end of file)
- Test: `tests/test_master.py` (append)

**Interfaces:**
- Consumes: `master._master_conn()`, `master.init_project(root_path: Path, name: str | None = None) -> Project` (Task 1); `brd.db.list_projects(conn) -> list[Project]`.
- Produces: `master.list_all_projects() -> list[Project]`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_master.py`:

```python
def test_list_all_projects(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo1 = tmp_path / "repo1"
    repo1.mkdir()
    repo2 = tmp_path / "repo2"
    repo2.mkdir()
    master.init_project(repo1)
    master.init_project(repo2)

    results = master.list_all_projects()
    assert {p.name for p in results} == {"repo1", "repo2"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_master.py::test_list_all_projects -v`

Expected: FAIL — `AttributeError: module 'brd.master' has no attribute 'list_all_projects'`.

- [ ] **Step 3: Write the minimal implementation**

Append to `src/brd/master.py`:

```python
def list_all_projects() -> list[Project]:
    conn = _master_conn()
    try:
        return db.list_projects(conn)
    finally:
        conn.close()
```

`_master_conn()` applies `db.init_master_schema` (idempotent `CREATE TABLE IF NOT EXISTS`), so calling `list_all_projects()` before any project is registered bootstraps an empty master DB and returns `[]` rather than raising `sqlite3.OperationalError: no such table`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_master.py::test_list_all_projects -v`

Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`

Expected: all tests pass, including the 8 in `tests/test_master.py`.

- [ ] **Step 6: Commit**

```bash
git add src/brd/master.py tests/test_master.py
git commit -m "Add list_all_projects to the master registry"
```

---

## Final verification

- [ ] `uv run pytest tests/test_master.py -v` → 8 passed (spec "Done when").
- [ ] `uv run pytest` → whole suite green.
- [ ] `git diff --stat origin/m1/task-7..HEAD` lists exactly `src/brd/master.py` and `tests/test_master.py` — nothing under `src/brd/db.py`, `paths.py`, `models.py`, or `cli.py` changed (sibling-owned scope).
- [ ] `grep -rn "print(\|json\|typer\|status\|blocked" src/brd/master.py` returns nothing — `master.py` does no rendering, no CLI, no status/cycle logic (out-of-scope guard).
