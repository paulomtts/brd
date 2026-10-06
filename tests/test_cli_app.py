import dataclasses
import json
import sqlite3

import pytest

from brd import db, master, paths
from brd.cli import _app
from brd.models import Project
from tests.cli_helpers import err, invoke, ok


def test_cli_is_a_package_exposing_app():
    from brd.cli import app

    assert app is _app.app


def test_commands_migrate_a_v0_board(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".brd").write_text("")
    monkeypatch.chdir(repo)
    master_conn = master._master_conn()
    try:
        db.upsert_project(
            master_conn,
            Project(
                id=db.new_project_id(),
                name="repo",
                root_path=str(repo),
                created_at="2026-01-01T00:00:00",
            ),
        )
    finally:
        master_conn.close()
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
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_domain_errors_become_envelopes(project):
    assert err("show", "nope") == "CardNotFoundError"


def test_missing_project_is_an_envelope(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    assert err("list") == "ProjectNotFoundError"


def test_ctx_has_exactly_conn_and_project():
    assert [f.name for f in dataclasses.fields(_app.Ctx)] == ["conn", "project"]


def test_open_project_carries_the_registered_project(project):
    ctx = _app.open_project()
    try:
        assert ctx.project == master.list_all_projects()[0]
        assert ctx.project.root_path == str(project)
        assert not hasattr(ctx, "root")
    finally:
        ctx.conn.close()


def test_open_project_from_a_subdirectory_resolves_the_same_project(project, monkeypatch):
    nested = project / "a" / "b"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    ctx = _app.open_project()
    try:
        assert ctx.project == master.list_all_projects()[0]
    finally:
        ctx.conn.close()


def test_open_project_through_a_symlinked_cwd_resolves_the_same_project(
    project, tmp_path, monkeypatch
):
    link = tmp_path / "link"
    link.symlink_to(project, target_is_directory=True)
    monkeypatch.chdir(link)
    ctx = _app.open_project()
    try:
        assert ctx.project == master.list_all_projects()[0]
    finally:
        ctx.conn.close()


def test_unregistered_marker_is_a_project_not_found_envelope(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".brd").write_text("")
    monkeypatch.chdir(repo)

    result = invoke("list")

    assert result.exit_code == 1
    error = json.loads(result.stdout)["error"]
    assert error["type"] == "ProjectNotFoundError"
    assert "brd init" in error["message"]
    assert str(repo) in error["message"]
    assert not paths.project_db_path(repo).exists()


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
    assert len(opened) == 2
    for conn in opened:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            conn.execute("SELECT 1")
