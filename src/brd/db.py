import sqlite3
from pathlib import Path

from brd.models import Card, Project


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
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


def init_project_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cards (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT NOT NULL CHECK (status IN ('todo', 'in_progress', 'done')),
            parent_id TEXT REFERENCES cards(id),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS blocked_by (
            card_id TEXT NOT NULL REFERENCES cards(id),
            blocks_on_id TEXT NOT NULL REFERENCES cards(id),
            PRIMARY KEY (card_id, blocks_on_id)
        )
        """
    )
    conn.commit()


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
