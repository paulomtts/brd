import shutil
import uuid

import pytest

from brd import db, master, paths


def test_init_project_creates_central_db_and_gitignored_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    project = master.init_project(repo)

    marker = repo / ".brd"
    assert marker.is_file()
    assert marker.read_text() == ""
    assert project.name == "myrepo"
    assert project.root_path == str(repo)

    db_path = paths.project_db_path(repo)
    assert db_path.is_file()
    assert str(db_path).startswith(str(tmp_path / "data"))

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
    master.init_project(repo)

    db_path = paths.project_db_path(repo)
    conn = db.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO cards (id, title, description, status, parent_id, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("c1", "Existing card", None, "todo", None, "now", "now"),
        )
        conn.commit()
    finally:
        conn.close()

    master.init_project(repo)

    conn = db.connect(db_path)
    try:
        row = conn.execute("SELECT * FROM cards WHERE id = 'c1'").fetchone()
    finally:
        conn.close()
    assert row is not None


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
    db.init_project_schema(old_conn)
    old_conn.execute(
        "INSERT INTO cards (id, title, description, status, parent_id, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("c1", "Old card", None, "todo", None, "now", "now"),
    )
    old_conn.commit()
    old_conn.close()

    master.init_project(repo)

    new_db_path = paths.project_db_path(repo)
    conn = db.connect(new_db_path)
    try:
        row = conn.execute("SELECT * FROM cards WHERE id = 'c1'").fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["title"] == "Old card"
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
    db.init_project_schema(old_conn)
    old_conn.execute(
        "INSERT INTO cards (id, title, description, status, parent_id, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("c1", "In-repo card", None, "todo", None, "now", "now"),
    )
    old_conn.commit()
    old_conn.close()

    master.init_project(repo)

    assert brd_dir.is_file()  # the directory is gone; .brd is a marker file again
    new_db_path = paths.project_db_path(repo)
    conn = db.connect(new_db_path)
    try:
        row = conn.execute("SELECT * FROM cards WHERE id = 'c1'").fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["title"] == "In-repo card"

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


def test_resolve_project_db_from_nested_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    nested = repo / "a"
    nested.mkdir(parents=True)
    master.init_project(repo)

    resolved = master.resolve_project_db(nested)
    assert resolved == paths.project_db_path(repo)


def test_resolve_project_db_raises_when_no_project(tmp_path):
    somewhere = tmp_path / "nowhere"
    somewhere.mkdir()
    with pytest.raises(master.ProjectNotFoundError):
        master.resolve_project_db(somewhere)


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


def test_forget_project_removes_db_marker_and_registry_row(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    master.init_project(repo)
    db_path = paths.project_db_path(repo)
    assert db_path.is_file()

    forgotten = master.forget_project(repo)

    assert forgotten.name == "myrepo"
    assert not db_path.is_file()
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
    db_path = paths.project_db_path(repo)
    shutil.rmtree(repo)

    forgotten = master.forget_project(repo)

    assert forgotten.name == "myrepo"
    assert not db_path.is_file()
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


def test_list_all_projects_is_empty_before_any_registration(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    assert master.list_all_projects() == []


def test_forget_removes_document_backups(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    master.init_project(repo)
    docs = paths.project_docs_dir(repo)
    docs.mkdir()
    (docs / "x.md").write_text("backup")
    master.forget_project(repo)
    assert not docs.exists()


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


def test_forget_project_returns_project_with_its_id(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    project = master.init_project(repo)

    assert master.forget_project(repo) == project
