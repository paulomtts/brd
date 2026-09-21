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
    assert columns == {"root_path", "name", "created_at"}


def test_init_master_schema_is_idempotent(conn):
    db.init_master_schema(conn)
    db.init_master_schema(conn)  # must not raise


def test_init_master_schema_migrates_legacy_schema_preserving_rows(conn):
    conn.execute(
        """
        CREATE TABLE projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            root_path TEXT NOT NULL,
            db_path TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO projects (id, name, root_path, db_path, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("old-id", "legacy-project", "/repo", "/old/db/path.db", "2026-01-01T00:00:00"),
    )
    conn.commit()

    db.init_master_schema(conn)

    columns = {row[1] for row in conn.execute("PRAGMA table_info(projects)")}
    assert columns == {"root_path", "name", "created_at"}
    row = conn.execute("SELECT * FROM projects").fetchone()
    assert row["root_path"] == "/repo"
    assert row["name"] == "legacy-project"
    assert row["created_at"] == "2026-01-01T00:00:00"


def test_init_master_schema_migration_is_idempotent(conn):
    conn.execute(
        """
        CREATE TABLE projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            root_path TEXT NOT NULL,
            db_path TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()

    db.init_master_schema(conn)
    db.init_master_schema(conn)  # must not raise on the already-migrated table


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


def test_projects_root_path_is_primary_key(conn):
    db.init_master_schema(conn)
    conn.execute(
        "INSERT INTO projects (root_path, name, created_at) VALUES (?, ?, ?)",
        ("/r", "dup", "now"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO projects (root_path, name, created_at) VALUES (?, ?, ?)",
            ("/r", "other", "now"),
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


def _sample_project(root_path="/repo", name="brd"):
    return Project(
        root_path=root_path,
        name=name,
        created_at="2026-09-17T00:00:00",
    )


def test_upsert_project_inserts_new(conn):
    db.init_master_schema(conn)
    db.upsert_project(conn, _sample_project())
    results = db.list_projects(conn)
    assert results == [_sample_project()]


def test_upsert_project_updates_name_on_existing_root_path(conn):
    db.init_master_schema(conn)
    db.upsert_project(conn, _sample_project(name="brd"))
    db.upsert_project(conn, _sample_project(name="renamed"))
    results = db.list_projects(conn)
    assert [p.name for p in results] == ["renamed"]
    assert len(results) == 1


def test_list_projects_returns_all(conn):
    db.init_master_schema(conn)
    db.upsert_project(conn, _sample_project("/repo1", "brd"))
    db.upsert_project(conn, _sample_project("/repo2", "other"))
    results = db.list_projects(conn)
    assert {p.root_path for p in results} == {"/repo1", "/repo2"}


def test_list_projects_orders_by_created_at(conn):
    db.init_master_schema(conn)
    later = Project(
        root_path="/repo1",
        name="brd",
        created_at="2026-09-17T12:00:00",
    )
    earlier = Project(
        root_path="/repo2",
        name="other",
        created_at="2026-09-16T08:00:00",
    )
    db.upsert_project(conn, later)
    db.upsert_project(conn, earlier)
    assert [p.root_path for p in db.list_projects(conn)] == ["/repo2", "/repo1"]


def test_upsert_project_commits_so_another_connection_sees_it(tmp_path):
    db_path = tmp_path / "master.db"
    writer = db.connect(db_path)
    db.init_master_schema(writer)
    db.upsert_project(writer, _sample_project())
    reader = db.connect(db_path)
    try:
        assert db.list_projects(reader) == [_sample_project()]
    finally:
        reader.close()


def test_get_project_returns_matching_project(conn):
    db.init_master_schema(conn)
    db.upsert_project(conn, _sample_project("/repo1", "brd"))
    db.upsert_project(conn, _sample_project("/repo2", "other"))
    assert db.get_project(conn, "/repo2") == _sample_project("/repo2", "other")


def test_get_project_returns_none_when_absent(conn):
    db.init_master_schema(conn)
    assert db.get_project(conn, "/nope") is None


def test_delete_project_removes_matching_row(conn):
    db.init_master_schema(conn)
    db.upsert_project(conn, _sample_project("/repo1", "brd"))
    db.upsert_project(conn, _sample_project("/repo2", "other"))
    db.delete_project(conn, "/repo1")
    assert [p.root_path for p in db.list_projects(conn)] == ["/repo2"]


def test_delete_project_is_a_noop_when_absent(conn):
    db.init_master_schema(conn)
    db.upsert_project(conn, _sample_project())
    db.delete_project(conn, "/nope")
    assert [p.root_path for p in db.list_projects(conn)] == ["/repo"]


def test_delete_project_commits_so_another_connection_sees_it(tmp_path):
    db_path = tmp_path / "master.db"
    writer = db.connect(db_path)
    db.init_master_schema(writer)
    db.upsert_project(writer, _sample_project())
    db.delete_project(writer, "/repo")
    reader = db.connect(db_path)
    try:
        assert db.list_projects(reader) == []
    finally:
        reader.close()
        writer.close()


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


def test_delete_card_removes_row(project_conn):
    db.insert_card(project_conn, _sample_card("c1"))
    db.delete_card(project_conn, "c1")
    assert db.get_card(project_conn, "c1") is None


def test_delete_card_removes_blocked_by_edges_in_both_directions(project_conn):
    db.insert_card(project_conn, _sample_card("c1"))
    db.insert_card(project_conn, _sample_card("c2"))
    db.insert_card(project_conn, _sample_card("c3"))
    db.add_blocked_by_edge(project_conn, "c1", "c2")
    db.add_blocked_by_edge(project_conn, "c3", "c1")

    db.delete_card(project_conn, "c1")

    assert db.list_blockers_of(project_conn, "c3") == []
    assert db.get_card(project_conn, "c2") is not None


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
