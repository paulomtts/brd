from tests.cli_helpers import human, ok


def test_show_card_renders_titles_for_links(project):
    target = ok("add", "--title", "Tokenizer spike")
    card = ok("add", "--title", "Parser", "--description", f"after [[{target['id']}]] and [[ghost]]")
    ok("comment", "add", card["id"], f"see [[{target['id']}|the spike]]", "--author", "claude")
    out = human("show", card["id"])
    assert out.splitlines()[0] == f"Parser  [todo]  ({card['id']})"
    assert "after [[Tokenizer spike]] and [[ghost]] (unresolved)" in out
    assert "refs: Tokenizer spike (card)" in out
    assert "claude · " in out
    assert "  see [[the spike]]" in out
    assert target["id"] not in out.split("\n", 1)[1]  # ids only in the header


def test_show_card_blocked_by_issue(project):
    card = ok("add", "--title", "Work")
    ok("issue", "open", "--title", "Grammar ambiguity", "--blocks", card["id"])
    assert "blocked by: [[Grammar ambiguity]] (issue, open)" in human("show", card["id"])


def test_show_issue_and_document(project):
    (project / "docs").mkdir()
    (project / "docs" / "notes.md").write_text("body")
    doc = ok("doc", "add", "docs/notes.md", "--tag", "design")
    issue = ok("issue", "open", "--title", "Q", "--body", "read [[notes]]")
    ok("issue", "close", issue["id"], "--reason", "wontfix")
    issue_out = human("show", issue["id"])
    assert issue_out.splitlines()[0] == f"Q  [closed: wontfix]  ({issue['id']})"
    assert "read [[notes]]" in issue_out
    doc_out = human("show", doc["id"])
    assert doc_out.splitlines()[0] == f"notes  [ok]  ({doc['id']})"
    assert "path: docs/notes.md" in doc_out and "tags: #design" in doc_out
    assert "referenced by: Q (issue)" in doc_out


def test_lists(project):
    (project / "docs").mkdir()
    (project / "docs" / "a.md").write_text("")
    doc = ok("doc", "add", "docs/a.md", "--tag", "x")
    issue = ok("issue", "open", "--title", "Q")
    card = ok("add", "--title", "C")
    assert human("doc", "list").strip() == f"{doc['id']}  [ok]  a  (docs/a.md)  #x"
    assert human("issue", "list").strip() == f"{issue['id']}  [open]  Q"
    assert human("list").strip() == f"{card['id']}  [todo]  C"
    ok("comment", "add", card["id"], "hi", "--author", "me")
    assert human("comment", "list", card["id"]).splitlines()[1] == "  hi"


def test_show_card_blocked_by_local_card(project):
    a = ok("add", "--title", "A")
    b = ok("add", "--title", "B", "--blocked-by", a["id"])
    assert "blocked by: [[A]] (card)" in human("show", b["id"]).splitlines()
