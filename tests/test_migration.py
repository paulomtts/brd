import sqlite3

import pytest

from brd import db, paths
from tests.factories import PROJECT, make_card, make_document

V0_SCHEMA = [
    """CREATE TABLE cards (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        description TEXT,
        status TEXT NOT NULL CHECK (status IN ('todo', 'in_progress', 'done')),
        parent_id TEXT REFERENCES cards(id),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE blocked_by (
        card_id TEXT NOT NULL REFERENCES cards(id),
        blocks_on_id TEXT NOT NULL REFERENCES cards(id),
        PRIMARY KEY (card_id, blocks_on_id)
    )""",
]

INSERT_CARD = (
    "INSERT INTO cards (id, title, description, status, parent_id, created_at, "
    "updated_at) VALUES (?, ?, NULL, 'todo', ?, 'now', 'now')"
)


def _make_v0(path, cards, edges):
    conn = sqlite3.connect(path)  # foreign keys OFF by default, like a legacy db
    for statement in V0_SCHEMA:
        conn.execute(statement)
    for card_id, parent_id in cards:
        conn.execute(INSERT_CARD, (card_id, card_id, parent_id))
    for edge in edges:
        conn.execute("INSERT INTO blocked_by VALUES (?, ?)", edge)
    conn.commit()
    conn.close()


@pytest.fixture
def v0_path(tmp_path):
    path = tmp_path / "project.db"
    _make_v0(path, cards=[("p", None), ("c", "p"), ("o", None)], edges=[("c", "o")])
    return path


def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _names(conn, type_):
    return {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = ?", (type_,))
    }


def _rows(conn, table, columns="*"):
    return sorted(tuple(r) for r in conn.execute(f"SELECT {columns} FROM {table}"))


REGISTER_TRIGGERS = {"cards_register_entity", "issues_register_entity", "documents_register_entity"}
V4_INDEXES = {"entities_project", "blocked_by_target", "refs_target"}
PROJECT_ROW = (PROJECT.id, PROJECT.name, PROJECT.root_path, PROJECT.created_at)


def _make_v3(path):
    # A faithful v3 board: the real historical migrations, then raw inserts
    # that the v3 register triggers turn into entities rows.
    conn = sqlite3.connect(path)  # foreign keys OFF, like the migrations run
    db._migrate_to_v1(conn)
    db._migrate_to_v2(conn)
    db._migrate_to_v3(conn)
    conn.execute("PRAGMA user_version = 3")
    conn.execute(INSERT_CARD, ("p", "p", None))
    conn.execute(INSERT_CARD, ("c", "c", "p"))
    conn.execute(
        "INSERT INTO issues (id, title, body, status, close_reason, created_at, updated_at) "
        "VALUES ('i', 'Q', 'body', 'open', NULL, 'now', 'now')"
    )
    conn.execute(
        "INSERT INTO documents (id, title, source_path, stem, content_hash, created_at, "
        "updated_at) VALUES ('d', 'Notes', 'docs/notes.md', 'notes', 'h', 'now', 'now')"
    )
    conn.execute("INSERT INTO blocked_by (card_id, blocks_on_id) VALUES ('c', 'p')")
    conn.execute("INSERT INTO blocked_by (card_id, blocks_on_id) VALUES ('p', 'i')")
    conn.execute(
        "INSERT INTO comments (id, entity_id, author, body, created_at) "
        "VALUES ('k', 'c', 'me', 'hi', 'now')"
    )
    conn.execute("INSERT INTO tags (entity_id, tag) VALUES ('d', 'design')")
    conn.execute("INSERT INTO refs (src_id, dst_id, origin) VALUES ('c', 'd', 'explicit')")
    conn.execute("INSERT INTO refs (src_id, dst_id, origin) VALUES ('i', 'c', 'link')")
    conn.commit()
    # The v4 rename only works if the trigger drop really comes first; that
    # is only exercised if the fixture really carries every register trigger.
    assert _names(conn, "trigger") == REGISTER_TRIGGERS
    conn.close()


V3_UNCHANGED_TABLES = ("cards", "issues", "comments", "tags", "blocked_by", "refs")
DOC_COLUMNS = "id, title, source_path, stem, content_hash, created_at, updated_at"


