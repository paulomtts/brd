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
