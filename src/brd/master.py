import shutil
import sqlite3
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from brd import consolidate, db, paths
from brd.models import Project
from brd.errors import ProjectNotFoundError  # noqa: F401  (re-exported)

MARKER_FILENAME = ".brd"


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


def _copy_cards(conn: sqlite3.Connection, old_db_path: Path, project: Project) -> None:
    """Copy a legacy board's cards, and the edges between them, into brd.db
    under project, whose projects row is already there."""
    old_conn = db.connect(old_db_path)
    try:
        copied: set[str] = set()
        with conn:
            for row in old_conn.execute("SELECT * FROM cards"):
                db.insert_entity(conn, project.id, row["id"], "card")
                conn.execute(
                    "INSERT INTO cards (id, title, description, status, "
                    "parent_id, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    tuple(row),
                )
                copied.add(row["id"])
            for row in old_conn.execute("SELECT card_id, blocks_on_id FROM blocked_by"):
                # Same rule as _migrate_to_v1: keep only edges between copied
                # cards. Edge targets have no FK, so nothing else would stop one.
                if row["card_id"] in copied and row["blocks_on_id"] in copied:
                    conn.execute(
                        "INSERT INTO blocked_by (card_id, blocks_on_id) VALUES (?, ?)",
                        tuple(row),
                    )
    finally:
        old_conn.close()


def _migrate_in_repo_format(conn: sqlite3.Connection, marker_dir: Path, project: Project) -> None:
    """Migrate the in-repo format (.brd/ directory with board.db, committed
    to git) back to central storage."""
    old_db_path = marker_dir / "board.db"
    if old_db_path.is_file():
        _copy_cards(conn, old_db_path, project)
    shutil.rmtree(marker_dir)


def _migrate_legacy_uuid_marker(conn: sqlite3.Connection, marker_file: Path, project: Project) -> None:
    """Migrate the original design (.brd file holding a UUID, cards in a
    central per-project db keyed by that UUID)."""
    legacy_id = marker_file.read_text().strip()
    old_db_path = paths.data_dir() / "projects" / f"{legacy_id}.db"
    if legacy_id and old_db_path.is_file():
        _copy_cards(conn, old_db_path, project)


def init_project(root_path: Path, name: str | None = None) -> Project:
    marker = root_path / MARKER_FILENAME
    conn = connect()
    try:
        # A root that is already registered keeps its id and created_at;
        # only the name changes.
        project = db.upsert_project(
            conn,
            Project(
                id=db.new_project_id(),
                name=name or root_path.name,
                root_path=str(root_path),
                created_at=_now(),
            ),
        )
        if marker.is_dir():
            _migrate_in_repo_format(conn, marker, project)
        elif marker.is_file():
            _migrate_legacy_uuid_marker(conn, marker, project)
    finally:
        conn.close()

    marker.write_text("")

    gitignore = root_path / ".gitignore"
    existing_lines = gitignore.read_text().splitlines() if gitignore.exists() else []
    if MARKER_FILENAME not in existing_lines:
        with gitignore.open("a") as f:
            if existing_lines and existing_lines[-1] != "":
                f.write("\n")
            f.write(f"{MARKER_FILENAME}\n")

    return project


def find_marker(start: Path) -> Path | None:
    current = start.resolve()
    while True:
        candidate = current / MARKER_FILENAME
        if candidate.is_file():
            return candidate
        if current.parent == current:
            return None
        current = current.parent


def resolve_project_root(start: Path) -> Path:
    marker = find_marker(start)
    if marker is None:
        raise ProjectNotFoundError(f"no {MARKER_FILENAME} marker found above {start}")
    return marker.parent


def registered_project(conn: sqlite3.Connection, root_path: Path) -> Project:
    project = db.get_project(conn, str(root_path))
    if project is None:
        raise ProjectNotFoundError(
            f"{root_path} has a {MARKER_FILENAME} marker but is not a registered "
            "project; run `brd init` there"
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
        db.delete_project(conn, str(root_path))
    finally:
        conn.close()

    for doc_id in doc_ids:
        (paths.docs_dir() / f"{doc_id}.md").unlink(missing_ok=True)

    marker = root_path / MARKER_FILENAME
    if marker.is_file():
        marker.unlink()

    return project


def _count_projects(db_path: Path, min_version: int) -> int | None:
    conn = db.connect(db_path)
    try:
        if _version(conn) < min_version:
            return None
        has_table = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'projects'"
        ).fetchone()[0]
        if not has_table:
            return 0
        return conn.execute("SELECT COUNT(DISTINCT root_path) FROM projects").fetchone()[0]
    finally:
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
        return _count_projects(paths.master_db_path(), 0)
    return 0


def purge_all() -> int:
    count = registry_count()
    shutil.rmtree(paths.data_dir())
    return count
