# Issue #3 — 1.2 Data model dataclasses

Narrowing of `docs/superpowers/specs/2026-09-17-brd-cli-design.md` (Data model, lines 85-135) and `docs/superpowers/plans/2026-09-17-brd-cli.md` (Task 2, lines 154-244) to a single subtask. Design decisions are already settled upstream; this document only fixes the boundary and the observable surface for #3.

## Scope

Add one module, `src/brd/models.py`, containing exactly two mutable `@dataclass` types — `Project` and `Card` — plus `tests/test_models.py`. Built on top of the scaffold delivered by sibling #2 (branch `m1/task-2`: `pyproject.toml`, `src/brd/__init__.py`, `src/brd/cli.py`, `tests/`).

In scope: the dataclass field names, order, and type annotations; the tests that pin them.

Out of scope (owned by siblings, do not drift): XDG path resolution (#4, `paths.py`), SQLite connection/schema including the `status` CHECK constraint (#5, `db.py`), master-DB project queries that construct `Project` (#6), project-DB card/edge queries that construct `Card` (#7), UUID4 id generation (#8/#10), derived `blocked` status and cycle detection (#9), output/CLI layers (#12-#17).

## Observable behavior

`from brd.models import Card, Project` succeeds, and:

- `Project(id: str, name: str, root_path: str, db_path: str, created_at: str)` — five positional-or-keyword fields in that order, no defaults.
- `Card(id: str, title: str, description: str | None, status: str, parent_id: str | None, created_at: str, updated_at: str)` — seven fields in that order, no defaults.
- Both are plain `@dataclass` (mutable — **not** `frozen=True`, per plan line 164, because later tasks mutate instances) and therefore get generated `__init__`, `__repr__`, and `__eq__`.
- Attribute reads return exactly what was passed; attribute assignment is permitted.

Deliberate non-behaviors, all load-bearing:

- `status` is annotated plain `str`, not a `Literal`/enum. The legal write values are `'todo' | 'in_progress' | 'done'`; `'blocked'` is a *derived read-time* value computed in `core.py` (#9) and rejected at the DB layer by a CHECK constraint (#5). `models.py` enforces neither.
- `id` fields are annotated `str`; they hold UUID4 strings, but generation and validation live elsewhere.
- `Card` has `parent_id` (hierarchy/grouping) and **no** `blocked_by` field — blocking is a separate `blocked_by` table, a distinct relationship from hierarchy (design spec lines 126-135).
- No ORM, no SQL, no validation, no `__post_init__`, no methods, no row-mapping helpers. Construction from rows belongs to #6/#7.
- `description` and `parent_id` are `Optional` in type only; they have no default value, so every construction site must pass them explicitly.

## Error paths

There is no runtime error surface of our own — the module contains no logic. The only failures reachable through this subtask are the dataclass-generated ones: `TypeError` on missing or extra constructor arguments. Type annotations are unenforced at runtime (no typechecker is configured in this repo), so passing a wrong-typed value is not an error path we specify or test.

## Test list

Test-placement rule (design spec lines 183-192) is a two-tier split: `core.py`/`db.py` get unit tests against a temp SQLite file; `cli.py` gets end-to-end tests against a temp XDG data dir. `models.py` touches neither SQLite nor the command surface, so neither tier applies to it; per the plan's own Task 2 Step 1, its tests are plain construction/field-assertion **unit tests** in `tests/test_models.py`, with no DB fixture and no CLI runner.

1. `test_project_fields` — unit tier (`tests/test_models.py`). Construct a `Project` with all five keyword args; assert `name` and `root_path` round-trip.
2. `test_card_fields_and_optional_defaults` — unit tier (`tests/test_models.py`). Construct a `Card` with `description=None`, `status="todo"`, `parent_id=None`; assert `title` round-trips and that `description is None` and `parent_id is None`.

These two are the plan's verbatim tests (lines 166-199) and are the required minimum. Any additional assertion must stay within the same unit tier and must not reach for SQLite or `typer.testing.CliRunner`.

## Verification

- `uv run pytest` — full suite, must pass (currently 3 passing tests from #2; this subtask adds 2).
- No typechecker and no linter are configured in this repo; nothing else to run.

## Commit

TDD order: write `tests/test_models.py` first and confirm it fails with `ModuleNotFoundError: No module named 'brd.models'`, then add the minimal `src/brd/models.py`, then confirm the suite passes, then commit both files together. The plan suggests the message `"Add Project and Card dataclasses"`; the branch this builds on established Conventional Commits (`feat: scaffold brd package with typer entry point`), so use `feat: add Project and Card dataclasses` to stay consistent with the existing history.
