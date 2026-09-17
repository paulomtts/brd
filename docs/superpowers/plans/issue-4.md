<!-- task-pipeline: validated -->
# Spec (verbatim): docs/superpowers/specs/issue-4-design.md

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

---

# XDG Data Directory Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `src/brd/paths.py`, a stdlib-only leaf module that resolves the XDG data directory and the master/per-project SQLite database paths, creating the directories it returns.

**Architecture:** One new module with three pure-ish functions (`data_dir`, `master_db_path`, `project_db_path`). `data_dir()` reads `XDG_DATA_HOME` (fallback `$HOME/.local/share`) from `os.environ` on every call — no module-level caching — appends `brd`, and `mkdir(parents=True, exist_ok=True)` before returning. The other two build on it: `master_db_path()` appends `master.db` (no file created), `project_db_path(project_id)` creates `projects/` and appends `f"{project_id}.db"` (no file created). The module imports nothing from `brd` and never opens a SQLite connection. Tests are plain pytest unit tests hitting the real filesystem via `tmp_path` with env vars monkeypatched — no mocking.

**Tech Stack:** Python 3.12+ (`requires-python = ">=3.12"`), stdlib `os` + `pathlib` only, pytest (dev dependency, already in `pyproject.toml` `[dependency-groups] dev`), `uv` as the runner.

**Spec:** `docs/superpowers/specs/issue-4-design.md` (reproduced verbatim at the top of this file).

## Global Constraints

