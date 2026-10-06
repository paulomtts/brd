import os
import shutil
import sqlite3
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from brd import consolidate, db, paths
from brd.models import Project
from brd.errors import ProjectNotFoundError  # noqa: F401  (re-exported)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_stderr(text: str) -> None:
    # Looked up at call time, so test runners that swap sys.stderr see it.
    print(text, file=sys.stderr)


def _version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def connect(notify: Callable[[str], None] = _to_stderr) -> sqlite3.Connection:
    """The brd.db connection every data command uses. An install that is not
    migrated yet is set up first: from master.db and the legacy boards when
    master.db exists (notify gets the one-time notice), else empty."""
    conn = db.connect(paths.brd_db_path())
    try:
        if _version(conn) < db.SCHEMA_VERSION:
            report = _set_up(conn)
            if report is not None:
                consolidate.retire(report.retired)
                notify(report.notice())
    except BaseException:
        conn.close()
        raise
    return conn


def _set_up(conn: sqlite3.Connection) -> consolidate.Report | None:
    """Migrate or create brd.db under its write lock; the report when this
    call migrated, None when it created an empty one or found it done."""
    conn.commit()
    # Must be issued outside a transaction; SQLite ignores it inside one.
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        # IMMEDIATE takes the write lock up front: a concurrent first run
        # waits here on the busy timeout, then finds the work already done.
        conn.execute("BEGIN IMMEDIATE")
        if _version(conn) >= db.SCHEMA_VERSION:
            conn.rollback()
            return None
        if paths.master_db_path().is_file():
            return consolidate.migrate(conn)
        db.init_brd_schema(conn)
        conn.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION}")
        conn.commit()
        return None
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def init_project(root_path: Path, name: str | None = None) -> Project:
    """Register root_path in brd.db. Writes nothing under root_path."""
    conn = connect()
    try:
        # A root that is already registered keeps its id and created_at;
        # only the name changes.
        return db.upsert_project(
            conn,
            Project(
                id=db.new_project_id(),
                name=name or root_path.name,
                root_path=str(root_path),
                created_at=_now(),
            ),
        )
    finally:
        conn.close()


def resolve_project(conn: sqlite3.Connection, start: Path) -> Project:
    """The registered project whose root is start or its deepest ancestor."""
    resolved = start.resolve()
    project = db.deepest_project(conn, [str(p) for p in (resolved, *resolved.parents)])
    if project is None:
        raise ProjectNotFoundError(
            f"no registered project at or above {resolved}; run `brd init` there"
        )
    return project


def relink_project(root_path: Path, ref: str, name: str | None = None) -> Project:
    """Point the project whose id or old root is ref at root_path, e.g. after
    the repo moved. Its id, created_at and board stay; the name changes only
    when name is given."""
    conn = connect()
    try:
        # IMMEDIATE takes the write lock up front, so the lookup and the
        # update see one state of projects.
        conn.execute("BEGIN IMMEDIATE")
        try:
            project = _find_relink_target(conn, root_path, ref)
            relinked = db.relink_project(conn, project.id, str(root_path), name or None)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        return relinked
    finally:
        conn.close()


def _find_relink_target(conn: sqlite3.Connection, root_path: Path, ref: str) -> Project:
    project = db.get_project_by_id(conn, ref)
    # An empty ref would normalise to root_path itself.
    if project is None and ref:
        # Not resolve(): the old directory is usually gone, and stored roots
        # do not follow symlinks either.
        old_root = os.path.normpath(os.path.join(root_path, ref))
        project = db.get_project(conn, old_root)
    if project is None:
        raise ProjectNotFoundError(
            f"no project with id or root path {ref}; see `brd projects`"
        )
    return project


def list_all_projects() -> list[Project]:
    conn = connect()
    try:
        return db.list_projects(conn)
    finally:
        conn.close()


def forget_project(root_path: Path) -> Project:
    conn = connect()
    try:
        project = db.get_project(conn, str(root_path))
        if project is None:
            raise ProjectNotFoundError(f"no registered project at {root_path}")
        # Read before the delete: the cascade through entities removes them.
        doc_ids = [
            row["id"]
            for row in conn.execute(
                "SELECT id FROM entities WHERE project_id = ? AND kind = 'document'",
                (project.id,),
            )
        ]
        db.delete_project(conn, project.id)
    finally:
        conn.close()

    for doc_id in doc_ids:
        (paths.docs_dir() / f"{doc_id}.md").unlink(missing_ok=True)

    return project


def _count_projects(db_path: Path, min_version: int) -> int | None:
    """None when the file is not at min_version or cannot be read at all."""
    conn = None
    try:
        conn = db.connect(db_path)
        if _version(conn) < min_version:
            return None
        has_table = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'projects'"
        ).fetchone()[0]
        if not has_table:
            return 0
        return conn.execute("SELECT COUNT(DISTINCT root_path) FROM projects").fetchone()[0]
    except sqlite3.DatabaseError:
        # Unreadable: purge must still be able to remove it.
        return None
    finally:
        if conn is not None:
            conn.close()


def registry_count() -> int:
    """How many projects are registered, read without migrating: purge is the
    way out when a migration aborts. brd.db once migrated, else master.db,
    else 0."""
    if paths.brd_db_path().is_file():
        count = _count_projects(paths.brd_db_path(), db.SCHEMA_VERSION)
        if count is not None:
            return count
    if paths.master_db_path().is_file():
        return _count_projects(paths.master_db_path(), 0) or 0
    return 0


def purge_all() -> int:
    count = registry_count()
    shutil.rmtree(paths.data_dir())
    return count
