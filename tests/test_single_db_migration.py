import json
import shutil
import sqlite3
import threading
from pathlib import Path

import pytest

from brd import db, master, paths
from brd.errors import MigrationError
from brd.models import Project
from tests.cli_helpers import invoke, ok
from tests.factories import NOW, OTHER_PROJECT, add_project, make_card, make_issue
from tests.test_migration import INSERT_CARD, _make_v0, _make_v2_without_archived, _make_v3

TABLES = ("entities", "cards", "issues", "documents", "comments", "tags", "blocked_by", "refs")
NOTICE = "brd: migrated {n} projects into brd.db (old files kept as *.migrated)"


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    return tmp_path / "data" / "brd"


def register(base: Path, name: str, created_at: str = "2026-01-01T00:00:00+00:00") -> Project:
    """Register base/name in master.db, the way brd did before brd.db."""
    root = base / name
    root.mkdir(parents=True)
    conn = db.connect(paths.master_db_path())
    try:
        db.init_master_schema(conn)
        return db.upsert_project(
            conn, Project(id=db.new_project_id(), name=name, root_path=str(root), created_at=created_at)
        )
    finally:
        conn.close()


def board_path(project: Project) -> Path:
    return paths.project_db_path(Path(project.root_path))


def backups_path(project: Project) -> Path:
    return paths.project_docs_dir(Path(project.root_path))


def migrated(path: Path) -> Path:
    return path.with_name(path.name + ".migrated")


def v4_board(project: Project) -> sqlite3.Connection:
    conn = db.connect(board_path(project))
    db.migrate_project(conn, project)
    return conn


def add_document(conn, project: Project, doc_id: str, stem: str, content: str) -> None:
    """A document row on a legacy board plus its backup in <hash>.docs/.
    (factories.make_document would put the backup next to the db file.)"""
    with conn:
        db.insert_entity(conn, project.id, doc_id, "document")
        conn.execute(
            "INSERT INTO documents (id, project_id, title, source_path, stem, content_hash, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (doc_id, project.id, stem, f"docs/{stem}.md", stem, "0" * 64, NOW, NOW),
        )
    backups = backups_path(project)
    backups.mkdir(parents=True, exist_ok=True)
    (backups / f"{doc_id}.md").write_text(content)


def rows(conn, table: str, columns: str = "*") -> list[tuple]:
    return sorted(tuple(r) for r in conn.execute(f"SELECT {columns} FROM {table}"))


def open_brd():
    """master.connect, with the notices it reports collected."""
    notices: list[str] = []
    conn = master.connect(notify=notices.append)
    return conn, notices


def seed_four_versions(base: Path) -> list[Project]:
    """Registered projects whose boards sit at v0, v2, v3 and v4. The v4 one
    holds a parent/child pair, an issue, a document with its backup, a
    comment, a tag, a ref and a blocked_by edge."""
    v0 = register(base, "v0", "2026-01-01T00:00:00+00:00")
    _make_v0(board_path(v0), cards=[("a-p", None), ("a-c", "a-p")], edges=[("a-c", "a-p")])

    v2 = register(base, "v2", "2026-01-02T00:00:00+00:00")
    _make_v2_without_archived(board_path(v2))
    legacy = sqlite3.connect(board_path(v2))
    legacy.execute(INSERT_CARD, ("b-1", "B", None))
    legacy.commit()
    legacy.close()

    v3 = register(base, "v3", "2026-01-03T00:00:00+00:00")
    _make_v3(board_path(v3))

    v4 = register(base, "v4", "2026-01-04T00:00:00+00:00")
    conn = v4_board(v4)
    make_card(conn, "d-card", project_id=v4.id)
    make_card(conn, "d-child", parent_id="d-card", project_id=v4.id)
    make_issue(conn, "d-issue", project_id=v4.id)
    add_document(conn, v4, "d-doc", "notes", "# Notes\n")
    conn.execute(
        "INSERT INTO comments (id, entity_id, author, body, created_at) "
        "VALUES ('d-comment', 'd-card', 'me', 'hi', ?)",
        (NOW,),
    )
    conn.execute("INSERT INTO tags (entity_id, tag) VALUES ('d-doc', 'design')")
    conn.execute("INSERT INTO refs (src_id, dst_id, origin) VALUES ('d-card', 'd-doc', 'explicit')")
    conn.execute("INSERT INTO blocked_by (card_id, blocks_on_id) VALUES ('d-child', 'd-issue')")
    conn.commit()
    conn.close()
    return [v0, v2, v3, v4]


