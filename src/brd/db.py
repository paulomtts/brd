import sqlite3
import uuid
from pathlib import Path

from brd.errors import MigrationError
from brd.models import Card, Project


def connect(db_path: Path) -> sqlite3.Connection:
    # Wait for concurrent writers (e.g. parallel first-run migrations)
    # instead of failing immediately with "database is locked".
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


_PROJECTS_SQL = """
CREATE TABLE {name} (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    root_path TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
)
"""


def new_project_id() -> str:
    return str(uuid.uuid4())


def _project_columns(conn: sqlite3.Connection) -> set[str]:
    return {row[1] for row in conn.execute("PRAGMA table_info(projects)")}


def _is_target_projects(columns: set[str]) -> bool:
    # Key the legacy check on db_path: the original legacy table also had an
    # id column, so "id" alone cannot tell it apart from the target.
    return "id" in columns and "db_path" not in columns


def _rebuild_projects(conn: sqlite3.Connection) -> None:
    """Rebuild a legacy or pre-id projects table into the target shape,
    keeping root_path, name and created_at and assigning fresh ids."""
    rows = conn.execute("SELECT root_path, name, created_at FROM projects").fetchall()
    conn.execute(_PROJECTS_SQL.format(name="projects_new"))
    for row in rows:
        # OR REPLACE collapses duplicate legacy root_paths: last row read wins.
        conn.execute(
            "INSERT OR REPLACE INTO projects_new (id, name, root_path, created_at) "
            "VALUES (?, ?, ?, ?)",
            (new_project_id(), row["name"], row["root_path"], row["created_at"]),
        )
    conn.execute("DROP TABLE projects")
    conn.execute("ALTER TABLE projects_new RENAME TO projects")


def init_master_schema(conn: sqlite3.Connection) -> None:
    if _is_target_projects(_project_columns(conn)):
        return
    conn.commit()
    try:
        # IMMEDIATE takes the write lock up front, so a concurrent first run
        # waits here and then sees the migrated table instead of re-migrating.
        conn.execute("BEGIN IMMEDIATE")
        columns = _project_columns(conn)
        if not columns:
            conn.execute(_PROJECTS_SQL.format(name="projects"))
        elif not _is_target_projects(columns):
            _rebuild_projects(conn)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


SCHEMA_VERSION = 4

# Stored card statuses ('blocked' is derived, never stored).
CARD_STATUSES = ("todo", "in_progress", "done", "merged", "canceled", "archived")

