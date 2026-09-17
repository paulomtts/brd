<!-- task-pipeline: validated -->
# Issue #16 — 1.15 CLI: `tree` and `next` commands

Subtask of story #1 "Implement brd CLI v1". Implements Task 15 of `docs/superpowers/plans/2026-09-17-brd-cli.md` (lines 2366-2492), narrowing `docs/superpowers/specs/2026-09-17-brd-cli-design.md` (CLI surface lines 137-153, envelope lines 160-167, architecture lines 33-52, testing lines 183-192).

## Scope

Add exactly two typer commands to `src/brd/cli.py`, inserted after the existing command definitions and before `if __name__ == "__main__":`, plus their end-to-end tests in `tests/test_cli.py`.

- `brd tree [<id>] [--pretty|--human]`
- `brd next [--limit N] [--pretty|--human]`

Both are thin wrappers: resolve the project connection, call `core.py`, render through `output.py`. No SQL in `cli.py`. No changes to `core.py`, `db.py`, `master.py`, `output.py`, `models.py`, or `paths.py` — `core.build_tree` (core.py:181-187), `core.next_cards` (core.py:163-166) and `output.render_tree_text` (output.py:19-26) are already implemented and are consumed as-is.

Out of scope: `update` / `block` / `unblock` (issue #15, already present in this worktree's `cli.py:187-301` — do not touch them); the full end-to-end integration test and README (issue #17); a `--verbose` flag or stack traces of any kind; any recomputation of status inside `cli.py`.

## Observable behavior

`brd tree`

- With no `<id>`: `core.build_tree(conn, root_id=None)` returns one node per top-level card (`parent_id IS NULL`), each node a dict of `id`, `title`, `status`, `blocked_by`, `children` with `children` recursively the same shape.
- With `<id>`: returns a single-element list whose one node is that card, with its subtree under `children`.
- Default (JSON) output: `{"ok": true, "data": [<nodes>]}` on stdout, exit code 0.
- `--pretty` / `--human` on success: prints `output.render_tree_text(envelope["data"])` — two-space indent per level, one line per node formatted `- <title> [<status>] (<id>)` — instead of the JSON envelope. `--pretty` on failure still goes through `output.print_result`, which renders `Error (<type>): <message>`.
- `status` in each node is whatever `core.resolve_status` derived (`blocked` is derived, never stored); `tree` surfaces it verbatim.

`brd next`

- Returns ready `todo` cards, oldest-created first, as a JSON list of the same detail shape `list`/`show` emit — produced by mapping `core.next_cards(conn, limit=limit)` through the existing `_card_detail` helper (cli.py:61-72), so each entry has `id`, `title`, `description`, `status`, `parent_id`, `created_at`, `updated_at`, `blocked_by`, `children`.
- `--limit N` truncates to the first N; omitted means all ready cards.
- No special-casing of parent vs leaf cards: a parent card with unfinished children is still returned if it is `todo` and unblocked.
- Never raises on unknown ids — there is no id input — so it has no `CardNotFoundError` branch. Empty board yields `{"ok": true, "data": []}`, exit 0.

## Error paths

Both commands use the identical `_project_conn()` (cli.py:55-58) try/except and `conn.close()` in `finally` pattern the existing commands use (cli.py:90-96, 126-132, 163-169):

| Condition | Envelope | Exit |
| --- | --- | --- |
| cwd not inside a registered project | `{"ok": false, "error": {"type": "ProjectNotFoundError", "message": ...}}` | 1 |
| `tree <id>` where `<id>` does not exist | `{"ok": false, "error": {"type": "CardNotFoundError", "message": ...}}` | 1 |
| `next` — no card-level error path exists | — | — |

No stack traces escape; every failure is an envelope on stdout plus a non-zero exit.

## Signature conventions

Use PEP 604 `str | None` / `int | None` in the typer signatures, matching the existing code (cli.py:24, 78, 152), not the `Optional[...]` spelling literally shown in the plan snippet. The `next` command function is named `next_cmd` and registered via `@app.command(name="next")` to avoid shadowing the builtin, mirroring `list_cards_cmd` (cli.py:150-151).

## Test list

Per the test-placement rule in `docs/superpowers/specs/2026-09-17-brd-cli-design.md` lines 183-192, `cli.py` owns end-to-end tests driven through typer's `CliRunner` against a temp XDG data dir. All five tests below are **CLI end-to-end tier**, appended to `tests/test_cli.py`, reusing the module-level `runner` and the `initialized_project` fixture (tests/test_cli.py:100-103). None belong in `tests/test_core.py`: `build_tree` and `next_cards` already have core unit-test coverage from prior subtasks, and this subtask adds no core logic.

1. `test_tree_whole_board` — CLI end-to-end. One `add`, then `tree`: exit 0, `data` has one node with the expected title.
2. `test_tree_rooted_at_card` — CLI end-to-end. Parent + child via `add --parent`, then `tree <parent-id>`: `data` has one node with exactly one child.
3. `test_tree_pretty_renders_indented_text` — CLI end-to-end. `tree --pretty`: stdout contains the card title in the `render_tree_text` line form and is not JSON.
4. `test_tree_missing_card_errors` — CLI end-to-end. `tree nope`: exit code != 0, `data`-free envelope with `ok: false` and `error.type == "CardNotFoundError"`, mirroring the existing `test_add_with_unknown_parent_errors` pattern (tests/test_cli.py:115-120) for `show`/`update`/`block`/`unblock`. This exercises the `except core.CardNotFoundError` branch of the new `tree` command, which the spec's error-paths table requires and which no other test would otherwise cover.
5. `test_next_returns_ready_cards` — CLI end-to-end. Two `add`s, then `next`: `data` has both, oldest first.
6. `test_next_respects_limit` — CLI end-to-end. Two `add`s, then `next --limit 1`: `data` has exactly one entry.

## Verification

`uv run pytest` — the 143 existing tests plus the 6 new ones (149 total) must all pass. No typecheck or lint step is configured for this repo.

---

# CLI `tree` and `next` Commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `brd tree [<id>] [--pretty]` and `brd next [--limit N]` typer commands to `src/brd/cli.py` as thin wrappers over already-implemented core/output functions.

**Architecture:** `cli.py` stays a thin layer: each command resolves the project connection via `_project_conn()`, calls one `core.py` function, and renders through `output.py`. `tree` calls `core.build_tree` and, on `--pretty` success, prints `output.render_tree_text(...)` directly instead of the JSON envelope; `next` calls `core.next_cards` and maps results through the existing `_card_detail` helper, exactly like `list` does. No SQL, no status recomputation, and no changes to any module other than `cli.py` and `tests/test_cli.py`.

**Tech Stack:** Python 3.12+, typer (CLI + `typer.testing.CliRunner`), stdlib `sqlite3`, pytest, `uv` as the runner.

**Spec:** `docs/superpowers/specs/issue-16-design.md` (reproduced verbatim above this plan).

## Global Constraints

- Only two files may change: `src/brd/cli.py` and `tests/test_cli.py`. `core.py`, `db.py`, `master.py`, `output.py`, `models.py`, `paths.py` are consumed as-is.
- No SQL in `cli.py` — parse args, call `core.py`, render via `output.py`.
- Typer option/argument annotations use PEP 604 (`str | None`, `int | None`), never `Optional[...]`.
- Every command resolves the connection with the `try: conn, _ = _project_conn() / except master.ProjectNotFoundError as exc:` pattern from cli.py:90-96 and closes it with `conn.close()` in a `finally`.
- Failure output is always an envelope on stdout (`{"ok": false, "error": {"type": ..., "message": ...}}`) plus `raise typer.Exit(code=1)`. No stack traces. No `--verbose` flag.
- Do not add, modify, or remove `update` / `block` / `unblock` (issue #15) or any README / full end-to-end integration test (issue #17).
- `--pretty` is always spelled `pretty: bool = typer.Option(False, "--pretty", "--human", help="Human-readable output.")`.
- New commands go after `unblock` (ends cli.py:301) and before `if __name__ == "__main__":` (cli.py:304).
- Baseline before starting: `uv run pytest` passes with 143 tests in this worktree.

---

### Task 1: `brd tree` command

**Files:**
- Modify: `src/brd/cli.py` — insert a new `tree` command between `unblock` (ends line 301) and `if __name__ == "__main__":` (line 304)
- Test: `tests/test_cli.py` — append after `test_update_rejects_parent_cycle` (ends line 348)

**Interfaces:**
- Consumes: `core.build_tree(conn: sqlite3.Connection, root_id: str | None = None) -> list[dict]` (core.py:181-187; raises `core.CardNotFoundError` when `root_id` is unknown); `core.CardNotFoundError`; `output.ok_envelope(data) -> dict`; `output.error_envelope(error_type: str, message: str) -> dict`; `output.print_result(envelope: dict, pretty: bool) -> None`; `output.render_tree_text(nodes: list[dict], indent: int = 0) -> str` (output.py:19-26); `cli._project_conn() -> tuple[sqlite3.Connection, master.Project]` (cli.py:55-58); `master.ProjectNotFoundError`.
- Produces: `cli.tree(card_id: str | None, pretty: bool) -> None`, registered as the `tree` command. Node dicts carry keys `id`, `title`, `status`, `blocked_by`, `children`.

- [ ] **Step 1: Write the four failing tests**

Append to `tests/test_cli.py`:

```python
def test_tree_whole_board(initialized_project):
    runner.invoke(app, ["add", "--title", "Root card"])

    result = runner.invoke(app, ["tree"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert [node["title"] for node in payload["data"]] == ["Root card"]
    assert payload["data"][0]["children"] == []


def test_tree_rooted_at_card(initialized_project):
    parent = json.loads(runner.invoke(app, ["add", "--title", "Parent"]).stdout)["data"]
    runner.invoke(app, ["add", "--title", "Child", "--parent", parent["id"]])

    result = runner.invoke(app, ["tree", parent["id"]])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert len(payload["data"]) == 1
    node = payload["data"][0]
    assert node["title"] == "Parent"
    assert [child["title"] for child in node["children"]] == ["Child"]


def test_tree_pretty_renders_indented_text(initialized_project):
    parent = json.loads(runner.invoke(app, ["add", "--title", "Parent"]).stdout)["data"]
    child = json.loads(
        runner.invoke(app, ["add", "--title", "Child", "--parent", parent["id"]]).stdout
    )["data"]

    result = runner.invoke(app, ["tree", "--pretty"])
    assert result.exit_code == 0
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)
    assert f"- Parent [todo] ({parent['id']})" in result.stdout
    assert f"  - Child [todo] ({child['id']})" in result.stdout


def test_tree_missing_card_errors(initialized_project):
    result = runner.invoke(app, ["tree", "nope"])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "CardNotFoundError"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -k tree -v`
Expected: FAIL — typer reports `No such command 'tree'`, so `result.exit_code` is 2 and `json.loads(result.stdout)` raises `json.JSONDecodeError` (the assertions on `exit_code == 0` / payload fail).

- [ ] **Step 3: Write the minimal implementation**

In `src/brd/cli.py`, insert after the `unblock` command (after line 301) and before `if __name__ == "__main__":`:

```python
@app.command()
def tree(
    card_id: str | None = typer.Argument(
        None, help="Root the tree at this card id (default: whole board)."
    ),
    pretty: bool = typer.Option(
        False, "--pretty", "--human", help="Human-readable output."
    ),
) -> None:
    """Print the hierarchy and dependency tree."""
    try:
        conn, _ = _project_conn()
    except master.ProjectNotFoundError as exc:
        output.print_result(
            output.error_envelope("ProjectNotFoundError", str(exc)), pretty
        )
        raise typer.Exit(code=1)

    try:
        envelope = output.ok_envelope(core.build_tree(conn, root_id=card_id))
    except core.CardNotFoundError as exc:
        output.print_result(
            output.error_envelope("CardNotFoundError", str(exc)), pretty
        )
        raise typer.Exit(code=1)
    finally:
        conn.close()

    if pretty:
        print(output.render_tree_text(envelope["data"]))
    else:
        output.print_result(envelope, pretty)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -k tree -v`
Expected: PASS — 4 passed.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: PASS — 147 passed (143 baseline + 4 new).

- [ ] **Step 6: Commit**

```bash
git add src/brd/cli.py tests/test_cli.py
git commit -m "Add brd tree command"
```

---

### Task 2: `brd next` command

**Files:**
- Modify: `src/brd/cli.py` — insert a new `next_cmd` command after the `tree` command added in Task 1 and before `if __name__ == "__main__":`
- Test: `tests/test_cli.py` — append after `test_tree_pretty_renders_indented_text` added in Task 1

**Interfaces:**
- Consumes: `core.next_cards(conn: sqlite3.Connection, limit: int | None = None) -> list[Card]` (core.py:163-166); `cli._card_detail(conn: sqlite3.Connection, card: Card) -> dict` (cli.py:61-72, returning `id`, `title`, `description`, `status`, `parent_id`, `created_at`, `updated_at`, `blocked_by`, `children`); `cli._project_conn()`; `output.ok_envelope`, `output.error_envelope`, `output.print_result`; `master.ProjectNotFoundError`.
- Produces: `cli.next_cmd(limit: int | None, pretty: bool) -> None`, registered as `@app.command(name="next")`.

- [ ] **Step 1: Write the two failing tests**

Append to `tests/test_cli.py`:

```python
def test_next_returns_ready_cards(initialized_project):
    first = json.loads(runner.invoke(app, ["add", "--title", "First"]).stdout)["data"]
    second = json.loads(runner.invoke(app, ["add", "--title", "Second"]).stdout)["data"]

    result = runner.invoke(app, ["next"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert [item["id"] for item in payload["data"]] == [first["id"], second["id"]]
    assert payload["data"][0]["status"] == "todo"


def test_next_respects_limit(initialized_project):
    first = json.loads(runner.invoke(app, ["add", "--title", "First"]).stdout)["data"]
    runner.invoke(app, ["add", "--title", "Second"])

    result = runner.invoke(app, ["next", "--limit", "1"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert [item["id"] for item in payload["data"]] == [first["id"]]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -k next -v`
Expected: FAIL — typer reports `No such command 'next'`, exit code 2, and `json.loads(result.stdout)` raises `json.JSONDecodeError`.

- [ ] **Step 3: Write the minimal implementation**

In `src/brd/cli.py`, insert after the `tree` command and before `if __name__ == "__main__":`:

```python
@app.command(name="next")
def next_cmd(
    limit: int | None = typer.Option(
        None, "--limit", help="Return at most this many cards."
    ),
    pretty: bool = typer.Option(
        False, "--pretty", "--human", help="Human-readable output."
    ),
) -> None:
    """List unblocked todo cards, oldest first."""
    try:
        conn, _ = _project_conn()
    except master.ProjectNotFoundError as exc:
        output.print_result(
            output.error_envelope("ProjectNotFoundError", str(exc)), pretty
        )
        raise typer.Exit(code=1)

    try:
        cards = core.next_cards(conn, limit=limit)
        envelope = output.ok_envelope([_card_detail(conn, card) for card in cards])
    finally:
        conn.close()

    output.print_result(envelope, pretty)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -k next -v`
Expected: PASS — 2 passed.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: PASS — 149 passed (143 baseline + 6 new).

- [ ] **Step 6: Commit**

```bash
git add src/brd/cli.py tests/test_cli.py
git commit -m "Add brd next command"
```
