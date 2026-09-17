<!-- task-pipeline: validated -->
# Issue #13 — 1.12 CLI: `init` and `projects` commands

Subtask of parent story #1 "Implement brd CLI v1". Narrows plan Task 12 (`docs/superpowers/plans/2026-09-17-brd-cli.md:1846-1968`) to one deliverable: the first two user-facing typer commands.

## Scope

Add two commands to `src/brd/cli.py`, which today holds only the `typer.Typer` app plus a no-op `@app.callback()` (`src/brd/cli.py:1-16`):

- `brd init [--name TEXT] [--pretty/--human]` — registers the current working directory as a brd project.
- `brd projects [--pretty/--human]` — lists every registered project.

Both are thin adapters: they call already-merged `brd.master` functions, wrap the result in an envelope from `brd.output`, and print it. No new business logic, no new persistence, no changes to `master.py`, `db.py`, `models.py`, or `output.py`.

Out of scope (owned by siblings): `add`/`show`/`list` (#14), `update`/`block`/`unblock` (#15), `tree`/`next` (#16), envelope and pretty-rendering internals (#12), master registration internals (#8).

### Prerequisite gap (already satisfied)

`src/brd/output.py` does not exist on `main`; it was added on sibling branch `m1/task-12` (commits `89a8a73`, `3a64a76`, `9f5c64b`). The PR stack is linear ("each subtask strictly builds on the previous one"), and this worktree's branch (`m1/task-13`) already tracks `m1/task-12`'s tip (`9f5c64b`) — `src/brd/output.py` and `tests/test_output.py` are already present on disk here, so `src/brd/cli.py` can import `output` with no further merge, rebase, or cherry-pick step. `output.py` and `tests/test_output.py` are not edited as part of this subtask's deliverable.

## Consumed APIs (all pre-existing, used as-is)

- `master.init_project(root_path: Path, name: str | None) -> Project` — `src/brd/master.py:29`; writes the `.brd` marker, appends `.brd` to `.gitignore`, creates the project DB, inserts the master row.
- `master.list_all_projects() -> list[Project]` — `src/brd/master.py:104`.
- `master.ProjectAlreadyExistsError` — `src/brd/master.py:11`; raised when a project of that name is already registered.
- `output.ok_envelope(data) -> {"ok": True, "data": data}`, `output.error_envelope(type, message) -> {"ok": False, "error": {"type":…, "message":…}}`, `output.print_result(envelope, pretty)`.
- `Project` dataclass fields `id, name, root_path, db_path, created_at` (`src/brd/models.py:4-10`), serialized with `dataclasses.asdict`.

## Observable behavior

**`brd init`** — resolves the project name from `--name`, defaulting (inside `master.init_project`) to `Path.cwd().name`. On success: exit code 0, and stdout carries `{"ok": true, "data": {...Project fields...}}` as JSON (or the pretty rendering when `--pretty`/`--human` is passed). Side effects — a `.brd` marker file containing the project id in the cwd, a `.gitignore` entry, and a new per-project SQLite DB under the XDG data dir — are produced by `master`, not by the CLI.

**`brd projects`** — exit code 0; stdout carries `{"ok": true, "data": [ {...}, ... ]}`, one object per registered project, in `db.list_projects` order. An empty registry yields `data: []` and still exits 0.

Both commands default to machine-readable JSON; `--pretty` (alias `--human`) switches to human rendering via `output.print_result`. The existing `--help`/no-args help behavior must keep working unchanged.

## Error paths

- `master.ProjectAlreadyExistsError` from `init` → print `error_envelope("ProjectAlreadyExistsError", str(exc))` to the same stream, then exit non-zero (code 1). The error is reported as a well-formed envelope, never as a traceback.
- Unknown option or unknown command → typer's own usage error (exit code 2). Not our concern to reshape here.
- `projects` has no expected failure mode of its own at this stage.

## Tests

Test-placement rule (`docs/superpowers/specs/2026-09-17-brd-cli-design.md:183-192`, the repo's only such guidance — no CLAUDE.md exists): `core.py`/`db.py` get unit tests against a temp SQLite file; `cli.py` gets **end-to-end tests driving the full command surface against a temp XDG data dir monkeypatched per test**. Every test below is therefore in the **CLI end-to-end tier**, appended to `tests/test_cli.py` and invoked through `CliRunner`. No unit tests of `master` or `output` are added here — those tiers belong to #8 and #12.

Shared `isolated_env` fixture (e2e tier): `monkeypatch.setenv("XDG_DATA_HOME", tmp_path / "data")`, create `tmp_path/"myrepo"`, `monkeypatch.chdir` into it, yield the repo path.

1. `test_init_registers_project` — e2e tier. `brd init` exits 0; parsed stdout has `ok is True` and `data["name"] == "myrepo"`; `.brd` exists in the repo dir.
2. `test_init_twice_fails_second_time` — e2e tier. Second `brd init` exits non-zero; parsed stdout has `ok is False` and `error["type"] == "ProjectAlreadyExistsError"`.
3. `test_projects_lists_registered_projects` — e2e tier. After `brd init`, `brd projects` exits 0 and `data[0]["name"] == "myrepo"`.

Existing e2e tests that must remain green: `test_help_exits_zero`, `test_help_prints_program_description`, `test_no_args_prints_help_instead_of_missing_command_error` (`tests/test_cli.py:10-24`).

## Verification

Full suite: `uv run pytest`. No typecheck or lint step is configured for this repo. Baseline before this change is 110 passing tests (verified via `uv run pytest -q` on this worktree's current `HEAD`); after it, 110 plus the three new e2e tests (113 total), with nothing previously passing turned red.

---

# CLI `init` and `projects` Commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `brd init` and `brd projects` typer commands to `src/brd/cli.py` as thin adapters over the existing `brd.master` and `brd.output` modules.

**Architecture:** `src/brd/cli.py` currently exposes only a `typer.Typer` app and a no-op `@app.callback()`. Two `@app.command()` functions are appended to it: `init` calls `master.init_project(Path.cwd(), name=name)` and prints `output.ok_envelope(dataclasses.asdict(project))`, translating `master.ProjectAlreadyExistsError` into `output.error_envelope(...)` plus `typer.Exit(code=1)`; `projects` calls `master.list_all_projects()` and prints a list payload. No other module is touched — all persistence, marker/`.gitignore` writing, and envelope/pretty rendering already exist.

**Tech Stack:** Python 3, `typer` (CLI), `typer.testing.CliRunner` + `pytest` (tests), `uv` (runner), stdlib `dataclasses`/`json`/`pathlib`.

**Spec:** `docs/superpowers/specs/issue-13-design.md` (reproduced verbatim above)

## Global Constraints

- Branch/worktree: `m1/task-13` at `/home/paulomtts/Code/brd/.claude/worktrees/m1/task-13`; run every command from that directory.
- Only two files may change: `src/brd/cli.py` and `tests/test_cli.py`. Do not edit `src/brd/output.py`, `src/brd/master.py`, `src/brd/db.py`, `src/brd/models.py`, `src/brd/paths.py`, or any other test file.
- Do not add `add`/`show`/`list` (#14), `update`/`block`/`unblock` (#15), or `tree`/`next` (#16) commands.
- All new tests go in the CLI end-to-end tier: appended to `tests/test_cli.py`, driven through the module-level `runner = CliRunner()` already defined at `tests/test_cli.py:5`, against a temp XDG data dir monkeypatched per test. No unit tests of `master` or `output` here.
- Keep the existing `@app.callback()` `main()` and `no_args_is_help=True` exactly as they are, so `test_help_exits_zero`, `test_help_prints_program_description`, and `test_no_args_prints_help_instead_of_missing_command_error` stay green.
- Both commands default to JSON; `--pretty` with alias `--human` is the flag name, verbatim.
- Error envelope type string is exactly `"ProjectAlreadyExistsError"`; exit code exactly `1`.
- Verification command: `uv run pytest`. Baseline is 110 passing tests; final state is 113 passing tests.
- No typecheck or lint step is configured for this repo — do not invent one.

## File Structure

- `src/brd/cli.py` (modify) — typer app and command surface. Gains imports (`dataclasses`, `pathlib.Path`, `brd.master`, `brd.output`) and two command functions, appended below the existing `main()` callback and above the `if __name__ == "__main__":` block.
- `tests/test_cli.py` (modify) — CLI end-to-end tier. Gains `json`/`pytest` imports, the `isolated_env` fixture, and three tests appended after the existing help tests.

---

### Task 1: `brd init` command

**Files:**
- Modify: `src/brd/cli.py:1-16`
- Test: `tests/test_cli.py` (append after line 24)

**Interfaces:**
- Consumes: `master.init_project(root_path: Path, name: str | None = None) -> Project` (`src/brd/master.py:29`); `master.ProjectAlreadyExistsError` (`src/brd/master.py:11`); `output.ok_envelope(data) -> dict` and `output.error_envelope(error_type: str, message: str) -> dict` and `output.print_result(envelope: dict, pretty: bool) -> None` (`src/brd/output.py:5,9,42`); `Project` dataclass fields `id, name, root_path, db_path, created_at` (`src/brd/models.py:4-10`).
- Produces: `init(name: str, pretty: bool) -> None` registered on `app` as the `init` command, i.e. the `brd init [--name TEXT] [--pretty/--human]` CLI surface; and the `isolated_env` pytest fixture in `tests/test_cli.py` (yields the `tmp_path / "myrepo"` directory, with `XDG_DATA_HOME` set to `tmp_path / "data"` and cwd changed into the repo), reused by Task 2.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py` (after the existing `test_no_args_prints_help_instead_of_missing_command_error`), and add the two new imports at the top of the file alongside `from typer.testing import CliRunner` so the header reads:

```python
import json

import pytest
from typer.testing import CliRunner

from brd.cli import app
```

Appended body:

```python
@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    return repo


def test_init_registers_project(isolated_env):
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["name"] == "myrepo"
    assert (isolated_env / ".brd").exists()


def test_init_twice_fails_second_time(isolated_env):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["init"])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "ProjectAlreadyExistsError"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: `test_init_registers_project` and `test_init_twice_fails_second_time` FAIL — typer reports `No such command 'init'` with exit code 2, so `assert result.exit_code == 0` fails in the first test and `json.loads(result.stdout)` fails on the usage text in the second. The three existing help tests still PASS.

- [ ] **Step 3: Write the minimal implementation**

Edit `src/brd/cli.py` so it reads exactly:

```python
import dataclasses
from pathlib import Path

import typer

from brd import master, output

app = typer.Typer(
    name="brd",
    help="Local kanban board for tracking work, no visual UI.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    pass


@app.command()
def init(
    name: str = typer.Option(None, "--name", help="Override the default project name."),
    pretty: bool = typer.Option(
        False, "--pretty", "--human", help="Human-readable output."
    ),
) -> None:
    """Register the current directory as a brd project."""
    try:
        project = master.init_project(Path.cwd(), name=name)
    except master.ProjectAlreadyExistsError as exc:
        output.print_result(
            output.error_envelope("ProjectAlreadyExistsError", str(exc)), pretty
        )
        raise typer.Exit(code=1)

    output.print_result(output.ok_envelope(dataclasses.asdict(project)), pretty)


if __name__ == "__main__":
    app()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS — 5 passed (3 help tests + 2 new init tests).

- [ ] **Step 5: Commit**

```bash
git add src/brd/cli.py tests/test_cli.py
git commit -m "Add brd init command"
```

---

### Task 2: `brd projects` command

**Files:**
- Modify: `src/brd/cli.py` (append a second `@app.command()` below `init`, above `if __name__ == "__main__":`)
- Test: `tests/test_cli.py` (append after `test_init_twice_fails_second_time`)

**Interfaces:**
- Consumes: `master.list_all_projects() -> list[Project]` (`src/brd/master.py:104`); `output.ok_envelope`, `output.print_result` (`src/brd/output.py:5,42`); the `isolated_env` fixture and the `init` command from Task 1.
- Produces: `projects(pretty: bool) -> None` registered on `app` as the `projects` command, i.e. the `brd projects [--pretty/--human]` CLI surface.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
def test_projects_lists_registered_projects(isolated_env):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["projects"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"][0]["name"] == "myrepo"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_projects_lists_registered_projects -v`
Expected: FAIL — typer reports `No such command 'projects'` with exit code 2, so `assert result.exit_code == 0` fails.

- [ ] **Step 3: Write the minimal implementation**

In `src/brd/cli.py`, insert this function between the `init` command and the `if __name__ == "__main__":` block:

```python
@app.command()
def projects(
    pretty: bool = typer.Option(
        False, "--pretty", "--human", help="Human-readable output."
    ),
) -> None:
    """List all registered projects."""
    all_projects = master.list_all_projects()
    envelope = output.ok_envelope([dataclasses.asdict(p) for p in all_projects])
    output.print_result(envelope, pretty)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS — 6 passed (3 help tests + 2 init tests + 1 projects test).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: 113 passed (110 baseline + 3 new). If anything previously passing is red, fix it before committing.

- [ ] **Step 6: Commit**

```bash
git add src/brd/cli.py tests/test_cli.py
git commit -m "Add brd projects command"
```

---

## Done when

- `uv run pytest` reports 113 passed from `/home/paulomtts/Code/brd/.claude/worktrees/m1/task-13`.
- `src/brd/cli.py` exposes exactly `init` and `projects` commands plus the pre-existing `main()` callback; no other source or test file differs from `HEAD` at the start of this plan.
