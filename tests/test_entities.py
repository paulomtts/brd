import pytest

from brd import entities
from brd.errors import EntityNotFoundError, NotTaggableError
from tests.factories import make_card, make_document, make_issue


def test_kind_of_each_kind(pconn):
    make_card(pconn, "c")
    make_issue(pconn, "i")
    make_document(pconn, "d", "notes")
    assert [entities.kind_of(pconn, x) for x in ("c", "i", "d", "zz")] == [
        "card", "issue", "document", None,
    ]


def test_require_raises_for_unknown(pconn):
    with pytest.raises(EntityNotFoundError, match="no entity with id zz"):
        entities.require(pconn, "zz")


def test_require_capability_rejects_disallowed_kind(pconn):
    make_card(pconn, "c")
    with pytest.raises(NotTaggableError, match="cards can't be tagged"):
        entities.require_capability(pconn, "c", entities.TAGGABLE, NotTaggableError, "tagged")


def test_require_capability_returns_kind(pconn):
    make_document(pconn, "d", "notes")
    assert entities.require_capability(
        pconn, "d", entities.TAGGABLE, NotTaggableError, "tagged"
    ) == "document"


def test_title_and_summary(pconn):
    make_issue(pconn, "i", title="Grammar ambiguity")
    assert entities.title_of(pconn, "i") == "Grammar ambiguity"
    assert entities.summary(pconn, "i") == {"id": "i", "kind": "issue", "title": "Grammar ambiguity"}
    assert entities.summary(pconn, "zz") is None


def test_delete_cascades(pconn):
    make_issue(pconn, "i")
    entities.delete(pconn, "i")
    assert entities.kind_of(pconn, "i") is None
    assert pconn.execute("SELECT COUNT(*) FROM issues").fetchone()[0] == 0


def test_capability_map():
    assert entities.COMMENTABLE == {"card", "issue"}
    assert entities.TAGGABLE == {"document"}
    assert entities.BLOCKERS == {"card", "issue"}
    assert entities.REF_SOURCES == {"card", "issue", "document"}
