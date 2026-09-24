import sqlite3

import pytest

from brd import db, paths

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


def test_fresh_db_gets_version_1_schema(tmp_path):
    conn = db.connect(tmp_path / "p.db")
    db.migrate_project(conn)
    assert {
        "entities", "cards", "blocked_by", "issues", "documents", "comments", "tags", "refs"
    } <= _tables(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1


def test_v0_cards_are_backfilled_into_entities(v0_path):
    conn = db.connect(v0_path)
    db.migrate_project(conn)
    rows = {(r["id"], r["kind"]) for r in conn.execute("SELECT * FROM entities")}
    assert rows == {("p", "card"), ("c", "card"), ("o", "card")}


def test_v0_rows_and_edges_survive(v0_path):
    conn = db.connect(v0_path)
    db.migrate_project(conn)
    assert db.get_card(conn, "c").parent_id == "p"
    assert db.list_blockers_of(conn, "c") == ["o"]


def test_migration_is_idempotent(v0_path):
    conn = db.connect(v0_path)
    db.migrate_project(conn)
    db.migrate_project(conn)
    assert conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 3
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1


def test_foreign_keys_are_on_after_migration(v0_path):
    conn = db.connect(v0_path)
    db.migrate_project(conn)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_deleting_entity_cascades_to_card_and_edges(v0_path):
    conn = db.connect(v0_path)
    db.migrate_project(conn)
    conn.execute("DELETE FROM entities WHERE id = 'o'")
    conn.commit()
    assert db.get_card(conn, "o") is None
    assert db.list_blockers_of(conn, "c") == []


def test_inserting_a_card_registers_its_entity(tmp_path):
    conn = db.connect(tmp_path / "p.db")
    db.migrate_project(conn)
    conn.execute(INSERT_CARD, ("x", "x", None))
    kind = conn.execute("SELECT kind FROM entities WHERE id = 'x'").fetchone()[0]
    assert kind == "card"


def test_dangling_legacy_rows_are_dropped_not_fatal(tmp_path):
    path = tmp_path / "project.db"
    _make_v0(
        path,
        cards=[("a", "ghost-parent")],
        edges=[("a", "ghost-blocker"), ("ghost-card", "a")],
    )
    conn = db.connect(path)
    db.migrate_project(conn)
    assert db.get_card(conn, "a").parent_id is None
    assert conn.execute("SELECT COUNT(*) FROM blocked_by").fetchone()[0] == 0


def test_delete_card_goes_through_entities(v0_path):
    conn = db.connect(v0_path)
    db.migrate_project(conn)
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
                db.migrate_project(conn)
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
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert [r[0] for r in conn.execute("SELECT id FROM entities ORDER BY id")] == ["c", "p"]
        conn.close()
