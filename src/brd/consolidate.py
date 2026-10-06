"""The one-time move of every per-project board into brd.db.

Before brd.db, each registered project had its own board file,
projects/<sha256(root)>.db, with its document backups in <hash>.docs/, and
master.db held the registry. migrate() copies all of them into brd.db in one
transaction; retire() then renames the old files with a .migrated suffix."""

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from brd import db, paths
from brd.errors import MigrationError
from brd.models import Project

# Copied in this order; foreign keys are off while they copy.
TABLES = ("entities", "cards", "issues", "documents", "comments", "tags", "blocked_by", "refs")
SUFFIX = ".migrated"


@dataclass
class Report:
    migrated: int
    skipped: list[str]
    retired: list[Path]

    def notice(self) -> str:
        lines = [
            f"brd: migrated {self.migrated} projects into brd.db "
            f"(old files kept as *{SUFFIX})"
        ]
        if self.skipped:
            lines.append(
                f"brd: skipped {len(self.skipped)} unregistered board files: "
                + ", ".join(self.skipped)
            )
        return "\n".join(lines)


def _board_path(project: Project) -> Path:
    return paths.project_db_path(Path(project.root_path))


def _backups_path(project: Project) -> Path:
    return paths.project_docs_dir(Path(project.root_path))


def _registered() -> list[Project]:
    path = paths.master_db_path()
    conn = None
    try:
        conn = db.connect(path)
        db.init_master_schema(conn)
        return db.list_projects(conn)
    except sqlite3.DatabaseError as exc:
        raise MigrationError(f"cannot migrate the registry at {path}: {exc}") from exc
    finally:
        if conn is not None:
            conn.close()


def _label(project: Project) -> str:
    return f"project {project.name} ({project.root_path})"


def _open_board(project: Project) -> sqlite3.Connection | None:
    """The project's legacy board, upgraded in place to v4; None when it has
    no board file (it is registered empty)."""
    path = _board_path(project)
    if not path.is_file():
        return None
    board = None
    try:
        board = db.connect(path)
        db.migrate_project(board, project)
        return board
    except BaseException as exc:
        if board is not None:
            board.close()
        # Not SQLite, or a board that records another project: name both.
        if isinstance(exc, (sqlite3.DatabaseError, MigrationError)):
            raise MigrationError(
                f"cannot migrate the board of {_label(project)} at {path}: {exc}"
            ) from exc
        raise


def _check_duplicates(boards: list[tuple[Project, sqlite3.Connection | None]]) -> None:
    """Abort before anything is copied when two boards hold the same entity or
    comment id; brd.db would otherwise fail on a raw IntegrityError."""
    projects = {project.id: project for project, _ in boards}
    clashes: dict[tuple[str, str], list[str]] = {}
    for table in ("entities", "comments"):
        owners: dict[str, str] = {}
        for project, board in boards:
            if board is None:
                continue
            for row in board.execute(f"SELECT id FROM {table}"):
                first = owners.setdefault(row[0], project.id)
                if first != project.id:
                    clashes.setdefault((first, project.id), []).append(row[0])
    if clashes:
        parts = [
            f"{_label(projects[a])} and {_label(projects[b])} share ids {', '.join(sorted(ids))}"
            for (a, b), ids in clashes.items()
        ]
        raise MigrationError(
            "cannot migrate into brd.db: "
            + "; ".join(parts)
            + "; no file was renamed, remove the duplicates and run brd again"
        )


def _copy(conn: sqlite3.Connection, project: Project, board: sqlite3.Connection | None) -> None:
    # The registry's row, not the board's: ids were settled in master.db.
    conn.execute(
        "INSERT INTO projects (id, name, root_path, created_at) VALUES (?, ?, ?, ?)",
        (project.id, project.name, project.root_path, project.created_at),
    )
    if board is None:
        return
    for table in TABLES:
        rows = board.execute(f"SELECT * FROM {table}").fetchall()
        if rows:
            columns = rows[0].keys()
            conn.executemany(
                f"INSERT INTO {table} ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                [tuple(row) for row in rows],
            )


def _copy_backups(projects: list[Project], created: list[Path]) -> None:
    """Copy every legacy backup into docs/, recording in `created` each file
    this made, so a failure before commit can remove exactly those."""
    target = paths.docs_dir()
    for project in projects:
        source = _backups_path(project)
        if not source.is_dir():
            continue
        target.mkdir(parents=True, exist_ok=True)
        for backup in sorted(source.glob("*.md")):
            destination = target / backup.name
            if not destination.exists():
                created.append(destination)
            shutil.copyfile(backup, destination)


def _unregistered(projects: list[Project]) -> list[str]:
    folder = paths.data_dir() / "projects"
    if not folder.is_dir():
        return []
    registered = {_board_path(project) for project in projects}
    return sorted(
        f"projects/{path.name}" for path in folder.glob("*.db") if path not in registered
    )


def _retirees(projects: list[Project]) -> list[Path]:
    found = [paths.master_db_path()]
    for project in projects:
        found += [path for path in (_board_path(project), _backups_path(project)) if path.exists()]
    return found


def migrate(conn: sqlite3.Connection) -> Report:
    """Copy master.db's projects and every registered legacy board into brd.db.

    conn is brd.db, already inside BEGIN IMMEDIATE with foreign keys off.
    Commits on success; on failure raises (MigrationError for anything in the
    old files) with the backups it copied removed, and leaves the rollback to
    the caller. retire() renames the old files once this has committed."""
    projects = _registered()
    boards: list[tuple[Project, sqlite3.Connection | None]] = []
    try:
        for project in projects:
            boards.append((project, _open_board(project)))
        _check_duplicates(boards)
        db.init_brd_schema(conn)
        try:
            for project, board in boards:
                _copy(conn, project, board)
        except sqlite3.IntegrityError as exc:
            raise MigrationError(f"cannot migrate into brd.db: {exc}") from exc
    finally:
        for _, board in boards:
            if board is not None:
                board.close()
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise MigrationError(
            f"cannot migrate into brd.db: {len(violations)} foreign key violation(s); "
            "no file was renamed"
        )
    created: list[Path] = []
    try:
        _copy_backups(projects, created)
        conn.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION}")
        conn.commit()
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return Report(
        migrated=len(projects), skipped=_unregistered(projects), retired=_retirees(projects)
    )


def _rename(source: Path, target: Path) -> None:
    try:
        source.rename(target)
    except OSError:
        # brd.db is migrated, so this never runs again; the stray old file
        # is left for the user.
        pass


def retire(old_files: list[Path]) -> None:
    """Rename each old file with the .migrated suffix, and its -wal/-shm
    sidecars with it so the renamed file still opens with all its data.
    Never deletes a file."""
    for path in old_files:
        target = path.with_name(path.name + SUFFIX)
        _rename(path, target)
        for sidecar in ("-wal", "-shm"):
            source = path.with_name(path.name + sidecar)
            if source.exists():
                _rename(source, target.with_name(target.name + sidecar))