def test_boards_at_v0_v2_v3_and_v4_move_into_brd_db_unchanged(data, tmp_path):
    projects = seed_four_versions(tmp_path)

    conn, notices = open_brd()
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert rows(conn, "projects") == sorted(
            (p.id, p.name, p.root_path, p.created_at) for p in projects
        )
        # Each board was upgraded in place, then copied; the renamed file is
        # that upgraded board, so brd.db must hold exactly the union of them.
        boards = [sqlite3.connect(migrated(board_path(p))) for p in projects]
        try:
            for table in TABLES:
                expected = sorted(row for board in boards for row in rows(board, table))
                assert rows(conn, table) == expected, table
        finally:
            for board in boards:
                board.close()
        v0, v2, v3, v4 = projects
        owners = dict(rows(conn, "entities", "id, project_id"))
        assert (owners["a-p"], owners["b-1"], owners["p"], owners["d-card"]) == (
            v0.id, v2.id, v3.id, v4.id,
        )
        assert tuple(
            conn.execute("SELECT created_at, updated_at FROM cards WHERE id = 'a-p'").fetchone()
        ) == ("now", "now")
        assert tuple(
            conn.execute("SELECT created_at, updated_at FROM cards WHERE id = 'd-card'").fetchone()
        ) == (NOW, NOW)
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()
    assert notices == [NOTICE.format(n=4)]


def test_registered_project_without_a_board_is_registered_empty(data, tmp_path):
    empty = register(tmp_path, "empty")

    conn, notices = open_brd()
    try:
        assert rows(conn, "projects") == [(empty.id, "empty", empty.root_path, empty.created_at)]
        assert rows(conn, "entities") == []
    finally:
        conn.close()
    assert notices == [NOTICE.format(n=1)]


def test_unregistered_board_files_are_left_alone(data, tmp_path):
    kept = register(tmp_path, "kept")
    conn = v4_board(kept)
    make_card(conn, "k-1", project_id=kept.id)
    conn.close()
    stray = data / "projects" / "stray.db"
    _make_v0(stray, cards=[("s-1", None)], edges=[])
    legacy_uuid = data / "projects" / "07a7d240-444a-4b71-b585-b5bc7b50fdf3.db"
    _make_v0(legacy_uuid, cards=[("u-1", None)], edges=[])
    (data / "projects" / "stray.docs").mkdir()
    (data / "projects" / "stray.docs" / "x.md").write_text("stray")

    conn, notices = open_brd()
    try:
        assert rows(conn, "cards", "id") == [("k-1",)]
    finally:
        conn.close()
    for path in (stray, legacy_uuid, data / "projects" / "stray.docs"):
        assert path.exists() and not migrated(path).exists()
    assert not (data / "docs" / "x.md").exists()
    assert notices == [
        NOTICE.format(n=1)
        + "\nbrd: skipped 2 unregistered board files: "
        "projects/07a7d240-444a-4b71-b585-b5bc7b50fdf3.db, projects/stray.db"
    ]


def test_document_backups_move_to_the_shared_docs_dir(data, tmp_path):
    owner = register(tmp_path, "owner")
    conn = v4_board(owner)
    add_document(conn, owner, "doc-1", "notes", "# Notes\n")
    conn.close()

    brd, _ = open_brd()
    brd.close()

    assert (paths.docs_dir() / "doc-1.md").read_text() == "# Notes\n"
    assert (migrated(backups_path(owner)) / "doc-1.md").read_text() == "# Notes\n"


def test_old_files_are_renamed_never_deleted(data, tmp_path):
    owner = register(tmp_path, "owner")
    conn = v4_board(owner)
    add_document(conn, owner, "doc-1", "notes", "x")
    conn.close()

    brd, _ = open_brd()
    brd.close()

    for path in (paths.master_db_path(), board_path(owner), backups_path(owner)):
        assert not path.exists(), path
        assert migrated(path).exists(), path
    registry = sqlite3.connect(migrated(paths.master_db_path()))
    try:
        assert [tuple(r) for r in registry.execute("SELECT id, root_path FROM projects")] == [
            (owner.id, owner.root_path)
        ]
    finally:
        registry.close()


