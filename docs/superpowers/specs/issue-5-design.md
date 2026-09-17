# Issue #5 — 1.4 DB connection management and schema

Subtask of story #1 ("1 Implement brd CLI v1"). Implements Task 4 of `docs/superpowers/plans/2026-09-17-brd-cli.md` (lines 343-501), narrowing the agreed design in `docs/superpowers/specs/2026-09-17-brd-cli-design.md` to a single module.

## Scope

Create `src/brd/db.py` — the lowest storage layer: open a SQLite connection with the project's standard pragmas, and create the master-tier and project-tier schemas. Plain stdlib `sqlite3` + `pathlib`; no ORM, no third-party dependency.

Create `tests/test_db.py` — unit tests against a real temp SQLite file.

**Out of scope** (owned by siblings, do not drift):
- Any CRUD/query function over `projects` (#6) or `cards`/`blocked_by` (#7).
- XDG path resolution — `db.connect` receives a `db_path: Path` argument and never calls `src/brd/paths.py` (#4, already implemented).
- `blocked` status derivation and `parent_id` / `blocked_by` cycle detection — those live in `core.py` (#9). This subtask contributes only the `CHECK` constraint that makes a literal `'blocked'` write impossible.
- Typed exceptions (`ProjectNotFoundError`, etc.), output envelope, CLI wiring.
- `.brd` marker handling and project registration (#8).

## Public interface

- `connect(db_path: Path) -> sqlite3.Connection` — opens the database at `db_path`, sets `row_factory = sqlite3.Row`, executes `PRAGMA journal_mode=WAL` and `PRAGMA foreign_keys=ON`, returns the connection. The caller owns the connection lifetime (one open/close per command invocation, per the design spec's Concurrency section; no daemon, no pooling, no context manager here).
- `init_master_schema(conn: sqlite3.Connection) -> None` — `CREATE TABLE IF NOT EXISTS projects` and commit.
- `init_project_schema(conn: sqlite3.Connection) -> None` — `CREATE TABLE IF NOT EXISTS cards` and `CREATE TABLE IF NOT EXISTS blocked_by`, then commit.

## Observable behavior

**Connection.** After `connect`, `PRAGMA journal_mode` reports `wal` (case-insensitively) and `PRAGMA foreign_keys` reports `1`. `conn.row_factory is sqlite3.Row`, so downstream query modules read columns by name. `connect` creates the file if it does not exist (standard `sqlite3.connect` behavior); it does not create parent directories — that is the caller's concern, already handled by `paths.py`.

**Master schema.** `projects` columns, in this order and matching `models.Project` field order: `id TEXT PRIMARY KEY`, `name TEXT NOT NULL UNIQUE`, `root_path TEXT NOT NULL`, `db_path TEXT NOT NULL`, `created_at TEXT NOT NULL`. Timestamps are ISO8601 strings. Calling `init_master_schema` twice on the same connection is a no-op the second time and must not raise.

**Project schema.** `cards` columns, in this order and matching `models.Card` field order: `id TEXT PRIMARY KEY`, `title TEXT NOT NULL`, `description TEXT` (nullable), `status TEXT NOT NULL CHECK (status IN ('todo', 'in_progress', 'done'))`, `parent_id TEXT REFERENCES cards(id)` (nullable, self-referential), `created_at TEXT NOT NULL`, `updated_at TEXT NOT NULL`. `blocked_by` columns: `card_id TEXT NOT NULL REFERENCES cards(id)`, `blocks_on_id TEXT NOT NULL REFERENCES cards(id)`, with composite `PRIMARY KEY (card_id, blocks_on_id)` — meaning "`card_id` is blocked by `blocks_on_id`". Calling `init_project_schema` twice must not raise.

**`blocked` is never stored.** Per the design spec (lines 109-113), `blocked` is a read-time-derived fourth status, not a column value. The `CHECK` constraint is the storage-level guarantee: any `INSERT`/`UPDATE` writing `status='blocked'` fails. Derivation itself is #9's job.

## Error paths

- `connect` on an unopenable path (missing parent directory, unwritable location) propagates `sqlite3.OperationalError` unchanged — no wrapping, no typed exception at this layer.
- Inserting a card with a `status` outside `('todo', 'in_progress', 'done')` — notably `'blocked'` — raises `sqlite3.IntegrityError`.
- Inserting a `blocked_by` row or a `cards.parent_id` referencing a non-existent card id raises `sqlite3.IntegrityError` (foreign keys are enforced because `connect` turns them on). Not asserted by this subtask's tests; it is a consequence of the pragma, and #7 owns edge-insert behavior.
- Duplicate `projects.name` or duplicate `(card_id, blocks_on_id)` raises `sqlite3.IntegrityError`. Also #6/#7's concern to surface.
- Both `init_*` functions are idempotent by construction (`IF NOT EXISTS`); neither raises on repeat calls. Neither migrates or alters an existing table with a different shape — v1 has no migrations.

## Test list

All tests in this subtask belong to the **`core.py`/`db.py` unit tier** per the design spec's Testing section (lines 183-192): "unit tests against a temp SQLite file … no mocking of SQLite itself". They live in `tests/test_db.py`, use a real `sqlite3` database under pytest's `tmp_path`, and mock nothing. The CLI end-to-end tier described in the same section (temp XDG data dir, monkeypatched env var) is owned by #13-#16 and gets no tests here.

Shared fixture: `conn(tmp_path)` — yields `db.connect(tmp_path / "test.db")`, closes it on teardown.

| # | Test | Tier | Asserts |
|---|---|---|---|
| 1 | `test_connect_enables_wal_and_foreign_keys` | db unit | `PRAGMA journal_mode` is `wal`; `PRAGMA foreign_keys` is `1` |
| 2 | `test_connect_sets_row_factory` | db unit | `conn.row_factory is sqlite3.Row` |
| 3 | `test_init_master_schema_creates_projects_table` | db unit | `PRAGMA table_info(projects)` column names == `{id, name, root_path, db_path, created_at}` |
| 4 | `test_init_master_schema_is_idempotent` | db unit | two consecutive calls do not raise |
| 5 | `test_init_project_schema_creates_cards_and_blocked_by_tables` | db unit | `cards` columns == `{id, title, description, status, parent_id, created_at, updated_at}`; `blocked_by` columns == `{card_id, blocks_on_id}` |
| 6 | `test_init_project_schema_is_idempotent` | db unit | two consecutive calls do not raise |
| 7 | `test_cards_status_check_constraint_rejects_blocked` | db unit | `INSERT` with `status='blocked'` raises `sqlite3.IntegrityError` |

The plan at lines 356-426 gives the exact test file content and at lines 437-489 the exact minimal implementation; follow both verbatim under TDD (write failing tests → verify `ModuleNotFoundError: No module named 'brd.db'` → implement → green).

## Verification

- Scoped, during development: `uv run pytest tests/test_db.py -v`
- Full suite: `uv run pytest`
- No typecheck or lint step configured for this repo.

## Done

`src/brd/db.py` and `tests/test_db.py` exist, all seven tests pass, the full suite is green, and the work is committed as exactly `git add src/brd/db.py tests/test_db.py` with message `Add DB connection management and schema creation`. `src/brd/models.py` and `src/brd/paths.py` are unmodified.
