import re
import sqlite3

import pytest

from brd import comments, core, db, documents, issues, snapshot, views
from brd.cli import cards as cli_cards
from brd.errors import CardNotFoundError, InvalidBlockerError
from brd.models import Card
from tests.factories import (
    NOW,
    OTHER_PROJECT,
    PROJECT,
    add_project,
    make_card,
    make_document,
    make_issue,
)

P = PROJECT.id
Q = OTHER_PROJECT.id


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


@pytest.fixture
def two(pconn):
    """P owns cards p1 and p2. Q owns card q1 (parent of q-child, blocked by
    p2 through a directly seeded cross-project edge), issue qi and
    document qd."""
    add_project(pconn, OTHER_PROJECT)
    make_card(pconn, "p1")
    make_card(pconn, "p2")
    make_card(pconn, "q1", project_id=Q)
    make_card(pconn, "q-child", parent_id="q1", project_id=Q)
    make_issue(pconn, "qi", project_id=Q)
    make_document(pconn, "qd", "qnotes", content="q body", project_id=Q)
    db.add_blocked_by_edge(pconn, "q1", "p2")
    return pconn


def test_in_project_filters_a_raw_query_to_the_bound_project(two):
    query = f"SELECT cards.id FROM cards {db.in_project('cards.id')} ORDER BY cards.id"
    assert [row["id"] for row in two.execute(query, (P,))] == ["p1", "p2"]
    assert [row["id"] for row in two.execute(query, (Q,))] == ["q-child", "q1"]


def test_owner_of_returns_the_owning_project(two):
    assert db.owner_of(two, "p1") == PROJECT
    assert db.owner_of(two, "q1") == OTHER_PROJECT
    assert db.owner_of(two, "qi") == OTHER_PROJECT
    assert db.owner_of(two, "qd") == OTHER_PROJECT
    assert db.owner_of(two, "nope") is None


def _foreign(entity_id, what="card"):
    return re.escape(
        f"no {what} with id {entity_id} in this project; "
        f"it belongs to project {OTHER_PROJECT.name} ({OTHER_PROJECT.id})"
    )


def _state(conn):
    return {
        table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2")]
        for table in ("entities", "cards", "issues", "blocked_by", "comments")
    }


REFUSED = [
    pytest.param(
        lambda c: core.update_card(c, P, "q1", title="x"), "q1", "card", id="update_card"
    ),
    pytest.param(
        lambda c: core.update_card(c, P, "q1", status="done"), "q1", "card",
        id="update_card_status",
    ),
    pytest.param(
        lambda c: core.update_card(c, P, "q-child", parent_id=core.CLEAR_PARENT),
        "q-child", "card", id="update_card_clear_parent",
    ),
    pytest.param(
        lambda c: core.update_card(c, P, "p1", title="x", parent_id="q1"), "q1", "card",
        id="update_card_foreign_parent",
    ),
    pytest.param(
        lambda c: core.create_card(c, P, "new", parent_id="q1"), "q1", "card",
        id="create_card_foreign_parent",
    ),
    pytest.param(lambda c: core.delete_card(c, P, "q1"), "q1", "card", id="delete_card"),
    pytest.param(
        lambda c: core.delete_card(c, P, "q1", cascade=True), "q1", "card",
        id="delete_card_cascade",
    ),
    pytest.param(
        lambda c: cli_cards.delete_entity(c, P, "q1", True), "q1", "card", id="delete_entity"
    ),
]


@pytest.mark.parametrize(("call", "foreign_id", "what"), REFUSED)
def test_refused_call_names_the_owner_and_writes_nothing(two, call, foreign_id, what):
    before = _state(two)
    with pytest.raises(CardNotFoundError, match=_foreign(foreign_id, what)):
        call(two)
    assert _state(two) == before


def test_require_card_returns_the_projects_card(two):
    assert core.require_card(two, P, "p1").id == "p1"


def test_require_card_on_a_missing_id_is_unchanged(two):
    with pytest.raises(CardNotFoundError, match=r"^no card with id nope$"):
        core.require_card(two, P, "nope")


def test_update_card_on_a_foreign_issue_still_says_no_card(two):
    with pytest.raises(CardNotFoundError, match=r"^no card with id qi$"):
        core.update_card(two, P, "qi", title="x")