def test_empty_registry_migrates_zero_projects(data):
    conn = db.connect(paths.master_db_path())
    db.init_master_schema(conn)
    conn.close()

    brd, notices = open_brd()
    try:
        assert rows(brd, "projects") == []
    finally:
        brd.close()
    assert notices == [NOTICE.format(n=0)]
    assert not paths.master_db_path().exists()
    assert migrated(paths.master_db_path()).is_file()


def test_pre_id_registry_is_upgraded_then_migrated(data, tmp_path):
    root = tmp_path / "old"
    root.mkdir()
    legacy = sqlite3.connect(paths.master_db_path())
    legacy.execute(
        "CREATE TABLE projects (root_path TEXT PRIMARY KEY, name TEXT NOT NULL, "
        "created_at TEXT NOT NULL)"
    )
    legacy.execute(
        "INSERT INTO projects VALUES (?, 'old', '2026-01-01T00:00:00')", (str(root),)
    )
    legacy.commit()
    legacy.close()
    _make_v0(paths.project_db_path(root), cards=[("o-1", None)], edges=[])

    brd, notices = open_brd()
    try:
        [project] = db.list_projects(brd)
        assert (project.name, project.root_path) == ("old", str(root))
        assert rows(brd, "entities", "id, project_id") == [("o-1", project.id)]
    finally:
        brd.close()
    assert notices == [NOTICE.format(n=1)]


def test_child_card_stored_before_its_parent_still_migrates(data, tmp_path):
    owner = register(tmp_path, "owner")
    _make_v0(board_path(owner), cards=[("child", "parent"), ("parent", None)], edges=[])

    brd, _ = open_brd()
    try:
        assert db.get_card(brd, "child").parent_id == "parent"
    finally:
        brd.close()


def test_fresh_install_gets_an_empty_v4_brd_db_and_no_notice(data):
    brd, notices = open_brd()
    try:
        assert brd.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert brd.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert rows(brd, "projects") == []
    finally:
        brd.close()
    assert notices == []
    assert not paths.master_db_path().exists()
    assert not (data / "projects").exists()


def test_second_connect_neither_migrates_nor_notifies(data, tmp_path):
    owner = register(tmp_path, "owner")
    conn = v4_board(owner)
    make_card(conn, "c1", project_id=owner.id)
    conn.close()
    first, _ = open_brd()
    first.close()

    second, notices = open_brd()
    try:
        assert rows(second, "cards", "id") == [("c1",)]
        assert len(rows(second, "projects")) == 1
    finally:
        second.close()
    assert notices == []


def seed_shared_ids(base: Path) -> tuple[Project, Project]:
    """Two registered v4 boards that both hold card 'dup' and comment
    'k-dup', each with one document backup."""
    first = register(base, "first", "2026-01-01T00:00:00+00:00")
    second = register(base, "second", "2026-01-02T00:00:00+00:00")
    for project in (first, second):
        conn = v4_board(project)
        make_card(conn, "dup", project_id=project.id)
        conn.execute(
            "INSERT INTO comments (id, entity_id, author, body, created_at) "
            "VALUES ('k-dup', 'dup', 'me', 'hi', ?)",
            (NOW,),
        )
        conn.commit()
        add_document(conn, project, f"doc-{project.name}", "notes", "body")
        conn.close()
    return first, second


def assert_nothing_migrated(projects: list[Project]) -> None:
    assert paths.master_db_path().is_file()
    assert not migrated(paths.master_db_path()).exists()
    for project in projects:
        assert board_path(project).is_file()
        assert not migrated(board_path(project)).exists()
        assert not migrated(backups_path(project)).exists()
    brd = paths.brd_db_path()
    if brd.exists():
        conn = sqlite3.connect(brd)
        try:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == 0
        finally:
            conn.close()


