import hashlib
import os
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from brd import db, entities, refs, tags
from brd.errors import (
    DocumentContentLostError,
    DocumentNotFoundError,
    DocumentSourceNotFoundError,
    DuplicatePathError,
    DuplicateStemError,
    NotMarkdownError,
    PathOutsideProjectError,
    RestoreConflictError,
)


@dataclass
class Document:
    id: str
    title: str
    source_path: str
    stem: str
    content_hash: str
    created_at: str
    updated_at: str


@dataclass
class SyncResult:
    content: str | None
    source_state: str  # ok | updated | missing | lost


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _decode(data: bytes) -> str:
    return data.decode("utf-8", "replace")


def backup_path(conn: sqlite3.Connection, doc_id: str) -> Path:
    return db.docs_dir(conn) / f"{doc_id}.md"


def _write_backup(conn: sqlite3.Connection, doc_id: str, data: bytes) -> None:
    target = backup_path(conn, doc_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _row(row: sqlite3.Row) -> Document:
    return Document(
        id=row["id"],
        title=row["title"],
        source_path=row["source_path"],
        stem=row["stem"],
        content_hash=row["content_hash"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def get(conn: sqlite3.Connection, doc_id: str) -> Document | None:
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    return _row(row) if row else None


def require(conn: sqlite3.Connection, doc_id: str) -> Document:
    doc = get(conn, doc_id)
    if doc is None:
        raise DocumentNotFoundError(f"no document with id {doc_id}")
    return doc


def list_all(conn: sqlite3.Connection) -> list[Document]:
    rows = conn.execute("SELECT * FROM documents ORDER BY created_at, source_path").fetchall()
    return [_row(row) for row in rows]


def _validate_path(root: Path, path: Path) -> tuple[str, str]:
    """Return (source_path relative to root in POSIX form, stem)."""
    resolved_root = root.resolve()
    candidate = (path if path.is_absolute() else Path.cwd() / path).resolve()
    if not candidate.is_relative_to(resolved_root):
        raise PathOutsideProjectError(f"{path} is outside the project root {resolved_root}")
    if candidate.suffix.lower() != ".md":
        raise NotMarkdownError(f"{path} is not a .md file")
    if not candidate.is_file():
        raise DocumentSourceNotFoundError(f"{path} does not exist")
    return candidate.relative_to(resolved_root).as_posix(), candidate.stem


def _check_unique(
    conn: sqlite3.Connection, rel: str, stem: str, exclude_id: str | None = None
) -> None:
    row = conn.execute(
        "SELECT id FROM documents WHERE source_path = ? AND id IS NOT ?", (rel, exclude_id)
    ).fetchone()
    if row:
        raise DuplicatePathError(f"{rel} is already registered as document {row['id']}")
    row = conn.execute(
        "SELECT source_path FROM documents WHERE stem = ? AND id IS NOT ?", (stem, exclude_id)
    ).fetchone()
    if row:
        raise DuplicateStemError(
            f"a document named {stem!r} is already registered ({row['source_path']}); "
            f"rename one of the files so [[{stem}]] stays unambiguous"
        )


def add(
    conn: sqlite3.Connection,
    project_id: str,
    root: Path,
    path: Path,
    title: str | None = None,
    tag_list: list[str] | None = None,
) -> Document:
    rel, stem = _validate_path(root, path)
    _check_unique(conn, rel, stem)
    normalized_tags = [tags.normalize(tag) for tag in tag_list or []]
    data = (root.resolve() / rel).read_bytes()
    now = _now()
    doc = Document(str(uuid.uuid4()), title or stem, rel, stem, _hash(data), now, now)
    _write_backup(conn, doc.id, data)
    conn.execute(
        "INSERT INTO documents (id, title, source_path, stem, content_hash, created_at, "
        "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (doc.id, doc.title, doc.source_path, doc.stem, doc.content_hash, doc.created_at, doc.updated_at),
    )
    conn.commit()
    if normalized_tags:
        tags.add(conn, doc.id, normalized_tags)
    refs.reindex(conn, doc.id)
    refs.reindex_mentions(conn, stem)
    return doc


def _source(root: Path, doc: Document) -> Path:
    """The document's source file, refusing any path that escapes the root."""
    resolved_root = root.resolve()
    source = resolved_root / doc.source_path
    if not source.resolve().is_relative_to(resolved_root):
        raise PathOutsideProjectError(
            f"{doc.source_path} is outside the project root {resolved_root}"
        )
    return source


def sync(conn: sqlite3.Connection, root: Path, doc: Document) -> SyncResult:
    """Bring the backup up to date with the source file. A differing hash
    always means the source advanced: the backup only changes by copying
    from the source."""
    source = _source(root, doc)
    backup = backup_path(conn, doc.id)
    if not source.is_file():
        if backup.is_file():
            return SyncResult(_decode(backup.read_bytes()), "missing")
        return SyncResult(None, "lost")
    data = source.read_bytes()
    digest = _hash(data)
    if digest == doc.content_hash and backup.is_file():
        return SyncResult(_decode(data), "ok")
    _write_backup(conn, doc.id, data)
    if digest != doc.content_hash:
        now = _now()
        conn.execute(
            "UPDATE documents SET content_hash = ?, updated_at = ? WHERE id = ?",
            (digest, now, doc.id),
        )
        conn.commit()
        doc.content_hash, doc.updated_at = digest, now
        refs.reindex(conn, doc.id)
    return SyncResult(_decode(data), "updated")


def sync_all(conn: sqlite3.Connection, root: Path) -> dict[str, SyncResult]:
    return {doc.id: sync(conn, root, doc) for doc in list_all(conn)}


def update(
    conn: sqlite3.Connection,
    root: Path,
    doc_id: str,
    new_path: Path | None = None,
    title: str | None = None,
) -> tuple[Document, SyncResult]:
    doc = require(conn, doc_id)
    old_stem = doc.stem
    if new_path is not None:
        rel, stem = _validate_path(root, new_path)
        _check_unique(conn, rel, stem, exclude_id=doc.id)
        conn.execute(
            "UPDATE documents SET source_path = ?, stem = ?, updated_at = ? WHERE id = ?",
            (rel, stem, _now(), doc.id),
        )
    if title is not None:
        conn.execute(
            "UPDATE documents SET title = ?, updated_at = ? WHERE id = ?",
            (title, _now(), doc.id),
        )
    conn.commit()
    doc = require(conn, doc_id)
    result = sync(conn, root, doc)
    if doc.stem.lower() != old_stem.lower():
        refs.reindex_mentions(conn, old_stem)
        refs.reindex_mentions(conn, doc.stem)
    return require(conn, doc_id), result


def restore(conn: sqlite3.Connection, root: Path, doc_id: str, force: bool = False) -> Document:
    doc = require(conn, doc_id)
    backup = backup_path(conn, doc.id)
    if not backup.is_file():
        raise DocumentContentLostError(f"no backup exists for document {doc_id}")
    source = _source(root, doc)
    if source.is_file():
        if _hash(source.read_bytes()) == doc.content_hash:
            return doc
        if not force:
            raise RestoreConflictError(
                f"{doc.source_path} exists and differs from brd's backup; "
                "pass --force to overwrite it"
            )
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(backup.read_bytes())
    return doc


def delete(conn: sqlite3.Connection, doc_id: str) -> None:
    require(conn, doc_id)
    entities.delete(conn, doc_id)
    backup_path(conn, doc_id).unlink(missing_ok=True)
