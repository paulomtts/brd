# Issue #4 — 1.3 XDG data directory resolution

Parent: #1 "Implement brd CLI v1". Source of truth: `docs/superpowers/plans/2026-09-17-brd-cli.md` lines 248-341 ("Task 3") and `docs/superpowers/specs/2026-09-17-brd-cli-design.md` lines 33-64, 183-198. This spec narrows that agreed design to one subtask; it introduces no new decisions.

## Scope

Create `src/brd/paths.py` — a leaf module holding the three functions that resolve where brd stores its SQLite databases — and `tests/test_paths.py`.

In scope:

- `data_dir() -> Path`
- `master_db_path() -> Path`
- `project_db_path(project_id: str) -> Path`
- `tests/test_paths.py` with the four tests listed below.

Out of scope (owned by sibling subtasks — do not drift):

- `src/brd/models.py` / `Card` / `Project` dataclasses (#3).
- `src/brd/db.py`, any `sqlite3` connection, WAL pragma, or schema creation (#5). This module resolves paths and creates directories only; it never opens a database file.
- Project-id generation or validation, `.brd` marker discovery, the project registry (owned by the later `master.py` subtask, #8 — not #2, which is scaffolding only).
- Package scaffolding, `pyproject.toml` dependencies, console-script entry point (#2).

## Constraints

- Stdlib only: `os` and `pathlib`. No external dependencies.
- Leaf module per the layered architecture (design spec lines 33-53): `paths.py` must not import `core.py`, `db.py`, `master.py`, `cli.py`, `models.py`, or `output.py`. Nothing in brd imports `paths` from within this subtask either.
- Both the master DB and all per-project DBs live under the XDG data directory, never inside a project repo (design spec lines 54-64). This module is where that layout is encoded:

```
<data_dir>/
  master.db
  projects/
    <project-id>.db
```

- The implementation and the test file are given verbatim in the plan (lines 264-327); follow them exactly, TDD order (test first, watch it fail with `ModuleNotFoundError: No module named 'brd.paths'`, then implement).

## Observable behavior

`data_dir()` returns `Path($XDG_DATA_HOME) / "brd"` when `XDG_DATA_HOME` is set and non-empty; otherwise `Path($HOME) / ".local" / "share" / "brd"`. The environment is read on every call — no module-level caching — so a test monkeypatching the env var mid-process sees the new value. Before returning, the directory is created with `mkdir(parents=True, exist_ok=True)`, so the returned path is always an existing directory and calling the function repeatedly is idempotent.

`master_db_path()` returns `data_dir() / "master.db"`. It creates the data dir as a side effect of calling `data_dir()`, but does not create or touch the `master.db` file itself — the returned path may not exist yet.

`project_db_path(project_id)` returns `data_dir() / "projects" / f"{project_id}.db"`, creating `projects/` with `mkdir(parents=True, exist_ok=True)` before returning. The `.db` file itself is not created. `project_id` is taken as an opaque string (UUID4 in practice, per plan line 22); no validation, normalization, or path-escaping check happens here — id generation and validity belong to the layers above.

## Error paths

No exceptions are defined or caught by this module; failures surface as stdlib exceptions from the caller's environment:

- `XDG_DATA_HOME` unset **and** `HOME` unset → `KeyError: 'HOME'` from `os.environ["HOME"]`. This is deliberate: an unresolvable data dir is not recoverable here, and the CLI-level error envelope (#owned by output.py/cli.py subtasks) is not this module's concern.
- Unwritable or non-directory parent → `PermissionError` / `NotADirectoryError` / `FileExistsError` propagate from `mkdir`. Not caught, not wrapped, not tested.

## Tests

Tier: all four are plain pytest unit tests in `tests/test_paths.py`, exercising the real filesystem via `tmp_path` with `monkeypatch.setenv`/`delenv` for the env vars. The design spec's Testing section (lines 183-193) names two tiers — unit tests for `core.py`/`db.py` against a temp SQLite file, and end-to-end tests for `cli.py` via a temp XDG data dir — but `paths.py` uses neither SQLite nor the CLI surface, so neither tier applies directly (same reasoning sibling #3 applies to `models.py`, per `issue-3-design.md`). These are plain unit tests against the real filesystem, one file per module, no mocking.

1. `test_data_dir_uses_xdg_data_home` — `XDG_DATA_HOME` set to `tmp_path`; asserts the result equals `tmp_path / "brd"` and `result.is_dir()`.
2. `test_data_dir_defaults_to_home_local_share` — `XDG_DATA_HOME` deleted (`raising=False`), `HOME` set to `tmp_path`; asserts the result equals `tmp_path / ".local" / "share" / "brd"` and `result.is_dir()`.
3. `test_master_db_path` — `XDG_DATA_HOME` set; asserts the result equals `tmp_path / "brd" / "master.db"`.
4. `test_project_db_path_creates_projects_dir` — `XDG_DATA_HOME` set; calls `project_db_path("abc-123")`, asserts the result equals `tmp_path / "brd" / "projects" / "abc-123.db"` and `result.parent.is_dir()`.

The exact test file body is fixed by the plan (lines 264-295) and should be reproduced verbatim.

## Prerequisite caveat

The story's subtasks form a single linear PR stack, so #4 depends on #2's package skeleton (`pyproject.toml` deps including pytest, console-script entry, `src/brd/__init__.py`, `src/brd/cli.py`, `tests/__init__.py`) having landed, and on #3 (`models.py`) for stack order — #4 has no functional dependency on `models.py` itself, but `from brd import paths` and `uv run pytest` require #2's scaffolding and pytest dev dependency. On this subtask's base branch, #2 and #3 have already landed (`src/brd/{__init__,cli,models}.py` and `tests/{__init__,test_cli,test_models}.py` already exist). The implementer must still confirm #2 and #3 are present on the base branch before starting — do not recreate scaffolding inline in this subtask.

## Verification

- Full suite: `uv run pytest`
- Typecheck: none configured.
- Lint: none configured.

## Commit

Stage exactly `src/brd/paths.py tests/test_paths.py`. This branch's history since #2 uses Conventional Commits (`feat:`, `test:`, `docs:`); use `feat: add XDG data directory resolution` to stay consistent.
