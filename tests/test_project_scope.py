import sqlite3

import pytest

from brd import core, db, documents, issues, snapshot
from brd.models import Card
from tests.factories import NOW, OTHER_PROJECT, PROJECT, add_project, make_card


def test_migrate_project_requires_the_project(tmp_path):
    conn = db.connect(tmp_path / "p.db")
    try:
        with pytest.raises(TypeError):
            db.migrate_project(conn)
        with pytest.raises(TypeError):
            db.init_project_schema(conn)
    finally:
        conn.close()


@pytest.mark.parametrize(
    "call",
    [
        lambda conn, root, source: db.insert_card(
            conn, Card("c", "c", None, "todo", None, NOW, NOW)
        ),
        lambda conn, root, source: core.create_card(conn, title="c"),
        lambda conn, root, source: core.import_tree(conn, []),
        lambda conn, root, source: issues.open_issue(conn, title="i"),
        lambda conn, root, source: documents.add(conn, root, source),
        lambda conn, root, source: snapshot.load(conn, root, []),
    ],
    ids=["insert_card", "create_card", "import_tree", "open_issue", "documents.add", "snapshot.load"],
)
def test_insert_paths_require_a_project_id(pconn, tmp_path, call):
    root = tmp_path / "repo"
    source = root / "docs" / "a.md"
    source.parent.mkdir(parents=True)
    source.write_text("")
    with pytest.raises(TypeError):
        call(pconn, root, source)


def _entity_count(conn):
    return conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]


def test_failed_card_insert_leaves_no_entity_row(pconn):
    with pytest.raises(sqlite3.IntegrityError):
        make_card(pconn, "bad", status="blocked")  # CHECK violation on the cards row
    pconn.commit()
    assert _entity_count(pconn) == 0


def test_failed_document_insert_leaves_no_entity_row(pconn, tmp_path, monkeypatch):
    root = tmp_path / "repo"
    source = root / "docs" / "a.md"
    source.parent.mkdir(parents=True)
    source.write_text("")
    documents.add(pconn, PROJECT.id, root, source)
    # A concurrent writer got past the pre-check: the UNIQUE constraint fires.
    monkeypatch.setattr(documents, "_check_unique", lambda *args, **kwargs: None)
    with pytest.raises(sqlite3.IntegrityError):
        documents.add(pconn, PROJECT.id, root, source)
    pconn.commit()
    assert _entity_count(pconn) == 1


def test_snapshot_load_records_its_project(pconn, tmp_path):
    add_project(pconn, OTHER_PROJECT)
    snap = {
        "brd_export": 1,
        "cards": [
            {"id": "c", "title": "C", "description": None, "status": "todo", "blocked_by": [],
             "created_at": NOW, "updated_at": NOW, "children": []}
        ],
        "issues": [
            {"id": "i", "title": "I", "body": None, "status": "open", "close_reason": None,
             "created_at": NOW, "updated_at": NOW}
        ],
        "documents": [
            {"id": "d", "title": "D", "source_path": "docs/d.md", "content": "x",
             "content_hash": "h", "created_at": NOW, "updated_at": NOW}
        ],
    }
    snapshot.load(pconn, OTHER_PROJECT.id, tmp_path, snap)
    rows = {r[0]: r[1] for r in pconn.execute("SELECT id, project_id FROM entities")}
    assert rows == {"c": OTHER_PROJECT.id, "i": OTHER_PROJECT.id, "d": OTHER_PROJECT.id}
    stored = pconn.execute("SELECT project_id FROM documents WHERE id = 'd'").fetchone()
    assert stored[0] == OTHER_PROJECT.id
