import sqlite3
from pathlib import Path

from brd.models import Card, Project


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_master_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            root_path TEXT NOT NULL,
            db_path TEXT NOT NULL,
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
        id=row["id"],
        name=row["name"],
        root_path=row["root_path"],
        db_path=row["db_path"],
        created_at=row["created_at"],
    )


def insert_project(conn: sqlite3.Connection, project: Project) -> None:
    conn.execute(
        "INSERT INTO projects (id, name, root_path, db_path, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            project.id,
            project.name,
            project.root_path,
            project.db_path,
            project.created_at,
        ),
    )
    conn.commit()


def get_project_by_id(conn: sqlite3.Connection, project_id: str) -> Project | None:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return _row_to_project(row) if row else None


def get_project_by_name(conn: sqlite3.Connection, name: str) -> Project | None:
    row = conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
    return _row_to_project(row) if row else None


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
