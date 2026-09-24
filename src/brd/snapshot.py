import dataclasses
import sqlite3
from pathlib import Path, PurePosixPath

from brd import core, documents, entities, issues, refs
from brd.errors import EntityAlreadyExistsError, ImportFormatError

FORMAT_VERSION = 1


def export(conn: sqlite3.Connection, root: Path) -> dict:
    results = documents.sync_all(conn, root)
    return {
        "brd_export": FORMAT_VERSION,
        "cards": core.build_tree(conn),
        "issues": [dataclasses.asdict(i) for i in issues.list_issues(conn)],
        "documents": [
            {
                "id": d.id,
                "title": d.title,
                "source_path": d.source_path,
                "content": results[d.id].content,
                "content_hash": d.content_hash,
                "created_at": d.created_at,
                "updated_at": d.updated_at,
            }
            for d in documents.list_all(conn)
        ],
        "comments": [
            dict(row)
            for row in conn.execute(
                "SELECT id, entity_id, author, body, created_at FROM comments "
                "ORDER BY created_at, rowid"
            )
        ],
        "tags": [
            dict(row)
            for row in conn.execute("SELECT entity_id, tag FROM tags ORDER BY entity_id, tag")
        ],
        "refs": [
            dict(row)
            for row in conn.execute(
                "SELECT src_id, dst_id, origin FROM refs WHERE origin = 'explicit' "
                "ORDER BY src_id, dst_id"
            )
        ],
    }


def load(conn: sqlite3.Connection, root: Path, raw) -> dict:
    # `brd export > file` writes the whole envelope; accept it unwrapped too.
    if isinstance(raw, dict) and isinstance(raw.get("data"), dict):
        raw = raw["data"]
    if isinstance(raw, dict) and "brd_export" in raw:
        if raw["brd_export"] != FORMAT_VERSION:
            raise ImportFormatError(f"unsupported brd_export version {raw['brd_export']!r}")
        return _load_export(conn, raw)
    nodes = raw["data"] if isinstance(raw, dict) and "data" in raw else raw
    if not isinstance(nodes, list):
        raise ImportFormatError("expected a `brd export` object or a `brd tree` snapshot list")
    return {"imported": core.import_tree(conn, nodes)}


def _load_export(conn: sqlite3.Connection, snap: dict) -> dict:
    flattened = core._flatten_tree(snap.get("cards", []))
    issue_rows = snap.get("issues", [])
    doc_rows = snap.get("documents", [])
    comment_rows = snap.get("comments", [])

    entity_ids = (
        [node["id"] for node, _ in flattened]
        + [i["id"] for i in issue_rows]
        + [d["id"] for d in doc_rows]
    )
    if len(set(entity_ids)) != len(entity_ids):
        raise ImportFormatError("snapshot contains duplicate ids")
    for entity_id in entity_ids:
        if entities.kind_of(conn, entity_id) is not None:
            raise EntityAlreadyExistsError(f"entity {entity_id} already exists in this board")
    for comment in comment_rows:
        if conn.execute("SELECT 1 FROM comments WHERE id = ?", (comment["id"],)).fetchone():
            raise EntityAlreadyExistsError(f"comment {comment['id']} already exists in this board")
    for doc in doc_rows:
        documents._check_unique(conn, doc["source_path"], PurePosixPath(doc["source_path"]).stem)

    contents = {
        d["id"]: d["content"].encode("utf-8") for d in doc_rows if d.get("content") is not None
    }
    try:
        with conn:  # one transaction: commits on success, rolls back on error
            for node, parent_id in flattened:
                status = "todo" if node["status"] == "blocked" else node["status"]
                conn.execute(
                    "INSERT INTO cards (id, title, description, status, parent_id, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (node["id"], node["title"], node.get("description"), status,
                     parent_id, node["created_at"], node["updated_at"]),
                )
            for i in issue_rows:
                conn.execute(
                    "INSERT INTO issues (id, title, body, status, close_reason, created_at, "
                    "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (i["id"], i["title"], i.get("body"), i["status"], i.get("close_reason"),
                     i["created_at"], i["updated_at"]),
                )
            for d in doc_rows:
                digest = documents._hash(contents[d["id"]]) if d["id"] in contents else d["content_hash"]
                conn.execute(
                    "INSERT INTO documents (id, title, source_path, stem, content_hash, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (d["id"], d["title"], d["source_path"], PurePosixPath(d["source_path"]).stem,
                     digest, d["created_at"], d["updated_at"]),
                )
            for node, _ in flattened:
                for blocker_id in node.get("blocked_by", []):
                    conn.execute(
                        "INSERT INTO blocked_by (card_id, blocks_on_id) VALUES (?, ?)",
                        (node["id"], blocker_id),
                    )
            for c in comment_rows:
                conn.execute(
                    "INSERT INTO comments (id, entity_id, author, body, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (c["id"], c["entity_id"], c["author"], c["body"], c["created_at"]),
                )
            for t in snap.get("tags", []):
                conn.execute(
                    "INSERT INTO tags (entity_id, tag) VALUES (?, ?)", (t["entity_id"], t["tag"])
                )
            for r in snap.get("refs", []):
                if r.get("origin", "explicit") == "explicit":
                    conn.execute(
                        "INSERT INTO refs (src_id, dst_id, origin) VALUES (?, ?, 'explicit')",
                        (r["src_id"], r["dst_id"]),
                    )
    except sqlite3.IntegrityError as exc:
        raise ImportFormatError(f"snapshot is internally inconsistent: {exc}") from exc

    for doc_id, data in contents.items():
        documents._write_backup(conn, doc_id, data)
    for entity_id in entity_ids:
        refs.reindex(conn, entity_id)
    return {
        "imported": len(entity_ids),
        "cards": len(flattened),
        "issues": len(issue_rows),
        "documents": len(doc_rows),
        "comments": len(comment_rows),
    }
