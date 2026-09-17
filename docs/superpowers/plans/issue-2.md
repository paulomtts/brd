<!-- task-pipeline: validated -->
# Issue #2 — 1.1 Project scaffolding

Parent story: #1 "Implement brd CLI v1". Task 1 of `docs/superpowers/plans/2026-09-17-brd-cli.md` (lines 51-150). Milestone design: `docs/superpowers/specs/2026-09-17-brd-cli-design.md`.

## Goal

Turn the current placeholder repo (a root `main.py` with a trivial `main()` and a `pyproject.toml` containing only a `[project]` table) into an installable `brd` package with a typer entry point, so that every later CLI task has a `brd.cli.app` to attach commands to.

## Scope

Touches exactly these paths, and nothing else:

- Modify `pyproject.toml` — add `[project.scripts]` (`brd = "brd.cli:app"`), `[build-system]` (`requires = ["hatchling"]`, `build-backend = "hatchling.build"`), `[tool.hatch.build.targets.wheel]` (`packages = ["src/brd"]`), and the dependencies added via `uv add typer` / `uv add --dev pytest`. `uv.lock` is regenerated as a side effect.
- Create `src/brd/__init__.py` — empty.
- Create `src/brd/cli.py` — the typer app skeleton only.
- Create `tests/__init__.py` — empty.
- Create `tests/test_cli.py` — the `--help` test.
- Delete `main.py` via `git rm`.

