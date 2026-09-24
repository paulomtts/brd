# Issues, Documents, Comments, Tags & References Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add issues, registered markdown documents (with backups), and comments to brd, on top of generic comment/tag/reference abstractions keyed by a global `entities` table.

**Architecture:** A schema migration (`PRAGMA user_version` 0 → 1) adds an `entities(id, kind)` registry; cards, issues, and documents each FK their id to it (rows are auto-registered by `BEFORE INSERT` triggers), and comments/tags/refs FK to `entities` with `ON DELETE CASCADE`. Pure `links.py` parses Obsidian-style `[[links]]`; `refs.py` resolves and reindexes them. `documents.py` keeps a hash-synced backup of each registered file next to the project db. The CLI becomes a package with one `run()` helper that maps every `BrdError` to the existing error envelope.

**Tech Stack:** Python ≥3.12, Typer, stdlib `sqlite3`, pytest (run via `uv run pytest`).

**Spec:** `docs/superpowers/specs/2026-09-24-issues-docs-comments-design.md`

## Global Constraints

- No new runtime dependencies (only `typer`).
- All entity and comment ids are UUID4 strings (`str(uuid.uuid4())`).
- JSON output envelope stays `{"ok": true, "data": ...}` / `{"ok": false, "error": {"type": <ExceptionClassName>, "message": ...}}`.
- Existing commands keep names, flags, and output keys (additions only). **Existing tests must pass unmodified** after every task.
- Tag format after normalization: `^[a-z0-9][a-z0-9_/-]*$` (lowercased, leading `#` stripped).
- Backups live at `<data_dir>/projects/<digest>.docs/<doc-id>.md` — i.e. `project_db_path(root).with_suffix(".docs")`.
- brd never writes a document's source file except in `doc restore`.
- Close reasons: `resolved`, `wontfix`, `duplicate` (default `resolved`).
- Author precedence: `--author` → `$BRD_AUTHOR` → `getpass.getuser()`.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

### Deliberate deviations from the spec (decided while planning)

1. Entity rows are registered by `BEFORE INSERT` triggers on `cards`/`issues`/`documents`, not an `entities.py` helper — so existing tests and `master._copy_cards` that insert raw card rows keep working.
2. `brd show`/`brd delete` on an unknown id raise `CardNotFoundError` (existing tests and agents depend on that type). New commands use `EntityNotFoundError`.
3. Blocking keeps the existing flag: `brd block <card> --by <card-or-issue>`.
4. SQL for issues/documents/comments/tags/refs lives in those modules (not `db.py`); pretty renderers live in `brd/pretty.py`; `import_tree` stays in `core.py`; a new `snapshot.py` owns export and the v2 import.
5. There is no `brd doc show`; `brd show <doc-id>` covers it.
6. Migration drops dangling legacy rows (edges to missing cards; parent ids to missing cards are nulled) instead of failing.
7. Extra error types: `EmptyCommentError`, `InvalidCloseReasonError`, `ImportReadError` (already emitted today as a string).
8. v2 import recomputes `content_hash` from the embedded content it writes.

## Review Focus

