# Issue #12 — 1.11 Output: envelope and pretty rendering

Subtask of story #1 ("Implement brd CLI v1"), milestone "brd CLI v1". Implements Task 11 of `docs/superpowers/plans/2026-09-17-brd-cli.md` (lines 1679–1836).

## Scope

Create `src/brd/output.py`, a pure formatting module, and its tests in `tests/test_output.py`.

In scope: building the result envelope, serializing it as JSON (including dataclass instances), rendering a human-readable form of an envelope, and rendering an already-built tree of node dicts as indented text.

Out of scope (owned by siblings): tree building and status derivation (`core.py`, #11/#9), exception types and the catch-at-the-boundary conversion into an error envelope (`cli.py`, #13–#16), exit codes, `--pretty`/`--verbose` flag wiring, any typer command. This module imports only `dataclasses` and `json` — never `core`, `db`, `master`, `paths`, `models`, or `typer` — and performs no I/O beyond `print()`. It receives `error_type` and `message` as plain strings, so it stays decoupled from the exception hierarchy.

## Observable behavior

`ok_envelope(data) -> dict` returns `{"ok": True, "data": data}` with `data` passed through unchanged (no copying, no coercion).

`error_envelope(error_type: str, message: str) -> dict` returns `{"ok": False, "error": {"type": error_type, "message": message}}`.

`print_result(envelope: dict, pretty: bool) -> None` prints exactly one `print()` call's worth of output and returns `None`.

- `pretty=False`: prints `json.dumps(envelope, default=_json_default)` — a single line of JSON. The `default` handler converts dataclass *instances* (`dataclasses.is_dataclass(obj) and not isinstance(obj, type)`) via `dataclasses.asdict`, so `Card` and `Project` from `models.py` serialize as nested dicts.
- `pretty=True` and `envelope["ok"]` is falsy: prints `f"Error ({error['type']}): {error['message']}"`.
- `pretty=True`, ok, and `data` is a list whose every item is a dict containing a `"title"` key: one line per item, `f"{item['id']}  [{item.get('status', '')}]  {item['title']}"` (two spaces between fields; missing `status` renders as empty brackets), joined by newlines. An empty list satisfies the `all(...)` predicate and therefore prints an empty line.
- Any other ok payload (dict, string, dataclass, list of non-dicts, list of dicts lacking `title`): prints `str(data)`.

`render_tree_text(nodes: list[dict], indent: int = 0) -> str` returns (does not print) a newline-joined string; each node contributes `"  " * indent + f"- {title} [{status}] ({id})"`, and a node's non-empty `children` list is rendered recursively at `indent + 1` immediately after its own line. An empty `nodes` list returns `""`. Extra node keys such as `blocked_by` are ignored by this renderer.

## Error paths

The module raises rather than papering over malformed input; `cli.py` never feeds it malformed input, so these are programmer-error paths:

- Non-serializable, non-dataclass object under `pretty=False`: `_json_default` raises `TypeError(f"object of type {type(obj)} is not JSON serializable")`.
- Envelope missing `"ok"`, or an error envelope missing `"error"`/`"type"`/`"message"`: `KeyError`.
- A node dict missing `title`, `status`, `id`, or `children` in `render_tree_text`: `KeyError`.
- Items in a card list missing `id`: `KeyError` (only `status` is tolerated as absent, via `.get`).

No stack-trace formatting, no logging, no `sys.exit`.

## Tests

Test-placement rule (per `docs/superpowers/specs/2026-09-17-brd-cli-design.md`, "## Testing", lines 183–192): the repo has a flat, non-tiered pytest layout — one `test_<module>.py` per source module, all run together by `uv run pytest`. The only placement rules stated are that `core.py`/`db.py` get direct tests against a temp SQLite file and `cli.py` gets end-to-end tests against a temp XDG data dir. `output.py` is neither, so every test below is a direct unit-style test living in the single flat file **`tests/test_output.py`** — there is no unit/integration/e2e/conformance split to choose between, and no subdirectory. Fixtures used: `capsys` only; no temp dirs, no DB, no `CliRunner`.

All in `tests/test_output.py`:

1. `test_ok_envelope` — `ok_envelope({"x": 1}) == {"ok": True, "data": {"x": 1}}`.
2. `test_error_envelope` — `error_envelope("CardNotFoundError", "no card")` equals the full error envelope dict.
3. `test_print_result_json_default` (capsys) — `pretty=False` output parses back via `json.loads` to `{"ok": True, "data": {"x": 1}}`.
4. `test_print_result_json_serializes_dataclasses` (capsys) — a local `@dataclass _FakeCard(id, title)` under `pretty=False` round-trips to `{"ok": True, "data": {"id": "c1", "title": "Card"}}`.
5. `test_print_result_pretty_error` (capsys) — stripped output equals `"Error (CardNotFoundError): no card"`.
6. `test_print_result_pretty_card_list` (capsys) — for `[{"id": "c1", "title": "First", "status": "todo"}]`, the output contains `c1`, `First`, and `todo`.
7. `test_render_tree_text_nests_children` — parent with one child yields `lines[0] == "- Parent [todo] (p1)"` and `lines[1] == "  - Child [blocked] (c1)"`.

Test bodies are given verbatim in the plan at lines 1697–1772 and are the acceptance criteria for this subtask.

## Done when

`uv run pytest tests/test_output.py` passes with the seven tests above, the full suite still passes, and `src/brd/output.py` + `tests/test_output.py` are committed with message `Add output envelope and pretty rendering`.
