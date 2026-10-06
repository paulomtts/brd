import sqlite3
import uuid

from brd import db, entities, links
from brd.errors import SelfReferenceError


def normalize_stem(target: str) -> str:
    name = target.rsplit("/", 1)[-1]
    if name.lower().endswith(".md"):
        name = name[:-3]
    return name.strip()


def _as_uuid(target: str) -> str | None:
    try:
        return str(uuid.UUID(target))
    except ValueError:
        return None


def resolve(conn: sqlite3.Connection, project_id: str | None, target: str) -> str | None:
    """A [[<uuid>]] target is any entity on the board; a [[stem]] target is
    a document of project_id only."""
    as_uuid = _as_uuid(target)
    if as_uuid is not None:
        return as_uuid if entities.kind_of(conn, as_uuid) else None
    row = conn.execute(
        f"SELECT documents.id FROM documents {db.in_project('documents.id')} "
        "WHERE documents.stem = ?",
        (project_id, normalize_stem(target)),
    ).fetchone()  # stem is COLLATE NOCASE
    return row["id"] if row else None


def _read_backup(conn: sqlite3.Connection, doc_id: str) -> str:
    path = db.docs_dir(conn) / f"{doc_id}.md"
    return path.read_bytes().decode("utf-8", "replace") if path.is_file() else ""


def own_text(conn: sqlite3.Connection, entity_id: str) -> str:
    kind = entities.kind_of(conn, entity_id)
    if kind == "card":
        row = conn.execute("SELECT description FROM cards WHERE id = ?", (entity_id,)).fetchone()
        return row["description"] or ""
    if kind == "issue":
        row = conn.execute("SELECT body FROM issues WHERE id = ?", (entity_id,)).fetchone()
        return row["body"] or ""
    if kind == "document":
        return _read_backup(conn, entity_id)
    return ""


def reindex(conn: sqlite3.Connection, entity_id: str) -> None:
    """Rebuild entity_id's origin='link' refs from its own text plus the
    bodies of its comments. Explicit refs are never touched."""
    owner = conn.execute(
        "SELECT project_id FROM entities WHERE id = ?", (entity_id,)
    ).fetchone()
    # Stems resolve within the project owning the text; an unknown entity
    # has none, so its stems resolve to nothing.
    project_id = owner["project_id"] if owner else None
    texts = [own_text(conn, entity_id)] + [
        row["body"]
        for row in conn.execute("SELECT body FROM comments WHERE entity_id = ?", (entity_id,))
    ]
    targets: set[str] = set()
    for text in texts:
        for token in links.parse(text):
            dst = resolve(conn, project_id, token.target)
            if dst is not None and dst != entity_id:
                targets.add(dst)
    conn.execute("DELETE FROM refs WHERE src_id = ? AND origin = 'link'", (entity_id,))
    conn.executemany(
        "INSERT INTO refs (src_id, dst_id, origin) VALUES (?, ?, 'link')",
        [(entity_id, dst) for dst in sorted(targets)],
    )
    conn.commit()


def reindex_mentions(conn: sqlite3.Connection, project_id: str, stem: str) -> None:
    """Reindex every entity of project_id whose text mentions stem, so links
    written before a document existed (or under its old name) resolve now.
    Other projects' texts can't link to this project's stems. Over-matching
    is harmless: reindex is idempotent."""
    pattern = "%" + stem.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    ids: set[str] = set()
    for query in (
        f"SELECT cards.id FROM cards {db.in_project('cards.id')} "
        "WHERE cards.description LIKE ? ESCAPE '\\'",
        f"SELECT issues.id FROM issues {db.in_project('issues.id')} "
        "WHERE issues.body LIKE ? ESCAPE '\\'",
        f"SELECT comments.entity_id AS id FROM comments {db.in_project('comments.entity_id')} "
        "WHERE comments.body LIKE ? ESCAPE '\\'",
    ):
        ids.update(row["id"] for row in conn.execute(query, (project_id, pattern)))
    needle = stem.lower()
    for row in conn.execute(
        f"SELECT documents.id FROM documents {db.in_project('documents.id')}", (project_id,)
    ).fetchall():
        if needle in _read_backup(conn, row["id"]).lower():
            ids.add(row["id"])
    for entity_id in sorted(ids):
        reindex(conn, entity_id)


def add_explicit(conn: sqlite3.Connection, project_id: str, src_id: str, dst_id: str) -> None:
    entities.require_in_project(conn, project_id, src_id)
    # Ref targets stay in the current project until S4 lifts the check.
    entities.require_in_project(conn, project_id, dst_id)
    if src_id == dst_id:
        raise SelfReferenceError(f"{src_id} can't reference itself")
    conn.execute(
        "INSERT OR IGNORE INTO refs (src_id, dst_id, origin) VALUES (?, ?, 'explicit')",
        (src_id, dst_id),
    )
    conn.commit()


def remove_explicit(conn: sqlite3.Connection, project_id: str, src_id: str, dst_id: str) -> None:
    # Only the source is checked: like `unblock --by`, an edge to another
    # project's entity can still be removed.
    entities.require_in_project(conn, project_id, src_id)
    conn.execute(
        "DELETE FROM refs WHERE src_id = ? AND dst_id = ? AND origin = 'explicit'",
        (src_id, dst_id),
    )
    conn.commit()


def _summaries(conn: sqlite3.Connection, rows, column: str) -> list[dict]:
    return [{**entities.summary(conn, row[column]), "origin": row["origin"]} for row in rows]


def outgoing(conn: sqlite3.Connection, entity_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT dst_id, origin FROM refs WHERE src_id = ? ORDER BY origin, dst_id",
        (entity_id,),
    ).fetchall()
    return _summaries(conn, rows, "dst_id")


def incoming(conn: sqlite3.Connection, entity_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT src_id, origin FROM refs WHERE dst_id = ? ORDER BY origin, src_id",
        (entity_id,),
    ).fetchall()
    return _summaries(conn, rows, "src_id")
