import pytest

from brd import comments, refs
from brd.errors import (
    CommentNotFoundError,
    EmptyCommentError,
    EntityNotFoundError,
    NotCommentableError,
)
from tests.factories import PROJECT, make_card, make_document, make_issue

B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def test_add_and_list_on_card_and_issue(pconn):
    make_card(pconn, "c")
    make_issue(pconn, "i")
    first = comments.add(pconn, PROJECT.id, "c", "one", "alice")
    comments.add(pconn, PROJECT.id, "c", "two", "claude")
    comments.add(pconn, PROJECT.id, "i", "on issue", "alice")
    assert [c.body for c in comments.list_for(pconn, PROJECT.id, "c")] == ["one", "two"]
    assert first.author == "alice" and first.entity_id == "c"


def test_documents_are_not_commentable(pconn):
    make_document(pconn, "d", "notes")
    with pytest.raises(NotCommentableError, match="documents can't be commented on"):
        comments.add(pconn, PROJECT.id, "d", "hi", "alice")


def test_unknown_entity(pconn):
    with pytest.raises(EntityNotFoundError):
        comments.add(pconn, PROJECT.id, "zz", "hi", "alice")
    with pytest.raises(EntityNotFoundError):
        comments.list_for(pconn, PROJECT.id, "zz")


def test_empty_body_rejected(pconn):
    make_card(pconn, "c")
    with pytest.raises(EmptyCommentError):
        comments.add(pconn, PROJECT.id, "c", "   ", "alice")


def test_links_in_comments_become_parent_refs_and_go_on_delete(pconn):
    make_card(pconn, "c")
    make_card(pconn, B)
    comment = comments.add(pconn, PROJECT.id, "c", f"see [[{B}]]", "alice")
    assert [r["id"] for r in refs.outgoing(pconn, "c")] == [B]
    comments.delete(pconn, PROJECT.id, comment.id)
    assert refs.outgoing(pconn, "c") == []


def test_delete_unknown(pconn):
    with pytest.raises(CommentNotFoundError):
        comments.delete(pconn, PROJECT.id, "nope")


def test_comments_cascade_with_entity(pconn):
    make_card(pconn, "c")
    comments.add(pconn, PROJECT.id, "c", "x", "alice")
    pconn.execute("DELETE FROM entities WHERE id = 'c'")
    assert pconn.execute("SELECT COUNT(*) FROM comments").fetchone()[0] == 0


def test_author_precedence(monkeypatch):
    monkeypatch.setattr(comments.getpass, "getuser", lambda: "osuser")
    monkeypatch.delenv("BRD_AUTHOR", raising=False)
    assert comments.resolve_author(None) == "osuser"
    monkeypatch.setenv("BRD_AUTHOR", "claude")
    assert comments.resolve_author(None) == "claude"
    assert comments.resolve_author("explicit") == "explicit"
