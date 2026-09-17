import uuid
from datetime import datetime, timezone
from pathlib import Path

from brd import db, paths
from brd.models import Project

MARKER_FILENAME = ".brd"


class ProjectAlreadyExistsError(Exception):
    pass


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
    conn = _master_conn()
    try:
        if db.get_project_by_name(conn, project_name) is not None:
            raise ProjectAlreadyExistsError(
                f"a project named '{project_name}' is already registered"
            )

        project_id = str(uuid.uuid4())
        project_db_path = paths.project_db_path(project_id)

        project_conn = db.connect(project_db_path)
        try:
            db.init_project_schema(project_conn)
        finally:
            project_conn.close()

        project = Project(
            id=project_id,
            name=project_name,
            root_path=str(root_path),
            db_path=str(project_db_path),
            created_at=_now(),
        )
        db.insert_project(conn, project)

        marker = root_path / MARKER_FILENAME
        marker.write_text(project_id + "\n")

        gitignore = root_path / ".gitignore"
        existing_lines = (
            gitignore.read_text().splitlines() if gitignore.exists() else []
        )
        if MARKER_FILENAME not in existing_lines:
            with gitignore.open("a") as f:
                if existing_lines and existing_lines[-1] != "":
                    f.write("\n")
                f.write(f"{MARKER_FILENAME}\n")

        return project
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


def resolve_current_project(start: Path) -> Project:
    marker = find_marker(start)
    if marker is None:
        raise ProjectNotFoundError(f"no {MARKER_FILENAME} marker found above {start}")

    project_id = marker.read_text().strip()
    conn = _master_conn()
    try:
        project = db.get_project_by_id(conn, project_id)
    finally:
        conn.close()

    if project is None:
        raise ProjectNotFoundError(
            f"marker at {marker} references unknown project id {project_id}"
        )
    return project


def list_all_projects() -> list[Project]:
    conn = _master_conn()
    try:
        return db.list_projects(conn)
    finally:
        conn.close()
