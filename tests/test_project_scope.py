import re
import sqlite3
from pathlib import Path

import pytest

from brd import comments, core, db, documents, entities, issues, pretty, refs, snapshot, views
from brd.cli import cards as cli_cards
from brd.errors import (
    CardNotFoundError,
    DocumentNotFoundError,
    DuplicatePathError,
    DuplicateStemError,
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
        ("p1", PROJECT, lambda c: views.card_detail(c, db.get_card(c, "p1"))),
        ("q1", OTHER_PROJECT, lambda c: views.card_detail(c, db.get_card(c, "q1"))),
        ("qi", OTHER_PROJECT, lambda c: views.issue_detail(c, issues.require(c, Q, "qi"))),
        (
            "qd",
            OTHER_PROJECT,
            lambda c: views.document_detail(
                c,
                documents.require(c, Q, "qd"),
                documents.sync(c, Path(OTHER_PROJECT.root_path), documents.require(c, Q, "qd")),
            ),
        ),
    ],
    ids=["own_card", "foreign_card", "foreign_issue", "foreign_document"],
)
def test_detail_is_global_and_names_the_owner(two, entity_id, owner, expected):
    shown = views.detail(two, entity_id)
    assert shown.pop("project") == {"id": owner.id, "name": owner.name}
    assert shown == expected(two)


def test_detail_of_a_missing_id_is_unchanged(two):
    with pytest.raises(CardNotFoundError, match=r"^no card, issue, or document with id nope$"):
        views.detail(two, "nope")


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


@pytest.fixture
def root(tmp_path):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    return repo


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _doc_state(conn, doc_id):
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    backup = documents.backup_path(conn, doc_id)
    return (tuple(row) if row else None, backup.read_text() if backup.is_file() else None)


def test_require_document_on_a_missing_or_non_document_id_is_unchanged(two):
    for missing in ("nope", "p1"):
        with pytest.raises(DocumentNotFoundError, match=rf"^no document with id {missing}$"):
            documents.require(two, P, missing)


def test_list_and_sync_all_cover_only_the_projects_documents(two, root):
    make_document(two, "pd", "pnotes", content="old")
    _write(root, "docs/pnotes.md", "new")
    _write(root, "docs/qnotes.md", "changed")  # Q's source path, under P's root
    q_before = _doc_state(two, "qd")
    assert [d.id for d in documents.list_all(two, P)] == ["pd"]
    assert [d.id for d in documents.list_all(two, Q)] == ["qd"]
    results = documents.sync_all(two, P, root)
    assert {k: v.source_state for k, v in results.items()} == {"pd": "updated"}
    assert _doc_state(two, "qd") == q_before


def test_document_uniqueness_is_per_project(two, root):
    make_document(two, "qn", "notes", project_id=Q)  # Q's docs/notes.md
    mine = documents.add(two, P, root, _write(root, "docs/notes.md", "p"))
    assert (mine.source_path, mine.stem) == ("docs/notes.md", "notes")
    with pytest.raises(DuplicateStemError):
        documents.add(two, P, root, _write(root, "other/Notes.md", ""))
    with pytest.raises(DuplicatePathError):
        documents.add(two, P, root, root / "docs" / "notes.md")
    second = documents.add(two, P, root, _write(root, "docs/second.md", ""))
    moved, _ = documents.update(
        two, P, root, second.id, new_path=_write(root, "elsewhere/qnotes.md", "")
    )
    assert moved.stem == "qnotes"  # Q's qd has this stem too


DOC_REFUSED = [
    pytest.param(
        lambda c, root: documents.update(c, P, root, "qd", title="x"), id="update_title"
    ),
    pytest.param(
        lambda c, root: documents.update(c, P, root, "qd", new_path=root / "docs" / "moved.md"),
        id="update_path",
    ),
    pytest.param(lambda c, root: documents.update(c, P, root, "qd"), id="update_sync_only"),
    pytest.param(
        lambda c, root: documents.restore(c, P, root, "qd", force=True), id="restore"
    ),
    pytest.param(lambda c, root: documents.delete(c, P, "qd"), id="delete"),
    pytest.param(
        lambda c, root: cli_cards.delete_entity(c, P, "qd", False), id="delete_entity"
    ),
]


@pytest.mark.parametrize("call", DOC_REFUSED)
def test_a_foreign_document_is_refused_and_untouched(two, root, call):
    _write(root, "docs/moved.md", "moved")
    _write(root, "docs/qnotes.md", "changed")
    before = _doc_state(two, "qd")
    with pytest.raises(DocumentNotFoundError, match=_foreign("qd", "document")):
        call(two, root)
    assert _doc_state(two, "qd") == before
    assert (root / "docs" / "qnotes.md").read_text() == "changed"


def test_show_syncs_only_the_owning_projects_documents(two, root):
    two.execute("UPDATE projects SET root_path = ? WHERE id = ?", (str(root), P))
    two.commit()
    make_document(two, "pd", "pnotes", content="old")
    _write(root, "docs/pnotes.md", "new")
    _write(root, "docs/qnotes.md", "changed")
    p_before, q_before = _doc_state(two, "pd"), _doc_state(two, "qd")
    assert views.detail(two, "qd")["source_state"] == "missing"  # nothing under /other
    assert _doc_state(two, "pd") == p_before
    views.detail(two, "p1")
    assert _doc_state(two, "qd") == q_before
    assert _doc_state(two, "pd") != p_before  # P's own documents are synced


