import dataclasses
import sqlite3
from pathlib import Path, PurePosixPath

from brd import core, db, documents, entities, issues, refs
from brd.errors import EntityAlreadyExistsError, ImportFormatError

FORMAT_VERSION = 1


def export(conn: sqlite3.Connection, project_id: str, root: Path) -> dict:
    results = documents.sync_all(conn, root)
    return {
        "brd_export": FORMAT_VERSION,
        "cards": core.build_tree(conn, project_id),
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


def load(conn: sqlite3.Connection, project_id: str, root: Path, raw) -> dict:
    try:
        return _load(conn, project_id, raw)
    except (KeyError, TypeError, AttributeError, sqlite3.ProgrammingError) as exc:
        # Missing keys or wrong value types in the snapshot. Any backups the
        # import wrote were already cleaned up by the time this is caught.
        raise ImportFormatError(f"malformed snapshot: {type(exc).__name__}: {exc}") from exc


def _load(conn: sqlite3.Connection, project_id: str, raw) -> dict:
    # `brd export > file` writes the whole envelope; accept it unwrapped too.
    if isinstance(raw, dict) and isinstance(raw.get("data"), dict):
        raw = raw["data"]
    if isinstance(raw, dict) and "brd_export" in raw:
        if raw["brd_export"] != FORMAT_VERSION:
            raise ImportFormatError(f"unsupported brd_export version {raw['brd_export']!r}")
        return _load_export(conn, project_id, raw)
    nodes = raw["data"] if isinstance(raw, dict) and "data" in raw else raw
    if not isinstance(nodes, list):
        raise ImportFormatError("expected a `brd export` object or a `brd tree` snapshot list")
    return {"imported": core.import_tree(conn, project_id, nodes)}


def _check_source_path(source_path) -> None:
    """A snapshot's source_path must stay inside the project: `doc restore`
    writes to it and sync/export read from it."""
    if not isinstance(source_path, str):
        raise ImportFormatError(f"document source_path must be a string, got {source_path!r}")
    path = PurePosixPath(source_path)
    if path.is_absolute() or ".." in path.parts or path.suffix.lower() != ".md":
        raise ImportFormatError(
            f"document source_path {source_path!r} must be a relative .md path "
            "inside the project"
        )


def _load_export(conn: sqlite3.Connection, project_id: str, snap: dict) -> dict:
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
        _check_source_path(doc["source_path"])
    for doc in doc_rows:
        documents._check_unique(conn, doc["source_path"], PurePosixPath(doc["source_path"]).stem)

    snapshot_ids = set(entity_ids)
    for node, _ in flattened:
        for blocker_id in node.get("blocked_by", []):
            core._require_import_target(conn, snapshot_ids, blocker_id, "blocker")
    for r in snap.get("refs", []):
        if r.get("origin", "explicit") == "explicit":
            core._require_import_target(conn, snapshot_ids, r["dst_id"], "ref target")

    contents = {
        d["id"]: d["content"].encode("utf-8") for d in doc_rows if d.get("content") is not None
    }
    # Write backups before touching the DB, so a DB failure never leaves a
    # document row with no backup: if the transaction below fails, we delete
    # exactly the backups we just wrote.
    for doc_id, data in contents.items():
        documents._write_backup(conn, doc_id, data)
    try:
        with conn:  # one transaction: commits on success, rolls back on error
            for node, parent_id in flattened:
                status = "todo" if node["status"] == "blocked" else node["status"]
                db.insert_entity(conn, project_id, node["id"], "card")
                conn.execute(
                    "INSERT INTO cards (id, title, description, status, parent_id, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (node["id"], node["title"], node.get("description"), status,
                     parent_id, node["created_at"], node["updated_at"]),
                )
            for i in issue_rows:
                db.insert_entity(conn, project_id, i["id"], "issue")
                conn.execute(
                    "INSERT INTO issues (id, title, body, status, close_reason, created_at, "
                    "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (i["id"], i["title"], i.get("body"), i["status"], i.get("close_reason"),
                     i["created_at"], i["updated_at"]),
                )
            for d in doc_rows:
                digest = documents._hash(contents[d["id"]]) if d["id"] in contents else d["content_hash"]
                db.insert_entity(conn, project_id, d["id"], "document")
                conn.execute(
                    "INSERT INTO documents (id, project_id, title, source_path, stem, "
                    "content_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (d["id"], project_id, d["title"], d["source_path"],
                     PurePosixPath(d["source_path"]).stem, digest, d["created_at"],
                     d["updated_at"]),
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
    except BaseException as exc:
        for doc_id in contents:
            documents.backup_path(conn, doc_id).unlink(missing_ok=True)
        if isinstance(exc, sqlite3.IntegrityError):
            raise ImportFormatError(f"snapshot is internally inconsistent: {exc}") from exc
        raise

    for entity_id in entity_ids:
        refs.reindex(conn, entity_id)
    return {
        "imported": len(entity_ids),
        "cards": len(flattened),
        "issues": len(issue_rows),
        "documents": len(doc_rows),
        "comments": len(comment_rows),
    }