Out of scope (owned by siblings #3-#17): `models.py`, `paths.py`, `db.py`, `master.py`, `core.py`, `output.py`, any actual CLI command (`init`, `add`, `show`, `list`, `update`, `block`, `unblock`, `tree`, `next`), any global `--pretty`/`--human` option, any SQLite access, the README, and the full end-to-end integration test. `cli.py` at the end of this subtask has zero commands registered.

## Observable behavior

- `uv sync` installs the project in editable mode; the `brd` console script resolves to `brd.cli:app`.
- `import brd.cli` succeeds and exposes module-level `app`, an instance of `typer.Typer`, constructed with `name="brd"`, `help="Local kanban board for tracking work, no visual UI."`, and `no_args_is_help=True`.
- Invoking the app with `["--help"]` exits 0 and prints usage text that includes the help string.
- Invoking the app with no arguments prints help rather than erroring out silently (consequence of `no_args_is_help=True`; typer exits non-zero here — this is the intended typer default and is not asserted as success).
- `src/brd/cli.py` ends with the standard `if __name__ == "__main__": app()` guard so the module is directly runnable.
- `main.py` no longer exists at the repo root.

## Error paths

There is no runtime error surface in this subtask — no I/O, no SQLite, no user input parsing beyond typer's own. The failure modes are build/packaging ones, and each must be resolved before the subtask is done:

- `ModuleNotFoundError: No module named 'brd'` when the hatch wheel target or `src/` layout is misconfigured, or `uv sync` was not re-run after editing `pyproject.toml`. This is the *expected* failure at the TDD red step.
- `ImportError: cannot import name 'app' from 'brd.cli'` if `cli.py` exists but `app` is not module-level.
- A `uv sync` failure if `[build-system]` is missing — uv otherwise cannot build the local package for editable install.

The envelope contract (`{"ok": true, "data": ...}` / `{"ok": false, "error": {...}}` with non-zero exit on failure) and the JSON-default/`--pretty` opt-in rule are milestone-global constraints that `cli.py` will grow into; they are implemented by #12-#16, not here.

## Constraints inherited

`cli.py` is the thin layer: it parses args, calls `core.py`, renders via `output.py`, and never touches SQL directly. The skeleton created here must not open connections, import `sqlite3`, or define helpers that would later invite business logic into the CLI module.

## TDD sequence

Write `tests/test_cli.py` first, run it, and confirm it fails with `ModuleNotFoundError` before creating `src/brd/cli.py`. Then implement, `uv sync`, and re-run to green.

## Test list

Per the milestone test-placement rule (`docs/.../2026-09-17-brd-cli-design.md` lines 183-192), this repo has exactly two tiers: **unit** tests against a temp SQLite file for `core.py`/`db.py`, and **end-to-end** tests driving the command surface via `CliRunner` for `cli.py`. Anything exercising `cli.py` belongs in the e2e tier, in `tests/test_cli.py`.

1. `test_help_exits_zero` — **e2e tier (`tests/test_cli.py`)**. `CliRunner().invoke(app, ["--help"])` returns `exit_code == 0`. This is the only test the plan requires for Task 1. No temp XDG data dir is needed yet because no command touches storage; the monkeypatched-XDG fixture arrives with #13.

No unit-tier tests are in scope: this subtask creates no `core.py`/`db.py` code and therefore nothing that belongs in that tier.

## Verification

- `uv run pytest tests/test_cli.py -v` passes.
- Full suite: `uv run pytest` passes.
- No typecheck or lint commands are configured for this repo.

## Commit

Stage `pyproject.toml uv.lock src/brd/__init__.py src/brd/cli.py tests/__init__.py tests/test_cli.py`, `git rm main.py`, commit as `Scaffold brd package with typer entry point`.

---

# brd Project Scaffolding (Issue #2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the placeholder repo into an installable `brd` package exposing a command-free `typer.Typer` instance at `brd.cli.app`, wired to a `brd` console script, with a passing e2e `--help` test.

**Architecture:** `src/` layout package built by hatchling. `src/brd/cli.py` holds only the `typer.Typer` app object, an empty `@app.callback()` (required so typer can build a click command at all — see Step 6 note), plus a `__main__` guard — no commands, no imports of `sqlite3`, no business logic; it is the thin layer that later subtasks (#13-#16) attach commands to. Tests live in the e2e tier (`tests/test_cli.py`) and drive the app through `typer.testing.CliRunner`.

**Tech Stack:** Python 3.12 (`.python-version` pins the interpreter), `uv` for dependency/env management, `typer` (runtime dep), `pytest` (dev dep), `hatchling` (build backend).

**Spec:** `docs/superpowers/specs/issue-2-design.md` (prepended verbatim above). Milestone design: `docs/superpowers/specs/2026-09-17-brd-cli-design.md`.

## Global Constraints

These are milestone-wide rules from `docs/superpowers/plans/2026-09-17-brd-cli.md` lines 15-22. Task 1 implements none of them directly, but the scaffolding must not contradict any of them:

- No ORM — plain stdlib `sqlite3` with a light wrapper (spec: Architecture).
- `status` column never stores `'blocked'`; it's a read-time derived value (spec: Data model).
- Both DB tiers live under the XDG data dir (`~/.local/share/brd/`), never inside project repos (spec: Storage layout).
- `.brd` marker file must be added to the repo's `.gitignore` by `brd init` (spec: CLI surface / user-approved addendum).
- JSON output is the default; `--pretty`/`--human` opts into formatted text (spec: Output format).
- Every command's output uses the envelope `{"ok": true, "data": ...}` or `{"ok": false, "error": {"type", "message"}}`, non-zero exit on failure (spec: Output format, Error handling).
- SQLite WAL mode; one connection opened/closed per command invocation, no daemon (spec: Concurrency).
- Card IDs and project IDs are UUID4 strings (spec: Data model).
- `cli.py` is the thin layer: parses args, calls `core.py`, renders via `output.py`, never touches SQL directly (issue spec: Constraints inherited).

## Working Directory

All commands run from the worktree root:

```
/home/paulomtts/Code/brd/.claude/worktrees/m1/task-2
```

Branch: `m1/task-2`, cut fresh from `origin/main`. The worktree currently contains only `.gitignore`, `.python-version`, `README.md`, `main.py`, `pyproject.toml`, and `docs/`. No `uv.lock`, no `src/`, no `tests/` exist yet — do not assume any other subtask's code is present.

## File Structure

| Path | Responsibility |
| --- | --- |
| `pyproject.toml` (modify) | Project metadata, `typer` dependency, `pytest` dev dependency, `brd` console script, hatchling build backend, wheel packages pointing at `src/brd`. |
| `uv.lock` (created by `uv add`) | Resolved dependency lock, committed. |
| `src/brd/__init__.py` (create) | Empty — marks `brd` as a package. |
| `src/brd/cli.py` (create) | The `typer.Typer` app instance and the `__main__` guard. Nothing else. |
| `tests/__init__.py` (create) | Empty — makes `tests` a package so pytest's rootdir import mode is unambiguous. |
| `tests/test_cli.py` (create) | E2E tier: `CliRunner`-driven tests of the CLI surface. Task 1 adds `test_help_exits_zero`. |
| `main.py` (delete) | Placeholder root script, superseded by the console-script entry point. |

---

### Task 1: Installable `brd` package with a typer entry point

**Files:**
- Modify: `pyproject.toml` (currently 7 lines: a single `[project]` table with `dependencies = []` and no `[build-system]`)
- Create: `src/brd/__init__.py`
- Create: `src/brd/cli.py`
- Delete: `main.py`
- Test: `tests/test_cli.py` (e2e tier), `tests/__init__.py`

**Interfaces:**
- Consumes: nothing — this is the first task on the branch.
- Produces: `brd.cli.app`, a module-level `typer.Typer` instance built with `name="brd"`, `help="Local kanban board for tracking work, no visual UI."`, `no_args_is_help=True`. Subtasks #13-#16 register commands on it via `@app.command(...)`. The console script `brd` resolves to `brd.cli:app`.

- [ ] **Step 1: Add the runtime and dev dependencies**

`typer` is needed by the implementation and `pytest` by the test runner, so both must be installed before the red step can even be executed. This creates `uv.lock` and `.venv/`.

```bash
cd /home/paulomtts/Code/brd/.claude/worktrees/m1/task-2
uv add typer
uv add --dev pytest
```

Expected: `uv add` rewrites `pyproject.toml` so `dependencies = ["typer>=..."]` and adds a `[dependency-groups]` (or `[tool.uv] dev-dependencies`) entry containing `pytest`, then writes `uv.lock`.

- [ ] **Step 2: Create the test package directory**

`tests/__init__.py` must exist before the test file so pytest imports `tests.test_cli` as a package module rather than a rootdir-relative script.

```bash
cd /home/paulomtts/Code/brd/.claude/worktrees/m1/task-2
mkdir -p tests
touch tests/__init__.py
```

- [ ] **Step 3: Write the failing e2e test**

E2E tier per the milestone test-placement rule: anything exercising `cli.py` goes in `tests/test_cli.py` and drives the app through `CliRunner`.

Create `tests/test_cli.py`:

```python
from typer.testing import CliRunner

from brd.cli import app

runner = CliRunner()


def test_help_exits_zero():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
```

- [ ] **Step 4: Run the test to verify it fails (RED)**

```bash
cd /home/paulomtts/Code/brd/.claude/worktrees/m1/task-2
uv run pytest tests/test_cli.py -v
```

Expected: collection error — `ModuleNotFoundError: No module named 'brd'`. Do not proceed until you have seen that exact module name in the output. If instead it fails with `ImportError: cannot import name 'app' from 'brd.cli'`, a `src/brd/cli.py` already exists without a module-level `app` — that also counts as red, but re-check the scope of what is on the branch.

- [ ] **Step 5: Create the package module files**

```bash
cd /home/paulomtts/Code/brd/.claude/worktrees/m1/task-2
mkdir -p src/brd
touch src/brd/__init__.py
```

`src/brd/__init__.py` stays empty — no re-exports. Later subtasks import `brd.cli`, `brd.core`, etc. by full module path.

- [ ] **Step 6: Write the minimal typer app**

Create `src/brd/cli.py` with exactly this content — no commands, no `sqlite3` import, no business-logic helper functions:

```python
import typer

app = typer.Typer(
    name="brd",
    help="Local kanban board for tracking work, no visual UI.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    pass


if __name__ == "__main__":
    app()
```

Note on the empty `@app.callback()`: with zero commands *and* zero callback registered, typer (0.27.x, the version `uv add typer` resolves as of this plan) raises `RuntimeError: Could not get a command for this Typer instance` from `typer.main.get_command` the moment the app is invoked — including for `--help` — so `test_help_exits_zero` cannot pass without it. Verified directly: `typer.testing.CliRunner().invoke(app, ["--help"])` on an app with no callback and no commands raises that `RuntimeError` instead of returning `exit_code == 0`; adding the empty `@app.callback()` above fixes it (`--help` then exits 0 and includes the help string, and no-args exits non-zero via `no_args_is_help=True`, matching the spec's Observable behavior section). This callback is a required typer wiring detail, not a command and not business logic — it stays a no-op forever; later subtasks (#13-#16) add `@app.command(...)` functions alongside it, they do not replace it.

- [ ] **Step 7: Add the build backend and console script to `pyproject.toml`**

Append these three tables to `pyproject.toml`, below the `[project]` table that `uv add` already edited in Step 1. Leave the existing `name`, `version`, `description`, `readme`, `requires-python`, `dependencies` keys as they are.

```toml
[project.scripts]
brd = "brd.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/brd"]
```

Without `[build-system]`, uv treats the project as virtual and never installs `brd` into the venv, so the test stays red with `ModuleNotFoundError`.

- [ ] **Step 8: Install the project in editable mode**

```bash
cd /home/paulomtts/Code/brd/.claude/worktrees/m1/task-2
uv sync
```

Expected: uv builds and installs `brd` as an editable local package (output line mentioning `+ brd==0.1.0 (from file://...)`), plus `typer` and `pytest`.

- [ ] **Step 9: Run the test to verify it passes (GREEN)**

```bash
cd /home/paulomtts/Code/brd/.claude/worktrees/m1/task-2
uv run pytest tests/test_cli.py -v
```

Expected: `tests/test_cli.py::test_help_exits_zero PASSED`, 1 passed.

- [ ] **Step 10: Verify the console script resolves**

```bash
cd /home/paulomtts/Code/brd/.claude/worktrees/m1/task-2
uv run brd --help
```

Expected: exit 0 and usage text containing `Local kanban board for tracking work, no visual UI.`. This checks the `[project.scripts]` wiring, which the `CliRunner` test cannot observe.

- [ ] **Step 11: Remove the placeholder root script**

```bash
cd /home/paulomtts/Code/brd/.claude/worktrees/m1/task-2
git rm main.py
```

Expected: `rm 'main.py'`. Nothing imports `main.py` — it contained only a `main()` printing `Hello from brd!` — so no other file needs updating.

- [ ] **Step 12: Run the full suite**

```bash
cd /home/paulomtts/Code/brd/.claude/worktrees/m1/task-2
uv run pytest
```

Expected: 1 passed, 0 failed. No typecheck or lint command is configured for this repo, so this is the complete verification gate.

- [ ] **Step 13: Commit**

```bash
cd /home/paulomtts/Code/brd/.claude/worktrees/m1/task-2
git add pyproject.toml uv.lock src/brd/__init__.py src/brd/cli.py tests/__init__.py tests/test_cli.py
git commit -m "Scaffold brd package with typer entry point"
```

`main.py`'s deletion is already staged by the `git rm` in Step 11. Confirm with `git status` that the commit contains exactly seven path changes: the six added/modified files plus the deleted `main.py`.

---

## Verification Summary

| Check | Command | Expected |
| --- | --- | --- |
| Full suite | `uv run pytest` | 1 passed |
| Console script | `uv run brd --help` | exit 0, help text printed |
| Typecheck | — | not configured for this repo |
| Lint | — | not configured for this repo |
