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
4. `test_next_returns_ready_cards` — CLI end-to-end. Two `add`s, then `next`: `data` has both, oldest first.
5. `test_next_respects_limit` — CLI end-to-end. Two `add`s, then `next --limit 1`: `data` has exactly one entry.

## Verification

`uv run pytest` — the 143 existing tests plus the 5 new ones (148 total) must all pass. No typecheck or lint step is configured for this repo.
