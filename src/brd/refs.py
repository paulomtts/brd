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


def resolve(conn: sqlite3.Connection, target: str) -> str | None:
    as_uuid = _as_uuid(target)
    if as_uuid is not None:
        return as_uuid if entities.kind_of(conn, as_uuid) else None
    row = conn.execute(
        "SELECT id FROM documents WHERE stem = ?", (normalize_stem(target),)
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
    texts = [own_text(conn, entity_id)] + [
        row["body"]
        for row in conn.execute("SELECT body FROM comments WHERE entity_id = ?", (entity_id,))
    ]
    targets: set[str] = set()
    for text in texts:
        for token in links.parse(text):
            dst = resolve(conn, token.target)
            if dst is not None and dst != entity_id:
                targets.add(dst)
    conn.execute("DELETE FROM refs WHERE src_id = ? AND origin = 'link'", (entity_id,))
    conn.executemany(
        "INSERT INTO refs (src_id, dst_id, origin) VALUES (?, ?, 'link')",
        [(entity_id, dst) for dst in sorted(targets)],
    )
    conn.commit()


def reindex_mentions(conn: sqlite3.Connection, stem: str) -> None:
    """Reindex every entity whose text mentions stem, so links written before
    a document existed (or under its old name) resolve now. Over-matching is
    harmless: reindex is idempotent."""
    pattern = "%" + stem.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    ids: set[str] = set()
    for query in (
        "SELECT id FROM cards WHERE description LIKE ? ESCAPE '\\'",
        "SELECT id FROM issues WHERE body LIKE ? ESCAPE '\\'",
        "SELECT entity_id AS id FROM comments WHERE body LIKE ? ESCAPE '\\'",
    ):
        ids.update(row["id"] for row in conn.execute(query, (pattern,)))
    needle = stem.lower()
    for row in conn.execute("SELECT id FROM documents").fetchall():
        if needle in _read_backup(conn, row["id"]).lower():
            ids.add(row["id"])
    for entity_id in sorted(ids):
        reindex(conn, entity_id)


def add_explicit(conn: sqlite3.Connection, src_id: str, dst_id: str) -> None:
    entities.require(conn, src_id)
    entities.require(conn, dst_id)
    if src_id == dst_id:
        raise SelfReferenceError(f"{src_id} can't reference itself")
    conn.execute(
        "INSERT OR IGNORE INTO refs (src_id, dst_id, origin) VALUES (?, ?, 'explicit')",
        (src_id, dst_id),
    )
    conn.commit()


def remove_explicit(conn: sqlite3.Connection, src_id: str, dst_id: str) -> None:
    entities.require(conn, src_id)
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
