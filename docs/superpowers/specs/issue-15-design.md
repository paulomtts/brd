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
