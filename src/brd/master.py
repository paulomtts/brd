import shutil
from datetime import datetime, timezone
from pathlib import Path

from brd import db, paths
from brd.models import Project
from brd.errors import ProjectNotFoundError  # noqa: F401  (re-exported)

MARKER_FILENAME = ".brd"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _master_conn():
    conn = db.connect(paths.master_db_path())
    db.init_master_schema(conn)
    return conn


def _copy_cards(old_db_path: Path, new_db_path: Path) -> None:
    old_conn = db.connect(old_db_path)
    new_conn = db.connect(new_db_path)
    try:
        db.init_project_schema(new_conn)
        for row in old_conn.execute("SELECT * FROM cards"):
            new_conn.execute(
                "INSERT INTO cards (id, title, description, status, "
                "parent_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                tuple(row),
            )
        for row in old_conn.execute("SELECT * FROM blocked_by"):
            new_conn.execute(
                "INSERT INTO blocked_by (card_id, blocks_on_id) VALUES (?, ?)",
                tuple(row),
            )
        new_conn.commit()
    finally:
        old_conn.close()
        new_conn.close()


def _migrate_in_repo_format(marker_dir: Path, new_db_path: Path) -> None:
    """Migrate the in-repo format (.brd/ directory with board.db, committed
    to git) back to central storage."""
    old_db_path = marker_dir / "board.db"
    if old_db_path.is_file():
        _copy_cards(old_db_path, new_db_path)
    shutil.rmtree(marker_dir)


def _migrate_legacy_uuid_marker(marker_file: Path, new_db_path: Path) -> None:
    """Migrate the original design (.brd file holding a UUID, cards in a
    central per-project db keyed by that UUID)."""
    project_id = marker_file.read_text().strip()
    old_db_path = paths.data_dir() / "projects" / f"{project_id}.db"
    if old_db_path.is_file() and old_db_path != new_db_path:
        _copy_cards(old_db_path, new_db_path)


def init_project(root_path: Path, name: str | None = None) -> Project:
    project_name = name or root_path.name
    marker = root_path / MARKER_FILENAME
    db_path = paths.project_db_path(root_path)

    if marker.is_dir():
        _migrate_in_repo_format(marker, db_path)
    elif marker.is_file():
        _migrate_legacy_uuid_marker(marker, db_path)

    project_conn = db.connect(db_path)
    try:
        db.init_project_schema(project_conn)
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

    project = Project(
        root_path=str(root_path),
        name=project_name,
        created_at=_now(),
    )
    conn = _master_conn()
    try:
        db.upsert_project(conn, project)
    finally:
        conn.close()

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


def resolve_project_db(start: Path) -> Path:
    marker = find_marker(start)
    if marker is None:
        raise ProjectNotFoundError(f"no {MARKER_FILENAME} marker found above {start}")
    return paths.project_db_path(marker.parent)


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