1. **Legacy db with dangling rows** (edge or parent pointing at a deleted card) → migration must succeed and drop/null the dangling references, not brick the board. Pinned in Task 1.
2. **Non-UTF-8 bytes in a registered document** → sync, show, and link parsing must not crash; content decodes with replacement characters. Pinned in Task 8.
3. **Stems with spaces and mixed case** (`Design Notes.md`, `[[design notes]]`) → resolve case-insensitively; registering `notes.md` and `Notes.md` in different dirs is rejected. Pinned in Tasks 5 and 8.
4. **`doc add` from a subdirectory** (agent's cwd is `src/`, path `../docs/a.md`) → resolved against cwd, stored as `docs/a.md` relative to root. Pinned in Task 10.
5. **Editing a card description to remove a link** → the `link` ref disappears (and explicit refs to the same target survive). Pinned in Task 5.

---

## File Structure

```
src/brd/errors.py         NEW  all domain exception types (BrdError base)
src/brd/db.py             MOD  migrate_project (v1 schema + triggers), docs_dir, delete via entities
src/brd/paths.py          MOD  project_docs_dir
src/brd/entities.py       NEW  kind lookup, capability map, titles, delete
src/brd/links.py          NEW  pure [[link]] parser/renderer
src/brd/refs.py           NEW  resolve, reindex, reindex_mentions, explicit refs, outgoing/incoming
src/brd/comments.py       NEW  comment CRUD + author resolution
src/brd/tags.py           NEW  tag normalization + CRUD
src/brd/documents.py      NEW  add/sync/update/restore/delete + backup io
src/brd/issues.py         NEW  issue CRUD + lifecycle
src/brd/snapshot.py       NEW  export + import dispatch (v2 + old tree format)
src/brd/views.py          NEW  JSON detail builders per kind
src/brd/pretty.py         NEW  --pretty renderers with link titles
src/brd/core.py           MOD  errors moved out; reindex hooks; issue blockers
src/brd/master.py         MOD  resolve_project_root; forget removes docs dir
src/brd/prompt.py         MOD  new sections
src/brd/cli.py            DEL  → package below
src/brd/cli/__init__.py   NEW  exposes app, imports command modules
src/brd/cli/_app.py       NEW  app, Ctx, run(), fail(), pretty_option()
src/brd/cli/project.py    NEW  prompt/init/projects/forget/purge (moved)
src/brd/cli/cards.py      NEW  card commands (moved) + generic show/delete
src/brd/cli/{comments,tags,refs,docs,issues,snapshot}.py NEW
tests/conftest.py         NEW  `project` and `pconn` fixtures
tests/cli_helpers.py      NEW  ok()/err()/human() CLI wrappers
tests/factories.py        NEW  raw row factories for cards/issues/documents
tests/test_{migration,entities,links,refs,comments,tags,documents,issues,snapshot,pretty}.py NEW
tests/test_cli_{app,social,docs,issues}.py NEW
```

---

## Milestone 1 — Foundation

### Task 1: Error module and schema v1 migration

**Files:**
- Create: `src/brd/errors.py`, `tests/test_migration.py`
- Modify: `src/brd/db.py`, `src/brd/paths.py`, `src/brd/core.py:9-10,62-79`, `src/brd/master.py:11-12`, `src/brd/cli.py:104-106`

**Interfaces:**
- Produces: `brd.errors.*` (full list below); `db.SCHEMA_VERSION = 1`; `db.migrate_project(conn) -> None`; `db.init_project_schema(conn)` (now calls `migrate_project`); `db.docs_dir(conn) -> Path`; `paths.project_docs_dir(root: Path) -> Path`. `core.CycleError` etc. and `master.ProjectNotFoundError` remain importable (re-exported).

- [ ] **Step 1: Write the failing tests** — `tests/test_migration.py`

```python
import sqlite3

import pytest

from brd import db, paths

V0_SCHEMA = [
    """CREATE TABLE cards (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        description TEXT,
        status TEXT NOT NULL CHECK (status IN ('todo', 'in_progress', 'done')),
        parent_id TEXT REFERENCES cards(id),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE blocked_by (
        card_id TEXT NOT NULL REFERENCES cards(id),
        blocks_on_id TEXT NOT NULL REFERENCES cards(id),
        PRIMARY KEY (card_id, blocks_on_id)
    )""",
]

INSERT_CARD = (
    "INSERT INTO cards (id, title, description, status, parent_id, created_at, "
    "updated_at) VALUES (?, ?, NULL, 'todo', ?, 'now', 'now')"
)


def _make_v0(path, cards, edges):
    conn = sqlite3.connect(path)  # foreign keys OFF by default, like a legacy db
    for statement in V0_SCHEMA:
        conn.execute(statement)
    for card_id, parent_id in cards:
        conn.execute(INSERT_CARD, (card_id, card_id, parent_id))
    for edge in edges:
        conn.execute("INSERT INTO blocked_by VALUES (?, ?)", edge)
    conn.commit()
    conn.close()


@pytest.fixture
def v0_path(tmp_path):
    path = tmp_path / "project.db"
    _make_v0(path, cards=[("p", None), ("c", "p"), ("o", None)], edges=[("c", "o")])
    return path


def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_fresh_db_gets_version_1_schema(tmp_path):
    conn = db.connect(tmp_path / "p.db")
    db.migrate_project(conn)
    assert {
        "entities", "cards", "blocked_by", "issues", "documents", "comments", "tags", "refs"
    } <= _tables(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1


def test_v0_cards_are_backfilled_into_entities(v0_path):
    conn = db.connect(v0_path)
    db.migrate_project(conn)
    rows = {(r["id"], r["kind"]) for r in conn.execute("SELECT * FROM entities")}
    assert rows == {("p", "card"), ("c", "card"), ("o", "card")}


def test_v0_rows_and_edges_survive(v0_path):
    conn = db.connect(v0_path)
    db.migrate_project(conn)
    assert db.get_card(conn, "c").parent_id == "p"
    assert db.list_blockers_of(conn, "c") == ["o"]


def test_migration_is_idempotent(v0_path):
    conn = db.connect(v0_path)
    db.migrate_project(conn)
    db.migrate_project(conn)
    assert conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 3
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1


def test_foreign_keys_are_on_after_migration(v0_path):
    conn = db.connect(v0_path)
    db.migrate_project(conn)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_deleting_entity_cascades_to_card_and_edges(v0_path):
    conn = db.connect(v0_path)
    db.migrate_project(conn)
    conn.execute("DELETE FROM entities WHERE id = 'o'")
    conn.commit()
    assert db.get_card(conn, "o") is None
    assert db.list_blockers_of(conn, "c") == []


def test_inserting_a_card_registers_its_entity(tmp_path):
    conn = db.connect(tmp_path / "p.db")
    db.migrate_project(conn)
    conn.execute(INSERT_CARD, ("x", "x", None))
    kind = conn.execute("SELECT kind FROM entities WHERE id = 'x'").fetchone()[0]
    assert kind == "card"


def test_dangling_legacy_rows_are_dropped_not_fatal(tmp_path):
    path = tmp_path / "project.db"
    _make_v0(
        path,
        cards=[("a", "ghost-parent")],
        edges=[("a", "ghost-blocker"), ("ghost-card", "a")],
    )
    conn = db.connect(path)
    db.migrate_project(conn)
    assert db.get_card(conn, "a").parent_id is None
    assert conn.execute("SELECT COUNT(*) FROM blocked_by").fetchone()[0] == 0


def test_delete_card_goes_through_entities(v0_path):
    conn = db.connect(v0_path)
    db.migrate_project(conn)
    db.delete_card(conn, "o")
    assert conn.execute("SELECT COUNT(*) FROM entities WHERE id = 'o'").fetchone()[0] == 0


def test_docs_dir_sits_next_to_the_db(tmp_path):
    conn = db.connect(tmp_path / "project.db")
    assert db.docs_dir(conn).resolve() == (tmp_path / "project.docs").resolve()


def test_project_docs_dir_matches_db_path(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    repo.mkdir()
    assert paths.project_docs_dir(repo) == paths.project_db_path(repo).with_suffix(".docs")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_migration.py -v`
Expected: FAIL — `AttributeError: module 'brd.db' has no attribute 'migrate_project'`.

- [ ] **Step 3: Create `src/brd/errors.py`**

```python
class BrdError(Exception):
    """Base for every domain error; the CLI turns these into error envelopes."""


class ProjectNotFoundError(BrdError):
    pass


class MigrationError(BrdError):
    pass


class CycleError(BrdError):
    pass


class InvalidStatusError(BrdError):
    pass


class CardAlreadyExistsError(BrdError):
    pass


class EntityAlreadyExistsError(BrdError):
    pass


class CardHasChildrenError(BrdError):
    pass


class EntityNotFoundError(BrdError):
    pass


class CardNotFoundError(EntityNotFoundError):
    pass


class IssueNotFoundError(EntityNotFoundError):
    pass


class DocumentNotFoundError(EntityNotFoundError):
    pass


class CommentNotFoundError(BrdError):
    pass


class EmptyCommentError(BrdError):
    pass


class DuplicateStemError(BrdError):
    pass


class DuplicatePathError(BrdError):
    pass


class PathOutsideProjectError(BrdError):
    pass


class NotMarkdownError(BrdError):
    pass


class DocumentSourceNotFoundError(BrdError):
    pass


class DocumentContentLostError(BrdError):
    pass


class RestoreConflictError(BrdError):
    pass


class NotTaggableError(BrdError):
    pass


class NotCommentableError(BrdError):
    pass


class InvalidBlockerError(BrdError):
    pass


class InvalidTagError(BrdError):
    pass


class InvalidCloseReasonError(BrdError):
    pass


class SelfReferenceError(BrdError):
    pass


class ImportFormatError(BrdError):
    pass


class ImportReadError(BrdError):
    pass
```

- [ ] **Step 4: Re-export moved errors**

In `src/brd/core.py`, delete the class bodies of `CycleError`, `CardNotFoundError`, `InvalidStatusError`, `CardAlreadyExistsError`, `CardHasChildrenError` and add after the existing imports:

```python
from brd.errors import (  # noqa: F401  (re-exported for existing callers)
    CardAlreadyExistsError,
    CardHasChildrenError,
    CardNotFoundError,
    CycleError,
    InvalidStatusError,
)
```

In `src/brd/master.py`, replace the `class ProjectNotFoundError(Exception): pass` block with:

```python
from brd.errors import ProjectNotFoundError  # noqa: F401  (re-exported)
```

- [ ] **Step 5: Implement the migration in `src/brd/db.py`**

Add `from brd.errors import MigrationError` to the imports, replace `init_project_schema` with the code below, and replace `delete_card`:

```python
SCHEMA_VERSION = 1

_CARDS_SQL = """
CREATE TABLE {name} (
    id TEXT PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL CHECK (status IN ('todo', 'in_progress', 'done')),
    parent_id TEXT REFERENCES cards(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_BLOCKED_BY_SQL = """
CREATE TABLE {name} (
    card_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    blocks_on_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    PRIMARY KEY (card_id, blocks_on_id)
)
"""

_V1_NEW_TABLES = [
    """
    CREATE TABLE issues (
        id TEXT PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        body TEXT,
        status TEXT NOT NULL CHECK (status IN ('open', 'closed')),
        close_reason TEXT CHECK (close_reason IN ('resolved', 'wontfix', 'duplicate')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE documents (
        id TEXT PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        source_path TEXT NOT NULL UNIQUE,
        stem TEXT NOT NULL UNIQUE COLLATE NOCASE,
        content_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE comments (
        id TEXT PRIMARY KEY,
        entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
        author TEXT NOT NULL,
        body TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE tags (
        entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
        tag TEXT NOT NULL,
        PRIMARY KEY (entity_id, tag)
    )
    """,
    """
    CREATE TABLE refs (
        src_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
        dst_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
        origin TEXT NOT NULL CHECK (origin IN ('explicit', 'link')),
        PRIMARY KEY (src_id, dst_id, origin)
    )
    """,
]

_ENTITY_KINDS = (("cards", "card"), ("issues", "issue"), ("documents", "document"))


def _register_trigger(table: str, kind: str) -> str:
    # Every card/issue/document row gets its entities row automatically, so
    # raw inserts (tests, legacy migrations) stay valid under the FK.
    return (
        f"CREATE TRIGGER {table}_register_entity BEFORE INSERT ON {table} "
        f"BEGIN INSERT INTO entities (id, kind) VALUES (NEW.id, '{kind}'); END"
    )


def _migrate_to_v1(conn: sqlite3.Connection) -> None:
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    conn.execute(
        "CREATE TABLE entities (id TEXT PRIMARY KEY, kind TEXT NOT NULL "
        "CHECK (kind IN ('card', 'issue', 'document')))"
    )
    if "cards" in tables:
        # Legacy boards may hold references to cards that no longer exist;
        # drop them rather than refusing to migrate the whole board.
        conn.execute(
            "UPDATE cards SET parent_id = NULL WHERE parent_id IS NOT NULL "
            "AND parent_id NOT IN (SELECT id FROM cards)"
        )
        conn.execute("INSERT INTO entities (id, kind) SELECT id, 'card' FROM cards")
        conn.execute(_CARDS_SQL.format(name="cards_new"))
        conn.execute(
            "INSERT INTO cards_new SELECT id, title, description, status, parent_id, "
            "created_at, updated_at FROM cards"
        )
        conn.execute(_BLOCKED_BY_SQL.format(name="blocked_by_new"))
        if "blocked_by" in tables:
            conn.execute(
                "INSERT INTO blocked_by_new SELECT card_id, blocks_on_id FROM blocked_by "
                "WHERE card_id IN (SELECT id FROM cards) "
                "AND blocks_on_id IN (SELECT id FROM cards)"
            )
            conn.execute("DROP TABLE blocked_by")
        conn.execute("DROP TABLE cards")
        conn.execute("ALTER TABLE cards_new RENAME TO cards")
        conn.execute("ALTER TABLE blocked_by_new RENAME TO blocked_by")
    else:
        conn.execute(_CARDS_SQL.format(name="cards"))
        conn.execute(_BLOCKED_BY_SQL.format(name="blocked_by"))
    for statement in _V1_NEW_TABLES:
        conn.execute(statement)
    for table, kind in _ENTITY_KINDS:
        conn.execute(_register_trigger(table, kind))


def migrate_project(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= SCHEMA_VERSION:
        return
    conn.commit()
    # Must be issued outside a transaction; SQLite ignores it inside one.
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("BEGIN")
        _migrate_to_v1(conn)
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise MigrationError(
                f"migration left {len(violations)} foreign key violation(s)"
            )
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def init_project_schema(conn: sqlite3.Connection) -> None:
    migrate_project(conn)


def docs_dir(conn: sqlite3.Connection) -> Path:
    """Directory holding document backups: next to the db, `<db stem>.docs`."""
    main = next(row for row in conn.execute("PRAGMA database_list") if row["name"] == "main")
    return Path(main["file"]).with_suffix(".docs")
```

```python
def delete_card(conn: sqlite3.Connection, card_id: str) -> None:
    # Cascades to the cards row, its block edges, comments, tags, and refs.
    conn.execute("DELETE FROM entities WHERE id = ?", (card_id,))
    conn.commit()
```

- [ ] **Step 6: `paths.project_docs_dir` and migrate-on-connect**

Append to `src/brd/paths.py`:

```python
def project_docs_dir(root_path: Path) -> Path:
    return project_db_path(root_path).with_suffix(".docs")
```

In `src/brd/cli.py`, change `_project_conn` to:

```python
def _project_conn() -> sqlite3.Connection:
    db_path = master.resolve_project_db(Path.cwd())
    conn = db.connect(db_path)
    db.migrate_project(conn)
    return conn
```

- [ ] **Step 7: Run everything**

Run: `uv run pytest -q`
Expected: all pass (206 existing + 11 new).

- [ ] **Step 8: Commit**

```bash
git add src/brd/errors.py src/brd/db.py src/brd/paths.py src/brd/core.py src/brd/master.py src/brd/cli.py tests/test_migration.py
git commit -m "Add schema v1 migration with entities registry and shared error module"
```

---

### Task 2: `entities.py` — kind lookup and capability map

**Files:**
- Create: `src/brd/entities.py`, `tests/factories.py`, `tests/conftest.py`, `tests/test_entities.py`

**Interfaces:**
- Consumes: `db.migrate_project`, `errors.EntityNotFoundError`
- Produces:
  - `COMMENTABLE`, `TAGGABLE`, `BLOCKERS`, `REF_SOURCES`: `frozenset[str]`
  - `kind_of(conn, entity_id: str) -> str | None`
  - `require(conn, entity_id: str) -> str` (raises `EntityNotFoundError("no entity with id X")`)
  - `require_capability(conn, entity_id, allowed: frozenset[str], error_cls: type[BrdError], verb: str) -> str` — message `"{kind}s can't be {verb}"`
  - `title_of(conn, entity_id) -> str | None`
  - `summary(conn, entity_id) -> dict | None` → `{"id", "kind", "title"}`
  - `delete(conn, entity_id) -> None`
  - test fixtures: `pconn` (migrated project connection at `tmp_path/"project.db"`); factories `make_card`, `make_issue`, `make_document`

- [ ] **Step 1: Test support files**

`tests/factories.py`:

```python
from brd import db
from brd.models import Card

NOW = "2026-09-24T00:00:00+00:00"


def make_card(conn, id_, title=None, description=None, parent_id=None, status="todo"):
    db.insert_card(
        conn, Card(id_, title or id_, description, status, parent_id, NOW, NOW)
    )
    return id_


def make_issue(conn, id_, title=None, body=None, status="open"):
    conn.execute(
        "INSERT INTO issues (id, title, body, status, close_reason, created_at, "
        "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (id_, title or id_, body, status, "resolved" if status == "closed" else None, NOW, NOW),
    )
    conn.commit()
    return id_


def make_document(conn, id_, stem, content="", title=None):
    conn.execute(
        "INSERT INTO documents (id, title, source_path, stem, content_hash, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (id_, title or stem, f"docs/{stem}.md", stem, "0" * 64, NOW, NOW),
    )
    conn.commit()
    backups = db.docs_dir(conn)
    backups.mkdir(parents=True, exist_ok=True)
    (backups / f"{id_}.md").write_text(content)
    return id_
```

`tests/conftest.py`:

```python
import pytest

from brd import db


@pytest.fixture
def pconn(tmp_path):
    connection = db.connect(tmp_path / "project.db")
    db.migrate_project(connection)
    yield connection
    connection.close()
```

- [ ] **Step 2: Write the failing tests** — `tests/test_entities.py`

```python
import pytest

from brd import entities
from brd.errors import EntityNotFoundError, NotTaggableError
from tests.factories import make_card, make_document, make_issue


def test_kind_of_each_kind(pconn):
    make_card(pconn, "c")
    make_issue(pconn, "i")
    make_document(pconn, "d", "notes")
    assert [entities.kind_of(pconn, x) for x in ("c", "i", "d", "zz")] == [
        "card", "issue", "document", None,
    ]


def test_require_raises_for_unknown(pconn):
    with pytest.raises(EntityNotFoundError, match="no entity with id zz"):
        entities.require(pconn, "zz")


def test_require_capability_rejects_disallowed_kind(pconn):
    make_card(pconn, "c")
    with pytest.raises(NotTaggableError, match="cards can't be tagged"):
        entities.require_capability(pconn, "c", entities.TAGGABLE, NotTaggableError, "tagged")


def test_require_capability_returns_kind(pconn):
    make_document(pconn, "d", "notes")
    assert entities.require_capability(
        pconn, "d", entities.TAGGABLE, NotTaggableError, "tagged"
    ) == "document"


def test_title_and_summary(pconn):
    make_issue(pconn, "i", title="Grammar ambiguity")
    assert entities.title_of(pconn, "i") == "Grammar ambiguity"
    assert entities.summary(pconn, "i") == {"id": "i", "kind": "issue", "title": "Grammar ambiguity"}
    assert entities.summary(pconn, "zz") is None


def test_delete_cascades(pconn):
    make_issue(pconn, "i")
    entities.delete(pconn, "i")
    assert entities.kind_of(pconn, "i") is None
    assert pconn.execute("SELECT COUNT(*) FROM issues").fetchone()[0] == 0


def test_capability_map():
    assert entities.COMMENTABLE == {"card", "issue"}
    assert entities.TAGGABLE == {"document"}
    assert entities.BLOCKERS == {"card", "issue"}
    assert entities.REF_SOURCES == {"card", "issue", "document"}
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_entities.py -v`
Expected: FAIL — `ImportError: cannot import name 'entities'`.

- [ ] **Step 4: Implement `src/brd/entities.py`**

```python
import sqlite3

from brd.errors import BrdError, EntityNotFoundError

# Which kinds support which shared feature. Enabling a feature for another
# kind is a one-word change here.
COMMENTABLE = frozenset({"card", "issue"})
TAGGABLE = frozenset({"document"})
BLOCKERS = frozenset({"card", "issue"})
REF_SOURCES = frozenset({"card", "issue", "document"})

_KIND_TABLES = {"card": "cards", "issue": "issues", "document": "documents"}


def kind_of(conn: sqlite3.Connection, entity_id: str) -> str | None:
    row = conn.execute("SELECT kind FROM entities WHERE id = ?", (entity_id,)).fetchone()
    return row["kind"] if row else None


def require(conn: sqlite3.Connection, entity_id: str) -> str:
    kind = kind_of(conn, entity_id)
    if kind is None:
        raise EntityNotFoundError(f"no entity with id {entity_id}")
    return kind


def require_capability(
    conn: sqlite3.Connection,
    entity_id: str,
    allowed: frozenset[str],
    error_cls: type[BrdError],
    verb: str,
) -> str:
    kind = require(conn, entity_id)
    if kind not in allowed:
        raise error_cls(f"{kind}s can't be {verb}")
    return kind


def title_of(conn: sqlite3.Connection, entity_id: str) -> str | None:
    kind = kind_of(conn, entity_id)
    if kind is None:
        return None
    row = conn.execute(
        f"SELECT title FROM {_KIND_TABLES[kind]} WHERE id = ?", (entity_id,)
    ).fetchone()
    return row["title"] if row else None


def summary(conn: sqlite3.Connection, entity_id: str) -> dict | None:
    kind = kind_of(conn, entity_id)
    if kind is None:
        return None
    return {"id": entity_id, "kind": kind, "title": title_of(conn, entity_id)}


def delete(conn: sqlite3.Connection, entity_id: str) -> None:
    conn.execute("DELETE FROM entities WHERE id = ?", (entity_id,))
    conn.commit()
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/brd/entities.py tests/factories.py tests/conftest.py tests/test_entities.py
git commit -m "Add entities module with kind lookup and capability map"
```

---

### Task 3: Split the CLI into a package with a shared `run()` helper

**Files:**
- Delete: `src/brd/cli.py`
- Create: `src/brd/cli/__init__.py`, `src/brd/cli/_app.py`, `src/brd/cli/project.py`, `src/brd/cli/cards.py`, `src/brd/views.py`, `tests/cli_helpers.py`, `tests/test_cli_app.py`
- Modify: `src/brd/master.py` (add `resolve_project_root`), `tests/conftest.py` (add `project` fixture)

**Interfaces:**
- Consumes: `db.migrate_project`, `errors.BrdError`
- Produces:
  - `master.resolve_project_root(start: Path) -> Path` (raises `ProjectNotFoundError`)
  - `brd.cli._app`: `app`, `Ctx(conn: sqlite3.Connection, root: Path)`, `pretty_option()`, `fail(exc: BrdError, pretty: bool) -> NoReturn`, `run(pretty: bool, fn: Callable[[Ctx], Any], render: Callable[[Ctx, Any], str] | None = None) -> None`
  - `views.card_detail(conn, card: Card) -> dict`
  - tests: `project` fixture (initialized repo, cwd set, `BRD_AUTHOR` unset); `tests.cli_helpers.ok(*args, input=None) -> data`, `err(*args, input=None) -> error type str`, `human(*args) -> stdout str`

- [ ] **Step 1: Test helpers and a failing test**

`tests/cli_helpers.py`:

```python
import json

from typer.testing import CliRunner

from brd.cli import app

runner = CliRunner()


def invoke(*args, input=None):
    return runner.invoke(app, [str(a) for a in args], input=input)


def ok(*args, input=None):
    result = invoke(*args, input=input)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True, payload
    return payload["data"]


def err(*args, input=None) -> str:
    result = invoke(*args, input=input)
    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is False, payload
    return payload["error"]["type"]


def human(*args) -> str:
    result = invoke(*args, "--pretty")
    assert result.exit_code == 0, result.output
    return result.stdout
```

Append to `tests/conftest.py`:

```python
@pytest.fixture
def project(tmp_path, monkeypatch):
    from tests.cli_helpers import ok

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("BRD_AUTHOR", raising=False)
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    ok("init")
    return repo
```

`tests/test_cli_app.py`:

```python
import sqlite3

from brd import db, paths
from brd.cli import _app
from tests.cli_helpers import err, ok


def test_cli_is_a_package_exposing_app():
    from brd.cli import app

    assert app is _app.app


def test_commands_migrate_a_v0_board(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".brd").write_text("")
    monkeypatch.chdir(repo)
    legacy = sqlite3.connect(paths.project_db_path(repo))
    legacy.execute(
        "CREATE TABLE cards (id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT, "
        "status TEXT NOT NULL, parent_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    legacy.execute("CREATE TABLE blocked_by (card_id TEXT, blocks_on_id TEXT)")
    legacy.execute("INSERT INTO cards VALUES ('c1', 'Old', NULL, 'todo', NULL, 'now', 'now')")
    legacy.commit()
    legacy.close()

    assert [c["id"] for c in ok("list")] == ["c1"]
    conn = db.connect(paths.project_db_path(repo))
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1


def test_domain_errors_become_envelopes(project):
    assert err("show", "nope") == "CardNotFoundError"


def test_missing_project_is_an_envelope(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    assert err("list") == "ProjectNotFoundError"
```

Run: `uv run pytest tests/test_cli_app.py -v`
Expected: FAIL — `ImportError: cannot import name '_app' from 'brd.cli'`.

- [ ] **Step 2: `master.resolve_project_root`**

In `src/brd/master.py`, replace `resolve_project_db` with:

```python
def resolve_project_root(start: Path) -> Path:
    marker = find_marker(start)
    if marker is None:
        raise ProjectNotFoundError(f"no {MARKER_FILENAME} marker found above {start}")
    return marker.parent


def resolve_project_db(start: Path) -> Path:
    return paths.project_db_path(resolve_project_root(start))
```

- [ ] **Step 3: `src/brd/views.py`**

```python
import sqlite3

from brd import core, db
from brd.models import Card


def card_detail(conn: sqlite3.Connection, card: Card) -> dict:
    return {
        "id": card.id,
        "title": card.title,
        "description": card.description,
        "status": core.resolve_status(conn, card),
        "parent_id": card.parent_id,
        "created_at": card.created_at,
        "updated_at": card.updated_at,
        "blocked_by": db.list_blockers_of(conn, card.id),
        "children": [child.id for child in db.list_children(conn, card.id)],
    }
```

- [ ] **Step 4: `src/brd/cli/_app.py`**

```python
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

import typer

from brd import db, master, output, paths
from brd.errors import BrdError

app = typer.Typer(
    name="brd",
    help="Local kanban board for tracking work, no visual UI.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    pass


def pretty_option():
    return typer.Option(False, "--pretty", "--human", help="Human-readable output.")


@dataclass
class Ctx:
    conn: sqlite3.Connection
    root: Path


def fail(exc: BrdError, pretty: bool) -> NoReturn:
    output.print_result(output.error_envelope(type(exc).__name__, str(exc)), pretty)
    raise typer.Exit(code=1)


def open_project() -> Ctx:
    root = master.resolve_project_root(Path.cwd())
    conn = db.connect(paths.project_db_path(root))
    db.migrate_project(conn)
    return Ctx(conn=conn, root=root)


def run(
    pretty: bool,
    fn: Callable[[Ctx], Any],
    render: Callable[[Ctx, Any], str] | None = None,
) -> None:
    """Open the current project, run fn, and print its result as an envelope
    (or as render's text in --pretty mode). Any BrdError becomes an error
    envelope and exit code 1."""
    try:
        ctx = open_project()
    except BrdError as exc:
        fail(exc, pretty)
    try:
        data = fn(ctx)
        text = render(ctx, data) if pretty and render is not None else None
    except BrdError as exc:
        fail(exc, pretty)
    finally:
        ctx.conn.close()
    if text is not None:
        print(text)
    else:
        output.print_result(output.ok_envelope(data), pretty)
```

- [ ] **Step 5: `src/brd/cli/project.py`** (moved verbatim, forget uses `fail`)

```python
import dataclasses
from pathlib import Path

import typer

from brd import master, output, prompt
from brd.cli._app import app, fail, pretty_option
from brd.errors import BrdError


@app.command(name="prompt")
def prompt_cmd() -> None:
    """Print a short CLAUDE.md snippet explaining how to use brd."""
    print(prompt.render(), end="")


@app.command()
def init(
    name: str | None = typer.Option(
        None, "--name", help="Override the default project name."
    ),
    pretty: bool = pretty_option(),
) -> None:
    """Register the current directory as a brd project."""
    project = master.init_project(Path.cwd(), name=name)
    output.print_result(output.ok_envelope(dataclasses.asdict(project)), pretty)


@app.command()
def projects(pretty: bool = pretty_option()) -> None:
    """List all registered projects."""
    all_projects = master.list_all_projects()
    envelope = output.ok_envelope([dataclasses.asdict(p) for p in all_projects])
    output.print_result(envelope, pretty)


@app.command()
def forget(
    path: Path | None = typer.Argument(
        None,
        help="Root path of the project to forget (defaults to the current "
        "directory).",
    ),
    pretty: bool = pretty_option(),
) -> None:
    """Un-register a project and delete its stored data."""
    root_path = path if path is not None else Path.cwd()
    try:
        project = master.forget_project(root_path)
    except BrdError as exc:
        fail(exc, pretty)
    output.print_result(output.ok_envelope(dataclasses.asdict(project)), pretty)


@app.command()
def purge(
    yes: bool = typer.Option(False, "--yes", help="Skip the confirmation prompt."),
    pretty: bool = pretty_option(),
) -> None:
    """Delete ALL brd data for every project. Cannot be undone."""
    all_projects = master.list_all_projects()
    if not yes:
        confirmed = typer.confirm(
            f"Delete all brd data for {len(all_projects)} project(s)? "
            "This cannot be undone."
        )
        if not confirmed:
            output.print_result(
                output.error_envelope("Aborted", "Purge cancelled."), pretty
            )
            raise typer.Exit(code=1)

    removed = master.purge_all()
    output.print_result(output.ok_envelope({"projects_removed": removed}), pretty)
```

- [ ] **Step 6: `src/brd/cli/cards.py`** (moved; boilerplate replaced by `run`)

```python
import json
import sqlite3
from pathlib import Path

import typer

from brd import core, db, output, views
from brd.cli._app import app, pretty_option, run
from brd.errors import CardNotFoundError, ImportReadError
from brd.models import Card


def _require_card(conn: sqlite3.Connection, card_id: str) -> Card:
    card = db.get_card(conn, card_id)
    if card is None:
        raise CardNotFoundError(f"no card with id {card_id}")
    return card


@app.command()
def add(
    title: str = typer.Option(..., "--title", help="Card title."),
    description: str | None = typer.Option(
        None, "--description", help="Card description."
    ),
    parent: str | None = typer.Option(None, "--parent", help="Parent card id."),
    blocked_by: list[str] = typer.Option(
        [], "--blocked-by", help="Id of a card this one is blocked by (repeatable)."
    ),
    pretty: bool = pretty_option(),
) -> None:
    """Create a card."""

    def action(ctx):
        card = core.create_card(
            ctx.conn,
            title=title,
            description=description,
            parent_id=parent,
            blocked_by=list(blocked_by),
        )
        return views.card_detail(ctx.conn, card)

    run(pretty, action)


@app.command()
def show(
    card_id: str = typer.Argument(..., help="Id of the card to show."),
    pretty: bool = pretty_option(),
) -> None:
    """Show a single card's full detail."""
    run(pretty, lambda ctx: views.card_detail(ctx.conn, _require_card(ctx.conn, card_id)))


@app.command(name="list")
def list_cards_cmd(
    status: str | None = typer.Option(None, "--status", help="Filter by stored status."),
    parent: str | None = typer.Option(
        None, "--parent", help="Only cards whose parent is this card id."
    ),
    pretty: bool = pretty_option(),
) -> None:
    """List cards, optionally filtered."""

    def action(ctx):
        # db.list_cards uses an _UNSET sentinel for parent_id, so only pass the
        # kwarg when --parent was given; passing None means "parent IS NULL".
        kwargs: dict = {"status": status}
        if parent is not None:
            kwargs["parent_id"] = parent
        return [views.card_detail(ctx.conn, card) for card in db.list_cards(ctx.conn, **kwargs)]

    run(pretty, action)


@app.command()
def update(
    card_id: str = typer.Argument(..., help="Id of the card to update."),
    title: str | None = typer.Option(None, "--title", help="New title."),
    description: str | None = typer.Option(
        None, "--description", help="New description."
    ),
    status: str | None = typer.Option(
        None, "--status", help="New stored status (cannot be 'blocked')."
    ),
    parent: str | None = typer.Option(None, "--parent", help="New parent card id."),
    clear_parent: bool = typer.Option(
        False, "--clear-parent", help="Detach the card from its parent."
    ),
    pretty: bool = pretty_option(),
) -> None:
    """Edit a card's fields."""

    def action(ctx):
        parent_arg = core.CLEAR_PARENT if clear_parent else parent
        card = core.update_card(
            ctx.conn,
            card_id,
            title=title,
            description=description,
            status=status,
            parent_id=parent_arg,
        )
        return views.card_detail(ctx.conn, card)

    run(pretty, action)


@app.command()
def delete(
    card_id: str = typer.Argument(..., help="Id of the card to delete."),
    cascade: bool = typer.Option(
        False, "--cascade", help="Also delete all descendant cards."
    ),
    pretty: bool = pretty_option(),
) -> None:
    """Delete a card."""
    run(pretty, lambda ctx: {"deleted": core.delete_card(ctx.conn, card_id, cascade=cascade)})


@app.command()
def block(
    card_id: str = typer.Argument(..., help="Id of the card to block."),
    by: str = typer.Option(..., "--by", help="Id of the card blocking it."),
    pretty: bool = pretty_option(),
) -> None:
    """Mark a card as blocked by another card."""

    def action(ctx):
        core.block_card(ctx.conn, card_id, by)
        return views.card_detail(ctx.conn, _require_card(ctx.conn, card_id))

    run(pretty, action)


@app.command()
def unblock(
    card_id: str = typer.Argument(..., help="Id of the card to unblock."),
    by: str = typer.Option(..., "--by", help="Id of the blocker to remove."),
    pretty: bool = pretty_option(),
) -> None:
    """Remove a blocked-by relationship."""

    def action(ctx):
        core.unblock_card(ctx.conn, card_id, by)
        return views.card_detail(ctx.conn, _require_card(ctx.conn, card_id))

    run(pretty, action)


@app.command()
def tree(
    card_id: str | None = typer.Argument(
        None, help="Root the tree at this card id (default: whole board)."
    ),
    pretty: bool = pretty_option(),
) -> None:
    """Print the hierarchy and dependency tree."""
    run(
        pretty,
        lambda ctx: core.build_tree(ctx.conn, root_id=card_id),
        render=lambda ctx, data: output.render_tree_text(data),
    )


@app.command(name="import")
def import_cmd(
    file: Path = typer.Argument(
        ..., help="Path to a JSON file in `brd tree`'s output shape."
    ),
    pretty: bool = pretty_option(),
) -> None:
    """Restore cards from a brd tree JSON snapshot."""

    def action(ctx):
        try:
            raw = json.loads(file.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ImportReadError(
                f"could not read a JSON snapshot from {file}: {exc}"
            ) from exc
        nodes = raw["data"] if isinstance(raw, dict) and "data" in raw else raw
        return {"imported": core.import_tree(ctx.conn, nodes)}

    run(pretty, action)


@app.command(name="next")
def next_cmd(
    limit: int | None = typer.Option(
        None, "--limit", help="Return at most this many cards."
    ),
    parent: str | None = typer.Option(
        None,
        "--parent",
        help="Ready direct children of this card id, instead of leaf cards "
        "across the whole board.",
    ),
    pretty: bool = pretty_option(),
) -> None:
    """List unblocked todo cards, oldest first."""

    def action(ctx):
        cards = core.next_cards(ctx.conn, limit=limit, parent_id=parent)
        return [views.card_detail(ctx.conn, card) for card in cards]

    run(pretty, action)
```

- [ ] **Step 7: `src/brd/cli/__init__.py`, then delete `src/brd/cli.py`**

```python
from brd.cli._app import app
from brd.cli import project, cards  # noqa: E402,F401  (registers commands)

__all__ = ["app"]
```

Run: `git rm src/brd/cli.py`

- [ ] **Step 8: Run everything**

Run: `uv run pytest -q`
Expected: all pass — including every test in `tests/test_cli.py`, unmodified.

- [ ] **Step 9: Commit**

```bash
git add -A src/brd tests/cli_helpers.py tests/conftest.py tests/test_cli_app.py
git commit -m "Split CLI into a package with a shared run() helper"
```

---

## Milestone 2 — Links, references, comments, tags

### Task 4: `links.py` — pure `[[link]]` parser and renderer

**Files:**
- Create: `src/brd/links.py`, `tests/test_links.py`

**Interfaces:**
- Produces:
  - `LinkToken(target: str, alias: str | None, start: int, end: int)` (frozen dataclass)
  - `parse(text: str | None) -> list[LinkToken]`
  - `render(text: str | None, display: Callable[[LinkToken], str | None]) -> str` — `display` returns the resolved target's title or `None` if unresolved.

- [ ] **Step 1: Write the failing tests** — `tests/test_links.py`

```python
import pytest

from brd import links


def targets(text):
    return [(t.target, t.alias) for t in links.parse(text)]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("see [[notes]]", [("notes", None)]),
        ("[[notes#Intro]]", [("notes", None)]),
        ("[[notes|the notes]]", [("notes", "the notes")]),
        ("[[notes#Intro|the notes]]", [("notes", "the notes")]),
        ("[[docs/notes.md]]", [("docs/notes.md", None)]),
        ("[[ Design Notes ]]", [("Design Notes", None)]),
        ("[[a]] and [[b]] on one line", [("a", None), ("b", None)]),
        ("[[a [[b]]", [("b", None)]),
        ("[[]] [[#only-heading]] [[|alias]]", []),
        ("no links here", []),
        ("", []),
        (None, []),
        ("`[[in inline code]]` but [[out]]", [("out", None)]),
        ("```\n[[fenced]]\n```\n[[after]]", [("after", None)]),
        ("~~~\n[[tilde]]\n~~~\n[[after]]", [("after", None)]),
        ("```\n[[unclosed fence]]", []),
        ("````\n```\n[[still fenced]]\n````\n[[after]]", [("after", None)]),
    ],
)
def test_parse(text, expected):
    assert targets(text) == expected


