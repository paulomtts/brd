import pytest

from brd import tags
from brd.errors import InvalidTagError, NotTaggableError
from tests.factories import make_card, make_document


@pytest.mark.parametrize(
    "raw, expected",
    [("Design", "design"), ("#design/parser", "design/parser"), (" wip-2_x ", "wip-2_x")],
)
def test_normalize(raw, expected):
    assert tags.normalize(raw) == expected


@pytest.mark.parametrize("raw", ["", "#", "-lead", "has space", "émoji", "a.b"])
def test_normalize_rejects(raw):
    with pytest.raises(InvalidTagError):
        tags.normalize(raw)


def test_add_remove_list(pconn):
    make_document(pconn, "d", "notes")
    assert tags.add(pconn, "d", ["B", "a", "b"]) == ["a", "b"]
    assert tags.remove(pconn, "d", ["a", "missing"]) == ["b"]
    assert tags.list_for(pconn, "d") == ["b"]


def test_invalid_tag_writes_nothing(pconn):
    make_document(pconn, "d", "notes")
    with pytest.raises(InvalidTagError):
        tags.add(pconn, "d", ["good", "bad tag"])
    assert tags.list_for(pconn, "d") == []


def test_cards_not_taggable(pconn):
    make_card(pconn, "c")
    with pytest.raises(NotTaggableError, match="cards can't be tagged"):
        tags.add(pconn, "c", ["x"])


def test_counts(pconn):
    make_document(pconn, "d1", "one")
    make_document(pconn, "d2", "two")
    tags.add(pconn, "d1", ["x", "y"])
    tags.add(pconn, "d2", ["x"])
    assert tags.counts(pconn) == [{"tag": "x", "count": 2}, {"tag": "y", "count": 1}]