def test_fresh_db_gets_current_schema(tmp_path):
    conn = db.connect(tmp_path / "p.db")
    db.migrate_project(conn, PROJECT)
    assert db.SCHEMA_VERSION == 4
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
    assert _tables(conn) == {
        "projects", "entities", "cards", "blocked_by", "issues", "documents",
        "comments", "tags", "refs",
    }
    assert _rows(conn, "projects") == [PROJECT_ROW]
    assert V4_INDEXES <= _names(conn, "index")
    assert not {name for name in _names(conn, "trigger") if name.endswith("_register_entity")}
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_v0_cards_are_backfilled_into_entities(v0_path):
    conn = db.connect(v0_path)
    db.migrate_project(conn, PROJECT)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    assert _rows(conn, "entities", "id, kind, project_id") == [
        ("c", "card", PROJECT.id), ("o", "card", PROJECT.id), ("p", "card", PROJECT.id),
    ]


def test_v0_rows_and_edges_survive(v0_path):
    conn = db.connect(v0_path)
    db.migrate_project(conn, PROJECT)
    assert db.get_card(conn, "c").parent_id == "p"
    assert db.list_blockers_of(conn, "c") == ["o"]


def test_migration_is_idempotent(v0_path):
    conn = db.connect(v0_path)
    db.migrate_project(conn, PROJECT)
    db.migrate_project(conn, PROJECT)
    assert conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 3
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_foreign_keys_are_on_after_migration(v0_path):
    conn = db.connect(v0_path)
    db.migrate_project(conn, PROJECT)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_deleting_entity_cascades_to_card_and_edges(v0_path):
    conn = db.connect(v0_path)
    db.migrate_project(conn, PROJECT)
    db.delete_card(conn, "o")
    assert db.get_card(conn, "o") is None
    assert db.list_blockers_of(conn, "c") == []


def test_dangling_legacy_rows_are_dropped_not_fatal(tmp_path):
    path = tmp_path / "project.db"
    _make_v0(
        path,
        cards=[("a", "ghost-parent")],
        edges=[("a", "ghost-blocker"), ("ghost-card", "a")],
    )
    conn = db.connect(path)
    db.migrate_project(conn, PROJECT)
    assert db.get_card(conn, "a").parent_id is None
    assert conn.execute("SELECT COUNT(*) FROM blocked_by").fetchone()[0] == 0
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert _rows(conn, "entities", "id, project_id") == [("a", PROJECT.id)]


def test_delete_card_goes_through_entities(v0_path):
    conn = db.connect(v0_path)
    db.migrate_project(conn, PROJECT)
    db.delete_card(conn, "o")
    assert conn.execute("SELECT COUNT(*) FROM entities WHERE id = 'o'").fetchone()[0] == 0


def test_docs_dir_sits_next_to_the_db(tmp_path):
    conn = db.connect(tmp_path / "project.db")
    assert db.docs_dir(conn).resolve() == (tmp_path / "project.docs").resolve()


