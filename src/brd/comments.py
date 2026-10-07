import getpass
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from brd import db, entities, refs
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


def add(
    conn: sqlite3.Connection, project_id: str, entity_id: str, body: str, author: str
) -> Comment:
    # Ownership first: a foreign document is reported as foreign, not
    # uncommentable, and a foreign issue's empty comment as foreign.
    entities.require_in_project(conn, project_id, entity_id)
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


def for_entity(conn: sqlite3.Connection, entity_id: str) -> list[Comment]:
    """Any entity's comments, unchecked: `brd show` is global."""
    rows = conn.execute(
        "SELECT * FROM comments WHERE entity_id = ? ORDER BY created_at, rowid",
        (entity_id,),
    ).fetchall()
    return [_row(row) for row in rows]


def list_for(conn: sqlite3.Connection, project_id: str, entity_id: str) -> list[Comment]:
    entities.require_in_project(conn, project_id, entity_id)
    return for_entity(conn, entity_id)


def delete(conn: sqlite3.Connection, project_id: str, comment_id: str) -> Comment:
    row = conn.execute("SELECT * FROM comments WHERE id = ?", (comment_id,)).fetchone()
    if row is None:
        raise CommentNotFoundError(f"no comment with id {comment_id}")
    comment = _row(row)
    owner = db.owner_of(conn, comment.entity_id)
    if owner is not None and owner.id != project_id:
        raise CommentNotFoundError(entities.foreign_message("comment", comment_id, owner))
    conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
    conn.commit()
    refs.reindex(conn, comment.entity_id)
    return comment
