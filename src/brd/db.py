import sqlite3
from pathlib import Path

from brd.errors import MigrationError
from brd.models import Card, Project


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_master_schema(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(projects)")}
    if "id" in columns:
        # Legacy schema (id PK, unique name, db_path): migrate in place,
        # preserving what still applies (root_path, name, created_at).
        old_rows = conn.execute(
            "SELECT name, root_path, created_at FROM projects"
        ).fetchall()
        conn.execute("DROP TABLE projects")
        conn.execute(
            """
            CREATE TABLE projects (
                root_path TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        for row in old_rows:
            conn.execute(
                "INSERT OR REPLACE INTO projects (root_path, name, created_at) "
                "VALUES (?, ?, ?)",
                (row["root_path"], row["name"], row["created_at"]),
            )
    else:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                root_path TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
    conn.commit()


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


def _row_to_project(row: sqlite3.Row) -> Project:
    return Project(
        root_path=row["root_path"],
        name=row["name"],
        created_at=row["created_at"],
    )


def upsert_project(conn: sqlite3.Connection, project: Project) -> None:
    conn.execute(
        "INSERT INTO projects (root_path, name, created_at) VALUES (?, ?, ?) "
        "ON CONFLICT(root_path) DO UPDATE SET name = excluded.name",
        (project.root_path, project.name, project.created_at),
    )
    conn.commit()


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


def insert_card(conn: sqlite3.Connection, card: Card) -> None:
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
    conn.commit()


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


def delete_card(conn: sqlite3.Connection, card_id: str) -> None:
    # Cascades to the cards row, its block edges, comments, tags, and refs.
    conn.execute("DELETE FROM entities WHERE id = ?", (card_id,))
    conn.commit()
