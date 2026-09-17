import pytest

from brd import master


def test_init_project_creates_marker_and_gitignore_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    project = master.init_project(repo)

    marker = repo / ".brd"
    assert marker.exists()
    assert marker.read_text().strip() == project.id

    gitignore = repo / ".gitignore"
    assert gitignore.exists()
    assert ".brd" in gitignore.read_text().splitlines()
    assert project.name == "myrepo"


def test_init_project_appends_to_existing_gitignore_once(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    (repo / ".gitignore").write_text("__pycache__/\n")

    master.init_project(repo)

    lines = (repo / ".gitignore").read_text().splitlines()
    assert lines.count(".brd") == 1
    assert "__pycache__/" in lines


def test_init_project_rejects_duplicate_name(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo1 = tmp_path / "repo1"
    repo1.mkdir()
    repo2 = tmp_path / "repo2"
    repo2.mkdir()

    master.init_project(repo1, name="shared")
    with pytest.raises(master.ProjectAlreadyExistsError):
        master.init_project(repo2, name="shared")


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


def test_resolve_current_project_from_nested_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    nested = repo / "a"
    nested.mkdir(parents=True)
    created = master.init_project(repo)

    resolved = master.resolve_current_project(nested)
    assert resolved == created


def test_resolve_current_project_raises_when_no_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    somewhere = tmp_path / "nowhere"
    somewhere.mkdir()
    with pytest.raises(master.ProjectNotFoundError):
        master.resolve_current_project(somewhere)


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


def test_init_project_preserves_gitignore_without_trailing_newline(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    (repo / ".gitignore").write_text("__pycache__/\n*.egg-info")

    master.init_project(repo)

    lines = (repo / ".gitignore").read_text().splitlines()
    assert "*.egg-info" in lines
    assert lines.count(".brd") == 1


def test_init_project_duplicate_name_leaves_no_trace(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo1 = tmp_path / "repo1"
    repo1.mkdir()
    repo2 = tmp_path / "repo2"
    repo2.mkdir()

    master.init_project(repo1, name="shared")
    with pytest.raises(master.ProjectAlreadyExistsError):
        master.init_project(repo2, name="shared")

    assert not (repo2 / ".brd").exists()
    assert not (repo2 / ".gitignore").exists()
    assert len(master.list_all_projects()) == 1


def test_resolve_current_project_raises_when_marker_id_unregistered(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    (repo / ".brd").write_text("00000000-0000-4000-8000-000000000000\n")

    with pytest.raises(master.ProjectNotFoundError):
        master.resolve_current_project(repo)


def test_find_marker_ignores_marker_directory(tmp_path):
    somewhere = tmp_path / "nowhere"
    (somewhere / ".brd").mkdir(parents=True)

    assert master.find_marker(somewhere) is None


def test_list_all_projects_is_empty_before_any_registration(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    assert master.list_all_projects() == []
