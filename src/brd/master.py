from datetime import datetime, timezone
from pathlib import Path

from brd import db, paths
from brd.models import Project

MARKER_DIRNAME = ".brd"
DB_FILENAME = "board.db"


class ProjectNotFoundError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _master_conn():
    conn = db.connect(paths.master_db_path())
    db.init_master_schema(conn)
    return conn


def init_project(root_path: Path, name: str | None = None) -> Project:
    project_name = name or root_path.name
    brd_dir = root_path / MARKER_DIRNAME
    brd_dir.mkdir(exist_ok=True)
    db_path = brd_dir / DB_FILENAME

    project_conn = db.connect(db_path)
    try:
        db.init_project_schema(project_conn)
    finally:
        project_conn.close()

    nested_gitignore = brd_dir / ".gitignore"
    if not nested_gitignore.exists():
        nested_gitignore.write_text(f"{DB_FILENAME}-journal\n")

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


def find_project_db(start: Path) -> Path | None:
    current = start.resolve()
    while True:
        candidate = current / MARKER_DIRNAME / DB_FILENAME
        if candidate.is_file():
            return candidate
        if current.parent == current:
            return None
        current = current.parent


def resolve_project_db(start: Path) -> Path:
    db_path = find_project_db(start)
    if db_path is None:
        raise ProjectNotFoundError(
            f"no {MARKER_DIRNAME}/{DB_FILENAME} found above {start}"
        )
    return db_path


def list_all_projects() -> list[Project]:
    conn = _master_conn()
    try:
        return db.list_projects(conn)
    finally:
        conn.close()
