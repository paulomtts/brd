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


def _migrate_legacy_marker(root_path: Path, marker_file: Path) -> None:
    """Migrate a repo initialized under the old design: `.brd` was a plain
    marker file holding a project UUID, and cards lived in a per-project DB
    under the central data dir, keyed by that UUID."""
    project_id = marker_file.read_text().strip()
    old_db_path = paths.data_dir() / "projects" / f"{project_id}.db"
    marker_file.unlink()

    brd_dir = root_path / MARKER_DIRNAME
    brd_dir.mkdir(exist_ok=True)

    if old_db_path.is_file():
        new_db_path = brd_dir / DB_FILENAME
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

    # A bare ".brd" line (from the old design, which gitignored the marker)
    # would now wrongly hide the tracked board.db too.
    gitignore = root_path / ".gitignore"
    if gitignore.exists():
        lines = gitignore.read_text().splitlines()
        if MARKER_DIRNAME in lines:
            lines = [line for line in lines if line != MARKER_DIRNAME]
            text = "\n".join(lines)
            gitignore.write_text(f"{text}\n" if text else "")


def init_project(root_path: Path, name: str | None = None) -> Project:
    project_name = name or root_path.name
    brd_dir = root_path / MARKER_DIRNAME

    if brd_dir.is_file():
        _migrate_legacy_marker(root_path, brd_dir)

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
