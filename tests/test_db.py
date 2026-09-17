import sqlite3

import pytest

from brd import db


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
