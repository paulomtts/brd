import sqlite3

import pytest

from brd import db, paths
from brd.cli import _app
from tests.cli_helpers import err, ok


def test_cli_is_a_package_exposing_app():
    from brd.cli import app

    assert app is _app.app


def test_commands_migrate_a_v0_board(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".brd").write_text("")
    monkeypatch.chdir(repo)
    legacy = sqlite3.connect(paths.project_db_path(repo))
    legacy.execute(
        "CREATE TABLE cards (id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT, "
        "status TEXT NOT NULL, parent_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    legacy.execute("CREATE TABLE blocked_by (card_id TEXT, blocks_on_id TEXT)")
    legacy.execute("INSERT INTO cards VALUES ('c1', 'Old', NULL, 'todo', NULL, 'now', 'now')")
    legacy.commit()
    legacy.close()

    assert [c["id"] for c in ok("list")] == ["c1"]
    conn = db.connect(paths.project_db_path(repo))
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1


def test_domain_errors_become_envelopes(project):
    assert err("show", "nope") == "CardNotFoundError"


def test_missing_project_is_an_envelope(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    assert err("list") == "ProjectNotFoundError"


def test_open_project_closes_connection_when_migration_fails(project, monkeypatch):
    from brd.errors import MigrationError

    opened = []
    real_connect = db.connect

    def tracking_connect(path):
        conn = real_connect(path)
        opened.append(conn)
        return conn

    def failing_migrate(conn):
        raise MigrationError("boom")

    monkeypatch.setattr(db, "connect", tracking_connect)
    monkeypatch.setattr(db, "migrate_project", failing_migrate)
    assert err("list") == "MigrationError"
    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")
