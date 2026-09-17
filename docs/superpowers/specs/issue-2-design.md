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
