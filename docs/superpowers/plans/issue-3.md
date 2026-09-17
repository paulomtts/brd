<!-- task-pipeline: validated -->
<!-- SPEC (verbatim copy of docs/superpowers/specs/issue-3-design.md) -->

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

<!-- END SPEC -->

---

# Issue #3 — Data Model Dataclasses Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `src/brd/models.py` with the two plain dataclasses `Project` and `Card` that every later brd layer (db, core, cli) constructs and mutates.

**Architecture:** One new leaf module with zero imports beyond `dataclasses`, and zero logic — no ORM, no SQL, no validation, no `__post_init__`, no methods. It sits at the bottom of the dependency graph: `db.py` (#5-#7) will construct these from SQLite rows, `core.py` (#9-#11) will read and mutate them, `output.py`/`cli.py` (#12-#17) will render them. Tests are plain construction/field-assertion unit tests in the flat `tests/` directory, matching the existing `tests/test_cli.py` layout.

**Tech Stack:** Python 3.12 (`requires-python = ">=3.12"`, so PEP 604 `str | None` annotations are native), stdlib `dataclasses`, pytest 9.x run via `uv run pytest`, hatchling src-layout (`packages = ["src/brd"]`).

**Spec:** `docs/superpowers/specs/issue-3-design.md` (also reproduced verbatim at the top of this file).

## Global Constraints

- Branch `m1/task-3`, worktree `/home/paulomtts/Code/brd/.claude/worktrees/m1/task-3`, cut from `origin/m1/task-2`. Only sibling #2's scaffold exists (`pyproject.toml`, `src/brd/__init__.py`, `src/brd/cli.py`, `tests/test_cli.py`). Assume **no** `paths.py`, `db.py`, `core.py`, `output.py` — do not import them.
- No ORM anywhere in the codebase. `models.py` is plain dataclasses only.
- Both dataclasses are mutable: plain `@dataclass`, never `frozen=True`, never `slots=True`.
- `status` is annotated plain `str` — never a `Literal`, never an `Enum`. Legal stored values are `'todo' | 'in_progress' | 'done'`; `'blocked'` is derived at read time in `core.py` (#9) and CHECK-rejected in `db.py` (#5). `models.py` enforces neither.
- `id` fields are annotated `str`. They hold UUID4 strings, but generation lives in #8/#10 — `models.py` does not import `uuid` and has no default factory.
- `Card` has `parent_id` (hierarchy) and **no** `blocked_by` field — blocking is a separate table, a distinct relationship.
- No field has a default value. `description` and `parent_id` are `Optional` in type only, so every construction site must pass them explicitly.
- Field order is load-bearing (later tasks may construct positionally): `Project(id, name, root_path, db_path, created_at)`; `Card(id, title, description, status, parent_id, created_at, updated_at)`.
- Verification command for this repo: `uv run pytest`. No linter and no typechecker are configured — do not add or run one.
- Commit style on this branch is Conventional Commits (`feat: scaffold brd package with typer entry point`).

---

### Task 1: `Project` and `Card` dataclasses

**Files:**
- Create: `src/brd/models.py`
- Test: `tests/test_models.py` (unit tier — flat `tests/` directory, same as the existing `tests/test_cli.py`; no DB fixture, no `typer.testing.CliRunner`)

**Interfaces:**
- Consumes: nothing from earlier tasks. Only the sibling-#2 scaffold, which already makes `brd` importable in tests (src-layout package `src/brd`, installed by `uv` into the project venv).
- Produces, for #5-#17 to rely on:
  - `brd.models.Project(id: str, name: str, root_path: str, db_path: str, created_at: str)` — mutable dataclass, no defaults.
  - `brd.models.Card(id: str, title: str, description: str | None, status: str, parent_id: str | None, created_at: str, updated_at: str)` — mutable dataclass, no defaults.
  - Both get the dataclass-generated `__init__`, `__repr__`, `__eq__`. Nothing else is exported.

- [ ] **Step 1: Write the failing test**

Create `tests/test_models.py` with exactly this content:

```python
from brd.models import Card, Project


def test_project_fields():
    p = Project(
        id="p1",
        name="brd",
        root_path="/repo",
        db_path="/data/p1.db",
        created_at="2026-09-17T00:00:00",
    )
    assert p.name == "brd"
    assert p.root_path == "/repo"


def test_card_fields_and_optional_defaults():
    c = Card(
        id="c1",
        title="Do the thing",
        description=None,
        status="todo",
        parent_id=None,
        created_at="2026-09-17T00:00:00",
        updated_at="2026-09-17T00:00:00",
    )
    assert c.title == "Do the thing"
    assert c.description is None
    assert c.parent_id is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_models.py -v`

Expected: FAIL at collection with `ModuleNotFoundError: No module named 'brd.models'`. If instead you see an `ImportError` naming `Card` or `Project`, a stale `models.py` exists — delete it and rerun so the RED state is the missing module.

- [ ] **Step 3: Write the minimal implementation**

Create `src/brd/models.py` with exactly this content:

```python
from dataclasses import dataclass


@dataclass
class Project:
    id: str
    name: str
    root_path: str
    db_path: str
    created_at: str


@dataclass
class Card:
    id: str
    title: str
    description: str | None
    status: str
    parent_id: str | None
    created_at: str
    updated_at: str
```

Do not add `frozen=True`, `slots=True`, defaults, `__post_init__`, methods, a `blocked_by` field, or any import beyond `dataclasses`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_models.py -v`

Expected: PASS — `test_project_fields` and `test_card_fields_and_optional_defaults`, 2 passed.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`

Expected: PASS — 5 passed (3 pre-existing from `tests/test_cli.py` plus the 2 new ones). Nothing in `tests/test_cli.py` may change.

- [ ] **Step 6: Commit**

```bash
git add src/brd/models.py tests/test_models.py
git commit -m "feat: add Project and Card dataclasses"
```

---

## Self-Review (performed)

**1. Spec coverage.** Scope (one module + one test file) → Task 1 Files. Observable behavior: `Project` five fields in order, `Card` seven fields in order, no defaults, mutable non-frozen → Task 1 Step 3 code + Global Constraints. Deliberate non-behaviors (`status` plain `str`, `id` plain `str` with no UUID generation, no `blocked_by`, no ORM/SQL/validation/`__post_init__`/row-mapping, `Optional` without defaults) → Global Constraints plus the explicit "do not add" line in Step 3. Error paths: the spec says there is no error surface of our own and explicitly declines to test wrong-typed values → no test added for it, correctly. Test list: both named tests present verbatim, in the unit tier path `tests/test_models.py`. Verification: `uv run pytest` in Step 5; no lint/typecheck steps added. Commit: `feat: add Project and Card dataclasses` in Step 6, matching the branch's Conventional Commits history. No gaps.

**2. Placeholder scan.** No TBD/TODO, no "add appropriate error handling", no "similar to Task N", no undefined references. Both code steps carry complete literal file contents.

**3. Type consistency.** `Project(id, name, root_path, db_path, created_at)` and `Card(id, title, description, status, parent_id, created_at, updated_at)` appear identically in the spec, the Interfaces block, the Global Constraints, the test code, and the implementation code — same names, same order, same annotations (`str | None` for `description` and `parent_id`, `str` elsewhere). The test's keyword arguments match the implementation's field names one-for-one.
