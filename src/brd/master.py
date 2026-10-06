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


def _master_conn():
    conn = db.connect(paths.master_db_path())
    db.init_master_schema(conn)
    return conn


def _copy_cards(old_db_path: Path, new_db_path: Path, project: Project) -> None:
    old_conn = db.connect(old_db_path)
    new_conn = db.connect(new_db_path)
    try:
        db.init_project_schema(new_conn, project)
        copied: set[str] = set()
        for row in old_conn.execute("SELECT * FROM cards"):
            db.insert_entity(new_conn, project.id, row["id"], "card")
            new_conn.execute(
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
                new_conn.execute(
                    "INSERT INTO blocked_by (card_id, blocks_on_id) VALUES (?, ?)",
                    tuple(row),
                )
        new_conn.commit()
    finally:
        old_conn.close()
        new_conn.close()


def _migrate_in_repo_format(marker_dir: Path, new_db_path: Path, project: Project) -> None:
    """Migrate the in-repo format (.brd/ directory with board.db, committed
    to git) back to central storage."""
    old_db_path = marker_dir / "board.db"
    if old_db_path.is_file():
        _copy_cards(old_db_path, new_db_path, project)
    shutil.rmtree(marker_dir)


def _migrate_legacy_uuid_marker(marker_file: Path, new_db_path: Path, project: Project) -> None:
    """Migrate the original design (.brd file holding a UUID, cards in a
    central per-project db keyed by that UUID)."""
    legacy_id = marker_file.read_text().strip()
    old_db_path = paths.data_dir() / "projects" / f"{legacy_id}.db"
    if old_db_path.is_file() and old_db_path != new_db_path:
        _copy_cards(old_db_path, new_db_path, project)


def _board_project(db_path: Path) -> Project | None:
    """The project a board file records, when it records exactly one."""
    if not db_path.is_file():
        return None
    conn = db.connect(db_path)
    try:
        rows = db.board_projects(conn)
    finally:
        conn.close()
    return rows[0] if len(rows) == 1 else None


def _settle_project(root_path: Path, name: str | None) -> Project:
    """The project this root is, settled before any board file is touched so
    the board and the registry agree on its id: the registered row, else the
    one project the board already records, else a new project."""
    project_name = name or root_path.name
    conn = _master_conn()
    try:
        stored = db.get_project(conn, str(root_path))
    finally:
        conn.close()
    known = stored or _board_project(paths.project_db_path(root_path))
    if known is not None:
        return Project(
            id=known.id,
            name=project_name,
            root_path=str(root_path),
            created_at=known.created_at,
        )
    return Project(
        id=db.new_project_id(),
        name=project_name,
        root_path=str(root_path),
        created_at=_now(),
    )


def init_project(root_path: Path, name: str | None = None) -> Project:
    project = _settle_project(root_path, name)
    marker = root_path / MARKER_FILENAME
    db_path = paths.project_db_path(root_path)

    if marker.is_dir():
        _migrate_in_repo_format(marker, db_path, project)
    elif marker.is_file():
        _migrate_legacy_uuid_marker(marker, db_path, project)

    project_conn = db.connect(db_path)
    try:
        db.init_project_schema(project_conn, project)
    finally:
        project_conn.close()

    marker.write_text("")

    gitignore = root_path / ".gitignore"
    existing_lines = gitignore.read_text().splitlines() if gitignore.exists() else []
    if MARKER_FILENAME not in existing_lines:
        with gitignore.open("a") as f:
            if existing_lines and existing_lines[-1] != "":
                f.write("\n")
            f.write(f"{MARKER_FILENAME}\n")

    conn = _master_conn()
    try:
        return db.upsert_project(conn, project)
    finally:
        conn.close()


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


def registered_project(root_path: Path) -> Project:
    conn = _master_conn()
    try:
        project = db.get_project(conn, str(root_path))
    finally:
        conn.close()
    if project is None:
        raise ProjectNotFoundError(
            f"{root_path} has a {MARKER_FILENAME} marker but is not a registered "
            "project; run `brd init` there"
        )
    return project


def resolve_project_db(start: Path) -> Path:
    return paths.project_db_path(resolve_project_root(start))


def list_all_projects() -> list[Project]:
    conn = _master_conn()
    try:
        return db.list_projects(conn)
    finally:
        conn.close()


def forget_project(root_path: Path) -> Project:
    conn = _master_conn()
    try:
        project = db.get_project(conn, str(root_path))
        if project is None:
            raise ProjectNotFoundError(f"no registered project at {root_path}")
        db.delete_project(conn, str(root_path))
    finally:
        conn.close()

    db_path = paths.project_db_path(root_path)
    if db_path.is_file():
        db_path.unlink()

    docs_dir = paths.project_docs_dir(root_path)
    if docs_dir.is_dir():
        shutil.rmtree(docs_dir)

    marker = root_path / MARKER_FILENAME
    if marker.is_file():
        marker.unlink()

    return project


def purge_all() -> int:
    conn = _master_conn()
    try:
        count = len(db.list_projects(conn))
    finally:
        conn.close()
    shutil.rmtree(paths.data_dir())
    return count