def test_shared_ids_abort_naming_both_projects_and_every_id(data, tmp_path):
    first, second = seed_shared_ids(tmp_path)
    notices: list[str] = []

    with pytest.raises(MigrationError) as excinfo:
        master.connect(notify=notices.append)

    message = str(excinfo.value)
    for text in ("first", first.root_path, "second", second.root_path, "dup", "k-dup"):
        assert text in message
    assert notices == []
    assert_nothing_migrated([first, second])
    assert backups_path(first).is_dir() and backups_path(second).is_dir()
    assert not (data / "docs").exists()

    conn = db.connect(board_path(second))
    db.delete_card(conn, "dup")  # the cascade takes comment k-dup with it
    conn.close()
    brd, notices = open_brd()
    try:
        assert rows(brd, "entities", "id") == sorted(
            [("dup",), ("doc-first",), ("doc-second",)]
        )
    finally:
        brd.close()
    assert notices == [NOTICE.format(n=2)]


def test_board_recording_another_project_aborts(data, tmp_path):
    owner = register(tmp_path, "owner")
    stranger = Project(id=db.new_project_id(), name="stranger", root_path="/elsewhere", created_at=NOW)
    conn = db.connect(board_path(owner))
    db.migrate_project(conn, stranger)
    conn.close()

    with pytest.raises(MigrationError) as excinfo:
        master.connect()

    assert "owner" in str(excinfo.value)
    assert str(board_path(owner)) in str(excinfo.value)
    assert_nothing_migrated([owner])


def test_unreadable_board_aborts_naming_the_project_and_file(data, tmp_path):
    owner = register(tmp_path, "owner")
    board_path(owner).write_bytes(b"not a database " * 100)

    with pytest.raises(MigrationError) as excinfo:
        master.connect()

    assert "owner" in str(excinfo.value)
    assert str(board_path(owner)) in str(excinfo.value)
    assert_nothing_migrated([owner])


def test_rows_of_an_unregistered_project_fail_the_foreign_key_check(data, tmp_path):
    owner = register(tmp_path, "owner")
    conn = v4_board(owner)
    add_project(conn, OTHER_PROJECT)
    make_card(conn, "stray", project_id=OTHER_PROJECT.id)
    conn.close()

    with pytest.raises(MigrationError, match="foreign key"):
        master.connect()

    assert_nothing_migrated([owner])


def test_failed_backup_copy_removes_the_backups_it_copied(data, tmp_path, monkeypatch):
    owner = register(tmp_path, "owner")
    conn = v4_board(owner)
    add_document(conn, owner, "doc-a", "a", "A")
    add_document(conn, owner, "doc-b", "b", "B")
    conn.close()
    (data / "docs").mkdir()
    (data / "docs" / "keep.md").write_text("mine")
    real_copyfile = shutil.copyfile
    calls = []

    def copyfile(source, target):
        calls.append(source)
        if len(calls) == 2:
            raise OSError("disk full")
        return real_copyfile(source, target)

    monkeypatch.setattr(shutil, "copyfile", copyfile)
    with pytest.raises(OSError, match="disk full"):
        master.connect()

    assert sorted(path.name for path in (data / "docs").iterdir()) == ["keep.md"]
    assert (data / "docs" / "keep.md").read_text() == "mine"
    assert_nothing_migrated([owner])


