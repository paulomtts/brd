<!-- task-pipeline: validated -->
# Spec (verbatim): `docs/superpowers/specs/issue-15-design.md`

---

# Issue #15 — CLI: `update`, `block`, `unblock` commands

Narrows the agreed milestone design (`docs/superpowers/specs/2026-09-17-brd-cli-design.md`) and plan Task 14 (`docs/superpowers/plans/2026-09-17-brd-cli.md:2190-2364`) to one subtask. No new design decisions.

## Scope

Add three typer commands to `src/brd/cli.py` and their end-to-end tests to `tests/test_cli.py`. Nothing else.

In scope:
- `brd update <card_id> [--title] [--description] [--status] [--parent] [--clear-parent] [--pretty/--human]`
- `brd block <card_id> --by <blocker_id> [--pretty/--human]`
- `brd unblock <card_id> --by <blocker_id> [--pretty/--human]`

Out of scope (owned by sibling subtasks, must not be touched): `core.py` operations (#9-#11 — already implemented: `core.update_card` at `src/brd/core.py:114`, `core.block_card` at `:150`, `core.unblock_card` at `:158`, `core.CLEAR_PARENT` at `:66`); `output.py` envelope/pretty rendering and `init`/`projects`/`_project_conn` (#13); `add`/`show`/`list` and `_card_detail` (#14); `tree`/`next` (#16); README and the full integration test (#17). Also out of scope: `--verbose` stack-trace opt-in.

Ordering dependency: #15 builds on top of #13 and #14, which are already implemented on this branch (`output.*`, `_project_conn`, `_card_detail`, `brd add`, `brd show`, `brd list`, and the `initialized_project` test fixture all exist). #15 consumes them as-is and does not reimplement them.

## Observable behaviour

All three commands resolve the current project through `_project_conn()` (`.brd` marker walk-up), do their work, always `conn.close()`, and print a single JSON envelope on stdout: `{"ok": true, "data": {...}}` on success, `{"ok": false, "error": {"type": ..., "message": ...}}` on failure with a non-zero exit code. `--pretty`/`--human` switches to formatted text via `output.print_result(envelope, pretty)`. JSON stays the default.

- `update`: applies only the flags given; `--parent <id>` reparents, `--clear-parent` passes `core.CLEAR_PARENT` to set `parent_id` to NULL (when both are given, `--clear-parent` wins, matching the plan's `core.CLEAR_PARENT if clear_parent else parent`). `--status blocked` is rejected — `blocked` is derived, never settable. Success data is the `_card_detail(conn, card)` payload (resolved status, parent, children, blockers).
- `block`: adds a `blocked_by` edge via `core.block_card`, then re-reads the card with `db.get_card` and emits `_card_detail`. The card's resolved status becomes `blocked` while the blocker is not `done`.
- `unblock`: removes the edge via `core.unblock_card`, re-reads, emits `_card_detail`. Removing a non-existent edge is not an error (`core.unblock_card` only requires the card to exist); the card returns to its stored status (e.g. `todo`) once no incomplete blockers remain.

## Error paths

Typed exceptions from core/master are caught at the `cli.py` boundary and converted to `output.error_envelope(type(exc).__name__, str(exc))` + `typer.Exit(code=1)`. No stack traces.

| command | caught | envelope `error.type` |
|---|---|---|
| all three | `master.ProjectNotFoundError` from `_project_conn()` | `ProjectNotFoundError` |
| `update` | `core.CardNotFoundError`, `core.CycleError`, `core.InvalidStatusError` | matching class name |
| `block` | `core.CardNotFoundError`, `core.CycleError` | matching class name |
| `unblock` | `core.CardNotFoundError` | `CardNotFoundError` |

`CycleError` covers both parent cycles (`update --parent`) and `blocked_by` cycles (`block`), consistent with the design's hierarchy-vs-blocking split. The connection is closed in a `finally` on every path, including the error paths that exit 1.

## Tests

Test-placement rule: the design spec's Testing section (`2026-09-17-brd-cli-design.md:183-192`) assigns `core.py`/`db.py` unit tests against a temp SQLite file, and `cli.py` end-to-end tests driving the full command surface against a temp XDG data dir monkeypatched per test. This subtask adds no core/db logic — only typer commands — so **every test below is a CLI-tier end-to-end test in `tests/test_cli.py`**, driven with `CliRunner` against the module-level `runner`/`app` and the `initialized_project` fixture established by #13/#14. None belong in `tests/test_core.py`.

| test | tier | asserts |
|---|---|---|
| `test_update_changes_title` | CLI end-to-end (`tests/test_cli.py`) | `add --title Old`, then `update <id> --title New` → `data.title == "New"` |
| `test_update_rejects_blocked_status` | CLI end-to-end (`tests/test_cli.py`) | `update <id> --status blocked` → exit code != 0 and `error.type == "InvalidStatusError"` |
| `test_block_and_unblock` | CLI end-to-end (`tests/test_cli.py`) | `block a --by b` exits 0 and `show a` reports status `blocked`; `unblock a --by b` exits 0 and `show a` reports status `todo` |
| `test_block_rejects_cycle` | CLI end-to-end (`tests/test_cli.py`) | after `block a --by b`, `block b --by a` → exit code != 0 and `error.type == "CycleError"` |

Verification: `uv run pytest tests/test_cli.py -v -k "update or block"` (expected to fail first with "No such command 'update'"), then `uv run pytest tests/test_cli.py -v` green (all pre-existing #13/#14 tests, including `test_list_filters_by_status`, already pass and must keep passing).

## Deliverable

Changed files: `src/brd/cli.py`, `tests/test_cli.py` only. Commit message: `Add brd update, block, and unblock commands`.

---

# brd `update` / `block` / `unblock` Commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `brd update`, `brd block`, and `brd unblock` typer commands to the CLI, driven by end-to-end tests.

**Architecture:** Three thin typer commands appended to `src/brd/cli.py`. Each resolves the project with the existing `_project_conn()` helper, delegates all logic to already-implemented `core.py` functions (`update_card`, `block_card`, `unblock_card`, sentinel `CLEAR_PARENT`), renders success through `_card_detail()` + `output.ok_envelope()`, maps typed exceptions to `output.error_envelope(type(exc).__name__, str(exc))` with `typer.Exit(code=1)`, and closes the connection in a `finally`. No new logic in `core.py`, `db.py`, or `output.py`.

**Tech Stack:** Python 3.11+, typer, sqlite3 (stdlib), pytest + `typer.testing.CliRunner`, `uv` for running.

**Spec:** `docs/superpowers/specs/issue-15-design.md` (prepended verbatim above).

## Global Constraints

- Changed files are limited to `src/brd/cli.py` and `tests/test_cli.py`. Do not edit `src/brd/core.py`, `src/brd/db.py`, `src/brd/output.py`, or `src/brd/master.py`.
- Output envelope: `{"ok": true, "data": ...}` on success; `{"ok": false, "error": {"type": ..., "message": ...}}` with a non-zero exit code on failure. JSON is the default; `--pretty`/`--human` switches to text via `output.print_result(envelope, pretty)`.
- `blocked` is a derived status and must never be settable via `--status`.
- No stack traces on error paths; `--verbose` is out of scope.
- Type annotations use PEP 604 unions (`str | None`), matching the existing `src/brd/cli.py` — do **not** import `typing.Optional` (the plan text in `docs/superpowers/plans/2026-09-17-brd-cli.md:2263` uses `Optional`, which is not imported in this file).
- `conn.close()` happens in a `finally` on every path, including error paths that exit 1.
- Single commit at the end, message exactly: `Add brd update, block, and unblock commands`.

---

### Task 1: `brd update`, `brd block`, `brd unblock`

**Files:**
- Modify: `src/brd/cli.py` (append after `list_cards_cmd`, which ends at line 184, and before the `if __name__ == "__main__":` block at lines 187-188)
- Test: `tests/test_cli.py` (append after `test_list_filters_by_status`, which ends at line 264; also modify the `@pytest.mark.parametrize` list at lines 152-159)

**Interfaces:**
- Consumes (all already on this branch): `_project_conn() -> tuple[sqlite3.Connection, master.Project]` (`src/brd/cli.py:55`), `_card_detail(conn: sqlite3.Connection, card: Card) -> dict` (`src/brd/cli.py:61`), `core.update_card(conn, card_id, title=None, description=None, status=None, parent_id=None) -> Card` (`src/brd/core.py:114`), `core.block_card(conn, card_id, blocker_id) -> None` (`src/brd/core.py:150`), `core.unblock_card(conn, card_id, blocker_id) -> None` (`src/brd/core.py:158`), `core.CLEAR_PARENT` (`src/brd/core.py:66`), `core.CardNotFoundError`, `core.CycleError`, `core.InvalidStatusError`, `db.get_card(conn, card_id) -> Card | None` (`src/brd/db.py:125`), `master.ProjectNotFoundError`, `output.ok_envelope`, `output.error_envelope`, `output.print_result`; test fixtures `isolated_env` and `initialized_project` (`tests/test_cli.py:30,100`) and the module-level `runner` / `app` (`tests/test_cli.py:6-8`).
- Produces: typer commands `update` (argument `card_id`, options `--title`, `--description`, `--status`, `--parent`, `--clear-parent`, `--pretty`/`--human`), `block` and `unblock` (argument `card_id`, required option `--by`, option `--pretty`/`--human`). Task 16 (`tree`/`next`) appends after these.

- [ ] **Step 1: Write the failing `update` tests**

Append to the end of `tests/test_cli.py`:

```python
def test_update_changes_title(initialized_project):
    add_result = runner.invoke(app, ["add", "--title", "Old"])
    card_id = json.loads(add_result.stdout)["data"]["id"]

    result = runner.invoke(app, ["update", card_id, "--title", "New"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["title"] == "New"


def test_update_rejects_blocked_status(initialized_project):
    add_result = runner.invoke(app, ["add", "--title", "A"])
    card_id = json.loads(add_result.stdout)["data"]["id"]

    result = runner.invoke(app, ["update", card_id, "--status", "blocked"])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "InvalidStatusError"
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v -k "update"`
Expected: FAIL — both tests error out; `result.stdout` contains `No such command 'update'` so `json.loads` raises `json.JSONDecodeError`.

- [ ] **Step 3: Implement the `update` command**

In `src/brd/cli.py`, insert this after the `list_cards_cmd` function (after line 184) and before `if __name__ == "__main__":`:

```python
@app.command()
def update(
    card_id: str = typer.Argument(..., help="Id of the card to update."),
    title: str | None = typer.Option(None, "--title", help="New title."),
    description: str | None = typer.Option(
        None, "--description", help="New description."
    ),
    status: str | None = typer.Option(
        None, "--status", help="New stored status (cannot be 'blocked')."
    ),
    parent: str | None = typer.Option(None, "--parent", help="New parent card id."),
    clear_parent: bool = typer.Option(
        False, "--clear-parent", help="Detach the card from its parent."
    ),
    pretty: bool = typer.Option(
        False, "--pretty", "--human", help="Human-readable output."
    ),
) -> None:
    """Edit a card's fields."""
    try:
        conn, _ = _project_conn()
    except master.ProjectNotFoundError as exc:
        output.print_result(
            output.error_envelope("ProjectNotFoundError", str(exc)), pretty
        )
        raise typer.Exit(code=1)

    try:
        parent_arg = core.CLEAR_PARENT if clear_parent else parent
        card = core.update_card(
            conn,
            card_id,
            title=title,
            description=description,
            status=status,
            parent_id=parent_arg,
        )
        envelope = output.ok_envelope(_card_detail(conn, card))
    except (core.CardNotFoundError, core.CycleError, core.InvalidStatusError) as exc:
        output.print_result(
            output.error_envelope(type(exc).__name__, str(exc)), pretty
        )
        raise typer.Exit(code=1)
    finally:
        conn.close()

    output.print_result(envelope, pretty)
```

- [ ] **Step 4: Run the `update` tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v -k "update"`
Expected: PASS — `test_update_changes_title` and `test_update_rejects_blocked_status` both green.

- [ ] **Step 5: Write the failing `block` / `unblock` tests**

Append to the end of `tests/test_cli.py`:

```python
def test_block_and_unblock(initialized_project):
    a = json.loads(runner.invoke(app, ["add", "--title", "A"]).stdout)["data"]
    b = json.loads(runner.invoke(app, ["add", "--title", "B"]).stdout)["data"]

    block_result = runner.invoke(app, ["block", a["id"], "--by", b["id"]])
    assert block_result.exit_code == 0
    assert json.loads(block_result.stdout)["data"]["blocked_by"] == [b["id"]]
    show_result = runner.invoke(app, ["show", a["id"]])
    assert json.loads(show_result.stdout)["data"]["status"] == "blocked"

    unblock_result = runner.invoke(app, ["unblock", a["id"], "--by", b["id"]])
    assert unblock_result.exit_code == 0
    show_result = runner.invoke(app, ["show", a["id"]])
    assert json.loads(show_result.stdout)["data"]["status"] == "todo"


def test_block_rejects_cycle(initialized_project):
    a = json.loads(runner.invoke(app, ["add", "--title", "A"]).stdout)["data"]
    b = json.loads(runner.invoke(app, ["add", "--title", "B"]).stdout)["data"]
    runner.invoke(app, ["block", a["id"], "--by", b["id"]])

    result = runner.invoke(app, ["block", b["id"], "--by", a["id"]])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "CycleError"
```

- [ ] **Step 6: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v -k "block"`
Expected: FAIL — `result.stdout` contains `No such command 'block'`, so `json.loads` raises `json.JSONDecodeError`.

- [ ] **Step 7: Implement the `block` and `unblock` commands**

In `src/brd/cli.py`, append after the `update` function added in Step 3 and before `if __name__ == "__main__":`:

```python
@app.command()
def block(
    card_id: str = typer.Argument(..., help="Id of the card to block."),
    by: str = typer.Option(..., "--by", help="Id of the card blocking it."),
    pretty: bool = typer.Option(
        False, "--pretty", "--human", help="Human-readable output."
    ),
) -> None:
    """Mark a card as blocked by another card."""
    try:
        conn, _ = _project_conn()
    except master.ProjectNotFoundError as exc:
        output.print_result(
            output.error_envelope("ProjectNotFoundError", str(exc)), pretty
        )
        raise typer.Exit(code=1)

    try:
        core.block_card(conn, card_id, by)
        card = db.get_card(conn, card_id)
        if card is None:
            raise core.CardNotFoundError(f"no card with id {card_id}")
        envelope = output.ok_envelope(_card_detail(conn, card))
    except (core.CardNotFoundError, core.CycleError) as exc:
        output.print_result(
            output.error_envelope(type(exc).__name__, str(exc)), pretty
        )
        raise typer.Exit(code=1)
    finally:
        conn.close()

    output.print_result(envelope, pretty)


@app.command()
def unblock(
    card_id: str = typer.Argument(..., help="Id of the card to unblock."),
    by: str = typer.Option(..., "--by", help="Id of the blocker to remove."),
    pretty: bool = typer.Option(
        False, "--pretty", "--human", help="Human-readable output."
    ),
) -> None:
    """Remove a blocked-by relationship."""
    try:
        conn, _ = _project_conn()
    except master.ProjectNotFoundError as exc:
        output.print_result(
            output.error_envelope("ProjectNotFoundError", str(exc)), pretty
        )
        raise typer.Exit(code=1)

    try:
        core.unblock_card(conn, card_id, by)
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

- [ ] **Step 8: Run the `block` / `unblock` tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v -k "update or block"`
Expected: PASS — all four new tests green.

- [ ] **Step 9: Write the failing outside-project error test for the three new commands**

The spec's error table requires all three commands to emit a `ProjectNotFoundError` envelope with a non-zero exit when run outside a project. `tests/test_cli.py` already has a parametrized test for this; extend its case list. Replace lines 152-159 of `tests/test_cli.py`:

```python
@pytest.mark.parametrize(
    "args",
    [
        ["add", "--title", "X"],
        ["show", "some-id"],
        ["list"],
    ],
)
```

with:

```python
@pytest.mark.parametrize(
    "args",
    [
        ["add", "--title", "X"],
        ["show", "some-id"],
        ["list"],
        ["update", "some-id", "--title", "X"],
        ["block", "some-id", "--by", "other-id"],
        ["unblock", "some-id", "--by", "other-id"],
    ],
)
```

- [ ] **Step 10: Run the parametrized test to confirm the new cases pass**

Run: `uv run pytest tests/test_cli.py -v -k "outside_project"`
Expected: PASS — 6 cases, including the three new ones. (This one is green on arrival because Step 3/Step 7 already wired the `ProjectNotFoundError` branch; if any new case fails, the corresponding command is missing its `_project_conn()` try/except.)

- [ ] **Step 11: Run the full test suite**

Run: `uv run pytest`
Expected: PASS — every test green, including the pre-existing `test_list_filters_by_status` and the rest of `tests/test_cli.py`, `tests/test_core.py`, `tests/test_db.py`.

- [ ] **Step 12: Confirm no out-of-scope files changed**

Run: `git status --porcelain`
Expected: the only modified (` M`) source paths are `src/brd/cli.py` and `tests/test_cli.py`. Untracked plan/spec docs under `docs/superpowers/` and the `.claude/` directory may also be listed and are fine — they are not staged by Step 13. If any other file under `src/` or `tests/` is modified, revert it.

- [ ] **Step 13: Commit**

```bash
git add src/brd/cli.py tests/test_cli.py
git commit -m "Add brd update, block, and unblock commands"
```
