from pathlib import Path

from brd import paths


def test_data_dir_uses_xdg_data_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    result = paths.data_dir()
    assert result == tmp_path / "brd"
    assert result.is_dir()


def test_data_dir_defaults_to_home_local_share(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    result = paths.data_dir()
    assert result == tmp_path / ".local" / "share" / "brd"
    assert result.is_dir()


def test_master_db_path(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.master_db_path() == tmp_path / "brd" / "master.db"


def test_data_dir_treats_empty_xdg_data_home_as_unset(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", "")
    monkeypatch.setenv("HOME", str(tmp_path))
    result = paths.data_dir()
    assert result == tmp_path / ".local" / "share" / "brd"
    assert result.is_dir()


def test_project_db_path_is_deterministic_per_root(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    project_root = tmp_path / "repo"
    project_root.mkdir()

    result = paths.project_db_path(project_root)
    assert result == paths.project_db_path(project_root)
    assert result.parent == tmp_path / "data" / "brd" / "projects"
    assert result.parent.is_dir()


def test_project_db_path_differs_per_root(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo1 = tmp_path / "repo1"
    repo1.mkdir()
    repo2 = tmp_path / "repo2"
    repo2.mkdir()

    assert paths.project_db_path(repo1) != paths.project_db_path(repo2)


def test_brd_db_path(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.brd_db_path() == tmp_path / "brd" / "brd.db"


def test_docs_dir_sits_in_the_data_dir_and_is_not_created(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.docs_dir() == tmp_path / "brd" / "docs"
    assert not paths.docs_dir().exists()
