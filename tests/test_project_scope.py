import re
import sqlite3

import pytest

from brd import comments, core, db, documents, entities, issues, snapshot, views
from brd.cli import cards as cli_cards
from brd.errors import (
    CardNotFoundError,
    DocumentNotFoundError,
    EntityNotFoundError,
    InvalidBlockerError,
    IssueNotFoundError,
)
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
        for table in (
            "entities", "cards", "issues", "documents", "blocked_by", "comments", "tags", "refs"
        )
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
    pytest.param(
        lambda c: core.block_card(c, P, "q1", "p1"), "q1", "card", id="block_card_foreign_source"
    ),
    pytest.param(
        lambda c: core.unblock_card(c, P, "q1", "p2"), "q1", "card",
        id="unblock_card_foreign_source",
    ),
    pytest.param(
        lambda c: core.block_card(c, P, "p1", "q1"), "q1", "card or issue",
        id="block_card_foreign_card_target",
    ),
    pytest.param(
        lambda c: core.block_card(c, P, "p1", "qi"), "qi", "card or issue",
        id="block_card_foreign_issue_target",
    ),
    pytest.param(
        lambda c: core.block_card(c, P, "p1", "qd"), "qd", "card or issue",
        id="block_card_foreign_document_target",
    ),
    pytest.param(
        lambda c: core.create_card(c, P, "new", blocked_by=["p2", "q1"]), "q1", "card or issue",
        id="create_card_foreign_blocker",
    ),
    pytest.param(
        lambda c: issues.open_issue(c, P, "t", blocks=["p1", "q1"]), "q1", "card",
        id="open_issue_foreign_blocks",
    ),
    pytest.param(
        lambda c: comments.add(c, P, "q1", "hi", "alice"), "q1", "card",
        id="comments_add_foreign_card",
    ),
    pytest.param(
        lambda c: core.next_cards(c, P, parent_id="q1"), "q1", "card",
        id="next_cards_foreign_parent",
    ),
    pytest.param(
        lambda c: core.build_tree(c, P, root_id="q1"), "q1", "card",
        id="build_tree_foreign_root",
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


def test_a_document_of_this_project_still_cannot_block(two):
    make_document(two, "pd", "pnotes")
    with pytest.raises(InvalidBlockerError):
        core.block_card(two, P, "p1", "pd")


def test_a_missing_blocker_is_unchanged(two):
    with pytest.raises(CardNotFoundError, match=r"^no card or issue with id nope$"):
        core.block_card(two, P, "p1", "nope")


def test_list_cards_returns_only_the_projects_cards(two):
    assert {c.id for c in db.list_cards(two, P)} == {"p1", "p2"}
    assert {c.id for c in db.list_cards(two, P, status="todo")} == {"p1", "p2"}
    assert {c.id for c in db.list_cards(two, P, parent_id=None)} == {"p1", "p2"}
    assert {c.id for c in db.list_cards(two, Q, parent_id=None)} == {"q1"}


def test_list_cards_with_a_foreign_parent_is_empty(two):
    assert db.list_cards(two, P, parent_id="q1") == []


def test_next_cards_skips_other_projects_and_follows_edges_across_them(two):
    assert {c.id for c in core.next_cards(two, P)} == {"p1", "p2"}
    make_card(two, "q-blocker", project_id=Q)
    make_card(two, "p-blocked")
    db.add_blocked_by_edge(two, "p-blocked", "q-blocker")
    assert core.resolve_status(two, db.get_card(two, "p-blocked")) == "blocked"
    assert {c.id for c in db.list_cards(two, P)} == {"p1", "p2", "p-blocked"}
    assert {c.id for c in core.next_cards(two, P)} == {"p1", "p2"}
    db.update_card_fields(two, "q-blocker", status="done")
    assert {c.id for c in core.next_cards(two, P)} == {"p1", "p2", "p-blocked"}


def test_build_tree_holds_only_the_projects_roots(two):
    make_card(two, "p-child", parent_id="p1")
    tree = core.build_tree(two, P)
    assert {node["id"] for node in tree} == {"p1", "p2"}
    p1 = next(node for node in tree if node["id"] == "p1")
    assert [child["id"] for child in p1["children"]] == ["p-child"]


def _tree_ids(nodes):
    return [node["id"] for node in nodes] + [
        child_id for node in nodes for child_id in _tree_ids(node["children"])
    ]


def test_export_cards_hold_only_the_projects_cards(two, tmp_path):
    assert set(_tree_ids(snapshot.export(two, P, tmp_path)["cards"])) == {"p1", "p2"}


@pytest.mark.parametrize(
    ("entity_id", "owner", "expected"),
    [
        ("p1", PROJECT, lambda c, root: views.card_detail(c, db.get_card(c, "p1"))),
        ("q1", OTHER_PROJECT, lambda c, root: views.card_detail(c, db.get_card(c, "q1"))),
        ("qi", OTHER_PROJECT, lambda c, root: views.issue_detail(c, issues.require(c, Q, "qi"))),
        (
            "qd",
            OTHER_PROJECT,
            lambda c, root: views.document_detail(
                c, documents.require(c, "qd"), documents.sync(c, root, documents.require(c, "qd"))
            ),
        ),
    ],
    ids=["own_card", "foreign_card", "foreign_issue", "foreign_document"],
)
def test_detail_is_global_and_names_the_owner(two, tmp_path, entity_id, owner, expected):
    shown = views.detail(two, tmp_path, entity_id)
    assert shown.pop("project") == {"id": owner.id, "name": owner.name}
    assert shown == expected(two, tmp_path)


def test_detail_of_a_missing_id_is_unchanged(two, tmp_path):
    with pytest.raises(CardNotFoundError, match=r"^no card, issue, or document with id nope$"):
        views.detail(two, tmp_path, "nope")


def test_card_detail_has_no_project_key(two):
    assert "project" not in views.card_detail(two, db.get_card(two, "p1"))


@pytest.mark.parametrize(
    ("entity_id", "error", "what"),
    [
        ("q1", CardNotFoundError, "card"),
        ("qi", IssueNotFoundError, "issue"),
        ("qd", DocumentNotFoundError, "document"),
    ],
)
def test_require_in_project_names_the_owner_of_a_foreign_entity(two, entity_id, error, what):
    with pytest.raises(error, match=_foreign(entity_id, what)):
        entities.require_in_project(two, P, entity_id)


def test_require_in_project_returns_the_kind_of_an_own_entity(two):
    make_issue(two, "pi")
    make_document(two, "pd", "pnotes")
    assert entities.require_in_project(two, P, "p1") == "card"
    assert entities.require_in_project(two, P, "pi") == "issue"
    assert entities.require_in_project(two, P, "pd") == "document"
    assert entities.require_in_project(two, Q, "q1") == "card"


def test_require_in_project_on_a_missing_id_is_unchanged(two):
    with pytest.raises(EntityNotFoundError, match=r"^no entity with id nope$") as raised:
        entities.require_in_project(two, P, "nope")
    assert type(raised.value) is EntityNotFoundError


def test_list_issues_returns_only_the_projects_issues(two):
    make_issue(two, "pi")
    make_issue(two, "pi-closed", status="closed")
    assert [i.id for i in issues.list_issues(two, P)] == ["pi", "pi-closed"]
    assert [i.id for i in issues.list_issues(two, P, "open")] == ["pi"]
    assert [i.id for i in issues.list_issues(two, Q)] == ["qi"]


def test_require_issue_returns_the_projects_issue(two):
    make_issue(two, "pi")
    assert issues.require(two, P, "pi").id == "pi"


@pytest.mark.parametrize("missing", ["nope", "p1", "q1"])
def test_require_issue_on_a_missing_or_non_issue_id_is_unchanged(two, missing):
    with pytest.raises(IssueNotFoundError, match=rf"^no issue with id {missing}$"):
        issues.require(two, P, missing)


SCOPED_REFUSED = [
    pytest.param(
        lambda c: issues.update(c, P, "qi", title="x"), IssueNotFoundError, "qi", "issue",
        id="issue_update",
    ),
    pytest.param(
        lambda c: issues.update(c, P, "qi"), IssueNotFoundError, "qi", "issue",
        id="issue_update_no_fields",
    ),
    pytest.param(
        lambda c: issues.update(c, P, "qi", body="[[qnotes]]"), IssueNotFoundError, "qi",
        "issue", id="issue_update_body",
    ),
    pytest.param(
        lambda c: issues.close(c, P, "qi"), IssueNotFoundError, "qi", "issue", id="issue_close"
    ),
    pytest.param(
        lambda c: issues.reopen(c, P, "qi"), IssueNotFoundError, "qi", "issue",
        id="issue_reopen",
    ),
    pytest.param(
        lambda c: issues.open_issue(c, P, "t", ref_ids=["q1"]), CardNotFoundError, "q1", "card",
        id="open_issue_foreign_ref",
    ),
    pytest.param(
        lambda c: issues.open_issue(c, P, "t", ref_ids=["p1", "qd"]), DocumentNotFoundError,
        "qd", "document", id="open_issue_mixed_refs",
    ),
    pytest.param(
        lambda c: cli_cards.delete_entity(c, P, "qi", False), IssueNotFoundError, "qi", "issue",
        id="delete_entity_issue",
    ),
]


@pytest.mark.parametrize(("call", "error", "foreign_id", "what"), SCOPED_REFUSED)
def test_scoped_refusal_names_the_owner_and_writes_nothing(two, call, error, foreign_id, what):
    before = _state(two)
    with pytest.raises(error, match=_foreign(foreign_id, what)):
        call(two)
    assert _state(two) == before
