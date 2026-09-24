import pytest

from brd import core, issues, refs
from brd.errors import (
    CardNotFoundError,
    EntityNotFoundError,
    InvalidBlockerError,
    InvalidCloseReasonError,
    InvalidStatusError,
    IssueNotFoundError,
)
from tests.factories import make_document


def test_open_and_get(pconn):
    issue = issues.open_issue(pconn, "Grammar ambiguity", body="details")
    assert (issue.status, issue.close_reason) == ("open", None)
    assert issues.require(pconn, issue.id) == issue


def test_require_unknown(pconn):
    with pytest.raises(IssueNotFoundError):
        issues.require(pconn, "nope")


def test_close_reopen_and_reasons(pconn):
    issue = issues.open_issue(pconn, "x")
    assert issues.close(pconn, issue.id).close_reason == "resolved"
    reopened = issues.reopen(pconn, issue.id)
    assert (reopened.status, reopened.close_reason) == ("open", None)
    assert issues.close(pconn, issue.id, reason="wontfix").close_reason == "wontfix"
    with pytest.raises(InvalidCloseReasonError):
        issues.close(pconn, issue.id, reason="meh")


def test_list_filters_by_status(pconn):
    a = issues.open_issue(pconn, "a")
    b = issues.open_issue(pconn, "b")
    issues.close(pconn, b.id)
    assert [i.id for i in issues.list_issues(pconn)] == [a.id, b.id]
    assert [i.id for i in issues.list_issues(pconn, status="open")] == [a.id]


def test_update_body_reindexes_links(pconn):
    card = core.create_card(pconn, title="Target")
    issue = issues.open_issue(pconn, "x")
    issues.update(pconn, issue.id, body=f"about [[{card.id}]]")
    assert [r["id"] for r in refs.outgoing(pconn, issue.id)] == [card.id]


def test_open_with_refs_and_blocks(pconn):
    card = core.create_card(pconn, title="Work")
    issue = issues.open_issue(pconn, "Question", ref_ids=[card.id], blocks=[card.id])
    assert refs.outgoing(pconn, issue.id)[0]["origin"] == "explicit"
    assert issues.blocks_of(pconn, issue.id) == [card.id]


def test_open_with_unknown_ref_writes_nothing(pconn):
    with pytest.raises(EntityNotFoundError):
        issues.open_issue(pconn, "x", ref_ids=["ghost"])
    with pytest.raises(CardNotFoundError):
        issues.open_issue(pconn, "x", blocks=["ghost"])
    assert issues.list_issues(pconn) == []


def test_open_issue_blocks_card_until_closed_any_reason(pconn):
    for reason in issues.CLOSE_REASONS:
        card = core.create_card(pconn, title=f"w-{reason}")
        issue = issues.open_issue(pconn, "q")
        core.block_card(pconn, card.id, issue.id)
        assert core.resolve_status(pconn, card) == "blocked"
        assert card.id not in [c.id for c in core.next_cards(pconn)]
        issues.close(pconn, issue.id, reason=reason)
        assert core.resolve_status(pconn, card) == "todo"
        assert card.id in [c.id for c in core.next_cards(pconn)]
        issues.reopen(pconn, issue.id)
        assert core.resolve_status(pconn, card) == "blocked"
        issues.close(pconn, issue.id)


def test_create_card_blocked_by_issue(pconn):
    issue = issues.open_issue(pconn, "q")
    card = core.create_card(pconn, title="w", blocked_by=[issue.id])
    assert core.resolve_status(pconn, card) == "blocked"


def test_documents_cannot_block(pconn):
    card = core.create_card(pconn, title="w")
    make_document(pconn, "d", "notes")
    with pytest.raises(InvalidBlockerError):
        core.block_card(pconn, card.id, "d")
    with pytest.raises(InvalidBlockerError):
        core.create_card(pconn, title="w2", blocked_by=["d"])


def test_issue_cannot_be_blocked(pconn):
    issue = issues.open_issue(pconn, "q")
    card = core.create_card(pconn, title="w")
    with pytest.raises(CardNotFoundError):
        core.block_card(pconn, issue.id, card.id)


def test_deleting_issue_unblocks(pconn):
    card = core.create_card(pconn, title="w")
    issue = issues.open_issue(pconn, "q", blocks=[card.id])
    pconn.execute("DELETE FROM entities WHERE id = ?", (issue.id,))
    assert core.resolve_status(pconn, card) == "todo"


def test_open_issue_ignores_duplicate_refs_and_blocks(pconn):
    card = core.create_card(pconn, "C")
    target = core.create_card(pconn, "T")
    issue = issues.open_issue(pconn, "x", ref_ids=[target.id, target.id], blocks=[card.id, card.id])
    assert [r["id"] for r in refs.outgoing(pconn, issue.id)] == [target.id]
    assert issues.blocks_of(pconn, issue.id) == [card.id]


def test_list_issues_rejects_unknown_status(pconn):
    with pytest.raises(InvalidStatusError, match="opne"):
        issues.list_issues(pconn, "opne")
    assert issues.list_issues(pconn, "closed") == []
