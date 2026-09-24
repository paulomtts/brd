from tests.cli_helpers import err, ok


def test_issue_lifecycle(project):
    issue = ok("issue", "open", "--title", "Grammar ambiguity", "--body", "details")
    assert (issue["status"], issue["kind"]) == ("open", "issue")
    assert ok("issue", "update", issue["id"], "--title", "Renamed")["title"] == "Renamed"
    closed = ok("issue", "close", issue["id"], "--reason", "wontfix")
    assert (closed["status"], closed["close_reason"]) == ("closed", "wontfix")
    assert ok("issue", "reopen", issue["id"])["close_reason"] is None
    assert ok("issue", "close", issue["id"])["close_reason"] == "resolved"


def test_issue_list_filter(project):
    a = ok("issue", "open", "--title", "a")
    b = ok("issue", "open", "--title", "b")
    ok("issue", "close", b["id"])
    assert [i["id"] for i in ok("issue", "list", "--status", "open")] == [a["id"]]
    assert len(ok("issue", "list")) == 2


def test_issue_open_with_ref_and_blocks(project):
    card = ok("add", "--title", "Work")
    issue = ok("issue", "open", "--title", "Q", "--ref", card["id"], "--blocks", card["id"])
    assert issue["blocks"] == [card["id"]]
    shown = ok("show", card["id"])
    assert (shown["status"], shown["blocked_by"]) == ("blocked", [issue["id"]])
    assert shown["referenced_by"][0]["id"] == issue["id"]
    ok("issue", "close", issue["id"])
    assert ok("show", card["id"])["status"] == "todo"


def test_block_card_on_issue_via_block_command(project):
    card = ok("add", "--title", "Work")
    issue = ok("issue", "open", "--title", "Q")
    assert ok("block", card["id"], "--by", issue["id"])["status"] == "blocked"
    assert ok("next") == []
    assert ok("unblock", card["id"], "--by", issue["id"])["status"] == "todo"


def test_comment_on_issue_and_show(project):
    issue = ok("issue", "open", "--title", "Q")
    ok("comment", "add", issue["id"], "thoughts", "--author", "claude")
    shown = ok("show", issue["id"])
    assert shown["comments"][0]["author"] == "claude"


def test_issue_errors(project):
    assert err("issue", "close", "nope") == "IssueNotFoundError"
    issue = ok("issue", "open", "--title", "Q")
    assert err("issue", "close", issue["id"], "--reason", "meh") == "InvalidCloseReasonError"
    assert err("issue", "open", "--title", "Q", "--blocks", "ghost") == "CardNotFoundError"


def test_delete_issue(project):
    issue = ok("issue", "open", "--title", "Q")
    assert ok("delete", issue["id"]) == {"deleted": [issue["id"]]}
    assert ok("issue", "list") == []