def test_concurrent_first_runs_migrate_exactly_once(tmp_path, monkeypatch):
    for attempt in range(5):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / f"data{attempt}"))
        for name in ("one", "two"):
            project = register(tmp_path / f"roots{attempt}", name)
            conn = v4_board(project)
            make_card(conn, f"{name}-card", project_id=project.id)
            conn.close()
        barrier = threading.Barrier(4, timeout=20)
        notices: list[str] = []
        errors = []

        def first_run():
            try:
                barrier.wait()
                master.connect(notify=notices.append).close()
            except Exception as exc:  # noqa: BLE001 — collected and asserted below
                errors.append(exc)

        threads = [threading.Thread(target=first_run) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert errors == []
        assert notices == [NOTICE.format(n=2)]
        conn = db.connect(paths.brd_db_path())
        try:
            assert rows(conn, "cards", "id") == [("one-card",), ("two-card",)]
            assert len(rows(conn, "projects")) == 2
        finally:
            conn.close()
        assert migrated(paths.master_db_path()).is_file()
        assert not paths.master_db_path().exists()


def test_concurrent_first_runs_on_a_fresh_install_all_succeed(tmp_path, monkeypatch):
    for attempt in range(10):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / f"fresh{attempt}"))
        barrier = threading.Barrier(4, timeout=20)
        notices: list[str] = []
        errors = []

        def first_run():
            try:
                barrier.wait()
                master.connect(notify=notices.append).close()
            except Exception as exc:  # noqa: BLE001 — collected and asserted below
                errors.append(exc)

        threads = [threading.Thread(target=first_run) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == []
        assert notices == []


def test_failed_rename_neither_fails_nor_reruns_the_migration(data, tmp_path, monkeypatch):
    owner = register(tmp_path, "owner")
    conn = v4_board(owner)
    make_card(conn, "c1", project_id=owner.id)
    conn.close()
    stuck = board_path(owner)
    real_rename = Path.rename

    def rename(self, target):
        if self == stuck:
            raise PermissionError("read-only")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", rename)
    first, notices = open_brd()
    first.close()
    assert notices == [NOTICE.format(n=1)]
    assert stuck.is_file()
    assert migrated(paths.master_db_path()).is_file()

    second, again = open_brd()
    try:
        assert rows(second, "cards", "id") == [("c1",)]
    finally:
        second.close()
    assert again == []


def test_wal_sidecar_follows_its_database(data, tmp_path):
    owner = register(tmp_path, "owner")
    holder = v4_board(owner)
    make_card(holder, "c1", project_id=owner.id)
    board = board_path(owner)
    # This open connection keeps the board's -wal file on disk.
    try:
        assert board.with_name(board.name + "-wal").exists()
        brd, _ = open_brd()
        brd.close()
        renamed = migrated(board)
        assert renamed.is_file()
        assert renamed.with_name(renamed.name + "-wal").exists()
        assert not board.with_name(board.name + "-wal").exists()
    finally:
        holder.close()


def test_purge_counts_the_registry_without_migrating(data, tmp_path):
    seed_shared_ids(tmp_path)  # a migration would abort

    declined = invoke("purge", input="n\n")
    assert declined.exit_code == 1
    assert "Delete all brd data for 2 project(s)?" in declined.stdout
    assert not paths.brd_db_path().exists()

    assert ok("purge", "--yes") == {"projects_removed": 2}
    assert not data.exists()


@pytest.mark.parametrize("args", [["list"], ["projects"], ["init"]])
def test_unreadable_board_is_a_migration_error_envelope(data, tmp_path, monkeypatch, args):
    owner = register(tmp_path, "owner")
    board_path(owner).write_bytes(b"not a database " * 100)
    root = Path(owner.root_path)
    (root / ".brd").write_text("")
    monkeypatch.chdir(root)

    result = invoke(*args)

    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)  # an envelope, not a traceback
    error = json.loads(result.stdout)["error"]
    assert error["type"] == "MigrationError"
    assert "owner" in error["message"]
    assert str(board_path(owner)) in error["message"]
    assert result.stderr == ""


def test_shared_ids_fail_the_command_and_a_retry_succeeds(data, tmp_path, monkeypatch):
    first, second = seed_shared_ids(tmp_path)
    (Path(first.root_path) / ".brd").write_text("")
    monkeypatch.chdir(first.root_path)

    result = invoke("list")

    assert result.exit_code == 1
    error = json.loads(result.stdout)["error"]
    assert error["type"] == "MigrationError"
    for text in ("first", "second", "dup", "k-dup"):
        assert text in error["message"]
    assert result.stderr == ""
    assert_nothing_migrated([first, second])
    assert not (data / "docs").exists()

    conn = db.connect(board_path(second))
    db.delete_card(conn, "dup")
    conn.close()
    retry = invoke("list")
    assert retry.exit_code == 0
    assert [c["id"] for c in json.loads(retry.stdout)["data"]] == ["dup"]
    assert retry.stderr.startswith(NOTICE.format(n=2))


