<!-- task-pipeline: validated -->
# Issue #14 — 1.13 CLI: `add`, `show`, `list` commands

Subtask of story #1 (`Implement brd CLI v1`), milestone `brd CLI v1`. Narrows Task 13 of `docs/superpowers/plans/2026-09-17-brd-cli.md` (lines 1972–2187) and the command/output contract in `docs/superpowers/specs/2026-09-17-brd-cli-design.md` (lines 140–174, 183–192). Design decisions are already settled upstream; this document only fixes the boundary of this subtask.

## Scope

Modify `src/brd/cli.py` only, plus append tests to `tests/test_cli.py`. Deliverables:

- `_project_conn() -> tuple[sqlite3.Connection, master.Project]` — private helper: `master.resolve_current_project(Path.cwd())`, then `db.connect(Path(project.db_path))`. Tasks 14/15 (issues #15, #16) reuse this exact signature, so it must not drift.
- `_card_detail(conn, card) -> dict` — private helper returning `id`, `title`, `description`, `status` (via `core.resolve_status(conn, card)`), `parent_id`, `created_at`, `updated_at`, `blocked_by` (via `db.list_blockers_of`, list of ids), `children` (ids of `db.list_children`).
- `add`, `show <id>`, and `list` typer commands. `list` is registered as `@app.command(name="list")` on a function named `list_cards_cmd`, because `list` shadows the builtin.

Out of scope: `output.py` itself (owned by #12), `brd init` / `brd projects` (owned by #13 — relied on only as a test fixture, never modified), `update` / `block` / `unblock` (#15), `tree` / `next` (#16), the full-flow e2e test and README (#17). No changes to `core.py`, `db.py`, `master.py`, or `models.py`: every lower-layer function this subtask consumes already exists with the expected signature.

## Prerequisites (met)

This subtask depends on two sibling deliverables, both already merged into this worktree:

- `src/brd/output.py` (#12) providing `ok_envelope`, `error_envelope`, `print_result` — required by all three commands.
- The `init` / `projects` commands in `src/brd/cli.py` (#13), plus the `isolated_env` fixture the tests below build on.

Do not modify or reimplement `output.py`, `init`, or `projects` — extend `cli.py` and `tests/test_cli.py` alongside them.

## Observable behavior

All output goes through `output.ok_envelope` / `output.error_envelope` / `output.print_result`: JSON by default, human text under `--pretty` (alias `--human`), envelope shape `{"ok": true, "data": ...}` or `{"ok": false, "error": {"type": ..., "message": ...}}`, non-zero exit whenever `ok` is false. The connection is closed in a `finally` block on every path.

`brd add --title <t> [--description <d>] [--parent <id>] [--blocked-by <id> ...] [--pretty]` — `--title` is required; `--blocked-by` is repeatable and collected into a list. Calls `core.create_card(conn, title=, description=, parent_id=, blocked_by=)` and prints `_card_detail` of the created card. A freshly created card has `status == "todo"` when it has no blockers.

`brd show <id> [--pretty]` — positional card id. `db.get_card`; if `None`, raise `core.CardNotFoundError(f"no card with id {card_id}")`. Prints `_card_detail`, so `children` and `blocked_by` are present (empty lists for a lone card).

`brd list [--status <s>] [--parent <id>] [--pretty]` — prints a list of `_card_detail` dicts. Filters pass straight through to `db.list_cards(conn, status=..., parent_id=...)`. The `parent_id` kwarg is included **only** when `--parent` was supplied, because `db.list_cards` uses an `_UNSET` sentinel (`src/brd/db.py:137-158`) to distinguish "no parent filter" from "filter on `parent_id IS NULL`"; passing `None` unconditionally would silently restrict results to root cards.

## Error paths

| trigger | envelope `error.type` | exit |
|---|---|---|
| any of the three commands run outside a registered project (`master.ProjectNotFoundError` out of `_project_conn`) | `ProjectNotFoundError` | 1 |
| `add` with unknown `--parent` or unknown `--blocked-by` id (`core.CardNotFoundError`) | `CardNotFoundError` | 1 |
| `add` creating a parent or blocker cycle (`core.CycleError`) | `CycleError` | 1 |
| `show <id>` for a nonexistent id | `CardNotFoundError` | 1 |

Error types are the exception class name (`type(exc).__name__` for the `add` tuple catch, literal names elsewhere), messages are `str(exc)`. No stack traces escape; nothing is raised past the typer boundary except `typer.Exit(code=1)`.

## Test list

Per the testing standard in `docs/superpowers/specs/2026-09-17-brd-cli-design.md:183-192`, everything below is the **`cli.py` end-to-end tier**: `CliRunner`-driven invocations of `app`, against a real SQLite file under a per-test monkeypatched `XDG_DATA_HOME`, with no mocking. They all belong in `tests/test_cli.py`. None of this subtask's behavior belongs in the `core.py` / `db.py` unit tier (owned by #9/#10 and #6/#7) — the helpers being exercised are CLI-layer glue.

- Fixture `initialized_project(isolated_env)` — invokes `["init"]` and returns the isolated env.
- `test_add_creates_card` — `add --title "My card"` exits 0; `data.title == "My card"`, `data.status == "todo"`.
- `test_show_returns_card_detail` — add, then `show <id>`: exits 0, `data.id` matches, `status == "todo"`, `children == []`, `blocked_by == []`.
- `test_show_unknown_card_errors` — `show nope`: non-zero exit, `ok is False`, `error.type == "CardNotFoundError"`.
- `test_list_returns_all_cards` — two adds, then `list`: `len(data) == 2`.
- `test_list_filters_by_status` — written now, **expected to fail until #15 lands** because it drives `update --status done`. Implementation runs `uv run pytest tests/test_cli.py -k "not filters_by_status"` for this subtask's red/green cycle, exactly as the plan directs (lines 2054-2060).
- `test_commands_outside_project_error` — `XDG_DATA_HOME` and cwd pointed at an unregistered directory; `add --title X` exits non-zero with `error.type == "ProjectNotFoundError"`.

## Verification

- Full suite: `uv run pytest` (baseline before this subtask: 119 passed). Expect one known failure, `test_list_filters_by_status`, until #15 lands.
- Typecheck: none configured.
- Lint: none configured (`pyproject.toml` has no ruff/flake8 section).

---

# `brd add` / `show` / `list` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `add`, `show <id>`, and `list` typer commands (plus the `_project_conn` and `_card_detail` helpers they share) to `src/brd/cli.py`, all speaking the standard envelope.

**Architecture:** `src/brd/cli.py` is the only production file touched. Each command resolves the current project through the new `_project_conn()` helper (which raises `master.ProjectNotFoundError` outside a registered project), does its work against the project SQLite connection through the already-existing `core`/`db` functions, serializes cards through the new `_card_detail()` helper, and prints via `output.ok_envelope` / `output.error_envelope` / `output.print_result`. Connections are always closed in a `finally`. Tests are appended to `tests/test_cli.py` as `CliRunner` end-to-end tests driving the real CLI against a real SQLite file under a monkeypatched `XDG_DATA_HOME` — no mocks.

**Tech Stack:** Python >= 3.12, typer >= 0.27.2, stdlib `sqlite3`, pytest >= 9.1.1 with `typer.testing.CliRunner`, `uv` as runner.

**Spec:** `docs/superpowers/specs/issue-14-design.md` (reproduced verbatim above).

## Global Constraints

- Modify `src/brd/cli.py` and `tests/test_cli.py` only. Do not touch `src/brd/output.py`, `src/brd/core.py`, `src/brd/db.py`, `src/brd/master.py`, `src/brd/models.py`, or the existing `init` / `projects` commands.
- Every command path prints exactly one envelope through `output.print_result(envelope, pretty)` and exits non-zero (`raise typer.Exit(code=1)`) whenever `ok` is `False`. No exception may escape past the typer boundary.
- Every command closes its sqlite connection in a `finally` block, on success and on error alike.
- `_project_conn() -> tuple[sqlite3.Connection, master.Project]` — this exact name and signature is reused verbatim by issues #15 and #16; do not rename it or change its return shape.
- `list` is registered as `@app.command(name="list")` on a function named `list_cards_cmd` (the name `list` shadows the builtin).
- `db.list_cards`'s `parent_id` parameter defaults to a module-private `_UNSET` sentinel (`src/brd/db.py:137-158`). Pass `parent_id=` **only** when `--parent` was supplied; passing `None` unconditionally filters to root cards.
- Pretty flag is always declared as `typer.Option(False, "--pretty", "--human", help="Human-readable output.")`, matching the existing `init` command (`src/brd/cli.py:25-27`).
- Verification: `uv run pytest`. Baseline before this work: 119 passed. No typecheck and no lint are configured for this repo.
- `test_list_filters_by_status` drives `brd update`, which is owned by issue #15 and does not exist yet. It is written in Task 3 and is a **known failure** until #15 lands; every green gate in this plan runs `-k "not filters_by_status"`.

## File Structure

- `src/brd/cli.py` (modify) — currently holds `app`, the `main()` callback, and the `init` / `projects` commands (54 lines). This plan appends two private helpers and three commands below `projects`, and widens the import block. It stays one focused file: the whole CLI surface for a single-binary tool, matching the established pattern.
- `tests/test_cli.py` (modify) — currently holds the help tests, the `isolated_env` fixture (lines 30-36) and the `init` / `projects` tests (98 lines). This plan appends the `initialized_project` fixture and seven tests.

---

### Task 1: `_project_conn`, `_card_detail`, and the `add` command

**Files:**
- Modify: `src/brd/cli.py:1-6` (imports) and append below `src/brd/cli.py:50`
- Test: `tests/test_cli.py` (append below line 97)

**Interfaces:**
- Consumes: `master.resolve_current_project(start: Path) -> Project` and `master.ProjectNotFoundError` (`src/brd/master.py:85-101`); `db.connect(db_path: Path) -> sqlite3.Connection` (`src/brd/db.py:7-12`); `db.list_blockers_of(conn, card_id) -> list[str]` (`src/brd/db.py:181-185`); `db.list_children(conn, parent_id) -> list[Card]` (`src/brd/db.py:188-192`); `core.create_card(conn, title, description=None, parent_id=None, blocked_by=None) -> Card` and `core.CardNotFoundError` / `core.CycleError` (`src/brd/core.py:80-111`); `core.resolve_status(conn, card) -> str` (`src/brd/core.py:13-31`); `output.ok_envelope(data) -> dict`, `output.error_envelope(error_type: str, message: str) -> dict`, `output.print_result(envelope: dict, pretty: bool) -> None` (`src/brd/output.py`); the `isolated_env` fixture (`tests/test_cli.py:30-36`) and the `init` command (`src/brd/cli.py:20-38`).
- Produces: `_project_conn() -> tuple[sqlite3.Connection, master.Project]`; `_card_detail(conn: sqlite3.Connection, card: Card) -> dict` with keys `id`, `title`, `description`, `status`, `parent_id`, `created_at`, `updated_at`, `blocked_by`, `children`; the `brd add` command; the pytest fixture `initialized_project`. Tasks 2 and 3 — and issues #15/#16 — call `_project_conn` and `_card_detail` unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py` (after the last existing test, line 97):

```python
@pytest.fixture
def initialized_project(isolated_env):
    runner.invoke(app, ["init"])
    return isolated_env


def test_add_creates_card(initialized_project):
    result = runner.invoke(app, ["add", "--title", "My card"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["title"] == "My card"
    assert payload["data"]["status"] == "todo"


def test_add_with_unknown_parent_errors(initialized_project):
    result = runner.invoke(app, ["add", "--title", "Child", "--parent", "nope"])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "CardNotFoundError"


def test_commands_outside_project_error(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)

    result = runner.invoke(app, ["add", "--title", "X"])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "ProjectNotFoundError"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v -k "add or outside_project"`
Expected: FAIL — all three tests fail because typer reports `No such command 'add'` (exit code 2, and `json.loads` raises `JSONDecodeError` on the usage text).

- [ ] **Step 3: Widen the import block**

Replace `src/brd/cli.py:1-6`:

```python
import dataclasses
import sqlite3
from pathlib import Path

import typer

from brd import core, db, master, output
from brd.models import Card
```

- [ ] **Step 4: Add the helpers and the `add` command**

Append to `src/brd/cli.py`, after the `projects` command (line 50) and **above** the `if __name__ == "__main__":` block:

```python
def _project_conn() -> tuple[sqlite3.Connection, master.Project]:
    project = master.resolve_current_project(Path.cwd())
    conn = db.connect(Path(project.db_path))
    return conn, project


def _card_detail(conn: sqlite3.Connection, card: Card) -> dict:
    return {
        "id": card.id,
        "title": card.title,
        "description": card.description,
        "status": core.resolve_status(conn, card),
        "parent_id": card.parent_id,
        "created_at": card.created_at,
        "updated_at": card.updated_at,
        "blocked_by": db.list_blockers_of(conn, card.id),
        "children": [child.id for child in db.list_children(conn, card.id)],
    }


@app.command()
def add(
    title: str = typer.Option(..., "--title", help="Card title."),
    description: str | None = typer.Option(
        None, "--description", help="Card description."
    ),
    parent: str | None = typer.Option(None, "--parent", help="Parent card id."),
    blocked_by: list[str] = typer.Option(
        [], "--blocked-by", help="Id of a card this one is blocked by (repeatable)."
    ),
    pretty: bool = typer.Option(
        False, "--pretty", "--human", help="Human-readable output."
    ),
) -> None:
    """Create a card."""
    try:
        conn, _ = _project_conn()
    except master.ProjectNotFoundError as exc:
        output.print_result(
            output.error_envelope("ProjectNotFoundError", str(exc)), pretty
        )
        raise typer.Exit(code=1)

    try:
        card = core.create_card(
            conn,
            title=title,
            description=description,
            parent_id=parent,
            blocked_by=list(blocked_by),
        )
        envelope = output.ok_envelope(_card_detail(conn, card))
    except (core.CardNotFoundError, core.CycleError) as exc:
        output.print_result(
            output.error_envelope(type(exc).__name__, str(exc)), pretty
        )
        raise typer.Exit(code=1)
    finally:
        conn.close()

    output.print_result(envelope, pretty)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v -k "add or outside_project"`
Expected: PASS (3 passed).

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest`
Expected: PASS, 122 passed (119 baseline + 3 new).

- [ ] **Step 7: Commit**

```bash
git add src/brd/cli.py tests/test_cli.py
git commit -m "Add brd add command with _project_conn and _card_detail helpers"
```

---

### Task 2: The `show <id>` command

**Files:**
- Modify: append to `src/brd/cli.py` below the `add` command
- Test: `tests/test_cli.py` (append below the Task 1 tests)

**Interfaces:**
- Consumes: `_project_conn() -> tuple[sqlite3.Connection, master.Project]` and `_card_detail(conn, card) -> dict` (Task 1); the `initialized_project` fixture (Task 1); `db.get_card(conn, card_id) -> Card | None` (`src/brd/db.py:125-127`); `core.CardNotFoundError` (`src/brd/core.py:58-59`); `master.ProjectNotFoundError`; `output.ok_envelope` / `output.error_envelope` / `output.print_result`.
- Produces: the `brd show <card_id>` command, printing the same `_card_detail` dict shape `add` returns.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_show_returns_card_detail(initialized_project):
    add_result = runner.invoke(app, ["add", "--title", "My card"])
    card_id = json.loads(add_result.stdout)["data"]["id"]

    result = runner.invoke(app, ["show", card_id])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["id"] == card_id
    assert payload["data"]["status"] == "todo"
    assert payload["data"]["children"] == []
    assert payload["data"]["blocked_by"] == []


def test_show_unknown_card_errors(initialized_project):
    result = runner.invoke(app, ["show", "nope"])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "CardNotFoundError"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v -k "show"`
Expected: FAIL — typer reports `No such command 'show'` (exit code 2, `json.loads` raises `JSONDecodeError`).

- [ ] **Step 3: Write the `show` command**

Append to `src/brd/cli.py`, directly after the `add` command and above `if __name__ == "__main__":`:

```python
@app.command()
def show(
    card_id: str = typer.Argument(..., help="Id of the card to show."),
    pretty: bool = typer.Option(
        False, "--pretty", "--human", help="Human-readable output."
    ),
) -> None:
    """Show a single card's full detail."""
    try:
        conn, _ = _project_conn()
    except master.ProjectNotFoundError as exc:
        output.print_result(
            output.error_envelope("ProjectNotFoundError", str(exc)), pretty
        )
        raise typer.Exit(code=1)

    try:
        card = db.get_card(conn, card_id)
        if card is None:
            raise core.CardNotFoundError(f"no card with id {card_id}")
        envelope = output.ok_envelope(_card_detail(conn, card))
    except core.CardNotFoundError as exc:
        output.print_result(
            output.error_envelope("CardNotFoundError", str(exc)), pretty
        )
        raise typer.Exit(code=1)
    finally:
        conn.close()

    output.print_result(envelope, pretty)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v -k "show"`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: PASS, 124 passed.

- [ ] **Step 6: Commit**

```bash
git add src/brd/cli.py tests/test_cli.py
git commit -m "Add brd show command"
```

---

### Task 3: The `list` command

**Files:**
- Modify: append to `src/brd/cli.py` below the `show` command
- Test: `tests/test_cli.py` (append below the Task 2 tests)

**Interfaces:**
- Consumes: `_project_conn() -> tuple[sqlite3.Connection, master.Project]` and `_card_detail(conn, card) -> dict` (Task 1); the `initialized_project` fixture (Task 1); `db.list_cards(conn, status: str | None = None, parent_id: str | None = _UNSET) -> list[Card]` (`src/brd/db.py:137-158`); `master.ProjectNotFoundError`; `output.ok_envelope` / `output.print_result`.
- Produces: the `brd list` command, registered as `@app.command(name="list")` on `list_cards_cmd`, printing a JSON list of `_card_detail` dicts.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`. `test_list_filters_by_status` drives `brd update`, which issue #15 delivers — it is written now and stays red until then; every run below excludes it with `-k "not filters_by_status"`:

```python
def test_list_returns_all_cards(initialized_project):
    runner.invoke(app, ["add", "--title", "A"])
    runner.invoke(app, ["add", "--title", "B"])
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert len(payload["data"]) == 2


def test_list_with_no_parent_filter_includes_child_cards(initialized_project):
    parent_result = runner.invoke(app, ["add", "--title", "Parent"])
    parent_id = json.loads(parent_result.stdout)["data"]["id"]
    runner.invoke(app, ["add", "--title", "Child", "--parent", parent_id])

    result = runner.invoke(app, ["list"])
    payload = json.loads(result.stdout)
    assert {item["title"] for item in payload["data"]} == {"Parent", "Child"}


def test_list_filters_by_parent(initialized_project):
    parent_result = runner.invoke(app, ["add", "--title", "Parent"])
    parent_id = json.loads(parent_result.stdout)["data"]["id"]
    runner.invoke(app, ["add", "--title", "Child", "--parent", parent_id])

    result = runner.invoke(app, ["list", "--parent", parent_id])
    payload = json.loads(result.stdout)
    assert [item["title"] for item in payload["data"]] == ["Child"]


def test_list_filters_by_status(initialized_project):
    add_result = runner.invoke(app, ["add", "--title", "A"])
    card_id = json.loads(add_result.stdout)["data"]["id"]
    runner.invoke(app, ["update", card_id, "--status", "done"])
    runner.invoke(app, ["add", "--title", "B"])

    result = runner.invoke(app, ["list", "--status", "done"])
    payload = json.loads(result.stdout)
    assert len(payload["data"]) == 1
    assert payload["data"][0]["id"] == card_id
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v -k "test_list_ and not filters_by_status"`
Expected: FAIL (3 failed) — typer reports `No such command 'list'` (exit code 2, `json.loads` raises `JSONDecodeError`).

Note: use `test_list_` (not bare `list`) as the keyword filter. The existing tests `test_projects_lists_registered_projects` and `test_projects_with_empty_registry_returns_empty_list` also contain the substring `list` and would otherwise be swept into the selection (and pass), skewing the pass/fail count away from the "3 failed" expected here.

- [ ] **Step 3: Write the `list` command**

Append to `src/brd/cli.py`, directly after the `show` command and above `if __name__ == "__main__":`:

```python
@app.command(name="list")
def list_cards_cmd(
    status: str | None = typer.Option(
        None, "--status", help="Filter by stored status."
    ),
    parent: str | None = typer.Option(
        None, "--parent", help="Only cards whose parent is this card id."
    ),
    pretty: bool = typer.Option(
        False, "--pretty", "--human", help="Human-readable output."
    ),
) -> None:
    """List cards, optionally filtered."""
    try:
        conn, _ = _project_conn()
    except master.ProjectNotFoundError as exc:
        output.print_result(
            output.error_envelope("ProjectNotFoundError", str(exc)), pretty
        )
        raise typer.Exit(code=1)

    try:
        # db.list_cards uses an _UNSET sentinel for parent_id, so only pass the
        # kwarg when --parent was given; passing None means "parent IS NULL".
        kwargs: dict = {"status": status}
        if parent is not None:
            kwargs["parent_id"] = parent
        cards = db.list_cards(conn, **kwargs)
        envelope = output.ok_envelope(
            [_card_detail(conn, card) for card in cards]
        )
    finally:
        conn.close()

    output.print_result(envelope, pretty)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v -k "test_list_ and not filters_by_status"`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the full suite minus the known-red test**

Run: `uv run pytest -k "not filters_by_status"`
Expected: PASS, 127 passed, 1 deselected.

- [ ] **Step 6: Run the unfiltered full suite and confirm the single known failure**

Run: `uv run pytest`
Expected: 127 passed, 1 failed — and the only failure is `tests/test_cli.py::test_list_filters_by_status`, failing because `brd update` does not exist yet (issue #15). Any other failure is a real regression and must be fixed before committing.

- [ ] **Step 7: Commit**

```bash
git add src/brd/cli.py tests/test_cli.py
git commit -m "Add brd list command"
```

---

## Done when

- `brd add`, `brd show <id>`, and `brd list` exist in `src/brd/cli.py` alongside the untouched `init` / `projects` commands, sharing `_project_conn()` and `_card_detail()`.
- `uv run pytest -k "not filters_by_status"` is fully green.
- `uv run pytest` shows exactly one failure, `tests/test_cli.py::test_list_filters_by_status`, which turns green when issue #15 adds `brd update`.