def test_export_holds_only_the_projects_issues_and_documents(two, root):
    make_issue(two, "pi")
    make_document(two, "pd", "pnotes")
    _write(root, "docs/qnotes.md", "changed")
    q_before = _doc_state(two, "qd")
    data = snapshot.export(two, P, root)
    assert [i["id"] for i in data["issues"]] == ["pi"]
    assert [d["id"] for d in data["documents"]] == ["pd"]
    assert _doc_state(two, "qd") == q_before


Q_UUID = "abababab-abab-4bab-8bab-abababababab"


def _comment(conn, comment_id, entity_id, body):
    conn.execute(
        "INSERT INTO comments (id, entity_id, author, body, created_at) "
        "VALUES (?, ?, 'me', ?, ?)",
        (comment_id, entity_id, body, NOW),
    )
    conn.commit()


def _link_targets(conn, entity_id):
    return {r["id"] for r in refs.outgoing(conn, entity_id) if r["origin"] == "link"}


@pytest.fixture
def notes(two):
    """Both projects have a document with stem `notes`: pn in P, qn in Q."""
    make_document(two, "pn", "notes", title="P notes")
    make_document(two, "qn", "notes", title="Q notes", project_id=Q)
    return two


def test_resolve_stems_within_the_project_and_uuids_globally(notes):
    assert refs.resolve(notes, P, "notes") == "pn"
    assert refs.resolve(notes, P, "docs/NOTES.md") == "pn"
    assert refs.resolve(notes, Q, "notes") == "qn"
    assert refs.resolve(notes, P, "qnotes") is None  # only Q has it
    make_card(notes, Q_UUID, project_id=Q)
    assert refs.resolve(notes, P, Q_UUID) == Q_UUID


def test_reindex_resolves_stems_against_the_owning_project(notes):
    make_card(notes, "pc", description="see [[notes]]")
    make_card(notes, "qc", description="see [[notes]]", project_id=Q)
    make_card(notes, Q_UUID, project_id=Q)
    make_card(notes, "pu", description=f"see [[{Q_UUID}]]")
    for card_id in ("pc", "qc", "pu"):
        refs.reindex(notes, card_id)
    assert _link_targets(notes, "pc") == {"pn"}
    assert _link_targets(notes, "qc") == {"qn"}
    assert _link_targets(notes, "pu") == {Q_UUID}


def test_a_stem_only_another_project_has_stays_unresolved(two):
    make_card(two, "pc")
    _comment(two, "k-p", "pc", "see [[qnotes]]")
    refs.reindex(two, "pc")
    assert _link_targets(two, "pc") == set()
    assert pretty.text(two, P, "see [[qnotes]]") == "see [[qnotes]] (unresolved)"


def test_reindex_mentions_rescans_only_the_projects_texts(two):
    make_card(two, "pc", description="[[notes]]")
    make_issue(two, "pi", body="[[notes]]")
    make_document(two, "ph", "phub", content="see [[notes]]")
    _comment(two, "k-p", "p1", "[[notes]]")
    make_card(two, "qc", description="[[notes]]", project_id=Q)
    _comment(two, "k-q", "q1", "[[notes]]")
    # Seeded without reindexing: no entity has a link ref yet.
    make_document(two, "pn", "notes")
    make_document(two, "qn", "notes", project_id=Q)
    refs.reindex_mentions(two, P, "notes")
    for entity_id in ("pc", "pi", "ph", "p1"):
        assert _link_targets(two, entity_id) == {"pn"}
    assert _link_targets(two, "qc") == set()  # not rescanned, though Q has `notes`
    assert _link_targets(two, "q1") == set()


def test_adding_or_renaming_a_document_rescans_only_its_project(two, root):
    make_document(two, "qn", "notes", project_id=Q)
    make_document(two, "qr", "renamed", project_id=Q)
    make_card(two, "qc", description="[[notes]] and [[renamed]]", project_id=Q)
    make_card(two, "pc", description="[[notes]] and [[renamed]]")
    added = documents.add(two, P, root, _write(root, "docs/notes.md", ""))
    assert _link_targets(two, "pc") == {added.id}
    assert _link_targets(two, "qc") == set()
    old = documents.add(two, P, root, _write(root, "docs/old.md", ""))
    (root / "docs" / "old.md").rename(root / "docs" / "renamed.md")
    documents.update(two, P, root, old.id, new_path=root / "docs" / "renamed.md")
    assert _link_targets(two, "pc") == {added.id, old.id}
    assert _link_targets(two, "qc") == set()


def test_pretty_renders_stem_links_against_the_owning_project(notes):
    make_card(notes, "qc", description="see [[notes]]", project_id=Q)
    _comment(notes, "k-q", "qc", "also [[notes]]")
    shown = views.detail(notes, "qc")
    out = pretty.render_detail(notes, shown)
    assert "see [[Q notes]]" in out
    assert "  also [[Q notes]]" in out
    assert "  also [[Q notes]]" in pretty.render_comments(notes, shown["comments"])
    assert pretty.text(notes, P, "[[notes]]") == "[[P notes]]"
