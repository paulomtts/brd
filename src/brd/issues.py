import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from brd import core, db, entities, refs
from brd.errors import (
    InvalidCloseReasonError,
    InvalidStatusError,
    IssueNotFoundError,
)

CLOSE_REASONS = ("resolved", "wontfix", "duplicate")
STATUSES = ("open", "closed")


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


def require(conn: sqlite3.Connection, project_id: str, issue_id: str) -> Issue:
    issue = get(conn, issue_id)
    if issue is None:
        raise IssueNotFoundError(f"no issue with id {issue_id}")
    entities.require_in_project(conn, project_id, issue_id)
    return issue


def list_issues(
    conn: sqlite3.Connection, project_id: str, status: str | None = None
) -> list[Issue]:
    if status is not None and status not in STATUSES:
        raise InvalidStatusError(
            f"invalid issue status {status!r}; use one of {', '.join(STATUSES)}"
        )
    query = f"SELECT issues.* FROM issues {db.in_project('issues.id')}"
    params = [project_id]
    if status is not None:
        query += " WHERE issues.status = ?"
        params.append(status)
    rows = conn.execute(query + " ORDER BY issues.created_at, issues.rowid", params).fetchall()
    return [_row(row) for row in rows]


def open_issue(
    conn: sqlite3.Connection,
    project_id: str,
    title: str,
    body: str | None = None,
    ref_ids: list[str] | None = None,
    blocks: list[str] | None = None,
) -> Issue:
    # De-duplicate (keeping order) so a repeated --ref/--blocks can't fail
    # on a unique constraint after the issue row is already committed.
    ref_ids = list(dict.fromkeys(ref_ids or []))
    blocks = list(dict.fromkeys(blocks or []))
    for ref_id in ref_ids:
        # Ref targets stay in the current project until S4 lifts the check.
        entities.require_in_project(conn, project_id, ref_id)
    for card_id in blocks:
        core.require_card(conn, project_id, card_id)
    now = _now()
    issue = Issue(str(uuid.uuid4()), title, body, "open", None, now, now)
    with conn:
        db.insert_entity(conn, project_id, issue.id, "issue")
        conn.execute(
            "INSERT INTO issues (id, title, body, status, close_reason, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (issue.id, issue.title, issue.body, issue.status, None, now, now),
        )
    for ref_id in ref_ids:
        refs.add_explicit(conn, project_id, issue.id, ref_id)
    for card_id in blocks:
        core.block_card(conn, project_id, card_id, issue.id)
    if body:
        refs.reindex(conn, issue.id)
    return issue


def _set(conn: sqlite3.Connection, project_id: str, issue_id: str, **fields) -> Issue:
    require(conn, project_id, issue_id)
    fields["updated_at"] = _now()
    columns = ", ".join(f"{key} = ?" for key in fields)
    conn.execute(f"UPDATE issues SET {columns} WHERE id = ?", [*fields.values(), issue_id])
    conn.commit()
    return require(conn, project_id, issue_id)


def update(
    conn: sqlite3.Connection,
    project_id: str,
    issue_id: str,
    title: str | None = None,
    body: str | None = None,
) -> Issue:
    fields = {key: value for key, value in (("title", title), ("body", body)) if value is not None}
    if not fields:
        return require(conn, project_id, issue_id)
    issue = _set(conn, project_id, issue_id, **fields)
    if body is not None:
        refs.reindex(conn, issue_id)
    return issue


def close(
    conn: sqlite3.Connection, project_id: str, issue_id: str, reason: str = "resolved"
) -> Issue:
    if reason not in CLOSE_REASONS:
        raise InvalidCloseReasonError(
            f"invalid close reason {reason!r}; use one of {', '.join(CLOSE_REASONS)}"
        )
    return _set(conn, project_id, issue_id, status="closed", close_reason=reason)


def reopen(conn: sqlite3.Connection, project_id: str, issue_id: str) -> Issue:
    return _set(conn, project_id, issue_id, status="open", close_reason=None)


def blocks_of(conn: sqlite3.Connection, issue_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT card_id FROM blocked_by WHERE blocks_on_id = ? ORDER BY card_id", (issue_id,)
    ).fetchall()
    return [row["card_id"] for row in rows]
