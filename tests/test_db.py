import sqlite3

import pytest

from brd import db
from brd.models import Project


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.db")
    yield connection
    connection.close()


def test_connect_enables_wal_and_foreign_keys(conn):
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1


def test_connect_sets_row_factory(conn):
    assert conn.row_factory is sqlite3.Row


def test_init_master_schema_creates_projects_table(conn):
    db.init_master_schema(conn)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(projects)")}
    assert columns == {"id", "name", "root_path", "db_path", "created_at"}


def test_init_master_schema_is_idempotent(conn):
    db.init_master_schema(conn)
    db.init_master_schema(conn)  # must not raise


def test_init_project_schema_creates_cards_and_blocked_by_tables(conn):
    db.init_project_schema(conn)
    card_columns = {row[1] for row in conn.execute("PRAGMA table_info(cards)")}
    assert card_columns == {
        "id",
        "title",
        "description",
        "status",
        "parent_id",
        "created_at",
        "updated_at",
    }
    edge_columns = {row[1] for row in conn.execute("PRAGMA table_info(blocked_by)")}
    assert edge_columns == {"card_id", "blocks_on_id"}


def test_init_project_schema_is_idempotent(conn):
    db.init_project_schema(conn)
    db.init_project_schema(conn)  # must not raise


def test_cards_status_check_constraint_rejects_blocked(conn):
    db.init_project_schema(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO cards (id, title, description, status, parent_id, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("c1", "t", None, "blocked", None, "now", "now"),
        )


def test_projects_name_is_unique(conn):
    db.init_master_schema(conn)
    conn.execute(
        "INSERT INTO projects (id, name, root_path, db_path, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("p1", "dup", "/r", "/d", "now"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO projects (id, name, root_path, db_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("p2", "dup", "/r", "/d", "now"),
        )


def _insert_card(conn, card_id, parent_id=None):
    conn.execute(
        "INSERT INTO cards (id, title, description, status, parent_id, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (card_id, "t", None, "todo", parent_id, "now", "now"),
    )


def test_cards_parent_id_foreign_key_is_enforced(conn):
    db.init_project_schema(conn)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_card(conn, "c1", parent_id="ghost")


def test_blocked_by_foreign_keys_are_enforced(conn):
    db.init_project_schema(conn)
    _insert_card(conn, "c1")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO blocked_by (card_id, blocks_on_id) VALUES (?, ?)",
            ("c1", "ghost"),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO blocked_by (card_id, blocks_on_id) VALUES (?, ?)",
            ("ghost", "c1"),
        )


def test_blocked_by_rejects_duplicate_edge(conn):
    db.init_project_schema(conn)
    _insert_card(conn, "c1")
    _insert_card(conn, "c2")
    conn.execute(
        "INSERT INTO blocked_by (card_id, blocks_on_id) VALUES (?, ?)", ("c1", "c2")
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO blocked_by (card_id, blocks_on_id) VALUES (?, ?)",
            ("c1", "c2"),
        )


def _sample_project(id_="p1", name="brd"):
    return Project(
        id=id_,
        name=name,
        root_path="/repo",
        db_path="/data/p1.db",
        created_at="2026-09-17T00:00:00",
    )


def test_insert_and_get_project_by_id(conn):
    db.init_master_schema(conn)
    db.insert_project(conn, _sample_project())
    result = db.get_project_by_id(conn, "p1")
    assert result == _sample_project()


def test_get_project_by_id_returns_none_when_missing(conn):
    db.init_master_schema(conn)
    assert db.get_project_by_id(conn, "nope") is None


def test_get_project_by_name(conn):
    db.init_master_schema(conn)
    db.insert_project(conn, _sample_project())
    result = db.get_project_by_name(conn, "brd")
    assert result == _sample_project()


def test_list_projects_returns_all(conn):
    db.init_master_schema(conn)
    db.insert_project(conn, _sample_project("p1", "brd"))
    db.insert_project(conn, _sample_project("p2", "other"))
    results = db.list_projects(conn)
    assert {p.id for p in results} == {"p1", "p2"}


def test_list_projects_orders_by_created_at(conn):
    db.init_master_schema(conn)
    later = Project(
        id="p1",
        name="brd",
        root_path="/repo",
        db_path="/data/p1.db",
        created_at="2026-09-17T12:00:00",
    )
    earlier = Project(
        id="p2",
        name="other",
        root_path="/repo",
        db_path="/data/p2.db",
        created_at="2026-09-16T08:00:00",
    )
    db.insert_project(conn, later)
    db.insert_project(conn, earlier)
    assert [p.id for p in db.list_projects(conn)] == ["p2", "p1"]


def test_insert_project_commits_so_another_connection_sees_it(tmp_path):
    db_path = tmp_path / "master.db"
    writer = db.connect(db_path)
    db.init_master_schema(writer)
    db.insert_project(writer, _sample_project())
    reader = db.connect(db_path)
    try:
        assert db.get_project_by_id(reader, "p1") == _sample_project()
    finally:
        reader.close()
        writer.close()


def test_insert_project_rejects_duplicate_name(conn):
    db.init_master_schema(conn)
    db.insert_project(conn, _sample_project("p1", "brd"))
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_project(conn, _sample_project("p2", "brd"))
