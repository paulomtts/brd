import re
import sqlite3

from brd import db, entities
from brd.errors import InvalidTagError, NotTaggableError

_TAG = re.compile(r"^[a-z0-9][a-z0-9_/-]*$")


def normalize(tag: str) -> str:
    normalized = tag.strip().removeprefix("#").lower()
    if not _TAG.match(normalized):
        raise InvalidTagError(
            f"invalid tag {tag!r}: use lowercase letters, digits, '-', '_' and '/'"
        )
    return normalized


def _require_taggable(conn: sqlite3.Connection, project_id: str, entity_id: str) -> None:
    # Ownership first: a foreign card is reported as foreign, not untaggable.
    entities.require_in_project(conn, project_id, entity_id)
    entities.require_capability(conn, entity_id, entities.TAGGABLE, NotTaggableError, "tagged")


def for_entity(conn: sqlite3.Connection, entity_id: str) -> list[str]:
    """Any entity's tags, unchecked: `brd show` is global."""
    rows = conn.execute(
        "SELECT tag FROM tags WHERE entity_id = ? ORDER BY tag", (entity_id,)
    ).fetchall()
    return [row["tag"] for row in rows]


def list_for(conn: sqlite3.Connection, project_id: str, entity_id: str) -> list[str]:
    entities.require_in_project(conn, project_id, entity_id)
    return for_entity(conn, entity_id)


def add(
    conn: sqlite3.Connection, project_id: str, entity_id: str, tag_list: list[str]
) -> list[str]:
    _require_taggable(conn, project_id, entity_id)
    normalized = [normalize(tag) for tag in tag_list]  # validate all before writing
    conn.executemany(
        "INSERT OR IGNORE INTO tags (entity_id, tag) VALUES (?, ?)",
        [(entity_id, tag) for tag in normalized],
    )
    conn.commit()
    return for_entity(conn, entity_id)


def remove(
    conn: sqlite3.Connection, project_id: str, entity_id: str, tag_list: list[str]
) -> list[str]:
    _require_taggable(conn, project_id, entity_id)
    normalized = [normalize(tag) for tag in tag_list]
    conn.executemany(
        "DELETE FROM tags WHERE entity_id = ? AND tag = ?",
        [(entity_id, tag) for tag in normalized],
    )
    conn.commit()
    return for_entity(conn, entity_id)


def counts(conn: sqlite3.Connection, project_id: str) -> list[dict]:
    rows = conn.execute(
        f"SELECT tags.tag, COUNT(*) AS count FROM tags {db.in_project('tags.entity_id')} "
        "GROUP BY tags.tag ORDER BY tags.tag",
        (project_id,),
    ).fetchall()
    return [{"tag": row["tag"], "count": row["count"]} for row in rows]
