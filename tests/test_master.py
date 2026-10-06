import shutil
import uuid

import pytest

from brd import db, master, paths
from brd.models import Project
from tests.factories import PROJECT, make_card, make_document


def _brd():
    return db.connect(paths.brd_db_path())


def _card_owner(card_id):
    """(title, project_id) of a card in brd.db, or None."""
    conn = _brd()
    try:
        row = conn.execute(
            "SELECT cards.title, entities.project_id FROM cards "
            "JOIN entities ON entities.id = cards.id WHERE cards.id = ?",
            (card_id,),
        ).fetchone()
    finally:
        conn.close()
    return tuple(row) if row else None


def test_init_project_creates_brd_db_and_gitignored_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    project = master.init_project(repo)

    marker = repo / ".brd"
    assert marker.is_file()
    assert marker.read_text() == ""
    assert project.name == "myrepo"
    assert project.root_path == str(repo)

    db_path = paths.brd_db_path()
    assert db_path.is_file()
    assert str(db_path).startswith(str(tmp_path / "data"))
    conn = _brd()
    try:
        assert db.list_projects(conn) == [project]
    finally:
        conn.close()

    gitignore = repo / ".gitignore"
    assert gitignore.exists()
    assert ".brd" in gitignore.read_text().splitlines()


def test_init_project_appends_to_existing_gitignore_once(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    (repo / ".gitignore").write_text("__pycache__/\n")

    master.init_project(repo)

    lines = (repo / ".gitignore").read_text().splitlines()
    assert lines.count(".brd") == 1
    assert "__pycache__/" in lines


def test_init_project_twice_preserves_existing_cards(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    project = master.init_project(repo)

    conn = _brd()
    try:
        make_card(conn, "c1", title="Existing card", project_id=project.id)
    finally:
        conn.close()

    master.init_project(repo)

    assert _card_owner("c1") == ("Existing card", project.id)


def test_init_project_upserts_name_on_rerun(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    master.init_project(repo, name="first-name")
    project = master.init_project(repo, name="second-name")

    assert project.name == "second-name"
    all_projects = master.list_all_projects()
    assert [p.name for p in all_projects] == ["second-name"]


def test_init_project_migrates_legacy_uuid_marker_preserving_cards(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    legacy_id = "07a7d240-444a-4b71-b585-b5bc7b50fdf3"
    (repo / ".brd").write_text(f"{legacy_id}\n")

    old_projects_dir = tmp_path / "data" / "brd" / "projects"
    old_projects_dir.mkdir(parents=True)
    old_db_path = old_projects_dir / f"{legacy_id}.db"
    old_conn = db.connect(old_db_path)
    db.init_project_schema(old_conn, PROJECT)
    make_card(old_conn, "c1", title="Old card")
    old_conn.close()

    project = master.init_project(repo)

    assert _card_owner("c1") == ("Old card", project.id)
    assert (repo / ".brd").read_text() == ""


def test_init_project_migrates_in_repo_format_preserving_cards(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    # Simulate a repo committed under the in-repo storage design: .brd/ is a
    # directory holding board.db, and it's absent from .gitignore.
    brd_dir = repo / ".brd"
    brd_dir.mkdir()
    old_db_path = brd_dir / "board.db"
    old_conn = db.connect(old_db_path)
    db.init_project_schema(old_conn, PROJECT)
    make_card(old_conn, "c1", title="In-repo card")
    old_conn.close()

    project = master.init_project(repo)

    assert brd_dir.is_file()  # the directory is gone; .brd is a marker file again
    assert _card_owner("c1") == ("In-repo card", project.id)

    gitignore_lines = (repo / ".gitignore").read_text().splitlines()
    assert ".brd" in gitignore_lines


def test_find_marker_walks_up_from_nested_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    nested = repo / "a" / "b"
    nested.mkdir(parents=True)
    master.init_project(repo)

    found = master.find_marker(nested)
    assert found == repo / ".brd"


def test_find_marker_returns_none_when_absent(tmp_path):
    somewhere = tmp_path / "nowhere"
    somewhere.mkdir()
    assert master.find_marker(somewhere) is None


def test_list_all_projects(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo1 = tmp_path / "repo1"
    repo1.mkdir()
    repo2 = tmp_path / "repo2"
    repo2.mkdir()
    master.init_project(repo1)
    master.init_project(repo2)

    results = master.list_all_projects()
    assert {p.name for p in results} == {"repo1", "repo2"}


def test_forget_project_removes_marker_and_registry_row(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    master.init_project(repo)

    forgotten = master.forget_project(repo)

    assert forgotten.name == "myrepo"
    assert not (repo / ".brd").exists()
    assert master.list_all_projects() == []


def test_forget_project_raises_when_not_registered(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    with pytest.raises(master.ProjectNotFoundError):
        master.forget_project(repo)


def test_forget_project_works_when_root_path_no_longer_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    master.init_project(repo)
    shutil.rmtree(repo)

    forgotten = master.forget_project(repo)

    assert forgotten.name == "myrepo"
    assert master.list_all_projects() == []


def test_purge_all_removes_entire_data_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "data" / "brd"
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo1 = tmp_path / "repo1"
    repo1.mkdir()
    repo2 = tmp_path / "repo2"
    repo2.mkdir()
    master.init_project(repo1)
    master.init_project(repo2)

    removed = master.purge_all()

    assert removed == 2
    assert not data_dir.exists()


def test_purge_all_returns_zero_when_nothing_registered(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert master.purge_all() == 0


def test_registry_count_reads_master_db_without_migrating(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    conn = db.connect(paths.master_db_path())
    db.init_master_schema(conn)
    for name in ("a", "b"):
        db.upsert_project(
            conn, Project(db.new_project_id(), name, str(tmp_path / name), "2026-01-01")
        )
    conn.close()

    assert master.registry_count() == 2
    assert not paths.brd_db_path().exists()
    assert paths.master_db_path().is_file()


def test_list_all_projects_is_empty_before_any_registration(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    assert master.list_all_projects() == []


def test_forget_removes_the_projects_document_backups(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    project = master.init_project(repo)
    conn = _brd()
    try:
        make_document(conn, "d1", "notes", content="backup", project_id=project.id)
    finally:
        conn.close()
    backup = paths.docs_dir() / "d1.md"
    assert backup.read_text() == "backup"

    master.forget_project(repo)

    assert not backup.exists()


def _is_uuid4(value):
    return uuid.UUID(value).version == 4 and str(uuid.UUID(value)) == value


def test_init_project_returns_stored_project_with_uuid4_id(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    project = master.init_project(repo)

    assert _is_uuid4(project.id)
    assert master.list_all_projects() == [project]


def test_init_project_rerun_keeps_id_and_created_at(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    first = master.init_project(repo, name="first-name")
    second = master.init_project(repo, name="second-name")
    third = master.init_project(repo)

    assert second.id == first.id
    assert second.created_at == first.created_at
    assert second.name == "second-name"
    assert third.id == first.id
    assert third.name == "myrepo"
    assert master.list_all_projects() == [third]


def test_init_project_gives_each_root_its_own_id(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo1 = tmp_path / "repo1"
    repo2 = tmp_path / "repo2"
    repo1.mkdir()
    repo2.mkdir()

    first = master.init_project(repo1)
    second = master.init_project(repo2)

    assert first.id != second.id


def test_init_rerun_keeps_the_brd_db_row_and_its_cards(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo1 = tmp_path / "repo1"
    repo2 = tmp_path / "repo2"
    repo1.mkdir()
    repo2.mkdir()
    first = master.init_project(repo1)
    conn = _brd()
    try:
        make_card(conn, "c1", project_id=first.id)
    finally:
        conn.close()

    master.init_project(repo1, name="renamed")
    other = master.init_project(repo2)

    conn = _brd()
    try:
        stored = {row["root_path"]: tuple(row) for row in conn.execute("SELECT * FROM projects")}
    finally:
        conn.close()
    assert stored[str(repo1)] == (first.id, "renamed", str(repo1), first.created_at)
    assert stored[str(repo2)][0] == other.id != first.id
    assert _card_owner("c1") == ("c1", first.id)


def test_init_on_an_unmigrated_install_keeps_the_registered_id(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    legacy = Project(db.new_project_id(), "myrepo", str(repo), "2026-01-01T00:00:00+00:00")
    conn = db.connect(paths.master_db_path())
    db.init_master_schema(conn)
    db.upsert_project(conn, legacy)
    conn.close()
    board = db.connect(paths.project_db_path(repo))
    db.migrate_project(board, legacy)
    make_card(board, "c1", project_id=legacy.id)
    board.close()

    project = master.init_project(repo)

    assert (project.id, project.created_at) == (legacy.id, legacy.created_at)
    assert _card_owner("c1") == ("c1", legacy.id)


def test_forget_project_returns_project_with_its_id(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    project = master.init_project(repo)

    assert master.forget_project(repo) == project


def test_registered_project_returns_the_registered_row(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    project = master.init_project(repo)

    conn = master.connect()
    try:
        assert master.registered_project(conn, repo) == project
    finally:
        conn.close()


def test_registered_project_raises_when_root_is_not_registered(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    conn = master.connect()
    try:
        with pytest.raises(master.ProjectNotFoundError, match="brd init"):
            master.registered_project(conn, repo)
    finally:
        conn.close()


def test_copy_cards_drops_dangling_legacy_edges(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    brd_dir = repo / ".brd"
    brd_dir.mkdir(parents=True)
    old_conn = db.connect(brd_dir / "board.db")
    db.init_project_schema(old_conn, PROJECT)
    make_card(old_conn, "c1")
    make_card(old_conn, "c2")
    db.add_blocked_by_edge(old_conn, "c2", "c1")
    db.add_blocked_by_edge(old_conn, "c1", "ghost")  # the legacy board's dangling edge
    old_conn.close()

    project = master.init_project(repo)

    conn = _brd()
    try:
        entities = conn.execute("SELECT id, project_id FROM entities ORDER BY id").fetchall()
        edges = conn.execute("SELECT card_id, blocks_on_id FROM blocked_by").fetchall()
    finally:
        conn.close()
    assert [tuple(r) for r in entities] == [("c1", project.id), ("c2", project.id)]
    assert [tuple(r) for r in edges] == [("c2", "c1")]
