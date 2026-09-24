import hashlib
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


def project_db_path(root_path: Path) -> Path:
    projects_dir = data_dir() / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(str(root_path.resolve()).encode()).hexdigest()
    return projects_dir / f"{digest}.db"


def project_docs_dir(root_path: Path) -> Path:
    return project_db_path(root_path).with_suffix(".docs")
