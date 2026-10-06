import getpass
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from brd import core, entities, refs
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
    kind = entities.require_capability(
        conn, entity_id, entities.COMMENTABLE, NotCommentableError, "commented on"
    )
    if kind == "card":
        # Only cards are scoped to the current project so far; issues follow.
        core.require_card(conn, project_id, entity_id)
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
