import sqlite3
import uuid

import pytest

from brd import db
from brd.models import Card, Project
from tests.factories import PROJECT


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


def _project_table_info(conn):
    return {row["name"]: row for row in conn.execute("PRAGMA table_info(projects)")}


def _project_rows(conn):
    return {
        row["root_path"]: dict(row)
        for row in conn.execute("SELECT * FROM projects")
    }


def _is_uuid4(value):
    return uuid.UUID(value).version == 4 and str(uuid.UUID(value)) == value


def _create_current_projects_table(conn, rows=()):
    conn.execute(
        """
        CREATE TABLE projects (
            root_path TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.executemany(
        "INSERT INTO projects (root_path, name, created_at) VALUES (?, ?, ?)", rows
    )
    conn.commit()


def _create_legacy_projects_table(conn, rows=()):
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
    conn.executemany(
        "INSERT INTO projects (id, name, root_path, db_path, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def test_init_master_schema_creates_projects_table(conn):
    db.init_master_schema(conn)
    info = _project_table_info(conn)
    assert set(info) == {"id", "name", "root_path", "created_at"}
    assert info["id"]["pk"] == 1
    assert [name for name, row in info.items() if row["pk"]] == ["id"]
    assert _project_rows(conn) == {}


def test_init_master_schema_is_idempotent(conn):
    db.init_master_schema(conn)
    db.init_master_schema(conn)  # must not raise


def test_init_master_schema_migrates_current_schema_assigning_uuid4_ids(conn):
    _create_current_projects_table(
        conn,
        [
            ("/repo1", "one", "2026-01-01T00:00:00"),
            ("/repo2", "two", "2026-01-02T00:00:00"),
        ],
    )

    db.init_master_schema(conn)

    assert set(_project_table_info(conn)) == {"id", "name", "root_path", "created_at"}
    rows = _project_rows(conn)
    assert {k: (v["name"], v["created_at"]) for k, v in rows.items()} == {
        "/repo1": ("one", "2026-01-01T00:00:00"),
        "/repo2": ("two", "2026-01-02T00:00:00"),
    }
    ids = [row["id"] for row in rows.values()]
    assert all(_is_uuid4(i) for i in ids)
    assert len(set(ids)) == 2


def test_init_master_schema_migrates_empty_current_table(conn):
    _create_current_projects_table(conn)
    db.init_master_schema(conn)
    assert set(_project_table_info(conn)) == {"id", "name", "root_path", "created_at"}
    assert _project_rows(conn) == {}


def test_init_master_schema_never_changes_ids_once_assigned(tmp_path):
    db_path = tmp_path / "master.db"
    first = db.connect(db_path)
    _create_current_projects_table(
        first,
        [
            ("/repo1", "one", "2026-01-01T00:00:00"),
            ("/repo2", "two", "2026-01-02T00:00:00"),
        ],
    )
    db.init_master_schema(first)
    ids = {k: v["id"] for k, v in _project_rows(first).items()}

    db.init_master_schema(first)
    db.init_master_schema(first)
    second = db.connect(db_path)
    try:
        db.init_master_schema(second)
        assert {k: v["id"] for k, v in _project_rows(second).items()} == ids
    finally:
        second.close()
    assert {k: v["id"] for k, v in _project_rows(first).items()} == ids
    first.close()


def test_init_master_schema_migrates_legacy_schema_preserving_rows(conn):
    _create_legacy_projects_table(
        conn,
        [("old-id", "legacy-project", "/repo", "/old/db/path.db", "2026-01-01T00:00:00")],
    )

    db.init_master_schema(conn)

    assert set(_project_table_info(conn)) == {"id", "name", "root_path", "created_at"}
    row = conn.execute("SELECT * FROM projects").fetchone()
    assert row["root_path"] == "/repo"
    assert row["name"] == "legacy-project"
    assert row["created_at"] == "2026-01-01T00:00:00"
    assert row["id"] != "old-id"
    assert _is_uuid4(row["id"])


def test_init_master_schema_migrates_empty_legacy_table(conn):
    _create_legacy_projects_table(conn)
    db.init_master_schema(conn)
    assert set(_project_table_info(conn)) == {"id", "name", "root_path", "created_at"}
    assert _project_rows(conn) == {}


def test_init_master_schema_collapses_duplicate_legacy_root_paths(conn):
    _create_legacy_projects_table(
        conn,
        [
            ("a", "first", "/repo", "/a.db", "2026-01-01T00:00:00"),
            ("b", "second", "/repo", "/b.db", "2026-01-02T00:00:00"),
        ],
    )

    db.init_master_schema(conn)

    rows = conn.execute("SELECT * FROM projects").fetchall()
    assert len(rows) == 1
    assert rows[0]["root_path"] == "/repo"
    assert _is_uuid4(rows[0]["id"])


def test_init_master_schema_migration_is_idempotent(conn):
    _create_legacy_projects_table(
        conn,
        [("old-id", "legacy-project", "/repo", "/old/db/path.db", "2026-01-01T00:00:00")],
    )

    db.init_master_schema(conn)
    ids = {k: v["id"] for k, v in _project_rows(conn).items()}
    db.init_master_schema(conn)  # must not raise on the already-migrated table
    db.init_master_schema(conn)

    assert {k: v["id"] for k, v in _project_rows(conn).items()} == ids


def test_init_master_schema_migration_is_atomic(conn, monkeypatch):
    rows = [
        ("/repo1", "one", "2026-01-01T00:00:00"),
        ("/repo2", "two", "2026-01-02T00:00:00"),
    ]
    _create_current_projects_table(conn, rows)
    calls = []
    real_new_project_id = db.new_project_id

    def failing_new_project_id():
        calls.append(None)
        if len(calls) == 2:
            raise RuntimeError("boom")
        return real_new_project_id()

    monkeypatch.setattr(db, "new_project_id", failing_new_project_id)

    with pytest.raises(RuntimeError, match="boom"):
        db.init_master_schema(conn)

    assert set(_project_table_info(conn)) == {"root_path", "name", "created_at"}
    assert sorted(
        tuple(row) for row in conn.execute("SELECT root_path, name, created_at FROM projects")
    ) == rows
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"projects"}
    assert not conn.in_transaction


def test_init_project_schema_creates_cards_and_blocked_by_tables(conn):
    db.init_project_schema(conn, PROJECT)
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
    db.init_project_schema(conn, PROJECT)
    db.init_project_schema(conn, PROJECT)  # must not raise


def test_cards_status_check_constraint_rejects_blocked(conn):
    db.init_project_schema(conn, PROJECT)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO cards (id, title, description, status, parent_id, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("c1", "t", None, "blocked", None, "now", "now"),
        )


def test_projects_root_path_is_unique(conn):
    db.init_master_schema(conn)
    conn.execute(
        "INSERT INTO projects (id, name, root_path, created_at) VALUES (?, ?, ?, ?)",
        ("id-1", "dup", "/r", "now"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO projects (id, name, root_path, created_at) VALUES (?, ?, ?, ?)",
            ("id-2", "other", "/r", "now"),
        )


def test_projects_id_is_unique_and_required(conn):
    db.init_master_schema(conn)
    conn.execute(
        "INSERT INTO projects (id, name, root_path, created_at) VALUES (?, ?, ?, ?)",
        ("id-1", "one", "/r1", "now"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO projects (id, name, root_path, created_at) VALUES (?, ?, ?, ?)",
            ("id-1", "two", "/r2", "now"),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO projects (id, name, root_path, created_at) VALUES (?, ?, ?, ?)",
            (None, "three", "/r3", "now"),
        )


def _insert_card(conn, card_id, parent_id=None):
    conn.execute(
        "INSERT INTO cards (id, title, description, status, parent_id, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (card_id, "t", None, "todo", parent_id, "now", "now"),
    )


def test_cards_parent_id_foreign_key_is_enforced(conn):
    db.init_project_schema(conn, PROJECT)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_card(conn, "c1", parent_id="ghost")


def test_blocked_by_foreign_keys_are_enforced(conn):
    db.init_project_schema(conn, PROJECT)
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
    db.init_project_schema(conn, PROJECT)
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


def _sample_project(
    root_path="/repo",
    name="brd",
    id="11111111-1111-4111-8111-111111111111",
    created_at="2026-09-17T00:00:00",
):
    return Project(id=id, name=name, root_path=root_path, created_at=created_at)


def test_upsert_project_inserts_new(conn):
    db.init_master_schema(conn)
    stored = db.upsert_project(conn, _sample_project())
    assert db.list_projects(conn) == [_sample_project()]
    assert stored == _sample_project()


def test_upsert_project_updates_only_name_on_existing_root_path(conn):
    db.init_master_schema(conn)
    db.upsert_project(conn, _sample_project(name="brd"))
    stored = db.upsert_project(
        conn,
        _sample_project(
            name="renamed",
            id="22222222-2222-4222-8222-222222222222",
            created_at="2026-12-31T00:00:00",
        ),
    )
    expected = _sample_project(name="renamed")
    assert db.list_projects(conn) == [expected]
    assert stored == expected


def test_list_projects_returns_all(conn):
    db.init_master_schema(conn)
    db.upsert_project(conn, _sample_project("/repo1", "brd", id="id-1"))
    db.upsert_project(conn, _sample_project("/repo2", "other", id="id-2"))
    results = db.list_projects(conn)
    assert {(p.id, p.root_path) for p in results} == {("id-1", "/repo1"), ("id-2", "/repo2")}


def test_list_projects_orders_by_created_at(conn):
    db.init_master_schema(conn)
    later = _sample_project("/repo1", "brd", id="id-1", created_at="2026-09-17T12:00:00")
    earlier = _sample_project("/repo2", "other", id="id-2", created_at="2026-09-16T08:00:00")
    db.upsert_project(conn, later)
    db.upsert_project(conn, earlier)
    assert db.list_projects(conn) == [earlier, later]


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
    db.upsert_project(conn, _sample_project("/repo1", "brd", id="id-1"))
    db.upsert_project(conn, _sample_project("/repo2", "other", id="id-2"))
    assert db.get_project(conn, "/repo2") == _sample_project("/repo2", "other", id="id-2")


def test_get_project_returns_none_when_absent(conn):
    db.init_master_schema(conn)
    assert db.get_project(conn, "/nope") is None


def test_delete_project_removes_matching_row(conn):
    db.init_master_schema(conn)
    db.upsert_project(conn, _sample_project("/repo1", "brd", id="id-1"))
    db.upsert_project(conn, _sample_project("/repo2", "other", id="id-2"))
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
    db.init_project_schema(connection, PROJECT)
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
    db.insert_card(project_conn, PROJECT.id, _sample_card())
    result = db.get_card(project_conn, "c1")
    assert result == _sample_card()


def test_get_card_returns_none_when_missing(project_conn):
    assert db.get_card(project_conn, "nope") is None


def test_update_card_fields(project_conn):
    db.insert_card(project_conn, PROJECT.id, _sample_card())
    db.update_card_fields(project_conn, "c1", title="New title", updated_at="later")
    result = db.get_card(project_conn, "c1")
    assert result.title == "New title"
    assert result.updated_at == "later"
    assert result.description == "desc"  # untouched fields survive


def test_list_cards_no_filter_returns_all(project_conn):
    db.insert_card(project_conn, PROJECT.id, _sample_card("c1"))
    db.insert_card(project_conn, PROJECT.id, _sample_card("c2"))
    results = db.list_cards(project_conn)
    assert {c.id for c in results} == {"c1", "c2"}


def test_list_cards_filters_by_status(project_conn):
    db.insert_card(project_conn, PROJECT.id, _sample_card("c1", status="todo"))
    db.insert_card(project_conn, PROJECT.id, _sample_card("c2", status="done"))
    results = db.list_cards(project_conn, status="done")
    assert [c.id for c in results] == ["c2"]


def test_list_cards_filters_by_parent_id(project_conn):
    db.insert_card(project_conn, PROJECT.id, _sample_card("parent"))
    db.insert_card(project_conn, PROJECT.id, _sample_card("child", parent_id="parent"))
    results = db.list_cards(project_conn, parent_id="parent")
    assert [c.id for c in results] == ["child"]


def test_list_cards_filters_by_explicit_none_parent(project_conn):
    db.insert_card(project_conn, PROJECT.id, _sample_card("top"))
    db.insert_card(project_conn, PROJECT.id, _sample_card("parent2"))
    db.insert_card(project_conn, PROJECT.id, _sample_card("child", parent_id="parent2"))
    results = db.list_cards(project_conn, parent_id=None)
    assert {c.id for c in results} == {"top", "parent2"}


def test_add_and_list_blockers_of(project_conn):
    db.insert_card(project_conn, PROJECT.id, _sample_card("c1"))
    db.insert_card(project_conn, PROJECT.id, _sample_card("c2"))
    db.add_blocked_by_edge(project_conn, "c1", "c2")
    assert db.list_blockers_of(project_conn, "c1") == ["c2"]


def test_remove_blocked_by_edge(project_conn):
    db.insert_card(project_conn, PROJECT.id, _sample_card("c1"))
    db.insert_card(project_conn, PROJECT.id, _sample_card("c2"))
    db.add_blocked_by_edge(project_conn, "c1", "c2")
    db.remove_blocked_by_edge(project_conn, "c1", "c2")
    assert db.list_blockers_of(project_conn, "c1") == []


def test_list_children(project_conn):
    db.insert_card(project_conn, PROJECT.id, _sample_card("parent"))
    db.insert_card(project_conn, PROJECT.id, _sample_card("child1", parent_id="parent"))
    db.insert_card(project_conn, PROJECT.id, _sample_card("child2", parent_id="parent"))
    results = db.list_children(project_conn, "parent")
    assert {c.id for c in results} == {"child1", "child2"}


def test_list_cards_orders_by_created_at(project_conn):
    db.insert_card(project_conn, PROJECT.id, _sample_card("c1", created_at="2026-09-17T12:00:00"))
    db.insert_card(project_conn, PROJECT.id, _sample_card("c2", created_at="2026-09-16T08:00:00"))
    assert [c.id for c in db.list_cards(project_conn)] == ["c2", "c1"]


def test_list_children_orders_by_created_at(project_conn):
    db.insert_card(project_conn, PROJECT.id, _sample_card("parent"))
    db.insert_card(project_conn, PROJECT.id, _sample_card("child1", parent_id="parent", created_at="2026-09-17T12:00:00"),
    )
    db.insert_card(project_conn, PROJECT.id, _sample_card("child2", parent_id="parent", created_at="2026-09-16T08:00:00"),
    )
    results = db.list_children(project_conn, "parent")
    assert [c.id for c in results] == ["child2", "child1"]


def test_delete_card_removes_row(project_conn):
    db.insert_card(project_conn, PROJECT.id, _sample_card("c1"))
    db.delete_card(project_conn, "c1")
    assert db.get_card(project_conn, "c1") is None


def test_delete_card_removes_blocked_by_edges_in_both_directions(project_conn):
    db.insert_card(project_conn, PROJECT.id, _sample_card("c1"))
    db.insert_card(project_conn, PROJECT.id, _sample_card("c2"))
    db.insert_card(project_conn, PROJECT.id, _sample_card("c3"))
    db.add_blocked_by_edge(project_conn, "c1", "c2")
    db.add_blocked_by_edge(project_conn, "c3", "c1")

    db.delete_card(project_conn, "c1")

    assert db.list_blockers_of(project_conn, "c3") == []
    assert db.get_card(project_conn, "c2") is not None


def _count(conn, sql, *params):
    return conn.execute(sql, params).fetchone()[0]


def test_delete_card_removes_incoming_edges_without_fk_cascade(project_conn):
    for card_id in ("c1", "c2", "c3"):
        db.insert_card(project_conn, PROJECT.id, _sample_card(card_id))
    db.add_blocked_by_edge(project_conn, "c3", "c1")
    db.add_blocked_by_edge(project_conn, "c3", "c2")
    project_conn.execute(
        "INSERT INTO refs (src_id, dst_id, origin) VALUES "
        "('c2', 'c1', 'explicit'), ('c3', 'c1', 'link')"
    )
    project_conn.commit()
    project_conn.execute("PRAGMA foreign_keys=OFF")

    db.delete_card(project_conn, "c1")

    assert _count(
        project_conn, "SELECT COUNT(*) FROM blocked_by WHERE blocks_on_id = ?", "c1"
    ) == 0
    assert _count(project_conn, "SELECT COUNT(*) FROM refs WHERE dst_id = ?", "c1") == 0
    assert db.list_blockers_of(project_conn, "c3") == ["c2"]


def test_delete_incoming_edges_does_not_commit(project_conn):
    db.insert_card(project_conn, PROJECT.id, _sample_card("c1"))
    db.insert_card(project_conn, PROJECT.id, _sample_card("c2"))
    db.add_blocked_by_edge(project_conn, "c2", "c1")
    project_conn.execute(
        "INSERT INTO refs (src_id, dst_id, origin) VALUES ('c2', 'c1', 'explicit')"
    )
    project_conn.commit()

    db.delete_incoming_edges(project_conn, "c1")
    assert project_conn.in_transaction
    project_conn.rollback()

    assert db.list_blockers_of(project_conn, "c2") == ["c1"]
    assert _count(project_conn, "SELECT COUNT(*) FROM refs WHERE dst_id = ?", "c1") == 1


def test_insert_card_commits_so_another_connection_sees_it(tmp_path):
    db_path = tmp_path / "project.db"
    writer = db.connect(db_path)
    db.init_project_schema(writer, PROJECT)
    db.insert_card(writer, PROJECT.id, _sample_card())
    reader = db.connect(db_path)
    try:
        assert db.get_card(reader, "c1") == _sample_card()
    finally:
        reader.close()
        writer.close()


def test_update_card_fields_commits_so_another_connection_sees_it(tmp_path):
    db_path = tmp_path / "project.db"
    writer = db.connect(db_path)
    db.init_project_schema(writer, PROJECT)
    db.insert_card(writer, PROJECT.id, _sample_card())
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
    db.init_project_schema(writer, PROJECT)
    db.insert_card(writer, PROJECT.id, _sample_card("c1"))
    db.insert_card(writer, PROJECT.id, _sample_card("c2"))
    db.add_blocked_by_edge(writer, "c1", "c2")
    reader = db.connect(db_path)
    try:
        assert db.list_blockers_of(reader, "c1") == ["c2"]
        db.remove_blocked_by_edge(writer, "c1", "c2")
        assert db.list_blockers_of(reader, "c1") == []
    finally:
        reader.close()
        writer.close()
