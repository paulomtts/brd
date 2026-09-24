import pytest

from brd import refs
from brd.errors import EntityNotFoundError, SelfReferenceError
from tests.factories import make_card, make_document

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
D = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
E = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"


def out(conn, entity_id):
    return {(r["id"], r["origin"]) for r in refs.outgoing(conn, entity_id)}


def test_resolve_uuid(pconn):
    make_card(pconn, A)
    assert refs.resolve(pconn, A) == A
    assert refs.resolve(pconn, A.upper()) == A
    assert refs.resolve(pconn, B) is None


@pytest.mark.parametrize(
    "target",
    ["design notes", "Design Notes", "Design Notes.md", "docs/Design Notes", "docs/design notes.MD"],
)
def test_resolve_stem_forms(pconn, target):
    make_document(pconn, D, "Design Notes")
    assert refs.resolve(pconn, target) == D


def test_resolve_unknown_stem(pconn):
    assert refs.resolve(pconn, "nowhere") is None


def test_reindex_creates_link_refs_and_skips_unresolved(pconn):
    make_card(pconn, B)
    make_document(pconn, D, "parser-notes")
    make_card(pconn, A, description=f"see [[{B}]], [[parser-notes]] and [[nowhere]]")
    refs.reindex(pconn, A)
    assert out(pconn, A) == {(B, "link"), (D, "link")}


def test_reindex_is_idempotent(pconn):
    make_card(pconn, B)
    make_card(pconn, A, description=f"[[{B}]]")
    refs.reindex(pconn, A)
    refs.reindex(pconn, A)
    assert len(refs.outgoing(pconn, A)) == 1


def test_reindex_preserves_explicit_refs(pconn):
    make_card(pconn, B)
    make_card(pconn, A, description=f"[[{B}]]")
    refs.add_explicit(pconn, A, B)
    pconn.execute("UPDATE cards SET description = NULL WHERE id = ?", (A,))
    refs.reindex(pconn, A)
    assert out(pconn, A) == {(B, "explicit")}


def test_self_links_are_dropped(pconn):
    make_card(pconn, A, description=f"[[{A}]]")
    refs.reindex(pconn, A)
    assert refs.outgoing(pconn, A) == []


def test_comment_links_are_attributed_to_parent(pconn):
    make_card(pconn, A)
    make_card(pconn, B)
    pconn.execute(
        "INSERT INTO comments (id, entity_id, author, body, created_at) "
        "VALUES ('k1', ?, 'me', ?, 'now')",
        (A, f"see [[{B}]]"),
    )
    refs.reindex(pconn, A)
    assert out(pconn, A) == {(B, "link")}


def test_document_backup_links_are_indexed(pconn):
    make_card(pconn, A)
    make_document(pconn, D, "notes", content=f"relates to [[{A}]]")
    refs.reindex(pconn, D)
    assert {(r["id"], r["origin"]) for r in refs.incoming(pconn, A)} == {(D, "link")}


def test_incoming_and_titles(pconn):
    make_card(pconn, B, title="Target")
    make_card(pconn, A, title="Source", description=f"[[{B}]]")
    refs.reindex(pconn, A)
    assert refs.incoming(pconn, B) == [{"id": A, "kind": "card", "title": "Source", "origin": "link"}]
    assert refs.outgoing(pconn, A) == [{"id": B, "kind": "card", "title": "Target", "origin": "link"}]


def test_deleted_target_disappears_from_refs(pconn):
    make_card(pconn, B)
    make_card(pconn, A, description=f"[[{B}]]")
    refs.reindex(pconn, A)
    pconn.execute("DELETE FROM entities WHERE id = ?", (B,))
    assert refs.outgoing(pconn, A) == []


def test_add_explicit_validates(pconn):
    make_card(pconn, A)
    with pytest.raises(SelfReferenceError):
        refs.add_explicit(pconn, A, A)
    with pytest.raises(EntityNotFoundError):
        refs.add_explicit(pconn, A, B)
    with pytest.raises(EntityNotFoundError):
        refs.add_explicit(pconn, B, A)


def test_remove_explicit(pconn):
    make_card(pconn, A)
    make_card(pconn, B)
    refs.add_explicit(pconn, A, B)
    refs.add_explicit(pconn, A, B)  # idempotent
    refs.remove_explicit(pconn, A, B)
    assert refs.outgoing(pconn, A) == []


def test_reindex_mentions_resolves_forward_links_in_cards(pconn):
    make_card(pconn, A, description="todo: [[later]]")
    refs.reindex(pconn, A)
    assert refs.outgoing(pconn, A) == []
    make_document(pconn, D, "later")
    refs.reindex_mentions(pconn, "later")
    assert out(pconn, A) == {(D, "link")}


def test_reindex_mentions_scans_document_backups(pconn):
    make_document(pconn, D, "hub", content="see [[Later]]")
    refs.reindex(pconn, D)
    make_document(pconn, E, "later")
    refs.reindex_mentions(pconn, "later")
    assert out(pconn, D) == {(E, "link")}