def test_skipped_unregistered_boards_are_reported_on_stderr(data, tmp_path, monkeypatch):
    kept = register(tmp_path, "kept")
    (data / "projects").mkdir(parents=True, exist_ok=True)
    stray = data / "projects" / "stray.db"
    _make_v0(stray, cards=[("s-1", None)], edges=[])
    monkeypatch.chdir(tmp_path)

    result = invoke("projects")

    assert result.exit_code == 0
    assert [p["id"] for p in json.loads(result.stdout)["data"]] == [kept.id]
    assert result.stderr == (
        NOTICE.format(n=1)
        + "\nbrd: skipped 1 unregistered board files: projects/stray.db\n"
    )
    assert stray.is_file() and not migrated(stray).exists()


def test_commands_read_backups_from_the_shared_docs_dir(data, tmp_path, monkeypatch):
    owner = register(tmp_path, "owner")
    conn = v4_board(owner)
    add_document(conn, owner, "doc-1", "notes", "# Notes\nbody\n")
    conn.close()
    root = Path(owner.root_path)
    (root / ".brd").write_text("")
    monkeypatch.chdir(root)

    ok("doc", "restore", "doc-1")

    assert (root / "docs" / "notes.md").read_text() == "# Notes\nbody\n"
    assert not backups_path(owner).exists()
    assert (paths.docs_dir() / "doc-1.md").is_file()


def test_notice_goes_to_stderr_and_stdout_stays_one_envelope(data, tmp_path, monkeypatch):
    for name in ("one", "two"):
        project = register(tmp_path, name)
        conn = v4_board(project)
        make_card(conn, f"{name}-card", project_id=project.id)
        conn.close()
    root = tmp_path / "one"
    (root / ".brd").write_text("")
    monkeypatch.chdir(root)

    first = invoke("list")
    assert first.exit_code == 0
    assert [c["id"] for c in json.loads(first.stdout)["data"]] == ["one-card"]
    assert first.stderr.startswith(NOTICE.format(n=2))

    second = invoke("list")
    assert second.exit_code == 0
    assert second.stderr == ""
    assert json.loads(second.stdout) == json.loads(first.stdout)


def test_fresh_install_init_creates_brd_db_without_notice(data, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)

    result = invoke("init")

    assert result.exit_code == 0
    assert json.loads(result.stdout)["ok"] is True
    assert result.stderr == ""
    conn = db.connect(paths.brd_db_path())
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert [r[0] for r in conn.execute("SELECT root_path FROM projects")] == [str(repo)]
    finally:
        conn.close()
    assert not paths.master_db_path().exists()
    assert not (data / "projects").exists()


def test_command_outside_any_project_still_migrates(data, tmp_path, monkeypatch):
    owner = register(tmp_path, "owner")
    conn = v4_board(owner)
    make_card(conn, "c1", project_id=owner.id)
    conn.close()
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)

    result = invoke("list")

    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["type"] == "ProjectNotFoundError"
    assert result.stderr.startswith(NOTICE.format(n=1))
    assert migrated(paths.master_db_path()).is_file()


@pytest.mark.parametrize("args", [["prompt"], ["--help"], ["doc", "--help"]])
def test_commands_without_data_do_not_migrate(data, tmp_path, args):
    register(tmp_path, "owner")

    result = invoke(*args)

    assert result.exit_code == 0
    assert result.stderr == ""
    assert paths.master_db_path().is_file()
    assert not paths.brd_db_path().exists()


def test_unreadable_master_db_is_a_migration_error_envelope(data, tmp_path, monkeypatch):
    data.mkdir(parents=True)
    paths.master_db_path().write_bytes(b"not a database " * 100)
    monkeypatch.chdir(tmp_path)

    result = invoke("projects")

    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)  # an envelope, not a traceback
    error = json.loads(result.stdout)["error"]
    assert error["type"] == "MigrationError"
    assert str(paths.master_db_path()) in error["message"]
    assert paths.master_db_path().is_file()
    assert not migrated(paths.master_db_path()).exists()


def test_purge_works_when_master_db_is_unreadable(data):
    data.mkdir(parents=True)
    paths.master_db_path().write_bytes(b"not a database " * 100)

    assert ok("purge", "--yes") == {"projects_removed": 0}
    assert not data.exists()
