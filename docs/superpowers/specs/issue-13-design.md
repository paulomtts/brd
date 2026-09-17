# Issue #13 — 1.12 CLI: `init` and `projects` commands

Subtask of parent story #1 "Implement brd CLI v1". Narrows plan Task 12 (`docs/superpowers/plans/2026-09-17-brd-cli.md:1846-1968`) to one deliverable: the first two user-facing typer commands.

## Scope

Add two commands to `src/brd/cli.py`, which today holds only the `typer.Typer` app plus a no-op `@app.callback()` (`src/brd/cli.py:1-16`):

- `brd init [--name TEXT] [--pretty/--human]` — registers the current working directory as a brd project.
- `brd projects [--pretty/--human]` — lists every registered project.

Both are thin adapters: they call already-merged `brd.master` functions, wrap the result in an envelope from `brd.output`, and print it. No new business logic, no new persistence, no changes to `master.py`, `db.py`, `models.py`, or `output.py`.

Out of scope (owned by siblings): `add`/`show`/`list` (#14), `update`/`block`/`unblock` (#15), `tree`/`next` (#16), envelope and pretty-rendering internals (#12), master registration internals (#8).

### Prerequisite gap (already satisfied)

`src/brd/output.py` does not exist on `main`; it was added on sibling branch `m1/task-12` (commits `89a8a73`, `3a64a76`, `9f5c64b`). The PR stack is linear ("each subtask strictly builds on the previous one"), and this worktree's branch (`m1/task-13`) already tracks `m1/task-12`'s tip (`9f5c64b`) — `src/brd/output.py` and `tests/test_output.py` are already present on disk here, so `src/brd/cli.py` can import `output` with no further merge, rebase, or cherry-pick step. `output.py` and `tests/test_output.py` are not edited as part of this subtask's deliverable.

## Consumed APIs (all pre-existing, used as-is)

- `master.init_project(root_path: Path, name: str | None) -> Project` — `src/brd/master.py:29`; writes the `.brd` marker, appends `.brd` to `.gitignore`, creates the project DB, inserts the master row.
- `master.list_all_projects() -> list[Project]` — `src/brd/master.py:104`.
- `master.ProjectAlreadyExistsError` — `src/brd/master.py:11`; raised when a project of that name is already registered.
- `output.ok_envelope(data) -> {"ok": True, "data": data}`, `output.error_envelope(type, message) -> {"ok": False, "error": {"type":…, "message":…}}`, `output.print_result(envelope, pretty)`.
- `Project` dataclass fields `id, name, root_path, db_path, created_at` (`src/brd/models.py:4-10`), serialized with `dataclasses.asdict`.

## Observable behavior

**`brd init`** — resolves the project name from `--name`, defaulting (inside `master.init_project`) to `Path.cwd().name`. On success: exit code 0, and stdout carries `{"ok": true, "data": {...Project fields...}}` as JSON (or the pretty rendering when `--pretty`/`--human` is passed). Side effects — a `.brd` marker file containing the project id in the cwd, a `.gitignore` entry, and a new per-project SQLite DB under the XDG data dir — are produced by `master`, not by the CLI.

**`brd projects`** — exit code 0; stdout carries `{"ok": true, "data": [ {...}, ... ]}`, one object per registered project, in `db.list_projects` order. An empty registry yields `data: []` and still exits 0.

Both commands default to machine-readable JSON; `--pretty` (alias `--human`) switches to human rendering via `output.print_result`. The existing `--help`/no-args help behavior must keep working unchanged.

## Error paths

- `master.ProjectAlreadyExistsError` from `init` → print `error_envelope("ProjectAlreadyExistsError", str(exc))` to the same stream, then exit non-zero (code 1). The error is reported as a well-formed envelope, never as a traceback.
- Unknown option or unknown command → typer's own usage error (exit code 2). Not our concern to reshape here.
- `projects` has no expected failure mode of its own at this stage.

## Tests

Test-placement rule (`docs/superpowers/specs/2026-09-17-brd-cli-design.md:183-192`, the repo's only such guidance — no CLAUDE.md exists): `core.py`/`db.py` get unit tests against a temp SQLite file; `cli.py` gets **end-to-end tests driving the full command surface against a temp XDG data dir monkeypatched per test**. Every test below is therefore in the **CLI end-to-end tier**, appended to `tests/test_cli.py` and invoked through `CliRunner`. No unit tests of `master` or `output` are added here — those tiers belong to #8 and #12.

Shared `isolated_env` fixture (e2e tier): `monkeypatch.setenv("XDG_DATA_HOME", tmp_path / "data")`, create `tmp_path/"myrepo"`, `monkeypatch.chdir` into it, yield the repo path.

1. `test_init_registers_project` — e2e tier. `brd init` exits 0; parsed stdout has `ok is True` and `data["name"] == "myrepo"`; `.brd` exists in the repo dir.
2. `test_init_twice_fails_second_time` — e2e tier. Second `brd init` exits non-zero; parsed stdout has `ok is False` and `error["type"] == "ProjectAlreadyExistsError"`.
3. `test_projects_lists_registered_projects` — e2e tier. After `brd init`, `brd projects` exits 0 and `data[0]["name"] == "myrepo"`.

Existing e2e tests that must remain green: `test_help_exits_zero`, `test_help_prints_program_description`, `test_no_args_prints_help_instead_of_missing_command_error` (`tests/test_cli.py:10-24`).

## Verification

Full suite: `uv run pytest`. No typecheck or lint step is configured for this repo. Baseline before this change is 110 passing tests (verified via `uv run pytest -q` on this worktree's current `HEAD`); after it, 110 plus the three new e2e tests (113 total), with nothing previously passing turned red.