- Stdlib only in `paths.py`: `os` and `pathlib`. No external dependencies, no new entries in `pyproject.toml`.
- `paths.py` is a leaf module: it must not import `core.py`, `db.py`, `master.py`, `cli.py`, `models.py`, or `output.py`. No other brd module imports `paths` in this subtask.
- No `sqlite3` import, no connection, no WAL pragma, no schema — this subtask resolves paths and creates directories only (#5 owns `db.py`).
- Do not define, touch, or re-create `Card`/`Project` (#3) or any scaffolding/`pyproject.toml`/entry-point change (#2). Those already exist on the base branch.
- Both `master.db` and every `<project-id>.db` live under the XDG data dir — never inside a project repo.
- `project_id` is an opaque string (UUID4 in practice); no validation, normalization, or path-escaping check happens in this module.
- No exceptions are caught or wrapped: `KeyError: 'HOME'` (both env vars unset) and `PermissionError`/`NotADirectoryError`/`FileExistsError` from `mkdir` propagate untouched and are not tested.
- Test placement: exactly one test file, `tests/test_paths.py` (flat `tests/` directory, matching the sibling files `tests/test_models.py` and `tests/test_cli.py`). No mocking of the filesystem.
- Verification: `uv run pytest`. No typecheck configured. No lint configured.

## File Structure

- `src/brd/paths.py` (create) — the three path-resolution functions. Sole responsibility: where on disk brd's data lives.
- `tests/test_paths.py` (create) — the four unit tests for that module, in the repo's flat `tests/` directory alongside `tests/test_models.py` and `tests/test_cli.py`.
- No other file is created or modified. `pyproject.toml`, `src/brd/__init__.py`, `src/brd/cli.py`, `src/brd/models.py` are untouched.

---

### Task 1: Path resolution module (`brd.paths`)

**Files:**
- Create: `src/brd/paths.py`
- Test: `tests/test_paths.py`

**Interfaces:**
- Consumes: nothing. The module imports only `os` and `pathlib.Path`. It relies on `src/brd/__init__.py` existing (it does, from #2) so that `from brd import paths` resolves.
- Produces (relied on by #5 `db.py` and later subtasks):
  - `paths.data_dir() -> Path` — `$XDG_DATA_HOME/brd` if `XDG_DATA_HOME` is set and non-empty, else `$HOME/.local/share/brd`; the directory is created before returning.
  - `paths.master_db_path() -> Path` — `data_dir() / "master.db"`; the file is not created.
  - `paths.project_db_path(project_id: str) -> Path` — `data_dir() / "projects" / f"{project_id}.db"`; `projects/` is created, the `.db` file is not.

- [ ] **Step 0: Confirm the base branch prerequisites are present**

Run: `ls src/brd/__init__.py src/brd/cli.py src/brd/models.py tests/__init__.py`
Expected: all four paths listed, no "No such file or directory". These come from #2 and #3. If any is missing, stop — do not create scaffolding inline in this subtask; escalate that #2/#3 have not landed on this branch's base.

- [ ] **Step 1: Write the failing test**

Create `tests/test_paths.py` with exactly this content (verbatim from `docs/superpowers/plans/2026-09-17-brd-cli.md` lines 264-295):

```python
from pathlib import Path

from brd import paths


def test_data_dir_uses_xdg_data_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    result = paths.data_dir()
    assert result == tmp_path / "brd"
    assert result.is_dir()


def test_data_dir_defaults_to_home_local_share(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    result = paths.data_dir()
    assert result == tmp_path / ".local" / "share" / "brd"
    assert result.is_dir()


def test_master_db_path(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.master_db_path() == tmp_path / "brd" / "master.db"


def test_project_db_path_creates_projects_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    result = paths.project_db_path("abc-123")
    assert result == tmp_path / "brd" / "projects" / "abc-123.db"
    assert result.parent.is_dir()
```

Note: the `from pathlib import Path` line is part of the verbatim block and is intentionally kept even though the tests use `tmp_path` rather than constructing a `Path` directly. Do not "clean it up" — it matches the agreed plan text.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_paths.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'brd.paths'` (or `ImportError: cannot import name 'paths' from 'brd'`). All four tests error out. If instead the tests pass, `src/brd/paths.py` already exists — stop and investigate before writing anything.

- [ ] **Step 3: Write the minimal implementation**

Create `src/brd/paths.py` with exactly this content (verbatim from `docs/superpowers/plans/2026-09-17-brd-cli.md` lines 306-327):

```python
import os
from pathlib import Path


def data_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path(os.environ["HOME"]) / ".local" / "share"
    result = base / "brd"
    result.mkdir(parents=True, exist_ok=True)
    return result


def master_db_path() -> Path:
    return data_dir() / "master.db"


def project_db_path(project_id: str) -> Path:
    projects_dir = data_dir() / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    return projects_dir / f"{project_id}.db"
```

Three details that are deliberate and must not be "improved": `os.environ` is read inside `data_dir()` on every call (no module-level constant, so monkeypatched env vars take effect); the truthiness check `if xdg` treats an empty `XDG_DATA_HOME` as unset, per the spec's "set and non-empty"; and `os.environ["HOME"]` subscripts rather than `.get()` so an unset `HOME` raises `KeyError: 'HOME'` uncaught, as the spec's Error paths section requires. Do not add validation of `project_id`, do not create the `.db` files, and do not import `sqlite3` or any other `brd` module.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_paths.py -v`
Expected: PASS — 4 passed (`test_data_dir_uses_xdg_data_home`, `test_data_dir_defaults_to_home_local_share`, `test_master_db_path`, `test_project_db_path_creates_projects_dir`).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: PASS — the four new tests plus the pre-existing `tests/test_models.py` and `tests/test_cli.py` tests from #2/#3, zero failures. No typecheck and no lint are configured for this repo, so there is nothing else to run.

- [ ] **Step 6: Commit**

```bash
git add src/brd/paths.py tests/test_paths.py
git commit -m "feat: add XDG data directory resolution"
```

Stage exactly those two files — nothing else changed in this subtask.

---

## Self-Review

- **Spec coverage:** Scope's three functions and four tests → Task 1 Steps 1/3. Constraints (stdlib-only, leaf module, layout) → Global Constraints + Step 3 notes. Observable behavior (env re-read per call, `mkdir(parents=True, exist_ok=True)`, files not created, opaque `project_id`) → Step 3 implementation and its notes. Error paths (uncaught `KeyError`/`mkdir` errors, untested) → Global Constraints + Step 3 note on `os.environ["HOME"]`. Tests tier (`tests/test_paths.py`, real filesystem) → Step 1. Prerequisite caveat → Step 0. Verification → Steps 4-5. Commit → Step 6. No gaps.
- **Placeholder scan:** no TBD/TODO/"handle edge cases"/"similar to Task N"; both code blocks are complete file bodies.
- **Type consistency:** `data_dir() -> Path`, `master_db_path() -> Path`, `project_db_path(project_id: str) -> Path` — identical in the Interfaces block, the implementation, and the tests' call sites.
