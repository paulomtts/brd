import sqlite3

from brd import db
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
    db.delete_incoming_edges(conn, entity_id)
    conn.execute("DELETE FROM entities WHERE id = ?", (entity_id,))
    conn.commit()
