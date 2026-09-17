import os
from pathlib import Path


def data_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path(os.environ["HOME"]) / ".local" / "share"
    result = base / "brd"
    result.mkdir(parents=True, exist_ok=True)
    return result


def master_db_path() -> Path:
    return data_dir() / "master.db"


def project_db_path(project_id: str) -> Path:
    projects_dir = data_dir() / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    return projects_dir / f"{project_id}.db"