def test_parse_positions_cover_the_whole_link():
    token = links.parse("x [[notes]] y")[0]
    assert "x [[notes]] y"[token.start : token.end] == "[[notes]]"


def test_render_uses_title_alias_and_marks_unresolved():
    titles = {"a": "Alpha"}
    rendered = links.render(
        "[[a]], [[a|custom]], [[ghost]], [[ghost|named]], `[[a]]`",
        lambda token: titles.get(token.target),
    )
    assert rendered == (
        "[[Alpha]], [[custom]], [[ghost]] (unresolved), [[named]] (unresolved), `[[a]]`"
    )


def test_render_empty():
    assert links.render(None, lambda t: None) == ""
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_links.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement `src/brd/links.py`**

```python
import re
from collections.abc import Callable
from dataclasses import dataclass

_LINK = re.compile(r"\[\[([^\[\]\n]+?)\]\]")
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


@dataclass(frozen=True)
class LinkToken:
    target: str
    alias: str | None
    start: int
    end: int


def _code_spans(text: str) -> list[tuple[int, int]]:
    """Character ranges covered by fenced code blocks and inline code spans."""
    spans: list[tuple[int, int]] = []
    offset = 0
    fence: str | None = None
    fence_start = 0
    for line in text.splitlines(keepends=True):
        match = _FENCE.match(line)
        if fence is None:
            if match:
                fence = match.group(1)
                fence_start = offset
            else:
                for inline in _INLINE_CODE.finditer(line):
                    spans.append((offset + inline.start(), offset + inline.end()))
        elif match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence):
            spans.append((fence_start, offset + len(line)))
            fence = None
        offset += len(line)
    if fence is not None:
        spans.append((fence_start, len(text)))
    return spans


def _split(inner: str) -> tuple[str, str | None]:
    target, has_alias, alias = inner.partition("|")
    target = target.partition("#")[0].strip()
    alias = alias.strip() if has_alias else ""
    return target, alias or None


def parse(text: str | None) -> list[LinkToken]:
    if not text:
        return []
    spans = _code_spans(text)
    tokens = []
    for match in _LINK.finditer(text):
        if any(start <= match.start() < end for start, end in spans):
            continue
        target, alias = _split(match.group(1))
        if target:
            tokens.append(LinkToken(target, alias, match.start(), match.end()))
    return tokens


def render(text: str | None, display: Callable[[LinkToken], str | None]) -> str:
    """Rewrite each link as [[<alias or target title>]]; unresolved links keep
    their text and gain an '(unresolved)' marker. Links in code are untouched."""
    if not text:
        return ""
    parts = []
    position = 0
    for token in parse(text):
        parts.append(text[position : token.start])
        title = display(token)
        if title is None:
            parts.append(f"[[{token.alias or token.target}]] (unresolved)")
        else:
            parts.append(f"[[{token.alias or title}]]")
        position = token.end
    parts.append(text[position:])
    return "".join(parts)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_links.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/brd/links.py tests/test_links.py
git commit -m "Add Obsidian-style link parser and renderer"
```

---

### Task 5: `refs.py` — resolution, reindexing, explicit refs; card hooks

**Files:**
- Create: `src/brd/refs.py`, `tests/test_refs.py`
- Modify: `src/brd/core.py` (`create_card`, `update_card`), `tests/test_core.py` (append tests only)

**Interfaces:**
- Consumes: `links.parse`, `entities.kind_of/require/summary`, `db.docs_dir`
- Produces:
  - `normalize_stem(target: str) -> str`
  - `resolve(conn, target: str) -> str | None`
  - `own_text(conn, entity_id) -> str`
  - `reindex(conn, entity_id) -> None`
  - `reindex_mentions(conn, stem: str) -> None`
  - `add_explicit(conn, src_id, dst_id) -> None`, `remove_explicit(conn, src_id, dst_id) -> None`
  - `outgoing(conn, entity_id) -> list[dict]`, `incoming(conn, entity_id) -> list[dict]` — items `{"id", "kind", "title", "origin"}`

- [ ] **Step 1: Write the failing tests** — `tests/test_refs.py`

```python
import pytest

from brd import refs
from brd.errors import EntityNotFoundError, SelfReferenceError
from tests.factories import make_card, make_document

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
D = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
E = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"


def out(conn, entity_id):
    return {(r["id"], r["origin"]) for r in refs.outgoing(conn, entity_id)}


def test_resolve_uuid(pconn):
    make_card(pconn, A)
    assert refs.resolve(pconn, A) == A
    assert refs.resolve(pconn, A.upper()) == A
    assert refs.resolve(pconn, B) is None


@pytest.mark.parametrize(
    "target",
    ["design notes", "Design Notes", "Design Notes.md", "docs/Design Notes", "docs/design notes.MD"],
)
def test_resolve_stem_forms(pconn, target):
    make_document(pconn, D, "Design Notes")
    assert refs.resolve(pconn, target) == D


def test_resolve_unknown_stem(pconn):
    assert refs.resolve(pconn, "nowhere") is None


def test_reindex_creates_link_refs_and_skips_unresolved(pconn):
    make_card(pconn, B)
    make_document(pconn, D, "parser-notes")
    make_card(pconn, A, description=f"see [[{B}]], [[parser-notes]] and [[nowhere]]")
    refs.reindex(pconn, A)
    assert out(pconn, A) == {(B, "link"), (D, "link")}


def test_reindex_is_idempotent(pconn):
    make_card(pconn, B)
    make_card(pconn, A, description=f"[[{B}]]")
    refs.reindex(pconn, A)
    refs.reindex(pconn, A)
    assert len(refs.outgoing(pconn, A)) == 1


def test_reindex_preserves_explicit_refs(pconn):
    make_card(pconn, B)
    make_card(pconn, A, description=f"[[{B}]]")
    refs.add_explicit(pconn, A, B)
    pconn.execute("UPDATE cards SET description = NULL WHERE id = ?", (A,))
    refs.reindex(pconn, A)
    assert out(pconn, A) == {(B, "explicit")}


def test_self_links_are_dropped(pconn):
    make_card(pconn, A, description=f"[[{A}]]")
    refs.reindex(pconn, A)
    assert refs.outgoing(pconn, A) == []


def test_comment_links_are_attributed_to_parent(pconn):
    make_card(pconn, A)
    make_card(pconn, B)
    pconn.execute(
        "INSERT INTO comments (id, entity_id, author, body, created_at) "
        "VALUES ('k1', ?, 'me', ?, 'now')",
        (A, f"see [[{B}]]"),
    )
    refs.reindex(pconn, A)
    assert out(pconn, A) == {(B, "link")}


def test_document_backup_links_are_indexed(pconn):
    make_card(pconn, A)
    make_document(pconn, D, "notes", content=f"relates to [[{A}]]")
    refs.reindex(pconn, D)
    assert {(r["id"], r["origin"]) for r in refs.incoming(pconn, A)} == {(D, "link")}


def test_incoming_and_titles(pconn):
    make_card(pconn, B, title="Target")
    make_card(pconn, A, title="Source", description=f"[[{B}]]")
    refs.reindex(pconn, A)
    assert refs.incoming(pconn, B) == [{"id": A, "kind": "card", "title": "Source", "origin": "link"}]
    assert refs.outgoing(pconn, A) == [{"id": B, "kind": "card", "title": "Target", "origin": "link"}]


def test_deleted_target_disappears_from_refs(pconn):
    make_card(pconn, B)
    make_card(pconn, A, description=f"[[{B}]]")
    refs.reindex(pconn, A)
    pconn.execute("DELETE FROM entities WHERE id = ?", (B,))
    assert refs.outgoing(pconn, A) == []


def test_add_explicit_validates(pconn):
    make_card(pconn, A)
    with pytest.raises(SelfReferenceError):
        refs.add_explicit(pconn, A, A)
    with pytest.raises(EntityNotFoundError):
        refs.add_explicit(pconn, A, B)
    with pytest.raises(EntityNotFoundError):
        refs.add_explicit(pconn, B, A)


def test_remove_explicit(pconn):
    make_card(pconn, A)
    make_card(pconn, B)
    refs.add_explicit(pconn, A, B)
    refs.add_explicit(pconn, A, B)  # idempotent
    refs.remove_explicit(pconn, A, B)
    assert refs.outgoing(pconn, A) == []


def test_reindex_mentions_resolves_forward_links_in_cards(pconn):
    make_card(pconn, A, description="todo: [[later]]")
    refs.reindex(pconn, A)
    assert refs.outgoing(pconn, A) == []
    make_document(pconn, D, "later")
    refs.reindex_mentions(pconn, "later")
    assert out(pconn, A) == {(D, "link")}


def test_reindex_mentions_scans_document_backups(pconn):
    make_document(pconn, D, "hub", content="see [[Later]]")
    refs.reindex(pconn, D)
    make_document(pconn, E, "later")
    refs.reindex_mentions(pconn, "later")
    assert out(pconn, D) == {(E, "link")}
```

Append to `tests/test_core.py`:

```python
from brd import refs as _refs


def test_create_card_indexes_description_links(conn):
    target = core.create_card(conn, title="Target")
    source = core.create_card(conn, title="Source", description=f"see [[{target.id}]]")
    assert [r["id"] for r in _refs.outgoing(conn, source.id)] == [target.id]


def test_update_card_removing_link_drops_link_ref_but_keeps_explicit(conn):
    target = core.create_card(conn, title="Target")
    other = core.create_card(conn, title="Other")
    source = core.create_card(conn, title="Source", description=f"[[{target.id}]] [[{other.id}]]")
    _refs.add_explicit(conn, source.id, other.id)
    core.update_card(conn, source.id, description="no links now")
    assert {(r["id"], r["origin"]) for r in _refs.outgoing(conn, source.id)} == {
        (other.id, "explicit")
    }
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_refs.py tests/test_core.py -v`
Expected: FAIL — `ImportError: cannot import name 'refs'`.

- [ ] **Step 3: Implement `src/brd/refs.py`**

```python
import sqlite3
import uuid

from brd import db, entities, links
from brd.errors import SelfReferenceError


def normalize_stem(target: str) -> str:
    name = target.rsplit("/", 1)[-1]
    if name.lower().endswith(".md"):
        name = name[:-3]
    return name.strip()


def _as_uuid(target: str) -> str | None:
    try:
        return str(uuid.UUID(target))
    except ValueError:
        return None


def resolve(conn: sqlite3.Connection, target: str) -> str | None:
    as_uuid = _as_uuid(target)
    if as_uuid is not None:
        return as_uuid if entities.kind_of(conn, as_uuid) else None
    row = conn.execute(
        "SELECT id FROM documents WHERE stem = ?", (normalize_stem(target),)
    ).fetchone()  # stem is COLLATE NOCASE
    return row["id"] if row else None


def _read_backup(conn: sqlite3.Connection, doc_id: str) -> str:
    path = db.docs_dir(conn) / f"{doc_id}.md"
    return path.read_bytes().decode("utf-8", "replace") if path.is_file() else ""


def own_text(conn: sqlite3.Connection, entity_id: str) -> str:
    kind = entities.kind_of(conn, entity_id)
    if kind == "card":
        row = conn.execute("SELECT description FROM cards WHERE id = ?", (entity_id,)).fetchone()
        return row["description"] or ""
    if kind == "issue":
        row = conn.execute("SELECT body FROM issues WHERE id = ?", (entity_id,)).fetchone()
        return row["body"] or ""
    if kind == "document":
        return _read_backup(conn, entity_id)
    return ""


def reindex(conn: sqlite3.Connection, entity_id: str) -> None:
    """Rebuild entity_id's origin='link' refs from its own text plus the
    bodies of its comments. Explicit refs are never touched."""
    texts = [own_text(conn, entity_id)] + [
        row["body"]
        for row in conn.execute("SELECT body FROM comments WHERE entity_id = ?", (entity_id,))
    ]
    targets: set[str] = set()
    for text in texts:
        for token in links.parse(text):
            dst = resolve(conn, token.target)
            if dst is not None and dst != entity_id:
                targets.add(dst)
    conn.execute("DELETE FROM refs WHERE src_id = ? AND origin = 'link'", (entity_id,))
    conn.executemany(
        "INSERT INTO refs (src_id, dst_id, origin) VALUES (?, ?, 'link')",
        [(entity_id, dst) for dst in sorted(targets)],
    )
    conn.commit()


def reindex_mentions(conn: sqlite3.Connection, stem: str) -> None:
    """Reindex every entity whose text mentions stem, so links written before
    a document existed (or under its old name) resolve now. Over-matching is
    harmless: reindex is idempotent."""
    pattern = "%" + stem.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    ids: set[str] = set()
    for query in (
        "SELECT id FROM cards WHERE description LIKE ? ESCAPE '\\'",
        "SELECT id FROM issues WHERE body LIKE ? ESCAPE '\\'",
        "SELECT entity_id AS id FROM comments WHERE body LIKE ? ESCAPE '\\'",
    ):
        ids.update(row["id"] for row in conn.execute(query, (pattern,)))
    needle = stem.lower()
    for row in conn.execute("SELECT id FROM documents").fetchall():
        if needle in _read_backup(conn, row["id"]).lower():
            ids.add(row["id"])
    for entity_id in sorted(ids):
        reindex(conn, entity_id)


def add_explicit(conn: sqlite3.Connection, src_id: str, dst_id: str) -> None:
    entities.require(conn, src_id)
    entities.require(conn, dst_id)
    if src_id == dst_id:
        raise SelfReferenceError(f"{src_id} can't reference itself")
    conn.execute(
        "INSERT OR IGNORE INTO refs (src_id, dst_id, origin) VALUES (?, ?, 'explicit')",
        (src_id, dst_id),
    )
    conn.commit()


def remove_explicit(conn: sqlite3.Connection, src_id: str, dst_id: str) -> None:
    entities.require(conn, src_id)
    conn.execute(
        "DELETE FROM refs WHERE src_id = ? AND dst_id = ? AND origin = 'explicit'",
        (src_id, dst_id),
    )
    conn.commit()


def _summaries(conn: sqlite3.Connection, rows, column: str) -> list[dict]:
    return [{**entities.summary(conn, row[column]), "origin": row["origin"]} for row in rows]


def outgoing(conn: sqlite3.Connection, entity_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT dst_id, origin FROM refs WHERE src_id = ? ORDER BY origin, dst_id",
        (entity_id,),
    ).fetchall()
    return _summaries(conn, rows, "dst_id")


def incoming(conn: sqlite3.Connection, entity_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT src_id, origin FROM refs WHERE dst_id = ? ORDER BY origin, src_id",
        (entity_id,),
    ).fetchall()
    return _summaries(conn, rows, "src_id")
```