def test_project_docs_dir_matches_db_path(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    repo.mkdir()
    assert paths.project_docs_dir(repo) == paths.project_db_path(repo).with_suffix(".docs")


def test_concurrent_first_run_migrations_all_succeed(tmp_path):
    import threading

    for attempt in range(5):
        path = tmp_path / f"race{attempt}.db"
        _make_v0(path, cards=[("p", None), ("c", "p")], edges=[])
        # Boards made by v0 brd were already WAL (journal mode persists).
        legacy = sqlite3.connect(path)
        legacy.execute("PRAGMA journal_mode=WAL")
        legacy.close()
        barrier = threading.Barrier(4, timeout=20)
        errors = []

        def migrate():
            try:
                conn = db.connect(path)
                barrier.wait()
                db.migrate_project(conn, PROJECT)
                conn.close()
            except Exception as exc:  # noqa: BLE001 — collected and asserted below
                errors.append(exc)

        threads = [threading.Thread(target=migrate) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == []
        conn = db.connect(path)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert [r[0] for r in conn.execute("SELECT id FROM entities ORDER BY id")] == ["c", "p"]
        conn.close()


def test_migration_preserves_cards_and_accepts_new_statuses(v0_path):
    conn = db.connect(v0_path)
    db.migrate_project(conn, PROJECT)

    assert [r["id"] for r in conn.execute("SELECT id FROM cards ORDER BY id")] == ["c", "o", "p"]
    assert conn.execute("SELECT COUNT(*) FROM blocked_by").fetchone()[0] == 1
    for status in ("merged", "canceled", "archived"):
        conn.execute("UPDATE cards SET status = ? WHERE id = 'o'", (status,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE cards SET status = 'blocked' WHERE id = 'o'")


def _make_v1(path):
    conn = sqlite3.connect(path)
    db._migrate_to_v1(conn)
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()


def _make_v2_without_archived(path):
    conn = sqlite3.connect(path)
    db._migrate_to_v1(conn)
    # The v2 shape: the pre-archived CHECK.
    conn.execute("DROP TRIGGER cards_register_entity")
    conn.execute("DROP TABLE cards")
    conn.execute(db._cards_sql("cards", ("todo", "in_progress", "done", "merged", "canceled")))
    conn.execute(db._register_trigger("cards", "card"))
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()


@pytest.mark.parametrize("make_board", [_make_v1, _make_v2_without_archived])
def test_v1_and_v2_boards_upgrade_to_v4_and_accept_archived(tmp_path, make_board):
    path = tmp_path / "p.db"
    make_board(path)

    conn = db.connect(path)
    db.migrate_project(conn, PROJECT)

    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    make_card(conn, "x", status="archived")
    row = conn.execute("SELECT kind, project_id FROM entities WHERE id = 'x'").fetchone()
    assert tuple(row) == ("card", PROJECT.id)


def test_v3_board_migrates_to_v4_with_project_id(tmp_path):
    path = tmp_path / "project.db"
    _make_v3(path)
    v3 = sqlite3.connect(path)
    before = {table: _rows(v3, table) for table in V3_UNCHANGED_TABLES}
    before_documents = _rows(v3, "documents", DOC_COLUMNS)
    before_entities = _rows(v3, "entities", "id, kind")
    v3.close()

    conn = db.connect(path)
    db.migrate_project(conn, PROJECT)

    assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
    assert {table: _rows(conn, table) for table in V3_UNCHANGED_TABLES} == before
    assert _rows(conn, "documents", DOC_COLUMNS) == before_documents
    assert _rows(conn, "entities", "id, kind") == before_entities
    assert _rows(conn, "entities", "DISTINCT project_id") == [(PROJECT.id,)]
    assert _rows(conn, "documents", "DISTINCT project_id") == [(PROJECT.id,)]
    assert _rows(conn, "projects") == [PROJECT_ROW]
    assert not _names(conn, "trigger") & REGISTER_TRIGGERS
    assert V4_INDEXES <= _names(conn, "index")
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_v4_migration_failure_leaves_v3_board_intact(tmp_path, monkeypatch):
    path = tmp_path / "project.db"
    _make_v3(path)
    real_migrate_to_v4 = db._migrate_to_v4

    def migrate_then_fail(conn, project):
        real_migrate_to_v4(conn, project)
        raise RuntimeError("boom")

    monkeypatch.setattr(db, "_migrate_to_v4", migrate_then_fail)
    conn = db.connect(path)
    with pytest.raises(RuntimeError, match="boom"):
        db.migrate_project(conn, PROJECT)

    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    assert REGISTER_TRIGGERS <= _names(conn, "trigger")
    assert "projects" not in _tables(conn)
    assert _rows(conn, "entities", "id, kind") == [
        ("c", "card"), ("d", "document"), ("i", "issue"), ("p", "card"),
    ]
    assert len(_rows(conn, "cards")) == 2
    assert len(_rows(conn, "documents")) == 1


def test_migrated_board_still_rejects_case_only_stem_collision(tmp_path):
    path = tmp_path / "project.db"
    _make_v3(path)
    conn = db.connect(path)
    db.migrate_project(conn, PROJECT)
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        make_document(conn, "d2", "Notes")  # docs/Notes.md vs the copied docs/notes.md
