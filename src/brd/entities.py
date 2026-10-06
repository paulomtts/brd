import sqlite3

from brd import db
from brd.errors import (
    BrdError,
    CardNotFoundError,
    DocumentNotFoundError,
    EntityNotFoundError,
    IssueNotFoundError,
)
from brd.models import Project

# Which kinds support which shared feature. Enabling a feature for another
# kind is a one-word change here.
COMMENTABLE = frozenset({"card", "issue"})
TAGGABLE = frozenset({"document"})
BLOCKERS = frozenset({"card", "issue"})
REF_SOURCES = frozenset({"card", "issue", "document"})

_KIND_TABLES = {"card": "cards", "issue": "issues", "document": "documents"}

_NOT_FOUND = {
    "card": CardNotFoundError,
    "issue": IssueNotFoundError,
    "document": DocumentNotFoundError,
}


def kind_of(conn: sqlite3.Connection, entity_id: str) -> str | None:
    row = conn.execute("SELECT kind FROM entities WHERE id = ?", (entity_id,)).fetchone()
    return row["kind"] if row else None


def require(conn: sqlite3.Connection, entity_id: str) -> str:
    kind = kind_of(conn, entity_id)
    if kind is None:
        raise EntityNotFoundError(f"no entity with id {entity_id}")
    return kind


def foreign_message(what: str, item_id: str, owner: Project) -> str:
    return (
        f"no {what} with id {item_id} in this project; "
        f"it belongs to project {owner.name} ({owner.id})"
    )


def require_in_project(conn: sqlite3.Connection, project_id: str, entity_id: str) -> str:
    """The entity's kind, refusing one another project owns. Commands act on
    the current project only; the error names the owner, so an id copied
    from another project's board says where it lives."""
    kind = require(conn, entity_id)
    owner = db.owner_of(conn, entity_id)
    if owner is not None and owner.id != project_id:
        raise _NOT_FOUND[kind](foreign_message(kind, entity_id, owner))
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
