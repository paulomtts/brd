<!-- task-pipeline: validated -->
# Spec (verbatim): `docs/superpowers/specs/issue-12-design.md`

> The full spec this plan implements is reproduced below, unmodified. The plan follows after the horizontal rule at the end of the spec.

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

---

# Output Envelope and Pretty Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `src/brd/output.py`, a dependency-free formatting module that builds the CLI's result envelope, serializes it as one-line JSON (dataclasses included), renders a human-readable form of it, and renders a pre-built tree of node dicts as indented text.

**Architecture:** One new pure module with four public functions (`ok_envelope`, `error_envelope`, `print_result`, `render_tree_text`) and two private helpers (`_json_default`, `_render_pretty`). It imports only `dataclasses` and `json` from the standard library and does no I/O beyond a single `print()` per `print_result` call, so it can be tested with `capsys` alone. Callers in `cli.py` (siblings #13–#16) pass plain strings for the error type and message, keeping this module decoupled from the exception hierarchy.

**Tech Stack:** Python >= 3.12, stdlib `json` + `dataclasses`, pytest (`uv run pytest`), uv for dependency/task running.

**Spec:** `docs/superpowers/specs/issue-12-design.md` (reproduced verbatim at the top of this file)

## Global Constraints

- Work in the worktree `/home/paulomtts/Code/brd/.claude/worktrees/m1/task-12` on branch `m1/task-12`. Do not assume any other subtask's code exists on this branch.
- `src/brd/output.py` must import **only** `dataclasses` and `json`. Never import `brd.core`, `brd.db`, `brd.master`, `brd.paths`, `brd.models`, or `typer`.
- No I/O other than `print()`. No logging, no `sys.exit`, no stack-trace formatting, no exit codes.
- Do not create or modify typer commands, do not touch `src/brd/cli.py`, do not implement tree building or status derivation.
- All tests for this subtask go in the single flat file `tests/test_output.py` (repo uses one `test_<module>.py` per source module, no unit/integration/e2e subdirectories — see the sibling files `tests/test_models.py`, `tests/test_paths.py`).
- Envelope shapes are the CLI-wide contract and are fixed: `{"ok": True, "data": data}` and `{"ok": False, "error": {"type": error_type, "message": message}}`.
- Malformed input raises (`KeyError` / `TypeError`); do not add defensive fallbacks beyond the single tolerated `item.get("status", "")`.
- Verification command for the repo: `uv run pytest`.

## File Structure

- **Create `src/brd/output.py`** — the entire deliverable: envelope constructors, JSON default handler, pretty renderer, tree text renderer, and the `print_result` dispatcher.
- **Create `tests/test_output.py`** — all seven direct unit tests for the module; uses `capsys` only.

This subtask is a single task: the module is one cohesive unit (~40 lines) whose four functions share one contract and one test file, and the spec's "Done when" requires a single commit. The task below runs four RED/GREEN cycles inside itself before that commit.

---

### Task 1: `src/brd/output.py` — envelope, JSON serialization, pretty rendering, tree text

**Files:**
- Create: `src/brd/output.py`
- Test: `tests/test_output.py`

**Interfaces:**
- Consumes: nothing (pure formatting over plain dicts/lists/dataclass instances).
- Produces:
  - `output.ok_envelope(data) -> dict` — `{"ok": True, "data": data}`
  - `output.error_envelope(error_type: str, message: str) -> dict` — `{"ok": False, "error": {"type": error_type, "message": message}}`
  - `output.print_result(envelope: dict, pretty: bool) -> None`
  - `output.render_tree_text(nodes: list[dict], indent: int = 0) -> str`
  - Private: `output._json_default(obj)`, `output._render_pretty(envelope: dict) -> str`

- [ ] **Step 1: Write the failing envelope tests**

Create `tests/test_output.py` with exactly this content:

```python
import json
from dataclasses import dataclass

from brd import output


def test_ok_envelope():
    assert output.ok_envelope({"x": 1}) == {"ok": True, "data": {"x": 1}}


def test_error_envelope():
    assert output.error_envelope("CardNotFoundError", "no card") == {
        "ok": False,
        "error": {"type": "CardNotFoundError", "message": "no card"},
    }
```

- [ ] **Step 2: Run the envelope tests to verify they fail**

Run: `uv run pytest tests/test_output.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'brd.output'`

- [ ] **Step 3: Create the module with the two envelope constructors**

Create `src/brd/output.py`:

```python
import dataclasses
import json


def ok_envelope(data) -> dict:
    return {"ok": True, "data": data}


def error_envelope(error_type: str, message: str) -> dict:
    return {"ok": False, "error": {"type": error_type, "message": message}}
```

(The `dataclasses` and `json` imports are unused for one step; the next cycle uses both. If your linter blocks the commit on unused imports, they will be used before Step 15 — no commit happens until then.)

- [ ] **Step 4: Run the envelope tests to verify they pass**

Run: `uv run pytest tests/test_output.py -v`
Expected: PASS — `test_ok_envelope`, `test_error_envelope`

- [ ] **Step 5: Write the failing JSON-output tests**

Append to `tests/test_output.py`:

```python
def test_print_result_json_default(capsys):
    output.print_result(output.ok_envelope({"x": 1}), pretty=False)
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"ok": True, "data": {"x": 1}}


@dataclass
class _FakeCard:
    id: str
    title: str


def test_print_result_json_serializes_dataclasses(capsys):
    output.print_result(output.ok_envelope(_FakeCard(id="c1", title="Card")), pretty=False)
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"ok": True, "data": {"id": "c1", "title": "Card"}}
```

- [ ] **Step 6: Run the JSON tests to verify they fail**

Run: `uv run pytest tests/test_output.py -v`
Expected: FAIL — `AttributeError: module 'brd.output' has no attribute 'print_result'` for both new tests; the two envelope tests still pass.

- [ ] **Step 7: Add `_json_default` and the JSON branch of `print_result`**

Append to `src/brd/output.py`:

```python
def _json_default(obj):
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    raise TypeError(f"object of type {type(obj)} is not JSON serializable")


def print_result(envelope: dict, pretty: bool) -> None:
    print(json.dumps(envelope, default=_json_default))
```

- [ ] **Step 8: Run the JSON tests to verify they pass**

Run: `uv run pytest tests/test_output.py -v`
Expected: PASS — all four tests so far.

- [ ] **Step 9: Write the failing pretty-rendering tests**

Append to `tests/test_output.py`:

```python
def test_print_result_pretty_error(capsys):
    output.print_result(
        output.error_envelope("CardNotFoundError", "no card"), pretty=True
    )
    captured = capsys.readouterr()
    assert captured.out.strip() == "Error (CardNotFoundError): no card"


def test_print_result_pretty_card_list(capsys):
    cards = [{"id": "c1", "title": "First", "status": "todo"}]
    output.print_result(output.ok_envelope(cards), pretty=True)
    captured = capsys.readouterr()
    assert "c1" in captured.out
    assert "First" in captured.out
    assert "todo" in captured.out
```

- [ ] **Step 10: Run the pretty tests to verify they fail**

Run: `uv run pytest tests/test_output.py -v`
Expected: FAIL — `test_print_result_pretty_error` fails its assertion because `print_result` still emits JSON (`{"ok": false, "error": ...}`), not `Error (CardNotFoundError): no card`.

- [ ] **Step 11: Add `_render_pretty` and dispatch on `pretty`**

Append `_render_pretty` to `src/brd/output.py` and replace the existing `print_result` body so the module ends like this:

```python
def _render_pretty(envelope: dict) -> str:
    if not envelope["ok"]:
        error = envelope["error"]
        return f"Error ({error['type']}): {error['message']}"

    data = envelope["data"]
    if isinstance(data, list) and all(isinstance(item, dict) and "title" in item for item in data):
        return "\n".join(
            f"{item['id']}  [{item.get('status', '')}]  {item['title']}" for item in data
        )
    return str(data)


def print_result(envelope: dict, pretty: bool) -> None:
    if pretty:
        print(_render_pretty(envelope))
    else:
        print(json.dumps(envelope, default=_json_default))
```

- [ ] **Step 12: Run the pretty tests to verify they pass**

Run: `uv run pytest tests/test_output.py -v`
Expected: PASS — all six tests so far.

- [ ] **Step 13: Write the failing tree-rendering test**

Append to `tests/test_output.py`:

```python
def test_render_tree_text_nests_children():
    nodes = [
        {
            "id": "p1",
            "title": "Parent",
            "status": "todo",
            "blocked_by": [],
            "children": [
                {
                    "id": "c1",
                    "title": "Child",
                    "status": "blocked",
                    "blocked_by": ["x"],
                    "children": [],
                }
            ],
        }
    ]
    text = output.render_tree_text(nodes)
    lines = text.splitlines()
    assert lines[0] == "- Parent [todo] (p1)"
    assert lines[1] == "  - Child [blocked] (c1)"
```

- [ ] **Step 14: Run the tree test to verify it fails**

Run: `uv run pytest tests/test_output.py::test_render_tree_text_nests_children -v`
Expected: FAIL — `AttributeError: module 'brd.output' has no attribute 'render_tree_text'`

- [ ] **Step 15: Add `render_tree_text`**

Insert this function into `src/brd/output.py` after `_json_default` and before `_render_pretty`:

```python
def render_tree_text(nodes: list[dict], indent: int = 0) -> str:
    lines = []
    prefix = "  " * indent
    for node in nodes:
        lines.append(f"{prefix}- {node['title']} [{node['status']}] ({node['id']})")
        if node["children"]:
            lines.append(render_tree_text(node["children"], indent + 1))
    return "\n".join(lines)
```

- [ ] **Step 16: Run the tree test to verify it passes**

Run: `uv run pytest tests/test_output.py::test_render_tree_text_nests_children -v`
Expected: PASS

- [ ] **Step 17: Run the full suite**

Run: `uv run pytest`
Expected: PASS — all seven tests in `tests/test_output.py` plus every pre-existing test in `tests/test_cli.py`, `tests/test_core.py`, `tests/test_db.py`, `tests/test_master.py`, `tests/test_models.py`, `tests/test_paths.py`. Read the summary line and confirm zero failures and zero errors before continuing.

- [ ] **Step 18: Confirm the module has no forbidden imports**

Run: `grep -n "^import\|^from" src/brd/output.py`
Expected: exactly two lines — `import dataclasses` and `import json`. If anything else appears, remove it before committing.

- [ ] **Step 19: Commit**

```bash
git add src/brd/output.py tests/test_output.py
git commit -m "$(cat <<'EOF'
Add output envelope and pretty rendering

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011rpKbM8YZgV45PCeiFqncT
EOF
)"
```
