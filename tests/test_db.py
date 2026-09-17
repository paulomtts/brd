import sqlite3

import pytest

from brd import db
from brd.models import Card, Project


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


@pytest.fixture
def project_conn(tmp_path):
    connection = db.connect(tmp_path / "project.db")
    db.init_project_schema(connection)
    yield connection
    connection.close()


def _sample_card(
    id_="c1",
    title="Card",
    status="todo",
    parent_id=None,
    created_at="2026-09-17T00:00:00",
):
    return Card(
        id=id_,
        title=title,
        description="desc",
        status=status,
        parent_id=parent_id,
        created_at=created_at,
        updated_at="2026-09-17T00:00:00",
    )


def test_insert_and_get_card(project_conn):
    db.insert_card(project_conn, _sample_card())
    result = db.get_card(project_conn, "c1")
    assert result == _sample_card()


def test_get_card_returns_none_when_missing(project_conn):
    assert db.get_card(project_conn, "nope") is None


def test_update_card_fields(project_conn):
    db.insert_card(project_conn, _sample_card())
    db.update_card_fields(project_conn, "c1", title="New title", updated_at="later")
    result = db.get_card(project_conn, "c1")
    assert result.title == "New title"
    assert result.updated_at == "later"
    assert result.description == "desc"  # untouched fields survive


def test_list_cards_no_filter_returns_all(project_conn):
    db.insert_card(project_conn, _sample_card("c1"))
    db.insert_card(project_conn, _sample_card("c2"))
    results = db.list_cards(project_conn)
    assert {c.id for c in results} == {"c1", "c2"}


def test_list_cards_filters_by_status(project_conn):
    db.insert_card(project_conn, _sample_card("c1", status="todo"))
    db.insert_card(project_conn, _sample_card("c2", status="done"))
    results = db.list_cards(project_conn, status="done")
    assert [c.id for c in results] == ["c2"]


def test_list_cards_filters_by_parent_id(project_conn):
    db.insert_card(project_conn, _sample_card("parent"))
    db.insert_card(project_conn, _sample_card("child", parent_id="parent"))
    results = db.list_cards(project_conn, parent_id="parent")
    assert [c.id for c in results] == ["child"]


def test_list_cards_filters_by_explicit_none_parent(project_conn):
    db.insert_card(project_conn, _sample_card("top"))
    db.insert_card(project_conn, _sample_card("parent2"))
    db.insert_card(project_conn, _sample_card("child", parent_id="parent2"))
    results = db.list_cards(project_conn, parent_id=None)
    assert {c.id for c in results} == {"top", "parent2"}


def test_add_and_list_blockers_of(project_conn):
    db.insert_card(project_conn, _sample_card("c1"))
    db.insert_card(project_conn, _sample_card("c2"))
    db.add_blocked_by_edge(project_conn, "c1", "c2")
    assert db.list_blockers_of(project_conn, "c1") == ["c2"]


def test_remove_blocked_by_edge(project_conn):
    db.insert_card(project_conn, _sample_card("c1"))
    db.insert_card(project_conn, _sample_card("c2"))
    db.add_blocked_by_edge(project_conn, "c1", "c2")
    db.remove_blocked_by_edge(project_conn, "c1", "c2")
    assert db.list_blockers_of(project_conn, "c1") == []


def test_list_children(project_conn):
    db.insert_card(project_conn, _sample_card("parent"))
    db.insert_card(project_conn, _sample_card("child1", parent_id="parent"))
    db.insert_card(project_conn, _sample_card("child2", parent_id="parent"))
    results = db.list_children(project_conn, "parent")
    assert {c.id for c in results} == {"child1", "child2"}


def test_list_cards_orders_by_created_at(project_conn):
    db.insert_card(project_conn, _sample_card("c1", created_at="2026-09-17T12:00:00"))
    db.insert_card(project_conn, _sample_card("c2", created_at="2026-09-16T08:00:00"))
    assert [c.id for c in db.list_cards(project_conn)] == ["c2", "c1"]


def test_list_children_orders_by_created_at(project_conn):
    db.insert_card(project_conn, _sample_card("parent"))
    db.insert_card(
        project_conn,
        _sample_card("child1", parent_id="parent", created_at="2026-09-17T12:00:00"),
    )
    db.insert_card(
        project_conn,
        _sample_card("child2", parent_id="parent", created_at="2026-09-16T08:00:00"),
    )
    results = db.list_children(project_conn, "parent")
    assert [c.id for c in results] == ["child2", "child1"]


def test_insert_card_commits_so_another_connection_sees_it(tmp_path):
    db_path = tmp_path / "project.db"
    writer = db.connect(db_path)
    db.init_project_schema(writer)
    db.insert_card(writer, _sample_card())
    reader = db.connect(db_path)
    try:
        assert db.get_card(reader, "c1") == _sample_card()
    finally:
        reader.close()
        writer.close()


def test_update_card_fields_commits_so_another_connection_sees_it(tmp_path):
    db_path = tmp_path / "project.db"
    writer = db.connect(db_path)
    db.init_project_schema(writer)
    db.insert_card(writer, _sample_card())
    db.update_card_fields(writer, "c1", title="New title")
    reader = db.connect(db_path)
    try:
        assert db.get_card(reader, "c1").title == "New title"
    finally:
        reader.close()
        writer.close()


def test_blocked_by_edge_writes_commit_so_another_connection_sees_them(tmp_path):
    db_path = tmp_path / "project.db"
    writer = db.connect(db_path)
    db.init_project_schema(writer)
    db.insert_card(writer, _sample_card("c1"))
    db.insert_card(writer, _sample_card("c2"))
    db.add_blocked_by_edge(writer, "c1", "c2")
    reader = db.connect(db_path)
    try:
        assert db.list_blockers_of(reader, "c1") == ["c2"]
        db.remove_blocked_by_edge(writer, "c1", "c2")
        assert db.list_blockers_of(reader, "c1") == []
    finally:
        reader.close()
        writer.close()