_CARDS_SQL = """
CREATE TABLE {name} (
    id TEXT PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL CHECK (status IN ({statuses})),
    parent_id TEXT REFERENCES cards(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_V1_CARD_STATUSES = ("todo", "in_progress", "done")


def _cards_sql(name: str, statuses: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{status}'" for status in statuses)
    return _CARDS_SQL.format(name=name, statuses=quoted)

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


_ENTITIES_SQL = """
CREATE TABLE {name} (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('card', 'issue', 'document')),
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE
)
"""

_DOCUMENTS_SQL = """
CREATE TABLE {name} (
    id TEXT PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL,
    title TEXT NOT NULL,
    source_path TEXT NOT NULL,
    stem TEXT NOT NULL COLLATE NOCASE,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (project_id, source_path),
    UNIQUE (project_id, stem COLLATE NOCASE)
)
"""

# From v4 on, edge targets have no foreign key: a target may live in another
# project, and deleting an entity removes its incoming edges explicitly.
_V4_BLOCKED_BY_SQL = """
CREATE TABLE {name} (
    card_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    blocks_on_id TEXT NOT NULL,
    PRIMARY KEY (card_id, blocks_on_id)
)
"""

_V4_REFS_SQL = """
CREATE TABLE {name} (
    src_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    dst_id TEXT NOT NULL,
    origin TEXT NOT NULL CHECK (origin IN ('explicit', 'link')),
    PRIMARY KEY (src_id, dst_id, origin)
)
"""

_V4_INDEXES = [
    "CREATE INDEX entities_project ON entities(project_id, kind)",
    "CREATE INDEX blocked_by_target ON blocked_by(blocks_on_id)",
    "CREATE INDEX refs_target ON refs(dst_id)",
]

_SAME_PROJECT_DOCUMENT = (
    "WHEN NEW.project_id IS NOT (SELECT project_id FROM entities WHERE id = NEW.id) "
    "BEGIN SELECT RAISE(ABORT, 'a document must be in the same project as its entity'); END"
)

# Fires only when the parent's entity exists and sits in another project; a
# parent that is not a card at all is left to the parent_id foreign key.
_SAME_PROJECT_PARENT = (
    "WHEN NEW.parent_id IS NOT NULL "
    "AND (SELECT project_id FROM entities WHERE id = NEW.parent_id) IS NOT NULL "
    "AND (SELECT project_id FROM entities WHERE id = NEW.parent_id) "
    "IS NOT (SELECT project_id FROM entities WHERE id = NEW.id) "
    "BEGIN SELECT RAISE(ABORT, 'a card''s parent must be in the same project as the card'); END"
)

_V4_TRIGGERS = [
    f"CREATE TRIGGER documents_project_insert BEFORE INSERT ON documents {_SAME_PROJECT_DOCUMENT}",
    "CREATE TRIGGER documents_project_update BEFORE UPDATE OF id, project_id ON documents "
    f"{_SAME_PROJECT_DOCUMENT}",
    f"CREATE TRIGGER cards_parent_project_insert BEFORE INSERT ON cards {_SAME_PROJECT_PARENT}",
    "CREATE TRIGGER cards_parent_project_update BEFORE UPDATE OF parent_id ON cards "
    f"{_SAME_PROJECT_PARENT}",
]

_DOCUMENT_COLUMNS = "title, source_path, stem, content_hash, created_at, updated_at"


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
        conn.execute(_cards_sql("cards_new", _V1_CARD_STATUSES))
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
        conn.execute(_cards_sql("cards", _V1_CARD_STATUSES))
        conn.execute(_BLOCKED_BY_SQL.format(name="blocked_by"))
    for statement in _V1_NEW_TABLES:
        conn.execute(statement)
    for table, kind in _ENTITY_KINDS:
        conn.execute(_register_trigger(table, kind))


def _migrate_to_v2(conn: sqlite3.Connection) -> None:
    # SQLite cannot alter a CHECK constraint, so rebuild cards with the wider
    # status set. Dropping the table drops its entity-registration trigger;
    # recreate it.
    conn.execute(_cards_sql("cards_new", CARD_STATUSES))
    conn.execute(
        "INSERT INTO cards_new SELECT id, title, description, status, parent_id, "
        "created_at, updated_at FROM cards"
    )
    conn.execute("DROP TABLE cards")
    conn.execute("ALTER TABLE cards_new RENAME TO cards")
    conn.execute(_register_trigger("cards", "card"))


def _migrate_to_v3(conn: sqlite3.Connection) -> None:
    # Same rebuild as v2, for the same reason: adding 'archived' to the CHECK
    # constraint. A fresh v0/v1 board runs this right after _migrate_to_v2,
    # which already rebuilt against the live (archived-inclusive)
    # CARD_STATUSES -- redundant in that case, but harmless, and it keeps
    # each version's migration naming the version it actually targets.
    conn.execute(_cards_sql("cards_new", CARD_STATUSES))
    conn.execute(
        "INSERT INTO cards_new SELECT id, title, description, status, parent_id, "
        "created_at, updated_at FROM cards"
    )
    conn.execute("DROP TABLE cards")
    conn.execute("ALTER TABLE cards_new RENAME TO cards")
    conn.execute(_register_trigger("cards", "card"))


def _rebuild_table(
    conn: sqlite3.Connection,
    table: str,
    create_sql: str,
    columns: str,
    values: str,
    params: tuple = (),
) -> None:
    # SQLite's usual rebuild: create the new shape, copy, drop, rename.
    # Child foreign keys name the table, so they follow the rename.
    conn.execute(create_sql.format(name=f"{table}_new"))
    conn.execute(f"INSERT INTO {table}_new ({columns}) SELECT {values} FROM {table}", params)
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE {table}_new RENAME TO {table}")


def _migrate_to_v4(conn: sqlite3.Connection, project: Project) -> None:
    # Drop the register triggers first: ALTER TABLE RENAME re-parses every
    # trigger, and their INSERT INTO entities would break the rebuilds.
    for table, _ in _ENTITY_KINDS:
        conn.execute(f"DROP TRIGGER IF EXISTS {table}_register_entity")
    # A legacy board may carry a stray projects table; the board's own row
    # replaces it.
    conn.execute("DROP TABLE IF EXISTS projects")
    conn.execute(_PROJECTS_SQL.format(name="projects"))
    conn.execute(
        "INSERT INTO projects (id, name, root_path, created_at) VALUES (?, ?, ?, ?)",
        (project.id, project.name, project.root_path, project.created_at),
    )
    _rebuild_table(
        conn, "entities", _ENTITIES_SQL, "id, kind, project_id", "id, kind, ?", (project.id,)
    )
    _rebuild_table(
        conn,
        "documents",
        _DOCUMENTS_SQL,
        f"id, project_id, {_DOCUMENT_COLUMNS}",
        f"id, ?, {_DOCUMENT_COLUMNS}",
        (project.id,),
    )
    _rebuild_table(
        conn, "blocked_by", _V4_BLOCKED_BY_SQL, "card_id, blocks_on_id", "card_id, blocks_on_id"
    )
    _rebuild_table(
        conn, "refs", _V4_REFS_SQL, "src_id, dst_id, origin", "src_id, dst_id, origin"
    )
    for statement in _V4_INDEXES:
        conn.execute(statement)
    for statement in _V4_TRIGGERS:
        conn.execute(statement)


def board_projects(conn: sqlite3.Connection) -> list[Project]:
    """The projects rows a board records; [] below v4, where a projects
    table, if any, is a legacy leftover."""
    if conn.execute("PRAGMA user_version").fetchone()[0] < 4:
        return []
    rows = conn.execute("SELECT * FROM projects ORDER BY created_at").fetchall()
    return [_row_to_project(row) for row in rows]


def _require_board_project(conn: sqlite3.Connection, project: Project) -> None:
    # Without this, a registry/board mismatch surfaces later as a raw FK
    # error on the first insert.
    stored = [row.id for row in board_projects(conn)]
    if project.id in stored:
        return
    held = f"project {', '.join(stored)}" if stored else "no project"
    raise MigrationError(
        f"this board records {held}, not project {project.id}; "
        "the registry and the board disagree"
    )


def migrate_project(conn: sqlite3.Connection, project: Project) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= SCHEMA_VERSION:
        _require_board_project(conn, project)
        return
    conn.commit()
    # Must be issued outside a transaction; SQLite ignores it inside one.
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        # IMMEDIATE takes the write lock up front, so concurrent migrators
        # queue on the busy timeout instead of failing to upgrade a read.
        conn.execute("BEGIN IMMEDIATE")
        # Another process may have migrated while we waited for the lock.
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version >= SCHEMA_VERSION:
            conn.rollback()
            _require_board_project(conn, project)
            return
        if version < 1:
            _migrate_to_v1(conn)
        if version < 2:
            _migrate_to_v2(conn)
        if version < 3:
            _migrate_to_v3(conn)
        if version < 4:
            _migrate_to_v4(conn, project)
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


def init_project_schema(conn: sqlite3.Connection, project: Project) -> None:
    migrate_project(conn, project)


def docs_dir(conn: sqlite3.Connection) -> Path:
    """Directory holding document backups: next to the db, `<db stem>.docs`."""
    main = next(row for row in conn.execute("PRAGMA database_list") if row["name"] == "main")
    return Path(main["file"]).with_suffix(".docs")


def _row_to_project(row: sqlite3.Row) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        root_path=row["root_path"],
        created_at=row["created_at"],
    )


def upsert_project(conn: sqlite3.Connection, project: Project) -> Project:
    """Register project, or rename the one already at its root_path. An
    existing row keeps its id and created_at; returns the stored row."""
    conn.execute(
        "INSERT INTO projects (id, name, root_path, created_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(root_path) DO UPDATE SET name = excluded.name",
        (project.id, project.name, project.root_path, project.created_at),
    )
    conn.commit()
    return get_project(conn, project.root_path)


def list_projects(conn: sqlite3.Connection) -> list[Project]:
    rows = conn.execute("SELECT * FROM projects ORDER BY created_at").fetchall()
    return [_row_to_project(row) for row in rows]


def get_project(conn: sqlite3.Connection, root_path: str) -> Project | None:
    row = conn.execute(
        "SELECT * FROM projects WHERE root_path = ?", (root_path,)
    ).fetchone()
    return _row_to_project(row) if row else None


def delete_project(conn: sqlite3.Connection, root_path: str) -> None:
    conn.execute("DELETE FROM projects WHERE root_path = ?", (root_path,))
    conn.commit()


def _row_to_card(row: sqlite3.Row) -> Card:
    return Card(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        status=row["status"],
        parent_id=row["parent_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def insert_entity(
    conn: sqlite3.Connection, project_id: str, entity_id: str, kind: str
) -> None:
    # No commit: callers insert the kind row in the same transaction, so the
    # two land together or not at all.
    conn.execute(
        "INSERT INTO entities (id, kind, project_id) VALUES (?, ?, ?)",
        (entity_id, kind, project_id),
    )


def insert_card(conn: sqlite3.Connection, project_id: str, card: Card) -> None:
    with conn:
        insert_entity(conn, project_id, card.id, "card")
        conn.execute(
            "INSERT INTO cards (id, title, description, status, parent_id, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                card.id,
                card.title,
                card.description,
                card.status,
                card.parent_id,
                card.created_at,
                card.updated_at,
            ),
        )


def get_card(conn: sqlite3.Connection, card_id: str) -> Card | None:
    row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    return _row_to_card(row) if row else None


def update_card_fields(conn: sqlite3.Connection, card_id: str, **fields) -> None:
    columns = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [card_id]
    conn.execute(f"UPDATE cards SET {columns} WHERE id = ?", values)
    conn.commit()


_UNSET = "__unset__"


def list_cards(
    conn: sqlite3.Connection,
    status: str | None = None,
    parent_id: str | None = _UNSET,
) -> list[Card]:
    query = "SELECT * FROM cards WHERE 1=1"
    params: list[str | None] = []
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    if parent_id is not _UNSET:
        if parent_id is None:
            query += " AND parent_id IS NULL"
        else:
            query += " AND parent_id = ?"
            params.append(parent_id)
    query += " ORDER BY created_at"
    rows = conn.execute(query, params).fetchall()
    return [_row_to_card(row) for row in rows]


def add_blocked_by_edge(
    conn: sqlite3.Connection, card_id: str, blocks_on_id: str
) -> None:
    conn.execute(
        "INSERT INTO blocked_by (card_id, blocks_on_id) VALUES (?, ?)",
        (card_id, blocks_on_id),
    )
    conn.commit()


def remove_blocked_by_edge(
    conn: sqlite3.Connection, card_id: str, blocks_on_id: str
) -> None:
    conn.execute(
        "DELETE FROM blocked_by WHERE card_id = ? AND blocks_on_id = ?",
        (card_id, blocks_on_id),
    )
    conn.commit()


def list_blockers_of(conn: sqlite3.Connection, card_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT blocks_on_id FROM blocked_by WHERE card_id = ?", (card_id,)
    ).fetchall()
    return [row["blocks_on_id"] for row in rows]


def list_children(conn: sqlite3.Connection, parent_id: str) -> list[Card]:
    rows = conn.execute(
        "SELECT * FROM cards WHERE parent_id = ? ORDER BY created_at", (parent_id,)
    ).fetchall()
    return [_row_to_card(row) for row in rows]


def delete_incoming_edges(conn: sqlite3.Connection, entity_id: str) -> None:
    # Edges pointing at entity_id. Explicit rather than an FK cascade so it
    # holds without one; no commit, so callers delete the entity in the same
    # transaction.
    conn.execute("DELETE FROM blocked_by WHERE blocks_on_id = ?", (entity_id,))
    conn.execute("DELETE FROM refs WHERE dst_id = ?", (entity_id,))


def delete_card(conn: sqlite3.Connection, card_id: str) -> None:
    # Incoming edges are deleted explicitly; the entities cascade takes the
    # cards row, its outgoing block edges and refs, comments, and tags.
    delete_incoming_edges(conn, card_id)
    conn.execute("DELETE FROM entities WHERE id = ?", (card_id,))
    conn.commit()
