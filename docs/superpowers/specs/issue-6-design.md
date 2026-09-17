# Issue #6 — 1.5 Master DB queries

Subtask of story #1 ("Implement brd CLI v1"). Implements Task 5 of `docs/superpowers/plans/2026-09-17-brd-cli.md` (lines 505-624), narrowing the agreed design in `docs/superpowers/specs/2026-09-17-brd-cli-design.md` to the master-tier query functions. Depends only on #5 (`db.connect`, `db.init_master_schema`, already implemented) and #3 (`models.Project`, already implemented).

## Scope

Append four public query functions plus one private row-mapper to `src/brd/db.py`, covering CRUD reads and the single write against the master-tier `projects` table. Plain stdlib `sqlite3`, parameterized `?` placeholders only, no ORM, no third-party dependency. Append the matching unit tests to `tests/test_db.py`.

**Out of scope** (owned by siblings, do not drift):
- Card and `blocked_by` edge queries against the per-project DB — `insert_card`, `get_card`, `update_card_fields`, `list_cards`, `add_blocked_by_edge`, `remove_blocked_by_edge`, `list_blockers_of`, `list_children`, and any `project_conn` fixture (#7).
- Project registration, UUID4 id generation, `created_at` stamping, `.brd` marker resolution, duplicate-name policy — `master.py` (#8) consumes these queries but owns those decisions. This subtask stores and reads whatever `Project` it is handed.
- XDG path resolution (#4) — these functions receive an open `sqlite3.Connection`, never a path.
- Typed exceptions (`ProjectNotFoundError`, …), output envelope, CLI wiring (#12-#16).
- Schema definition itself (#5) — unchanged here.

## Public interface

Appended to `src/brd/db.py`, with `from brd.models import Project` added to the top-level imports:

- `insert_project(conn: sqlite3.Connection, project: Project) -> None` — `INSERT INTO projects (id, name, root_path, db_path, created_at)` with the dataclass's five fields as bound parameters, then `conn.commit()` (matching the self-committing style of `init_master_schema` / `init_project_schema`, `src/brd/db.py:25,51`).
- `get_project_by_id(conn: sqlite3.Connection, project_id: str) -> Project | None` — `SELECT * FROM projects WHERE id = ?`, `fetchone()`, mapped to `Project` or `None`.
- `get_project_by_name(conn: sqlite3.Connection, name: str) -> Project | None` — `SELECT * FROM projects WHERE name = ?`, `fetchone()`, mapped to `Project` or `None`.
- `list_projects(conn: sqlite3.Connection) -> list[Project]` — `SELECT * FROM projects ORDER BY created_at`, `fetchall()`, mapped to a list (empty list when the table is empty).

Private helper:

- `_row_to_project(row: sqlite3.Row) -> Project` — maps `row["id"]`, `row["name"]`, `row["root_path"]`, `row["db_path"]`, `row["created_at"]` onto the dataclass. Column-name access is safe because `connect` sets `row_factory = sqlite3.Row` (`src/brd/db.py:7`). `Project` has no optional fields (`src/brd/models.py:4-10`), so all five must be supplied.

## Observable behavior

**Round-trip fidelity.** A `Project` inserted by `insert_project` and read back by `get_project_by_id` or `get_project_by_name` compares equal to the original — every field is a `str` stored in a `TEXT` column, so no coercion happens in either direction. `created_at` is an opaque ISO8601 string to this layer; it is never parsed, only stored and used as the `ORDER BY` key.

**Commit boundary.** `insert_project` commits before returning, so the row is durable and visible to a separately opened connection without further caller action. The read functions never commit and never mutate.

**Missing rows are not errors.** `get_project_by_id` and `get_project_by_name` return `None` when no row matches. They never raise for absence, and never return a partially populated `Project`. Turning `None` into a user-facing "project not found" error is #8's / the CLI's job.

**Ordering.** `list_projects` returns rows ordered by `created_at` ascending (lexicographic on the ISO8601 string, which is chronological for this format). Ties fall back to SQLite's unspecified order; callers must not rely on tie order.

**Name lookups assume uniqueness.** `projects.name` carries a `UNIQUE` constraint (`src/brd/db.py:18`), so `get_project_by_name` can safely `fetchone()` — at most one row can match.

## Error paths

- Inserting a project whose `name` duplicates an existing row raises `sqlite3.IntegrityError` (UNIQUE on `projects.name`), propagated unwrapped. Same for a duplicate `id` (PRIMARY KEY). This layer adds no typed exception; surfacing it as a friendly message belongs to #8/#13.
- Calling any of these functions on a connection whose master schema was never initialized raises `sqlite3.OperationalError: no such table: projects`, propagated unchanged. Callers initialize the schema first.
- Passing a `Project` with a `None` field would raise `sqlite3.IntegrityError` on the `NOT NULL` columns; the dataclass types forbid it, and no validation is added here.
- No other error handling: no `try`/`except`, no retries, no rollback logic. All SQL uses `?` placeholders, so malformed or hostile input is a value, never injected SQL.

## Test list

All tests in this subtask belong to the **`core.py`/`db.py` unit tier** per the design spec's Testing section (`docs/superpowers/specs/2026-09-17-brd-cli-design.md:183-192`): "unit tests against a temp SQLite file … no mocking of SQLite itself". They are appended to `tests/test_db.py`, reuse the existing `conn(tmp_path)` fixture (`tests/test_db.py:8-12`) backed by a real SQLite file, and mock nothing. The other tier named in that section — `cli.py` end-to-end tests against a monkeypatched temp XDG data dir — is owned by #13-#16; this subtask adds nothing to `tests/test_cli.py`. There is no third "integration" or "conformance" tier in this repo.

Shared helper added alongside the tests: `_sample_project(id_="p1", name="brd")`, returning a `Project` with fixed `root_path="/repo"`, `db_path="/data/p1.db"`, `created_at="2026-09-17T00:00:00"`.

| # | Test | Tier | Asserts |
|---|---|---|---|
| 1 | `test_insert_and_get_project_by_id` | db unit | after `init_master_schema` + `insert_project`, `get_project_by_id(conn, "p1")` equals the original `Project` |
| 2 | `test_get_project_by_id_returns_none_when_missing` | db unit | `get_project_by_id(conn, "nope")` is `None` on an initialized-but-empty table |
| 3 | `test_get_project_by_name` | db unit | `get_project_by_name(conn, "brd")` equals the inserted `Project` |
| 4 | `test_list_projects_returns_all` | db unit | after inserting `("p1","brd")` and `("p2","other")`, `{p.id for p in list_projects(conn)} == {"p1","p2"}` |

Each test calls `db.init_master_schema(conn)` itself, matching the existing style at `tests/test_db.py:26-35,68-80`. The plan gives the exact test bodies (lines 519-562) and the exact minimal implementation (lines 573-609); follow both verbatim under TDD: write the failing tests → verify `AttributeError: module 'brd.db' has no attribute 'insert_project'` → implement → green.

## Verification

- Scoped, during development: `uv run pytest tests/test_db.py -v`
- Full suite: `uv run pytest` — baseline before this subtask is 23 passed; expect 27 after.
- No typecheck or lint step configured for this repo.

## Done

`src/brd/db.py` gains `_row_to_project`, `insert_project`, `get_project_by_id`, `get_project_by_name`, `list_projects`; `tests/test_db.py` gains `_sample_project` and the four tests above; the full suite is green; the work is committed as exactly `git add src/brd/db.py tests/test_db.py` with message `Add master DB project queries`. `src/brd/models.py`, `src/brd/paths.py`, `src/brd/cli.py` and `tests/test_cli.py` are unmodified, and no card/edge query exists yet.