- [ ] **Step 4: Hook card writes in `src/brd/core.py`**

Change `from brd import db` to `from brd import db, refs`. In `create_card`, immediately before `return card`, add:

```python
    if description:
        refs.reindex(conn, card.id)
```

In `update_card`, immediately after `db.update_card_fields(conn, card_id, **fields)` (inside the `if fields:` block), add:

```python
        if description is not None:
            refs.reindex(conn, card_id)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/brd/refs.py src/brd/core.py tests/test_refs.py tests/test_core.py
git commit -m "Add reference resolution and link reindexing"
```

---

### Task 6: `comments.py` and `tags.py`

**Files:**
- Create: `src/brd/comments.py`, `src/brd/tags.py`, `tests/test_comments.py`, `tests/test_tags.py`

**Interfaces:**
- Consumes: `entities.require/require_capability/COMMENTABLE/TAGGABLE`, `refs.reindex`
- Produces:
  - `comments.Comment(id, entity_id, author, body, created_at)` dataclass
  - `comments.resolve_author(explicit: str | None) -> str`
  - `comments.add(conn, entity_id, body, author) -> Comment`
  - `comments.list_for(conn, entity_id) -> list[Comment]`
  - `comments.delete(conn, comment_id) -> Comment`
  - `tags.normalize(tag: str) -> str`
  - `tags.add(conn, entity_id, tag_list: list[str]) -> list[str]`, `tags.remove(...) -> list[str]` (both return the entity's sorted tags)
  - `tags.list_for(conn, entity_id) -> list[str]`
  - `tags.counts(conn) -> list[dict]` → `[{"tag", "count"}]` sorted by tag

- [ ] **Step 1: Write the failing tests**

`tests/test_comments.py`:

```python
import pytest

from brd import comments, refs
from brd.errors import (
    CommentNotFoundError,
    EmptyCommentError,
    EntityNotFoundError,
    NotCommentableError,
)
from tests.factories import make_card, make_document, make_issue

B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def test_add_and_list_on_card_and_issue(pconn):
    make_card(pconn, "c")
    make_issue(pconn, "i")
    first = comments.add(pconn, "c", "one", "alice")
    comments.add(pconn, "c", "two", "claude")
    comments.add(pconn, "i", "on issue", "alice")
    assert [c.body for c in comments.list_for(pconn, "c")] == ["one", "two"]
    assert first.author == "alice" and first.entity_id == "c"


def test_documents_are_not_commentable(pconn):
    make_document(pconn, "d", "notes")
    with pytest.raises(NotCommentableError, match="documents can't be commented on"):
        comments.add(pconn, "d", "hi", "alice")


def test_unknown_entity(pconn):
    with pytest.raises(EntityNotFoundError):
        comments.add(pconn, "zz", "hi", "alice")
    with pytest.raises(EntityNotFoundError):
        comments.list_for(pconn, "zz")


def test_empty_body_rejected(pconn):
    make_card(pconn, "c")
    with pytest.raises(EmptyCommentError):
        comments.add(pconn, "c", "   ", "alice")


def test_links_in_comments_become_parent_refs_and_go_on_delete(pconn):
    make_card(pconn, "c")
    make_card(pconn, B)
    comment = comments.add(pconn, "c", f"see [[{B}]]", "alice")
    assert [r["id"] for r in refs.outgoing(pconn, "c")] == [B]
    comments.delete(pconn, comment.id)
    assert refs.outgoing(pconn, "c") == []


def test_delete_unknown(pconn):
    with pytest.raises(CommentNotFoundError):
        comments.delete(pconn, "nope")


def test_comments_cascade_with_entity(pconn):
    make_card(pconn, "c")
    comments.add(pconn, "c", "x", "alice")
    pconn.execute("DELETE FROM entities WHERE id = 'c'")
    assert pconn.execute("SELECT COUNT(*) FROM comments").fetchone()[0] == 0


def test_author_precedence(monkeypatch):
    monkeypatch.setattr(comments.getpass, "getuser", lambda: "osuser")
    monkeypatch.delenv("BRD_AUTHOR", raising=False)
    assert comments.resolve_author(None) == "osuser"
    monkeypatch.setenv("BRD_AUTHOR", "claude")
    assert comments.resolve_author(None) == "claude"
    assert comments.resolve_author("explicit") == "explicit"
```

`tests/test_tags.py`:

```python
import pytest

from brd import tags
from brd.errors import InvalidTagError, NotTaggableError
from tests.factories import make_card, make_document


@pytest.mark.parametrize(
    "raw, expected",
    [("Design", "design"), ("#design/parser", "design/parser"), (" wip-2_x ", "wip-2_x")],
)
def test_normalize(raw, expected):
    assert tags.normalize(raw) == expected


@pytest.mark.parametrize("raw", ["", "#", "-lead", "has space", "émoji", "a.b"])
def test_normalize_rejects(raw):
    with pytest.raises(InvalidTagError):
        tags.normalize(raw)


def test_add_remove_list(pconn):
    make_document(pconn, "d", "notes")
    assert tags.add(pconn, "d", ["B", "a", "b"]) == ["a", "b"]
    assert tags.remove(pconn, "d", ["a", "missing"]) == ["b"]
    assert tags.list_for(pconn, "d") == ["b"]


def test_invalid_tag_writes_nothing(pconn):
    make_document(pconn, "d", "notes")
    with pytest.raises(InvalidTagError):
        tags.add(pconn, "d", ["good", "bad tag"])
    assert tags.list_for(pconn, "d") == []


def test_cards_not_taggable(pconn):
    make_card(pconn, "c")
    with pytest.raises(NotTaggableError, match="cards can't be tagged"):
        tags.add(pconn, "c", ["x"])


def test_counts(pconn):
    make_document(pconn, "d1", "one")
    make_document(pconn, "d2", "two")
    tags.add(pconn, "d1", ["x", "y"])
    tags.add(pconn, "d2", ["x"])
    assert tags.counts(pconn) == [{"tag": "x", "count": 2}, {"tag": "y", "count": 1}]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_comments.py tests/test_tags.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement `src/brd/comments.py`**

```python
import getpass
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from brd import entities, refs
from brd.errors import CommentNotFoundError, EmptyCommentError, NotCommentableError


@dataclass
class Comment:
    id: str
    entity_id: str
    author: str
    body: str
    created_at: str


def resolve_author(explicit: str | None) -> str:
    return explicit or os.environ.get("BRD_AUTHOR") or getpass.getuser()


def _row(row: sqlite3.Row) -> Comment:
    return Comment(row["id"], row["entity_id"], row["author"], row["body"], row["created_at"])


def add(conn: sqlite3.Connection, entity_id: str, body: str, author: str) -> Comment:
    entities.require_capability(
        conn, entity_id, entities.COMMENTABLE, NotCommentableError, "commented on"
    )
    if not body.strip():
        raise EmptyCommentError("comment body is empty")
    comment = Comment(
        id=str(uuid.uuid4()),
        entity_id=entity_id,
        author=author,
        body=body,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    conn.execute(
        "INSERT INTO comments (id, entity_id, author, body, created_at) VALUES (?, ?, ?, ?, ?)",
        (comment.id, comment.entity_id, comment.author, comment.body, comment.created_at),
    )
    conn.commit()
    refs.reindex(conn, entity_id)
    return comment


def list_for(conn: sqlite3.Connection, entity_id: str) -> list[Comment]:
    entities.require(conn, entity_id)
    rows = conn.execute(
        "SELECT * FROM comments WHERE entity_id = ? ORDER BY created_at, rowid",
        (entity_id,),
    ).fetchall()
    return [_row(row) for row in rows]


def delete(conn: sqlite3.Connection, comment_id: str) -> Comment:
    row = conn.execute("SELECT * FROM comments WHERE id = ?", (comment_id,)).fetchone()
    if row is None:
        raise CommentNotFoundError(f"no comment with id {comment_id}")
    comment = _row(row)
    conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
    conn.commit()
    refs.reindex(conn, comment.entity_id)
    return comment
```

- [ ] **Step 4: Implement `src/brd/tags.py`**

```python
import re
import sqlite3

from brd import entities
from brd.errors import InvalidTagError, NotTaggableError

_TAG = re.compile(r"^[a-z0-9][a-z0-9_/-]*$")


def normalize(tag: str) -> str:
    normalized = tag.strip().removeprefix("#").lower()
    if not _TAG.match(normalized):
        raise InvalidTagError(
            f"invalid tag {tag!r}: use lowercase letters, digits, '-', '_' and '/'"
        )
    return normalized


def _require_taggable(conn: sqlite3.Connection, entity_id: str) -> None:
    entities.require_capability(conn, entity_id, entities.TAGGABLE, NotTaggableError, "tagged")


def list_for(conn: sqlite3.Connection, entity_id: str) -> list[str]:
    entities.require(conn, entity_id)
    rows = conn.execute(
        "SELECT tag FROM tags WHERE entity_id = ? ORDER BY tag", (entity_id,)
    ).fetchall()
    return [row["tag"] for row in rows]


def add(conn: sqlite3.Connection, entity_id: str, tag_list: list[str]) -> list[str]:
    _require_taggable(conn, entity_id)
    normalized = [normalize(tag) for tag in tag_list]  # validate all before writing
    conn.executemany(
        "INSERT OR IGNORE INTO tags (entity_id, tag) VALUES (?, ?)",
        [(entity_id, tag) for tag in normalized],
    )
    conn.commit()
    return list_for(conn, entity_id)


def remove(conn: sqlite3.Connection, entity_id: str, tag_list: list[str]) -> list[str]:
    _require_taggable(conn, entity_id)
    normalized = [normalize(tag) for tag in tag_list]
    conn.executemany(
        "DELETE FROM tags WHERE entity_id = ? AND tag = ?",
        [(entity_id, tag) for tag in normalized],
    )
    conn.commit()
    return list_for(conn, entity_id)


def counts(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT tag, COUNT(*) AS count FROM tags GROUP BY tag ORDER BY tag"
    ).fetchall()
    return [{"tag": row["tag"], "count": row["count"]} for row in rows]
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/brd/comments.py src/brd/tags.py tests/test_comments.py tests/test_tags.py
git commit -m "Add generic comments and tags"
```

---

### Task 7: CLI for comments, tags, refs; generic `show`/`delete`; richer card detail

**Files:**
- Create: `src/brd/cli/comments.py`, `src/brd/cli/tags.py`, `src/brd/cli/refs.py`, `tests/test_cli_social.py`
- Modify: `src/brd/views.py`, `src/brd/cli/cards.py` (`show`, `delete`), `src/brd/cli/__init__.py`

**Interfaces:**
- Consumes: `comments.*`, `tags.*`, `refs.*`, `entities.kind_of/delete`
- Produces:
  - `views.comment_dict(comment) -> dict`
  - `views.links_of(conn, entity_id) -> {"refs": [...], "referenced_by": [...]}`
  - `views.card_detail` now also returns `kind: "card"`, `comments`, `refs`, `referenced_by`
  - `views.detail(conn, root: Path, entity_id) -> dict` (card branch now; later tasks add document and issue branches; unknown id → `CardNotFoundError("no card, issue, or document with id X")`)
  - `cli.cards.delete_entity(conn, entity_id, cascade) -> list[str]` (later tasks add the document branch)

- [ ] **Step 1: Write the failing tests** — `tests/test_cli_social.py`

```python
from brd import comments as comments_module
from tests.cli_helpers import err, ok


def _card(title="A", **kwargs):
    args = ["add", "--title", title]
    for key, value in kwargs.items():
        args += [f"--{key}", value]
    return ok(*args)


def test_comment_add_list_delete(project, monkeypatch):
    monkeypatch.setattr(comments_module.getpass, "getuser", lambda: "osuser")
    card = _card()
    comment = ok("comment", "add", card["id"], "first")
    assert comment["author"] == "osuser"
    assert [c["body"] for c in ok("comment", "list", card["id"])] == ["first"]
    assert ok("show", card["id"])["comments"][0]["id"] == comment["id"]
    ok("comment", "delete", comment["id"])
    assert ok("comment", "list", card["id"]) == []


def test_comment_author_env_and_flag(project, monkeypatch):
    card = _card()
    monkeypatch.setenv("BRD_AUTHOR", "claude")
    assert ok("comment", "add", card["id"], "x")["author"] == "claude"
    assert ok("comment", "add", card["id"], "y", "--author", "bot")["author"] == "bot"


def test_comment_body_from_stdin(project):
    card = _card()
    assert ok("comment", "add", card["id"], "-", input="long\ntext\n")["body"] == "long\ntext\n"


def test_comment_errors(project):
    assert err("comment", "add", "nope", "x") == "EntityNotFoundError"
    assert err("comment", "delete", "nope") == "CommentNotFoundError"
    card = _card()
    assert err("comment", "add", card["id"], "  ") == "EmptyCommentError"


def test_tag_card_is_rejected(project):
    card = _card()
    assert err("tag", "add", card["id"], "x") == "NotTaggableError"
    assert err("tag", "add", "nope", "x") == "EntityNotFoundError"
    assert ok("tag", "list") == []


def test_explicit_refs_and_backlinks(project):
    a = _card("A")
    b = _card("B")
    ok("ref", "add", a["id"], b["id"])
    assert ok("show", a["id"])["refs"] == [
        {"id": b["id"], "kind": "card", "title": "B", "origin": "explicit"}
    ]
    assert ok("show", b["id"])["referenced_by"][0]["id"] == a["id"]
    ok("ref", "remove", a["id"], b["id"])
    assert ok("show", a["id"])["refs"] == []
    assert err("ref", "add", a["id"], a["id"]) == "SelfReferenceError"


def test_description_links_show_up_in_refs(project):
    b = _card("B")
    a = _card("A", description=f"depends on [[{b['id']}]]")
    assert ok("show", a["id"])["refs"][0]["origin"] == "link"


def test_show_and_delete_unknown_keep_card_error(project):
    assert err("show", "nope") == "CardNotFoundError"
    assert err("delete", "nope") == "CardNotFoundError"


def test_show_card_has_kind(project):
    assert ok("show", _card()["id"])["kind"] == "card"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_cli_social.py -v`
Expected: FAIL — `No such command 'comment'` (exit code 2 assertion).

- [ ] **Step 3: Extend `src/brd/views.py`** (full file)

```python
import dataclasses
import sqlite3
from pathlib import Path

from brd import comments, core, db, entities, refs
from brd.errors import CardNotFoundError
from brd.models import Card


def comment_dict(comment: comments.Comment) -> dict:
    return dataclasses.asdict(comment)


def links_of(conn: sqlite3.Connection, entity_id: str) -> dict:
    return {
        "refs": refs.outgoing(conn, entity_id),
        "referenced_by": refs.incoming(conn, entity_id),
    }


def card_detail(conn: sqlite3.Connection, card: Card) -> dict:
    return {
        "id": card.id,
        "kind": "card",
        "title": card.title,
        "description": card.description,
        "status": core.resolve_status(conn, card),
        "parent_id": card.parent_id,
        "created_at": card.created_at,
        "updated_at": card.updated_at,
        "blocked_by": db.list_blockers_of(conn, card.id),
        "children": [child.id for child in db.list_children(conn, card.id)],
        "comments": [comment_dict(c) for c in comments.list_for(conn, card.id)],
        **links_of(conn, card.id),
    }


def detail(conn: sqlite3.Connection, root: Path, entity_id: str) -> dict:
    kind = entities.kind_of(conn, entity_id)
    if kind == "card":
        return card_detail(conn, db.get_card(conn, entity_id))
    raise CardNotFoundError(f"no card, issue, or document with id {entity_id}")
```

- [ ] **Step 4: Generic `show`/`delete` in `src/brd/cli/cards.py`**

Add `entities` to the `from brd import ...` line. Replace the `show` and `delete` commands with:

```python
@app.command()
def show(
    entity_id: str = typer.Argument(..., help="Id of the card, issue, or document to show."),
    pretty: bool = pretty_option(),
) -> None:
    """Show a card, issue, or document in full."""
    run(pretty, lambda ctx: views.detail(ctx.conn, ctx.root, entity_id))


def delete_entity(conn: sqlite3.Connection, entity_id: str, cascade: bool) -> list[str]:
    kind = entities.kind_of(conn, entity_id)
    if kind is None:
        raise CardNotFoundError(f"no card, issue, or document with id {entity_id}")
    if kind == "card":
        return core.delete_card(conn, entity_id, cascade=cascade)
    entities.delete(conn, entity_id)
    return [entity_id]


@app.command()
def delete(
    entity_id: str = typer.Argument(..., help="Id of the card, issue, or document to delete."),
    cascade: bool = typer.Option(
        False, "--cascade", help="Also delete all descendant cards (cards only)."
    ),
    pretty: bool = pretty_option(),
) -> None:
    """Delete a card, issue, or document (a document's source file is kept)."""
    run(pretty, lambda ctx: {"deleted": delete_entity(ctx.conn, entity_id, cascade)})
```

- [ ] **Step 5: `src/brd/cli/comments.py`**

```python
import sys

import typer

from brd import comments, views
from brd.cli._app import app, pretty_option, run

comment_app = typer.Typer(help="Comment on cards and issues.", no_args_is_help=True)
app.add_typer(comment_app, name="comment")


@comment_app.command("add")
def add(
    entity_id: str = typer.Argument(..., help="Card or issue id."),
    body: str = typer.Argument(..., help='Comment text; "-" reads it from stdin.'),
    author: str | None = typer.Option(
        None, "--author", help="Author name (default: $BRD_AUTHOR, then the OS user)."
    ),
    pretty: bool = pretty_option(),
) -> None:
    """Add a comment."""
    text = sys.stdin.read() if body == "-" else body
    run(
        pretty,
        lambda ctx: views.comment_dict(
            comments.add(ctx.conn, entity_id, text, comments.resolve_author(author))
        ),
    )


@comment_app.command("list")
def list_cmd(
    entity_id: str = typer.Argument(..., help="Card or issue id."),
    pretty: bool = pretty_option(),
) -> None:
    """List comments, oldest first."""
    run(pretty, lambda ctx: [views.comment_dict(c) for c in comments.list_for(ctx.conn, entity_id)])


@comment_app.command("delete")
def delete(
    comment_id: str = typer.Argument(..., help="Comment id."),
    pretty: bool = pretty_option(),
) -> None:
    """Delete a comment."""
    run(pretty, lambda ctx: views.comment_dict(comments.delete(ctx.conn, comment_id)))
```

- [ ] **Step 6: `src/brd/cli/tags.py`**

```python
import typer

from brd import tags
from brd.cli._app import app, pretty_option, run

tag_app = typer.Typer(help="Tag documents.", no_args_is_help=True)
app.add_typer(tag_app, name="tag")


@tag_app.command("add")
def add(
    entity_id: str = typer.Argument(..., help="Document id."),
    tag_list: list[str] = typer.Argument(..., metavar="TAG...", help="Tags to add."),
    pretty: bool = pretty_option(),
) -> None:
    """Add tags."""
    run(pretty, lambda ctx: {"id": entity_id, "tags": tags.add(ctx.conn, entity_id, tag_list)})


@tag_app.command("remove")
def remove(
    entity_id: str = typer.Argument(..., help="Document id."),
    tag_list: list[str] = typer.Argument(..., metavar="TAG...", help="Tags to remove."),
    pretty: bool = pretty_option(),
) -> None:
    """Remove tags."""
    run(pretty, lambda ctx: {"id": entity_id, "tags": tags.remove(ctx.conn, entity_id, tag_list)})


@tag_app.command("list")
def list_cmd(
    entity_id: str | None = typer.Argument(None, help="Only this entity's tags."),
    pretty: bool = pretty_option(),
) -> None:
    """List one entity's tags, or every tag in the project with counts."""

    def action(ctx):
        if entity_id is None:
            return tags.counts(ctx.conn)
        return {"id": entity_id, "tags": tags.list_for(ctx.conn, entity_id)}

    run(pretty, action)
```

- [ ] **Step 7: `src/brd/cli/refs.py`**

```python
import typer

from brd import refs
from brd.cli._app import app, pretty_option, run

ref_app = typer.Typer(help="Explicit references between entities.", no_args_is_help=True)
app.add_typer(ref_app, name="ref")


@ref_app.command("add")
def add(
    src_id: str = typer.Argument(..., help="Referencing entity id."),
    dst_id: str = typer.Argument(..., help="Referenced entity id."),
    pretty: bool = pretty_option(),
) -> None:
    """Add an explicit reference."""

    def action(ctx):
        refs.add_explicit(ctx.conn, src_id, dst_id)
        return {"id": src_id, "refs": refs.outgoing(ctx.conn, src_id)}

    run(pretty, action)


@ref_app.command("remove")
def remove(
    src_id: str = typer.Argument(..., help="Referencing entity id."),
    dst_id: str = typer.Argument(..., help="Referenced entity id."),
    pretty: bool = pretty_option(),
) -> None:
    """Remove an explicit reference ([[links]] are managed by editing text)."""

    def action(ctx):
        refs.remove_explicit(ctx.conn, src_id, dst_id)
        return {"id": src_id, "refs": refs.outgoing(ctx.conn, src_id)}

    run(pretty, action)
```

- [ ] **Step 8: Register modules** — `src/brd/cli/__init__.py` import line becomes:

```python
from brd.cli import project, cards, comments, tags, refs  # noqa: E402,F401  (registers commands)
```

- [ ] **Step 9: Run tests**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add src/brd/views.py src/brd/cli tests/test_cli_social.py
git commit -m "Add comment, tag, and ref commands; make show and delete kind-agnostic"
```

---

## Milestone 3 — Documents

### Task 8: `documents.py` — registration, backup, sync

**Files:**
- Create: `src/brd/documents.py`, `tests/test_documents.py`

**Interfaces:**
- Consumes: `db.docs_dir`, `refs.reindex/reindex_mentions`, `tags.normalize/add`
- Produces:
  - `Document(id, title, source_path, stem, content_hash, created_at, updated_at)` dataclass
  - `SyncResult(content: str | None, source_state: str)` dataclass; states `"ok" | "updated" | "missing" | "lost"`
  - `backup_path(conn, doc_id) -> Path`
  - `get(conn, doc_id) -> Document | None`; `require(conn, doc_id) -> Document` (`DocumentNotFoundError`)
  - `list_all(conn) -> list[Document]`
  - `add(conn, root: Path, path: Path, title: str | None = None, tag_list: list[str] | None = None) -> Document`
  - `sync(conn, root, doc) -> SyncResult`; `sync_all(conn, root) -> dict[str, SyncResult]`
  - internal but reused by Task 9/13: `_validate_path(root, path) -> tuple[str, str]`, `_check_unique(conn, rel, stem, exclude_id=None)`, `_write_backup(conn, doc_id, data: bytes)`, `_hash(data: bytes) -> str`

- [ ] **Step 1: Write the failing tests** — `tests/test_documents.py`

```python
import pytest

from brd import core, documents, refs, tags
from brd.errors import (
    DocumentSourceNotFoundError,
    DuplicatePathError,
    DuplicateStemError,
    NotMarkdownError,
    PathOutsideProjectError,
)


@pytest.fixture
def root(tmp_path):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    return repo


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_add_registers_and_backs_up(pconn, root):
    path = write(root, "docs/parser-notes.md", "# Notes\n")
    doc = documents.add(pconn, root, path)
    assert (doc.source_path, doc.stem, doc.title) == ("docs/parser-notes.md", "parser-notes", "parser-notes")
    assert documents.backup_path(pconn, doc.id).read_text() == "# Notes\n"
    assert doc.content_hash == documents._hash(b"# Notes\n")
    assert documents.require(pconn, doc.id) == doc


def test_add_with_title_and_tags(pconn, root):
    doc = documents.add(pconn, root, write(root, "docs/a.md", ""), title="Alpha", tag_list=["#Design"])
    assert doc.title == "Alpha"
    assert tags.list_for(pconn, doc.id) == ["design"]


def test_add_rejects_outside_root(pconn, root, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("x")
    with pytest.raises(PathOutsideProjectError):
        documents.add(pconn, root, outside)
    with pytest.raises(PathOutsideProjectError):
        documents.add(pconn, root, root / "docs" / ".." / ".." / "outside.md")


def test_add_rejects_symlink_escape(pconn, root, tmp_path):
    outside = tmp_path / "secret.md"
    outside.write_text("x")
    (root / "docs" / "link.md").symlink_to(outside)
    with pytest.raises(PathOutsideProjectError):
        documents.add(pconn, root, root / "docs" / "link.md")


def test_add_rejects_non_markdown_and_missing(pconn, root):
    with pytest.raises(NotMarkdownError):
        documents.add(pconn, root, write(root, "notes.txt", "x"))
    with pytest.raises(DocumentSourceNotFoundError):
        documents.add(pconn, root, root / "docs" / "ghost.md")


def test_add_rejects_duplicate_path_and_stem(pconn, root):
    documents.add(pconn, root, write(root, "docs/notes.md", ""))
    with pytest.raises(DuplicatePathError):
        documents.add(pconn, root, root / "docs" / "notes.md")
    with pytest.raises(DuplicateStemError, match="rename"):
        documents.add(pconn, root, write(root, "other/Notes.md", ""))


def test_add_with_invalid_tag_writes_nothing(pconn, root):
    from brd.errors import InvalidTagError

    with pytest.raises(InvalidTagError):
        documents.add(pconn, root, write(root, "docs/a.md", ""), tag_list=["bad tag"])
    assert documents.list_all(pconn) == []


def test_sync_states(pconn, root):
    path = write(root, "docs/a.md", "v1")
    doc = documents.add(pconn, root, path)
    assert documents.sync(pconn, root, doc) == documents.SyncResult("v1", "ok")

    path.write_text("v2")
    assert documents.sync(pconn, root, doc) == documents.SyncResult("v2", "updated")
    assert documents.backup_path(pconn, doc.id).read_text() == "v2"
    assert documents.require(pconn, doc.id).content_hash == documents._hash(b"v2")
    assert documents.sync(pconn, root, documents.require(pconn, doc.id)).source_state == "ok"

    path.unlink()
    assert documents.sync(pconn, root, doc) == documents.SyncResult("v2", "missing")

    documents.backup_path(pconn, doc.id).unlink()
    assert documents.sync(pconn, root, doc) == documents.SyncResult(None, "lost")


def test_sync_rewrites_deleted_backup(pconn, root):
    doc = documents.add(pconn, root, write(root, "docs/a.md", "v1"))
    documents.backup_path(pconn, doc.id).unlink()
    assert documents.sync(pconn, root, doc).source_state == "updated"
    assert documents.backup_path(pconn, doc.id).read_text() == "v1"


def test_sync_reindexes_changed_links(pconn, root):
    card = core.create_card(pconn, title="Target")
    path = write(root, "docs/a.md", "nothing")
    doc = documents.add(pconn, root, path)
    path.write_text(f"see [[{card.id}]]")
    documents.sync(pconn, root, doc)
    assert [r["id"] for r in refs.outgoing(pconn, doc.id)] == [card.id]


def test_non_utf8_content_does_not_crash(pconn, root):
    path = root / "docs" / "bin.md"
    path.write_bytes(b"ok \xff\xfe [[x]]")
    doc = documents.add(pconn, root, path)
    result = documents.sync(pconn, root, doc)
    assert result.source_state == "ok"
    assert "�" in result.content


def test_add_resolves_forward_links(pconn, root):
    card = core.create_card(pconn, title="Early", description="see [[Design Notes]]")
    assert refs.outgoing(pconn, card.id) == []
    doc = documents.add(pconn, root, write(root, "docs/design notes.md", ""))
    assert [r["id"] for r in refs.outgoing(pconn, card.id)] == [doc.id]


def test_sync_all_and_no_temp_files_left(pconn, root):
    a = documents.add(pconn, root, write(root, "docs/a.md", "a"))
    b = documents.add(pconn, root, write(root, "docs/b.md", "b"))
    (root / "docs" / "b.md").write_text("b2")
    results = documents.sync_all(pconn, root)
    assert {k: v.source_state for k, v in results.items()} == {a.id: "ok", b.id: "updated"}
    assert sorted(p.suffix for p in documents.backup_path(pconn, a.id).parent.iterdir()) == [".md", ".md"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_documents.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement `src/brd/documents.py`**

```python
import hashlib
import os
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from brd import db, refs, tags
from brd.errors import (
    DocumentNotFoundError,
    DocumentSourceNotFoundError,
    DuplicatePathError,
    DuplicateStemError,
    NotMarkdownError,
    PathOutsideProjectError,
)


@dataclass
class Document:
    id: str
    title: str
    source_path: str
    stem: str
    content_hash: str
    created_at: str
    updated_at: str


@dataclass
class SyncResult:
    content: str | None
    source_state: str  # ok | updated | missing | lost


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _decode(data: bytes) -> str:
    return data.decode("utf-8", "replace")


def backup_path(conn: sqlite3.Connection, doc_id: str) -> Path:
    return db.docs_dir(conn) / f"{doc_id}.md"


def _write_backup(conn: sqlite3.Connection, doc_id: str, data: bytes) -> None:
    target = backup_path(conn, doc_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _row(row: sqlite3.Row) -> Document:
    return Document(
        id=row["id"],
        title=row["title"],
        source_path=row["source_path"],
        stem=row["stem"],
        content_hash=row["content_hash"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def get(conn: sqlite3.Connection, doc_id: str) -> Document | None:
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    return _row(row) if row else None


def require(conn: sqlite3.Connection, doc_id: str) -> Document:
    doc = get(conn, doc_id)
    if doc is None:
        raise DocumentNotFoundError(f"no document with id {doc_id}")
    return doc


def list_all(conn: sqlite3.Connection) -> list[Document]:
    rows = conn.execute("SELECT * FROM documents ORDER BY created_at, source_path").fetchall()
    return [_row(row) for row in rows]


def _validate_path(root: Path, path: Path) -> tuple[str, str]:
    """Return (source_path relative to root in POSIX form, stem)."""
    resolved_root = root.resolve()
    candidate = (path if path.is_absolute() else Path.cwd() / path).resolve()
    if not candidate.is_relative_to(resolved_root):
        raise PathOutsideProjectError(f"{path} is outside the project root {resolved_root}")
    if candidate.suffix.lower() != ".md":
        raise NotMarkdownError(f"{path} is not a .md file")
    if not candidate.is_file():
        raise DocumentSourceNotFoundError(f"{path} does not exist")
    return candidate.relative_to(resolved_root).as_posix(), candidate.stem


def _check_unique(
    conn: sqlite3.Connection, rel: str, stem: str, exclude_id: str | None = None
) -> None:
    row = conn.execute(
        "SELECT id FROM documents WHERE source_path = ? AND id IS NOT ?", (rel, exclude_id)
    ).fetchone()
    if row:
        raise DuplicatePathError(f"{rel} is already registered as document {row['id']}")
    row = conn.execute(
        "SELECT source_path FROM documents WHERE stem = ? AND id IS NOT ?", (stem, exclude_id)
    ).fetchone()
    if row:
        raise DuplicateStemError(
            f"a document named {stem!r} is already registered ({row['source_path']}); "
            f"rename one of the files so [[{stem}]] stays unambiguous"
        )


def add(
    conn: sqlite3.Connection,
    root: Path,
    path: Path,
    title: str | None = None,
    tag_list: list[str] | None = None,
) -> Document:
    rel, stem = _validate_path(root, path)
    _check_unique(conn, rel, stem)
    normalized_tags = [tags.normalize(tag) for tag in tag_list or []]
    data = (root.resolve() / rel).read_bytes()
    now = _now()
    doc = Document(str(uuid.uuid4()), title or stem, rel, stem, _hash(data), now, now)
    _write_backup(conn, doc.id, data)
    conn.execute(
        "INSERT INTO documents (id, title, source_path, stem, content_hash, created_at, "
        "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (doc.id, doc.title, doc.source_path, doc.stem, doc.content_hash, doc.created_at, doc.updated_at),
    )
    conn.commit()
    if normalized_tags:
        tags.add(conn, doc.id, normalized_tags)
    refs.reindex(conn, doc.id)
    refs.reindex_mentions(conn, stem)
    return doc


def sync(conn: sqlite3.Connection, root: Path, doc: Document) -> SyncResult:
    """Bring the backup up to date with the source file. A differing hash
    always means the source advanced: the backup only changes by copying
    from the source."""
    source = root.resolve() / doc.source_path
    backup = backup_path(conn, doc.id)
    if not source.is_file():
        if backup.is_file():
            return SyncResult(_decode(backup.read_bytes()), "missing")
        return SyncResult(None, "lost")
    data = source.read_bytes()
    digest = _hash(data)
    if digest == doc.content_hash and backup.is_file():
        return SyncResult(_decode(data), "ok")
    _write_backup(conn, doc.id, data)
    if digest != doc.content_hash:
        now = _now()
        conn.execute(
            "UPDATE documents SET content_hash = ?, updated_at = ? WHERE id = ?",
            (digest, now, doc.id),
        )
        conn.commit()
        doc.content_hash, doc.updated_at = digest, now
        refs.reindex(conn, doc.id)
    return SyncResult(_decode(data), "updated")


def sync_all(conn: sqlite3.Connection, root: Path) -> dict[str, SyncResult]:
    return {doc.id: sync(conn, root, doc) for doc in list_all(conn)}
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/brd/documents.py tests/test_documents.py
git commit -m "Add document registration with hash-synced backups"
```

---

### Task 9: Document rename/retitle, restore, delete, and `forget` cleanup

**Files:**
- Modify: `src/brd/documents.py`, `src/brd/master.py` (`forget_project`), `tests/test_documents.py` (append), `tests/test_master.py` (append)

**Interfaces:**
- Produces:
  - `documents.update(conn, root, doc_id, new_path: Path | None = None, title: str | None = None) -> tuple[Document, SyncResult]`
  - `documents.restore(conn, root, doc_id, force: bool = False) -> Document`
  - `documents.delete(conn, doc_id) -> None`

- [ ] **Step 1: Append failing tests to `tests/test_documents.py`**

```python
from brd.errors import (
    DocumentContentLostError,
    DocumentNotFoundError,
    RestoreConflictError,
)


def test_update_rename_path_and_stem(pconn, root):
    old = write(root, "docs/old.md", "x")
    doc = documents.add(pconn, root, old)
    old.rename(root / "docs" / "new.md")
    updated, result = documents.update(pconn, root, doc.id, new_path=root / "docs" / "new.md")
    assert (updated.source_path, updated.stem, result.source_state) == ("docs/new.md", "new", "ok")


def test_update_rename_moves_link_resolution(pconn, root):
    old_card = core.create_card(pconn, title="Old", description="[[old]]")
    new_card = core.create_card(pconn, title="New", description="[[new]]")
    old = write(root, "docs/old.md", "x")
    doc = documents.add(pconn, root, old)
    old.rename(root / "docs" / "new.md")
    documents.update(pconn, root, doc.id, new_path=root / "docs" / "new.md")
    assert refs.outgoing(pconn, old_card.id) == []
    assert [r["id"] for r in refs.outgoing(pconn, new_card.id)] == [doc.id]


def test_update_rename_to_taken_stem(pconn, root):
    documents.add(pconn, root, write(root, "docs/a.md", ""))
    b = documents.add(pconn, root, write(root, "docs/b.md", ""))
    write(root, "other/a.md", "")
    with pytest.raises(DuplicateStemError):
        documents.update(pconn, root, b.id, new_path=root / "other" / "a.md")


def test_update_title_only(pconn, root):
    doc = documents.add(pconn, root, write(root, "docs/a.md", ""))
    updated, _ = documents.update(pconn, root, doc.id, title="Better")
    assert updated.title == "Better"


def test_update_unknown(pconn, root):
    with pytest.raises(DocumentNotFoundError):
        documents.update(pconn, root, "nope")


def test_restore_missing_source(pconn, root):
    path = write(root, "docs/a.md", "keep me")
    doc = documents.add(pconn, root, path)
    path.unlink()
    documents.restore(pconn, root, doc.id)
    assert path.read_text() == "keep me"


def test_restore_recreates_parent_dirs(pconn, root):
    path = write(root, "deep/dir/a.md", "x")
    doc = documents.add(pconn, root, path)
    path.unlink()
    path.parent.rmdir()
    documents.restore(pconn, root, doc.id)
    assert path.read_text() == "x"


def test_restore_conflict_and_force(pconn, root):
    path = write(root, "docs/a.md", "v1")
    doc = documents.add(pconn, root, path)
    path.write_text("local edit")
    with pytest.raises(RestoreConflictError):
        documents.restore(pconn, root, doc.id)
    documents.restore(pconn, root, doc.id, force=True)
    assert path.read_text() == "v1"


def test_restore_matching_is_noop(pconn, root):
    path = write(root, "docs/a.md", "v1")
    doc = documents.add(pconn, root, path)
    documents.restore(pconn, root, doc.id)
    assert path.read_text() == "v1"


def test_restore_lost(pconn, root):
    path = write(root, "docs/a.md", "v1")
    doc = documents.add(pconn, root, path)
    path.unlink()
    documents.backup_path(pconn, doc.id).unlink()
    with pytest.raises(DocumentContentLostError):
        documents.restore(pconn, root, doc.id)


def test_delete_removes_backup_keeps_source(pconn, root):
    path = write(root, "docs/a.md", "v1")
    doc = documents.add(pconn, root, path)
    documents.delete(pconn, doc.id)
    assert documents.get(pconn, doc.id) is None
    assert not documents.backup_path(pconn, doc.id).exists()
    assert path.read_text() == "v1"
```

Append to `tests/test_master.py`:

```python
def test_forget_removes_document_backups(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    master.init_project(repo)
    docs = paths.project_docs_dir(repo)
    docs.mkdir()
    (docs / "x.md").write_text("backup")
    master.forget_project(repo)
    assert not docs.exists()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_documents.py tests/test_master.py -v`
Expected: FAIL — `AttributeError: module 'brd.documents' has no attribute 'update'`; forget test fails on `docs.exists()`.

- [ ] **Step 3: Append to `src/brd/documents.py`**

Add `entities` to the `from brd import ...` line and `DocumentContentLostError, RestoreConflictError` to the errors import. Then:

```python
def update(
    conn: sqlite3.Connection,
    root: Path,
    doc_id: str,
    new_path: Path | None = None,
    title: str | None = None,
) -> tuple[Document, SyncResult]:
    doc = require(conn, doc_id)
    old_stem = doc.stem
    if new_path is not None:
        rel, stem = _validate_path(root, new_path)
        _check_unique(conn, rel, stem, exclude_id=doc.id)
        conn.execute(
            "UPDATE documents SET source_path = ?, stem = ?, updated_at = ? WHERE id = ?",
            (rel, stem, _now(), doc.id),
        )
    if title is not None:
        conn.execute(
            "UPDATE documents SET title = ?, updated_at = ? WHERE id = ?",
            (title, _now(), doc.id),
        )
    conn.commit()
    doc = require(conn, doc_id)
    result = sync(conn, root, doc)
    if doc.stem.lower() != old_stem.lower():
        refs.reindex_mentions(conn, old_stem)
        refs.reindex_mentions(conn, doc.stem)
    return require(conn, doc_id), result


def restore(conn: sqlite3.Connection, root: Path, doc_id: str, force: bool = False) -> Document:
    doc = require(conn, doc_id)
    backup = backup_path(conn, doc.id)
    if not backup.is_file():
        raise DocumentContentLostError(f"no backup exists for document {doc_id}")
    source = root.resolve() / doc.source_path
    if source.is_file():
        if _hash(source.read_bytes()) == doc.content_hash:
            return doc
        if not force:
            raise RestoreConflictError(
                f"{doc.source_path} exists and differs from brd's backup; "
                "pass --force to overwrite it"
            )
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(backup.read_bytes())
    return doc


def delete(conn: sqlite3.Connection, doc_id: str) -> None:
    require(conn, doc_id)
    entities.delete(conn, doc_id)
    backup_path(conn, doc_id).unlink(missing_ok=True)
```

- [ ] **Step 4: `forget` cleanup** — in `src/brd/master.py` `forget_project`, after the `db_path.unlink()` block add:

```python
    docs_dir = paths.project_docs_dir(root_path)
    if docs_dir.is_dir():
        shutil.rmtree(docs_dir)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/brd/documents.py src/brd/master.py tests/test_documents.py tests/test_master.py
git commit -m "Add document rename, restore, and delete; forget removes backups"
```

---

### Task 10: `brd doc` commands and document `show`

**Files:**
- Create: `src/brd/cli/docs.py`, `tests/test_cli_docs.py`
- Modify: `src/brd/views.py`, `src/brd/cli/cards.py` (`delete_entity`), `src/brd/cli/__init__.py`

**Interfaces:**
- Consumes: `documents.*`, `tags.*`
- Produces:
  - `views.document_summary(conn, doc, source_state: str) -> dict` → `{id, kind: "document", title, source_path, source_state, tags, created_at, updated_at}`
  - `views.document_detail(conn, doc, result: SyncResult) -> dict` → summary + `content` + `refs` + `referenced_by`
  - `views.detail` now runs `documents.sync_all` first (fresh backlinks) and handles documents

- [ ] **Step 1: Write the failing tests** — `tests/test_cli_docs.py`

```python
from tests.cli_helpers import err, ok


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_doc_add_from_subdirectory_stores_root_relative_path(project, monkeypatch):
    write(project, "docs/a.md", "x")
    (project / "src").mkdir()
    monkeypatch.chdir(project / "src")
    doc = ok("doc", "add", "../docs/a.md")
    assert doc["source_path"] == "docs/a.md"
    assert doc["source_state"] == "ok"
    assert doc["kind"] == "document"


def test_doc_add_with_tags_and_title(project):
    write(project, "docs/a.md", "x")
    doc = ok("doc", "add", "docs/a.md", "--title", "Alpha", "--tag", "design", "--tag", "#WIP")
    assert (doc["title"], doc["tags"]) == ("Alpha", ["design", "wip"])


def test_doc_add_errors(project):
    write(project, "notes.txt", "x")
    assert err("doc", "add", "notes.txt") == "NotMarkdownError"
    assert err("doc", "add", "ghost.md") == "DocumentSourceNotFoundError"


def test_doc_list_filters(project):
    write(project, "docs/a.md", "")
    write(project, "docs/b.md", "")
    a = ok("doc", "add", "docs/a.md", "--tag", "x", "--tag", "y")
    b = ok("doc", "add", "docs/b.md", "--tag", "x")
    assert [d["id"] for d in ok("doc", "list")] == [a["id"], b["id"]]
    assert [d["id"] for d in ok("doc", "list", "--tag", "x", "--tag", "y")] == [a["id"]]
    (project / "docs" / "b.md").unlink()
    assert [(d["id"], d["source_state"]) for d in ok("doc", "list", "--missing")] == [
        (b["id"], "missing")
    ]


def test_doc_update_reports_sync_and_rename(project):
    path = write(project, "docs/a.md", "v1")
    doc = ok("doc", "add", "docs/a.md")
    path.write_text("v2")
    assert ok("doc", "update", doc["id"])["source_state"] == "updated"
    path.rename(project / "docs" / "b.md")
    renamed = ok("doc", "update", doc["id"], "--path", "docs/b.md", "--title", "Bee")
    assert (renamed["source_path"], renamed["title"]) == ("docs/b.md", "Bee")


def test_doc_restore(project):
    path = write(project, "docs/a.md", "v1")
    doc = ok("doc", "add", "docs/a.md")
    path.write_text("edited")
    assert err("doc", "restore", doc["id"]) == "RestoreConflictError"
    ok("doc", "restore", doc["id"], "--force")
    assert path.read_text() == "v1"


def test_show_document_includes_content_and_tags(project):
    write(project, "docs/a.md", "hello")
    doc = ok("doc", "add", "docs/a.md", "--tag", "x")
    shown = ok("show", doc["id"])
    assert (shown["content"], shown["tags"], shown["source_state"]) == ("hello", ["x"], "ok")


def test_show_card_sees_backlink_from_document_edited_on_disk(project):
    card = ok("add", "--title", "Target")
    path = write(project, "docs/a.md", "nothing yet")
    doc = ok("doc", "add", "docs/a.md")
    path.write_text(f"now links [[{card['id']}]]")  # no `doc update` run
    assert [r["id"] for r in ok("show", card["id"])["referenced_by"]] == [doc["id"]]


def test_delete_document_keeps_source(project):
    path = write(project, "docs/a.md", "x")
    doc = ok("doc", "add", "docs/a.md")
    assert ok("delete", doc["id"]) == {"deleted": [doc["id"]]}
    assert path.exists()
    assert ok("doc", "list") == []


def test_tag_commands_on_document(project):
    write(project, "docs/a.md", "")
    doc = ok("doc", "add", "docs/a.md")
    assert ok("tag", "add", doc["id"], "one", "two")["tags"] == ["one", "two"]
    assert ok("tag", "remove", doc["id"], "one")["tags"] == ["two"]
    assert ok("tag", "list") == [{"tag": "two", "count": 1}]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_cli_docs.py -v`
Expected: FAIL — `No such command 'doc'`.

- [ ] **Step 3: Views** — in `src/brd/views.py` add `documents, tags` to the `from brd import ...` line, add these functions, and replace `detail`:

```python
def document_summary(conn: sqlite3.Connection, doc: documents.Document, source_state: str) -> dict:
    return {
        "id": doc.id,
        "kind": "document",
        "title": doc.title,
        "source_path": doc.source_path,
        "source_state": source_state,
        "tags": tags.list_for(conn, doc.id),
        "created_at": doc.created_at,
        "updated_at": doc.updated_at,
    }


def document_detail(
    conn: sqlite3.Connection, doc: documents.Document, result: documents.SyncResult
) -> dict:
    return {
        **document_summary(conn, doc, result.source_state),
        "content": result.content,
        **links_of(conn, doc.id),
    }


def detail(conn: sqlite3.Connection, root: Path, entity_id: str) -> dict:
    kind = entities.kind_of(conn, entity_id)
    if kind is None:
        raise CardNotFoundError(f"no card, issue, or document with id {entity_id}")
    # Documents may have been edited on disk; sync them all so backlinks
    # (referenced_by) reflect their current content.
    results = documents.sync_all(conn, root)
    if kind == "document":
        return document_detail(conn, documents.require(conn, entity_id), results[entity_id])
    return card_detail(conn, db.get_card(conn, entity_id))
```

- [ ] **Step 4: Document branch in `delete_entity`** (`src/brd/cli/cards.py`) — add `documents` to the `from brd import ...` line and insert before `entities.delete(conn, entity_id)`:

```python
    if kind == "document":
        documents.delete(conn, entity_id)
        return [entity_id]
```

- [ ] **Step 5: `src/brd/cli/docs.py`**

```python
from pathlib import Path

import typer

from brd import documents, tags, views
from brd.cli._app import app, pretty_option, run

doc_app = typer.Typer(help="Register and track markdown documents.", no_args_is_help=True)
app.add_typer(doc_app, name="doc")


@doc_app.command("add")
def add(
    path: Path = typer.Argument(..., help="Path to a .md file inside the project."),
    title: str | None = typer.Option(None, "--title", help="Title (default: filename stem)."),
    tag_list: list[str] = typer.Option([], "--tag", help="Tag (repeatable)."),
    pretty: bool = pretty_option(),
) -> None:
    """Register a markdown file as a document; brd keeps a backup of it."""

    def action(ctx):
        doc = documents.add(ctx.conn, ctx.root, path, title=title, tag_list=list(tag_list))
        return views.document_summary(ctx.conn, doc, "ok")

    run(pretty, action)


@doc_app.command("list")
def list_cmd(
    tag_list: list[str] = typer.Option([], "--tag", help="Only documents with this tag (repeatable: all must match)."),
    missing: bool = typer.Option(False, "--missing", help="Only documents whose source file is gone."),
    pretty: bool = pretty_option(),
) -> None:
    """List documents, syncing each backup first."""

    def action(ctx):
        wanted = [tags.normalize(tag) for tag in tag_list]
        results = documents.sync_all(ctx.conn, ctx.root)
        items = []
        for doc in documents.list_all(ctx.conn):
            state = results[doc.id].source_state
            if missing and state not in ("missing", "lost"):
                continue
            summary = views.document_summary(ctx.conn, doc, state)
            if all(tag in summary["tags"] for tag in wanted):
                items.append(summary)
        return items

    run(pretty, action)


@doc_app.command("update")
def update(
    doc_id: str = typer.Argument(..., help="Document id."),
    path: Path | None = typer.Option(None, "--path", help="Record a move/rename to this path."),
    title: str | None = typer.Option(None, "--title", help="New title."),
    pretty: bool = pretty_option(),
) -> None:
    """Sync brd's backup after editing a document (run this after every edit)."""

    def action(ctx):
        doc, result = documents.update(ctx.conn, ctx.root, doc_id, new_path=path, title=title)
        return views.document_summary(ctx.conn, doc, result.source_state)

    run(pretty, action)


@doc_app.command("restore")
def restore(
    doc_id: str = typer.Argument(..., help="Document id."),
    force: bool = typer.Option(False, "--force", help="Overwrite a source file that differs."),
    pretty: bool = pretty_option(),
) -> None:
    """Write brd's backup back to the document's source path."""

    def action(ctx):
        doc = documents.restore(ctx.conn, ctx.root, doc_id, force=force)
        return views.document_summary(ctx.conn, doc, "ok")

    run(pretty, action)
```

- [ ] **Step 6: Register** — `src/brd/cli/__init__.py` import line becomes:

```python
from brd.cli import project, cards, comments, tags, refs, docs  # noqa: E402,F401  (registers commands)
```

- [ ] **Step 7: Run tests**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/brd/views.py src/brd/cli tests/test_cli_docs.py
git commit -m "Add brd doc commands and document show"
```

---

## Milestone 4 — Issues

### Task 11: `issues.py` and issue blockers in `core`

**Files:**
- Create: `src/brd/issues.py`, `tests/test_issues.py`
- Modify: `src/brd/core.py` (`resolve_status`, `create_card`, `block_card`)

**Interfaces:**
- Consumes: `entities.kind_of/require/BLOCKERS`, `refs.add_explicit/reindex`, `core.block_card`
- Produces:
  - `issues.CLOSE_REASONS = ("resolved", "wontfix", "duplicate")`
  - `issues.Issue(id, title, body, status, close_reason, created_at, updated_at)` dataclass
  - `issues.open_issue(conn, title, body=None, ref_ids=None, blocks=None) -> Issue`
  - `issues.get(conn, id) -> Issue | None`; `issues.require(conn, id) -> Issue` (`IssueNotFoundError`)
  - `issues.list_issues(conn, status: str | None = None) -> list[Issue]`
  - `issues.update(conn, id, title=None, body=None) -> Issue`
  - `issues.close(conn, id, reason="resolved") -> Issue`; `issues.reopen(conn, id) -> Issue`
  - `issues.blocks_of(conn, issue_id) -> list[str]`
  - `core._require_blocker(conn, blocker_id) -> None` (unknown → `CardNotFoundError`; document → `InvalidBlockerError`)

- [ ] **Step 1: Write the failing tests** — `tests/test_issues.py`

```python
import pytest

from brd import core, issues, refs
from brd.errors import (
    CardNotFoundError,
    EntityNotFoundError,
    InvalidBlockerError,
    InvalidCloseReasonError,
    IssueNotFoundError,
)
from tests.factories import make_document


def test_open_and_get(pconn):
    issue = issues.open_issue(pconn, "Grammar ambiguity", body="details")
    assert (issue.status, issue.close_reason) == ("open", None)
    assert issues.require(pconn, issue.id) == issue


def test_require_unknown(pconn):
    with pytest.raises(IssueNotFoundError):
        issues.require(pconn, "nope")


def test_close_reopen_and_reasons(pconn):
    issue = issues.open_issue(pconn, "x")
    assert issues.close(pconn, issue.id).close_reason == "resolved"
    reopened = issues.reopen(pconn, issue.id)
    assert (reopened.status, reopened.close_reason) == ("open", None)
    assert issues.close(pconn, issue.id, reason="wontfix").close_reason == "wontfix"
    with pytest.raises(InvalidCloseReasonError):
        issues.close(pconn, issue.id, reason="meh")


def test_list_filters_by_status(pconn):
    a = issues.open_issue(pconn, "a")
    b = issues.open_issue(pconn, "b")
    issues.close(pconn, b.id)
    assert [i.id for i in issues.list_issues(pconn)] == [a.id, b.id]
    assert [i.id for i in issues.list_issues(pconn, status="open")] == [a.id]


def test_update_body_reindexes_links(pconn):
    card = core.create_card(pconn, title="Target")
    issue = issues.open_issue(pconn, "x")
    issues.update(pconn, issue.id, body=f"about [[{card.id}]]")
    assert [r["id"] for r in refs.outgoing(pconn, issue.id)] == [card.id]


def test_open_with_refs_and_blocks(pconn):
    card = core.create_card(pconn, title="Work")
    issue = issues.open_issue(pconn, "Question", ref_ids=[card.id], blocks=[card.id])
    assert refs.outgoing(pconn, issue.id)[0]["origin"] == "explicit"
    assert issues.blocks_of(pconn, issue.id) == [card.id]


def test_open_with_unknown_ref_writes_nothing(pconn):
    with pytest.raises(EntityNotFoundError):
        issues.open_issue(pconn, "x", ref_ids=["ghost"])
    with pytest.raises(CardNotFoundError):
        issues.open_issue(pconn, "x", blocks=["ghost"])
    assert issues.list_issues(pconn) == []


def test_open_issue_blocks_card_until_closed_any_reason(pconn):
    for reason in issues.CLOSE_REASONS:
        card = core.create_card(pconn, title=f"w-{reason}")
        issue = issues.open_issue(pconn, "q")
        core.block_card(pconn, card.id, issue.id)
        assert core.resolve_status(pconn, card) == "blocked"
        assert card.id not in [c.id for c in core.next_cards(pconn)]
        issues.close(pconn, issue.id, reason=reason)
        assert core.resolve_status(pconn, card) == "todo"
        assert card.id in [c.id for c in core.next_cards(pconn)]
        issues.reopen(pconn, issue.id)
        assert core.resolve_status(pconn, card) == "blocked"
        issues.close(pconn, issue.id)


def test_create_card_blocked_by_issue(pconn):
    issue = issues.open_issue(pconn, "q")
    card = core.create_card(pconn, title="w", blocked_by=[issue.id])
    assert core.resolve_status(pconn, card) == "blocked"


def test_documents_cannot_block(pconn):
    card = core.create_card(pconn, title="w")
    make_document(pconn, "d", "notes")
    with pytest.raises(InvalidBlockerError):
        core.block_card(pconn, card.id, "d")
    with pytest.raises(InvalidBlockerError):
        core.create_card(pconn, title="w2", blocked_by=["d"])


def test_issue_cannot_be_blocked(pconn):
    issue = issues.open_issue(pconn, "q")
    card = core.create_card(pconn, title="w")
    with pytest.raises(CardNotFoundError):
        core.block_card(pconn, issue.id, card.id)


def test_deleting_issue_unblocks(pconn):
    card = core.create_card(pconn, title="w")
    issue = issues.open_issue(pconn, "q", blocks=[card.id])
    pconn.execute("DELETE FROM entities WHERE id = ?", (issue.id,))
    assert core.resolve_status(pconn, card) == "todo"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_issues.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: `core.py` blocker support**

Change imports to `from brd import db, entities, refs` and add `InvalidBlockerError` to the `from brd.errors import (...)` block. Add after `_require_card`:

```python
def _require_blocker(conn: sqlite3.Connection, blocker_id: str) -> None:
    kind = entities.kind_of(conn, blocker_id)
    if kind is None:
        raise CardNotFoundError(f"no card or issue with id {blocker_id}")
    if kind not in entities.BLOCKERS:
        raise InvalidBlockerError(f"a {kind} can't block a card; only cards and issues can")
```

In `create_card`, change the blocker validation loop to:

```python
    for blocker_id in blocked_by:
        _require_blocker(conn, blocker_id)
```

In `block_card`, replace `_require_card(conn, blocker_id)` with `_require_blocker(conn, blocker_id)`.

In `resolve_status`, replace the blocker loop with:

```python
    for blocker_id in db.list_blockers_of(conn, card.id):
        blocker = db.get_card(conn, blocker_id)
        if blocker is None:
            # Issues block while open, whatever reason they are later closed with.
            issue = conn.execute(
                "SELECT status FROM issues WHERE id = ?", (blocker_id,)
            ).fetchone()
            if issue is not None and issue["status"] == "open":
                return "blocked"
            continue
        if resolve_status(conn, blocker, seen) != "done":
            return "blocked"
```

- [ ] **Step 4: Implement `src/brd/issues.py`**

```python
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from brd import core, db, entities, refs
from brd.errors import CardNotFoundError, InvalidCloseReasonError, IssueNotFoundError

CLOSE_REASONS = ("resolved", "wontfix", "duplicate")


@dataclass
class Issue:
    id: str
    title: str
    body: str | None
    status: str
    close_reason: str | None
    created_at: str
    updated_at: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(row: sqlite3.Row) -> Issue:
    return Issue(
        id=row["id"],
        title=row["title"],
        body=row["body"],
        status=row["status"],
        close_reason=row["close_reason"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def get(conn: sqlite3.Connection, issue_id: str) -> Issue | None:
    row = conn.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
    return _row(row) if row else None


def require(conn: sqlite3.Connection, issue_id: str) -> Issue:
    issue = get(conn, issue_id)
    if issue is None:
        raise IssueNotFoundError(f"no issue with id {issue_id}")
    return issue


def list_issues(conn: sqlite3.Connection, status: str | None = None) -> list[Issue]:
    if status is None:
        rows = conn.execute("SELECT * FROM issues ORDER BY created_at, rowid").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM issues WHERE status = ? ORDER BY created_at, rowid", (status,)
        ).fetchall()
    return [_row(row) for row in rows]


def open_issue(
    conn: sqlite3.Connection,
    title: str,
    body: str | None = None,
    ref_ids: list[str] | None = None,
    blocks: list[str] | None = None,
) -> Issue:
    ref_ids = ref_ids or []
    blocks = blocks or []
    for ref_id in ref_ids:
        entities.require(conn, ref_id)
    for card_id in blocks:
        if db.get_card(conn, card_id) is None:
            raise CardNotFoundError(f"no card with id {card_id}")
    now = _now()
    issue = Issue(str(uuid.uuid4()), title, body, "open", None, now, now)
    conn.execute(
        "INSERT INTO issues (id, title, body, status, close_reason, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (issue.id, issue.title, issue.body, issue.status, None, now, now),
    )
    conn.commit()
    for ref_id in ref_ids:
        refs.add_explicit(conn, issue.id, ref_id)
    for card_id in blocks:
        core.block_card(conn, card_id, issue.id)
    if body:
        refs.reindex(conn, issue.id)
    return issue


def _set(conn: sqlite3.Connection, issue_id: str, **fields) -> Issue:
    require(conn, issue_id)
    fields["updated_at"] = _now()
    columns = ", ".join(f"{key} = ?" for key in fields)
    conn.execute(f"UPDATE issues SET {columns} WHERE id = ?", [*fields.values(), issue_id])
    conn.commit()
    return require(conn, issue_id)


def update(
    conn: sqlite3.Connection, issue_id: str, title: str | None = None, body: str | None = None
) -> Issue:
    fields = {key: value for key, value in (("title", title), ("body", body)) if value is not None}
    if not fields:
        return require(conn, issue_id)
    issue = _set(conn, issue_id, **fields)
    if body is not None:
        refs.reindex(conn, issue_id)
    return issue


def close(conn: sqlite3.Connection, issue_id: str, reason: str = "resolved") -> Issue:
    if reason not in CLOSE_REASONS:
        raise InvalidCloseReasonError(
            f"invalid close reason {reason!r}; use one of {', '.join(CLOSE_REASONS)}"
        )
    return _set(conn, issue_id, status="closed", close_reason=reason)


def reopen(conn: sqlite3.Connection, issue_id: str) -> Issue:
    return _set(conn, issue_id, status="open", close_reason=None)


def blocks_of(conn: sqlite3.Connection, issue_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT card_id FROM blocked_by WHERE blocks_on_id = ? ORDER BY card_id", (issue_id,)
    ).fetchall()
    return [row["card_id"] for row in rows]
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/brd/issues.py src/brd/core.py tests/test_issues.py
git commit -m "Add issues with open/closed lifecycle; open issues block cards"
```

---

### Task 12: `brd issue` commands and issue `show`

**Files:**
- Create: `src/brd/cli/issues.py`, `tests/test_cli_issues.py`
- Modify: `src/brd/views.py`, `src/brd/cli/__init__.py`, `src/brd/cli/cards.py` (help text of `block --by`)

**Interfaces:**
- Produces: `views.issue_detail(conn, issue) -> dict` → `{id, kind: "issue", title, body, status, close_reason, blocks, created_at, updated_at, comments, refs, referenced_by}`; `views.detail` issue branch.

- [ ] **Step 1: Write the failing tests** — `tests/test_cli_issues.py`

```python
from tests.cli_helpers import err, ok


def test_issue_lifecycle(project):
    issue = ok("issue", "open", "--title", "Grammar ambiguity", "--body", "details")
    assert (issue["status"], issue["kind"]) == ("open", "issue")
    assert ok("issue", "update", issue["id"], "--title", "Renamed")["title"] == "Renamed"
    closed = ok("issue", "close", issue["id"], "--reason", "wontfix")
    assert (closed["status"], closed["close_reason"]) == ("closed", "wontfix")
    assert ok("issue", "reopen", issue["id"])["close_reason"] is None
    assert ok("issue", "close", issue["id"])["close_reason"] == "resolved"


def test_issue_list_filter(project):
    a = ok("issue", "open", "--title", "a")
    b = ok("issue", "open", "--title", "b")
    ok("issue", "close", b["id"])
    assert [i["id"] for i in ok("issue", "list", "--status", "open")] == [a["id"]]
    assert len(ok("issue", "list")) == 2


def test_issue_open_with_ref_and_blocks(project):
    card = ok("add", "--title", "Work")
    issue = ok("issue", "open", "--title", "Q", "--ref", card["id"], "--blocks", card["id"])
    assert issue["blocks"] == [card["id"]]
    shown = ok("show", card["id"])
    assert (shown["status"], shown["blocked_by"]) == ("blocked", [issue["id"]])
    assert shown["referenced_by"][0]["id"] == issue["id"]
    ok("issue", "close", issue["id"])
    assert ok("show", card["id"])["status"] == "todo"


def test_block_card_on_issue_via_block_command(project):
    card = ok("add", "--title", "Work")
    issue = ok("issue", "open", "--title", "Q")
    assert ok("block", card["id"], "--by", issue["id"])["status"] == "blocked"
    assert ok("next") == []
    assert ok("unblock", card["id"], "--by", issue["id"])["status"] == "todo"


def test_comment_on_issue_and_show(project):
    issue = ok("issue", "open", "--title", "Q")
    ok("comment", "add", issue["id"], "thoughts", "--author", "claude")
    shown = ok("show", issue["id"])
    assert shown["comments"][0]["author"] == "claude"


def test_issue_errors(project):
    assert err("issue", "close", "nope") == "IssueNotFoundError"
    issue = ok("issue", "open", "--title", "Q")
    assert err("issue", "close", issue["id"], "--reason", "meh") == "InvalidCloseReasonError"
    assert err("issue", "open", "--title", "Q", "--blocks", "ghost") == "CardNotFoundError"


def test_delete_issue(project):
    issue = ok("issue", "open", "--title", "Q")
    assert ok("delete", issue["id"]) == {"deleted": [issue["id"]]}
    assert ok("issue", "list") == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_cli_issues.py -v`
Expected: FAIL — `No such command 'issue'`.

- [ ] **Step 3: Views** — in `src/brd/views.py` add `issues` to the `from brd import ...` line, add `issue_detail`, and add the issue branch in `detail` (before the final card `return`):

```python
def issue_detail(conn: sqlite3.Connection, issue: issues.Issue) -> dict:
    return {
        "id": issue.id,
        "kind": "issue",
        "title": issue.title,
        "body": issue.body,
        "status": issue.status,
        "close_reason": issue.close_reason,
        "blocks": issues.blocks_of(conn, issue.id),
        "created_at": issue.created_at,
        "updated_at": issue.updated_at,
        "comments": [comment_dict(c) for c in comments.list_for(conn, issue.id)],
        **links_of(conn, issue.id),
    }
```

```python
    if kind == "issue":
        return issue_detail(conn, issues.require(conn, entity_id))
```

- [ ] **Step 4: `src/brd/cli/issues.py`**

```python
import typer

from brd import issues, views
from brd.cli._app import app, pretty_option, run

issue_app = typer.Typer(help="Track bugs, questions, and findings.", no_args_is_help=True)
app.add_typer(issue_app, name="issue")


@issue_app.command("open")
def open_cmd(
    title: str = typer.Option(..., "--title", help="Issue title."),
    body: str | None = typer.Option(None, "--body", help="Issue body; may contain [[links]]."),
    ref: list[str] = typer.Option([], "--ref", help="Id of a card/issue/document it references (repeatable)."),
    blocks: list[str] = typer.Option([], "--blocks", help="Id of a card it blocks while open (repeatable)."),
    pretty: bool = pretty_option(),
) -> None:
    """Open an issue."""

    def action(ctx):
        issue = issues.open_issue(ctx.conn, title, body=body, ref_ids=list(ref), blocks=list(blocks))
        return views.issue_detail(ctx.conn, issue)

    run(pretty, action)


@issue_app.command("list")
def list_cmd(
    status: str | None = typer.Option(None, "--status", help="open or closed."),
    pretty: bool = pretty_option(),
) -> None:
    """List issues, oldest first."""
    run(
        pretty,
        lambda ctx: [views.issue_detail(ctx.conn, i) for i in issues.list_issues(ctx.conn, status)],
    )


@issue_app.command("update")
def update(
    issue_id: str = typer.Argument(..., help="Issue id."),
    title: str | None = typer.Option(None, "--title", help="New title."),
    body: str | None = typer.Option(None, "--body", help="New body."),
    pretty: bool = pretty_option(),
) -> None:
    """Edit an issue's title or body."""
    run(
        pretty,
        lambda ctx: views.issue_detail(ctx.conn, issues.update(ctx.conn, issue_id, title=title, body=body)),
    )


@issue_app.command("close")
def close(
    issue_id: str = typer.Argument(..., help="Issue id."),
    reason: str = typer.Option("resolved", "--reason", help="resolved, wontfix, or duplicate."),
    pretty: bool = pretty_option(),
) -> None:
    """Close an issue (unblocks any cards it blocks)."""
    run(pretty, lambda ctx: views.issue_detail(ctx.conn, issues.close(ctx.conn, issue_id, reason)))


@issue_app.command("reopen")
def reopen(
    issue_id: str = typer.Argument(..., help="Issue id."),
    pretty: bool = pretty_option(),
) -> None:
    """Reopen a closed issue."""
    run(pretty, lambda ctx: views.issue_detail(ctx.conn, issues.reopen(ctx.conn, issue_id)))
```

- [ ] **Step 5: Register and help text**

`src/brd/cli/__init__.py` import line becomes:

```python
from brd.cli import project, cards, comments, tags, refs, docs, issues  # noqa: E402,F401  (registers commands)
```

In `src/brd/cli/cards.py`, change the `block` command's `--by` help to `"Id of the card or issue blocking it."` and its docstring to `"""Mark a card as blocked by another card or an open issue."""`.

- [ ] **Step 6: Run tests**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/brd/views.py src/brd/cli tests/test_cli_issues.py
git commit -m "Add brd issue commands and issue show"
```

---

## Milestone 5 — Snapshot and presentation

### Task 13: `brd export` and v2 `brd import`

**Files:**
- Create: `src/brd/snapshot.py`, `src/brd/cli/snapshot.py`, `tests/test_snapshot.py`
- Modify: `src/brd/core.py` (`import_tree`), `src/brd/cli/cards.py` (remove `import_cmd`), `src/brd/cli/__init__.py`

**Interfaces:**
- Consumes: `documents._check_unique/_write_backup/_hash/sync_all/list_all`, `issues.list_issues`, `core.build_tree/_flatten_tree/import_tree`, `refs.reindex`
- Produces:
  - `snapshot.export(conn, root) -> dict` (format in spec §7)
  - `snapshot.load(conn, root, raw) -> dict` — old format → `{"imported": n}`; new format → `{"imported": n_entities, "cards": n, "issues": n, "documents": n, "comments": n}`
  - `core.import_tree` now checks collisions against `entities` and reindexes imported cards

- [ ] **Step 1: Write the failing tests** — `tests/test_snapshot.py`

```python
import json

import pytest

from tests.cli_helpers import err, ok


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def populated(project):
    card = ok("add", "--title", "Parser", "--description", "see [[notes]]")
    child = ok("add", "--title", "Lexer", "--parent", card["id"])
    write(project, "docs/notes.md", f"# Notes\nabout [[{card['id']}]]")
    doc = ok("doc", "add", "docs/notes.md", "--tag", "design")
    issue = ok("issue", "open", "--title", "Q", "--body", "hmm", "--ref", doc["id"], "--blocks", child["id"])
    ok("comment", "add", card["id"], "progress", "--author", "claude")
    return {"card": card, "child": child, "doc": doc, "issue": issue}


def _shows(ids):
    return {i: ok("show", i) for i in ids}


def test_export_shape(populated):
    data = ok("export")
    assert data["brd_export"] == 1
    assert [c["id"] for c in data["cards"]] == [populated["card"]["id"]]
    assert data["documents"][0]["content"].startswith("# Notes")
    assert data["tags"] == [{"entity_id": populated["doc"]["id"], "tag": "design"}]
    assert all(r["origin"] == "explicit" for r in data["refs"])


def test_round_trip_into_fresh_project(populated, tmp_path, monkeypatch):
    ids = [populated[k]["id"] for k in ("card", "child", "doc", "issue")]
    before = _shows(ids)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(ok("export")))

    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    ok("init")
    result = ok("import", snapshot)
    assert (result["cards"], result["issues"], result["documents"], result["comments"]) == (2, 1, 1, 1)

    after = _shows(ids)
    # The source file isn't in the new repo; brd serves the backup.
    assert after[populated["doc"]["id"]]["source_state"] == "missing"
    for data in (before, after):
        data[populated["doc"]["id"]].pop("source_state")
    assert before == after
    ok("doc", "restore", populated["doc"]["id"])
    assert (other / "docs" / "notes.md").read_text().startswith("# Notes")


def test_import_collision_touches_nothing(populated, tmp_path):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(ok("export")))
    before = len(ok("list"))
    assert err("import", snapshot) == "EntityAlreadyExistsError"
    assert len(ok("list")) == before


def test_import_accepts_wrapped_export_envelope(populated, tmp_path, monkeypatch):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"ok": True, "data": ok("export")}))
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    ok("init")
    assert ok("import", snapshot)["cards"] == 2


def test_old_tree_snapshot_still_imports(project, tmp_path, monkeypatch):
    a = ok("add", "--title", "A")
    ok("add", "--title", "B", "--blocked-by", a["id"])
    snapshot = tmp_path / "tree.json"
    snapshot.write_text(json.dumps({"ok": True, "data": ok("tree")}))
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    ok("init")
    assert ok("import", snapshot) == {"imported": 2}
    assert err("import", snapshot) == "CardAlreadyExistsError"


def test_import_rejects_unknown_format(project, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"hello": 1}))
    assert err("import", bad) == "ImportFormatError"
    bad.write_text(json.dumps({"brd_export": 99}))
    assert err("import", bad) == "ImportFormatError"
    bad.write_text("not json")
    assert err("import", bad) == "ImportReadError"


def test_import_stem_collision_touches_nothing(populated, tmp_path, monkeypatch):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(ok("export")))
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    ok("init")
    write(other, "docs/notes.md", "local")
    ok("doc", "add", "docs/notes.md")
    assert err("import", snapshot) == "DuplicatePathError"
    assert ok("list") == [] and ok("issue", "list") == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_snapshot.py -v`
Expected: FAIL — `No such command 'export'`.

- [ ] **Step 3: `core.import_tree` changes**

In `core.import_tree`, replace the collision loop's `db.get_card(conn, node["id"]) is not None` with `entities.kind_of(conn, node["id"]) is not None`, and before `return len(flattened)` add:

```python
    for node, _ in flattened:
        refs.reindex(conn, node["id"])
```

- [ ] **Step 4: Implement `src/brd/snapshot.py`**

```python
import dataclasses
import sqlite3
from pathlib import Path, PurePosixPath

from brd import core, documents, entities, issues, refs
from brd.errors import EntityAlreadyExistsError, ImportFormatError

FORMAT_VERSION = 1


def export(conn: sqlite3.Connection, root: Path) -> dict:
    results = documents.sync_all(conn, root)
    return {
        "brd_export": FORMAT_VERSION,
        "cards": core.build_tree(conn),
        "issues": [dataclasses.asdict(i) for i in issues.list_issues(conn)],
        "documents": [
            {
                "id": d.id,
                "title": d.title,
                "source_path": d.source_path,
                "content": results[d.id].content,
                "content_hash": d.content_hash,
                "created_at": d.created_at,
                "updated_at": d.updated_at,
            }
            for d in documents.list_all(conn)
        ],
        "comments": [
            dict(row)
            for row in conn.execute(
                "SELECT id, entity_id, author, body, created_at FROM comments "
                "ORDER BY created_at, rowid"
            )
        ],
        "tags": [
            dict(row)
            for row in conn.execute("SELECT entity_id, tag FROM tags ORDER BY entity_id, tag")
        ],
        "refs": [
            dict(row)
            for row in conn.execute(
                "SELECT src_id, dst_id, origin FROM refs WHERE origin = 'explicit' "
                "ORDER BY src_id, dst_id"
            )
        ],
    }


def load(conn: sqlite3.Connection, root: Path, raw) -> dict:
    # `brd export > file` writes the whole envelope; accept it unwrapped too.
    if isinstance(raw, dict) and isinstance(raw.get("data"), dict):
        raw = raw["data"]
    if isinstance(raw, dict) and "brd_export" in raw:
        if raw["brd_export"] != FORMAT_VERSION:
            raise ImportFormatError(f"unsupported brd_export version {raw['brd_export']!r}")
        return _load_export(conn, raw)
    nodes = raw["data"] if isinstance(raw, dict) and "data" in raw else raw
    if not isinstance(nodes, list):
        raise ImportFormatError("expected a `brd export` object or a `brd tree` snapshot list")
    return {"imported": core.import_tree(conn, nodes)}


def _load_export(conn: sqlite3.Connection, snap: dict) -> dict:
    flattened = core._flatten_tree(snap.get("cards", []))
    issue_rows = snap.get("issues", [])
    doc_rows = snap.get("documents", [])
    comment_rows = snap.get("comments", [])

    entity_ids = (
        [node["id"] for node, _ in flattened]
        + [i["id"] for i in issue_rows]
        + [d["id"] for d in doc_rows]
    )
    if len(set(entity_ids)) != len(entity_ids):
        raise ImportFormatError("snapshot contains duplicate ids")
    for entity_id in entity_ids:
        if entities.kind_of(conn, entity_id) is not None:
            raise EntityAlreadyExistsError(f"entity {entity_id} already exists in this board")
    for comment in comment_rows:
        if conn.execute("SELECT 1 FROM comments WHERE id = ?", (comment["id"],)).fetchone():
            raise EntityAlreadyExistsError(f"comment {comment['id']} already exists in this board")
    for doc in doc_rows:
        documents._check_unique(conn, doc["source_path"], PurePosixPath(doc["source_path"]).stem)

    contents = {
        d["id"]: d["content"].encode("utf-8") for d in doc_rows if d.get("content") is not None
    }
    try:
        with conn:  # one transaction: commits on success, rolls back on error
            for node, parent_id in flattened:
                status = "todo" if node["status"] == "blocked" else node["status"]
                conn.execute(
                    "INSERT INTO cards (id, title, description, status, parent_id, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (node["id"], node["title"], node.get("description"), status,
                     parent_id, node["created_at"], node["updated_at"]),
                )
            for i in issue_rows:
                conn.execute(
                    "INSERT INTO issues (id, title, body, status, close_reason, created_at, "
                    "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (i["id"], i["title"], i.get("body"), i["status"], i.get("close_reason"),
                     i["created_at"], i["updated_at"]),
                )
            for d in doc_rows:
                digest = documents._hash(contents[d["id"]]) if d["id"] in contents else d["content_hash"]
                conn.execute(
                    "INSERT INTO documents (id, title, source_path, stem, content_hash, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (d["id"], d["title"], d["source_path"], PurePosixPath(d["source_path"]).stem,
                     digest, d["created_at"], d["updated_at"]),
                )
            for node, _ in flattened:
                for blocker_id in node.get("blocked_by", []):
                    conn.execute(
                        "INSERT INTO blocked_by (card_id, blocks_on_id) VALUES (?, ?)",
                        (node["id"], blocker_id),
                    )
            for c in comment_rows:
                conn.execute(
                    "INSERT INTO comments (id, entity_id, author, body, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (c["id"], c["entity_id"], c["author"], c["body"], c["created_at"]),
                )
            for t in snap.get("tags", []):
                conn.execute(
                    "INSERT INTO tags (entity_id, tag) VALUES (?, ?)", (t["entity_id"], t["tag"])
                )
            for r in snap.get("refs", []):
                if r.get("origin", "explicit") == "explicit":
                    conn.execute(
                        "INSERT INTO refs (src_id, dst_id, origin) VALUES (?, ?, 'explicit')",
                        (r["src_id"], r["dst_id"]),
                    )
    except sqlite3.IntegrityError as exc:
        raise ImportFormatError(f"snapshot is internally inconsistent: {exc}") from exc

    for doc_id, data in contents.items():
        documents._write_backup(conn, doc_id, data)
    for entity_id in entity_ids:
        refs.reindex(conn, entity_id)
    return {
        "imported": len(entity_ids),
        "cards": len(flattened),
        "issues": len(issue_rows),
        "documents": len(doc_rows),
        "comments": len(comment_rows),
    }
```

- [ ] **Step 5: `src/brd/cli/snapshot.py`** — and delete `import_cmd` (plus the now-unused `json`, `Path`, `ImportReadError` imports) from `src/brd/cli/cards.py`

```python
import json
from pathlib import Path

import typer

from brd import snapshot
from brd.cli._app import app, pretty_option, run
from brd.errors import ImportReadError


@app.command(name="export")
def export_cmd(pretty: bool = pretty_option()) -> None:
    """Print a full JSON snapshot: cards, issues, documents, comments, tags, refs."""
    run(pretty, lambda ctx: snapshot.export(ctx.conn, ctx.root))


@app.command(name="import")
def import_cmd(
    file: Path = typer.Argument(
        ..., help="Path to a `brd export` file (or an older `brd tree` snapshot)."
    ),
    pretty: bool = pretty_option(),
) -> None:
    """Restore a board from a snapshot; touches nothing if any id already exists."""

    def action(ctx):
        try:
            raw = json.loads(file.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ImportReadError(f"could not read a JSON snapshot from {file}: {exc}") from exc
        return snapshot.load(ctx.conn, ctx.root, raw)

    run(pretty, action)
```

`src/brd/cli/__init__.py` import line becomes:

```python
from brd.cli import project, cards, comments, tags, refs, docs, issues, snapshot  # noqa: E402,F401  (registers commands)
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest -q`
Expected: all pass (existing `import` tests in `tests/test_cli.py` included).

- [ ] **Step 7: Commit**

```bash
git add src/brd/snapshot.py src/brd/core.py src/brd/cli tests/test_snapshot.py
git commit -m "Add brd export and full-board import"
```

---

### Task 14: `--pretty` renderers with link titles

**Files:**
- Create: `src/brd/pretty.py`, `tests/test_pretty.py`
- Modify: `src/brd/cli/cards.py` (`show`, `list`, `next`), `src/brd/cli/issues.py` (`list`), `src/brd/cli/docs.py` (`list`), `src/brd/cli/comments.py` (`list`)

**Interfaces:**
- Consumes: `links.render`, `refs.resolve`, `entities.title_of/kind_of`
- Produces: `pretty.text(conn, value) -> str`, `pretty.render_detail(conn, data: dict) -> str`, `pretty.render_list(conn, items: list[dict]) -> str`, `pretty.render_comments(conn, items: list[dict]) -> str`. CLI wiring passes `render=lambda ctx, data: pretty.render_x(ctx.conn, data)`.

- [ ] **Step 1: Write the failing tests** — `tests/test_pretty.py`

```python
from tests.cli_helpers import human, ok


def test_show_card_renders_titles_for_links(project):
    target = ok("add", "--title", "Tokenizer spike")
    card = ok("add", "--title", "Parser", "--description", f"after [[{target['id']}]] and [[ghost]]")
    ok("comment", "add", card["id"], f"see [[{target['id']}|the spike]]", "--author", "claude")
    out = human("show", card["id"])
    assert out.splitlines()[0] == f"Parser  [todo]  ({card['id']})"
    assert "after [[Tokenizer spike]] and [[ghost]] (unresolved)" in out
    assert "refs: Tokenizer spike (card)" in out
    assert "claude · " in out
    assert "  see [[the spike]]" in out
    assert target["id"] not in out.split("\n", 1)[1]  # ids only in the header


def test_show_card_blocked_by_issue(project):
    card = ok("add", "--title", "Work")
    ok("issue", "open", "--title", "Grammar ambiguity", "--blocks", card["id"])
    assert "blocked by: [[Grammar ambiguity]] (issue, open)" in human("show", card["id"])


def test_show_issue_and_document(project):
    (project / "docs").mkdir()
    (project / "docs" / "notes.md").write_text("body")
    doc = ok("doc", "add", "docs/notes.md", "--tag", "design")
    issue = ok("issue", "open", "--title", "Q", "--body", "read [[notes]]")
    ok("issue", "close", issue["id"], "--reason", "wontfix")
    issue_out = human("show", issue["id"])
    assert issue_out.splitlines()[0] == f"Q  [closed: wontfix]  ({issue['id']})"
    assert "read [[notes]]" in issue_out
    doc_out = human("show", doc["id"])
    assert doc_out.splitlines()[0] == f"notes  [ok]  ({doc['id']})"
    assert "path: docs/notes.md" in doc_out and "tags: #design" in doc_out
    assert "referenced by: Q (issue)" in doc_out


def test_lists(project):
    (project / "docs").mkdir()
    (project / "docs" / "a.md").write_text("")
    doc = ok("doc", "add", "docs/a.md", "--tag", "x")
    issue = ok("issue", "open", "--title", "Q")
    card = ok("add", "--title", "C")
    assert human("doc", "list").strip() == f"{doc['id']}  [ok]  a  (docs/a.md)  #x"
    assert human("issue", "list").strip() == f"{issue['id']}  [open]  Q"
    assert human("list").strip() == f"{card['id']}  [todo]  C"
    ok("comment", "add", card["id"], "hi", "--author", "me")
    assert human("comment", "list", card["id"]).splitlines()[1] == "  hi"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_pretty.py -v`
Expected: FAIL — pretty `show` prints a Python dict.

- [ ] **Step 3: Implement `src/brd/pretty.py`**

```python
import sqlite3

from brd import entities, links, refs


def text(conn: sqlite3.Connection, value: str | None) -> str:
    def display(token: links.LinkToken) -> str | None:
        dst = refs.resolve(conn, token.target)
        return entities.title_of(conn, dst) if dst else None

    return links.render(value, display)


def _stamp(iso: str) -> str:
    return iso[:16].replace("T", " ")


def _ref_line(label: str, items: list[dict]) -> str | None:
    seen: dict[str, dict] = {}
    for item in items:
        seen.setdefault(item["id"], item)
    if not seen:
        return None
    return f"{label}: " + ", ".join(f"{i['title']} ({i['kind']})" for i in seen.values())


def _blocker(conn: sqlite3.Connection, blocker_id: str) -> str:
    kind = entities.kind_of(conn, blocker_id)
    title = entities.title_of(conn, blocker_id)
    if kind == "issue":
        status = conn.execute("SELECT status FROM issues WHERE id = ?", (blocker_id,)).fetchone()
        return f"[[{title}]] (issue, {status['status']})"
    return f"[[{title}]] (card)"


def _comment_lines(conn: sqlite3.Connection, items: list[dict]) -> list[str]:
    lines = []
    for comment in items:
        lines.append(f"{comment['author']} · {_stamp(comment['created_at'])}")
        lines.extend(f"  {line}" for line in text(conn, comment["body"]).splitlines())
    return lines


def render_detail(conn: sqlite3.Connection, data: dict) -> str:
    kind = data["kind"]
    extra: list[str | None] = []
    if kind == "card":
        header = f"{data['title']}  [{data['status']}]  ({data['id']})"
        if data["blocked_by"]:
            extra.append("blocked by: " + ", ".join(_blocker(conn, b) for b in data["blocked_by"]))
        body = data["description"]
    elif kind == "issue":
        status = data["status"] + (f": {data['close_reason']}" if data["close_reason"] else "")
        header = f"{data['title']}  [{status}]  ({data['id']})"
        if data["blocks"]:
            extra.append("blocks: " + ", ".join(f"[[{entities.title_of(conn, c)}]]" for c in data["blocks"]))
        body = data["body"]
    else:
        header = f"{data['title']}  [{data['source_state']}]  ({data['id']})"
        extra.append(f"path: {data['source_path']}")
        if data["tags"]:
            extra.append("tags: " + " ".join(f"#{t}" for t in data["tags"]))
        body = data["content"]

    parts = [header, *[line for line in extra if line]]
    if body:
        parts += ["", text(conn, body)]
    ref_lines = [
        line
        for line in (
            _ref_line("refs", data["refs"]),
            _ref_line("referenced by", data["referenced_by"]),
        )
        if line
    ]
    if ref_lines:
        parts += ["", *ref_lines]
    if data.get("comments"):
        parts += ["", "── comments ──", *_comment_lines(conn, data["comments"])]
    return "\n".join(parts)


def _list_line(item: dict) -> str:
    if item.get("kind") == "document":
        line = f"{item['id']}  [{item['source_state']}]  {item['title']}  ({item['source_path']})"
        if item["tags"]:
            line += "  " + " ".join(f"#{t}" for t in item["tags"])
        return line
    return f"{item['id']}  [{item['status']}]  {item['title']}"


def render_list(conn: sqlite3.Connection, items: list[dict]) -> str:
    return "\n".join(_list_line(item) for item in items)


def render_comments(conn: sqlite3.Connection, items: list[dict]) -> str:
    return "\n".join(_comment_lines(conn, items))
```

- [ ] **Step 4: Wire renderers**

Add `from brd import pretty as pretty_render` to each CLI module below (the parameter `pretty` shadows the module name, hence the alias), then pass `render=`:

- `cli/cards.py` `show`: `run(pretty, lambda ctx: views.detail(ctx.conn, ctx.root, entity_id), render=lambda ctx, data: pretty_render.render_detail(ctx.conn, data))`
- `cli/cards.py` `list_cards_cmd` and `next_cmd`: `run(pretty, action, render=lambda ctx, data: pretty_render.render_list(ctx.conn, data))`
- `cli/issues.py` `list_cmd`: add `render=lambda ctx, data: pretty_render.render_list(ctx.conn, data)`
- `cli/docs.py` `list_cmd`: `run(pretty, action, render=lambda ctx, data: pretty_render.render_list(ctx.conn, data))`
- `cli/comments.py` `list_cmd`: add `render=lambda ctx, data: pretty_render.render_comments(ctx.conn, data)`

- [ ] **Step 5: Run tests**

Run: `uv run pytest -q`
Expected: all pass (including existing `test_next_pretty_flag_switches_off_json`).

- [ ] **Step 6: Commit**

```bash
git add src/brd/pretty.py src/brd/cli tests/test_pretty.py
git commit -m "Render links as titles in --pretty output"
```

---

### Task 15: Agent prompt and README

**Files:**
- Modify: `src/brd/prompt.py`, `README.md`, `tests/test_cli.py` is NOT modified; create `tests/test_prompt.py`

- [ ] **Step 1: Write the failing test** — `tests/test_prompt.py`

```python
from brd import prompt


def test_prompt_covers_new_features():
    snippet = prompt.render()
    assert "Whenever you edit a registered document, run `brd doc update <id>`" in snippet
    assert "BRD_AUTHOR" in snippet
    assert "brd issue open" in snippet
    assert "brd block <card> --by <issue>" in snippet
    assert "brd export" in snippet
    assert "brd tree > docs/board/snapshot.json" not in snippet
```

Run: `uv run pytest tests/test_prompt.py -v`
Expected: FAIL.

- [ ] **Step 2: Update `SNIPPET` in `src/brd/prompt.py`**

Replace the paragraph starting "Board data lives outside this repo" and add new sections, so `SNIPPET` reads:

```python
SNIPPET = """## Task tracking with brd

This repo tracks work with `brd`, a local kanban CLI.

- `brd next` — see what's ready to work on (unblocked todo cards)
- `brd show <id>` — full detail of any card, issue, or document
- `brd add --title "..." [--parent <id>] [--blocked-by <id>]` — create a card
- `brd update <id> --status in_progress|done` — update status as you go
- `brd tree` — see the whole board's hierarchy/dependencies

No fixed Epic/Story/Task types — any card becomes an "epic" just by
giving other cards `--parent <its-id>`. A card with children is a
container, not work: `brd next` skips it and only surfaces its leaves.

**Issues:** for bugs, questions, and findings that aren't work yet
(`brd issue open --title "..." [--body "..."]`, `brd issue close <id>
[--reason resolved|wontfix|duplicate]`). Block a card on an open issue
with `brd block <card> --by <issue>`; closing the issue unblocks it.

**Documents:** registered `.md` files (`brd doc list`) are tracked by brd,
which keeps a backup. **Whenever you edit a registered document, run
`brd doc update <id>` right after.** If you move or rename one, run
`brd doc update <id> --path <new>`. Register new ones with
`brd doc add <path> [--tag t]`.

**Links:** write `[[doc-stem]]` or `[[<id>]]` in card descriptions, issue
bodies, and comments to link things; `brd show` lists refs and backlinks.

**Comments:** `brd comment add <id> "..."` records progress or decisions
on a card or issue. Set `BRD_AUTHOR` to your agent name once per session.

Board data lives outside this repo (in `~/.local/share/brd/`), keyed to
this project's path — the `.brd` marker file is gitignored and doesn't
carry any board data itself. `brd export > docs/board/snapshot.json`
gives you a committable record of everything; `brd import <file>`
restores it (same ids and timestamps) on another machine or clone.

Output is JSON by default; add `--pretty` for human-readable text.
Use `brd --help` to see all commands.
"""
```

- [ ] **Step 3: README** — in `README.md`:

Replace the Usage code block with:

```bash
cd your-project
brd init                                  # register this repo as a project
brd add --title "Write the parser"        # create a card
brd add --title "Write tests" \
  --blocked-by <parser-card-id>           # create a card blocked on another
brd next                                  # fetch ready-to-work card(s)
brd tree                                  # view the whole board as a tree
brd show <id>                             # full detail of a card, issue, or document
brd update <card-id> --status done        # move a card forward
brd delete <id>                           # delete (--cascade for cards with children)
brd projects                              # list all registered projects

brd issue open --title "Grammar is ambiguous" --blocks <card-id>
brd issue close <issue-id> --reason wontfix
brd doc add docs/parser-notes.md --tag design   # register a markdown file
brd doc update <doc-id>                   # after editing it: refresh brd's backup
brd comment add <card-or-issue-id> "Lexer done; see [[parser-notes]]"
brd tag list                              # all tags with counts
```

Replace the two snapshot commands in the Storage section with:

```bash
brd export > docs/board/snapshot.json   # commit this
brd import docs/board/snapshot.json     # on another machine/clone, after brd init
```

and change the sentence after them to: "`import` preserves the original ids, content, and timestamps — including document backups (restore a missing file with `brd doc restore <id>`) — and refuses to run (touching nothing) if any id in the snapshot already exists in the target board. Older `brd tree` snapshots still import."

Add a new section before "## For agents":

```markdown
## Documents

`brd doc add <path>` registers a markdown file inside the project. brd
stores a backup copy next to the board database and compares hashes on
every read: if the file changed, the backup is refreshed; if the file is
gone, brd serves the backup and reports it as `missing`. brd never writes
your files except when you run `brd doc restore`.

Link anything from any text with Obsidian-style `[[doc-stem]]` or
`[[<id>]]`; `brd show` lists outgoing refs and backlinks, and `--pretty`
renders links as titles.
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q`
Expected: all pass (existing `test_prompt_prints_plain_markdown_not_json` still sees `## Task tracking with brd`, `brd next`, `--parent`).

- [ ] **Step 5: Commit**

```bash
git add src/brd/prompt.py README.md tests/test_prompt.py
git commit -m "Document issues, documents, comments, and export in prompt and README"
```
