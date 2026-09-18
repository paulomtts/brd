import pytest

from brd import db, master


def test_init_project_creates_board_db_and_nested_gitignore(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    project = master.init_project(repo)

    board_db = repo / ".brd" / "board.db"
    assert board_db.is_file()
    assert project.name == "myrepo"
    assert project.root_path == str(repo)

    nested_gitignore = repo / ".brd" / ".gitignore"
    assert nested_gitignore.exists()
    assert "board.db-journal" in nested_gitignore.read_text()

    # The repo's own .gitignore is untouched: board.db is meant to be tracked.
    assert not (repo / ".gitignore").exists()


def test_init_project_twice_preserves_existing_cards(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    master.init_project(repo)

    board_db = repo / ".brd" / "board.db"
    conn = db.connect(board_db)
    try:
        conn.execute(
            "INSERT INTO cards (id, title, description, status, parent_id, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("c1", "Existing card", None, "todo", None, "now", "now"),
        )
        conn.commit()
    finally:
        conn.close()

    master.init_project(repo)  # simulates re-running init on a cloned repo

    conn = db.connect(board_db)
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


def test_init_project_migrates_legacy_marker_file_preserving_cards(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    # Simulate a repo initialized under the old design: a plain .brd marker
    # file holding a UUID, real cards in the old central per-project store,
    # and a root .gitignore that hides ".brd" (which would now wrongly hide
    # the tracked board.db too).
    legacy_id = "07a7d240-444a-4b71-b585-b5bc7b50fdf3"
    (repo / ".brd").write_text(f"{legacy_id}\n")
    (repo / ".gitignore").write_text("__pycache__/\n.brd\n")

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

    board_db = repo / ".brd" / "board.db"
    assert board_db.is_file()
    conn = db.connect(board_db)
    try:
        row = conn.execute("SELECT * FROM cards WHERE id = 'c1'").fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["title"] == "Old card"

    gitignore_lines = (repo / ".gitignore").read_text().splitlines()
    assert ".brd" not in gitignore_lines
    assert "__pycache__/" in gitignore_lines


def test_init_project_handles_legacy_marker_with_no_old_data(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    (repo / ".brd").write_text("00000000-0000-4000-8000-000000000000\n")

    project = master.init_project(repo)

    assert (repo / ".brd" / "board.db").is_file()
    assert project.name == "myrepo"


def test_find_project_db_walks_up_from_nested_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    nested = repo / "a" / "b"
    nested.mkdir(parents=True)
    master.init_project(repo)

    found = master.find_project_db(nested)
    assert found == repo / ".brd" / "board.db"


def test_find_project_db_returns_none_when_absent(tmp_path):
    somewhere = tmp_path / "nowhere"
    somewhere.mkdir()
    assert master.find_project_db(somewhere) is None


def test_resolve_project_db_from_nested_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    nested = repo / "a"
    nested.mkdir(parents=True)
    master.init_project(repo)

    resolved = master.resolve_project_db(nested)
    assert resolved == repo / ".brd" / "board.db"


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


def test_init_project_does_not_overwrite_existing_nested_gitignore(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    (repo / ".brd").mkdir()
    (repo / ".brd" / ".gitignore").write_text("custom-rule\n")

    master.init_project(repo)

    assert (repo / ".brd" / ".gitignore").read_text() == "custom-rule\n"


def test_list_all_projects_is_empty_before_any_registration(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    assert master.list_all_projects() == []
