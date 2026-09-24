from brd import comments as comments_module
from tests.cli_helpers import err, ok


def _card(title="A", **kwargs):
    args = ["add", "--title", title]
    for key, value in kwargs.items():
        args += [f"--{key}", value]
    return ok(*args)


def test_comment_add_list_delete(project, monkeypatch):
    monkeypatch.setattr(comments_module.getpass, "getuser", lambda: "osuser")
    card = _card()
    comment = ok("comment", "add", card["id"], "first")
    assert comment["author"] == "osuser"
    assert [c["body"] for c in ok("comment", "list", card["id"])] == ["first"]
    assert ok("show", card["id"])["comments"][0]["id"] == comment["id"]
    ok("comment", "delete", comment["id"])
    assert ok("comment", "list", card["id"]) == []


def test_comment_author_env_and_flag(project, monkeypatch):
    card = _card()
    monkeypatch.setenv("BRD_AUTHOR", "claude")
    assert ok("comment", "add", card["id"], "x")["author"] == "claude"
    assert ok("comment", "add", card["id"], "y", "--author", "bot")["author"] == "bot"


def test_comment_body_from_stdin(project):
    card = _card()
    assert ok("comment", "add", card["id"], "-", input="long\ntext\n")["body"] == "long\ntext\n"


def test_comment_errors(project):
    assert err("comment", "add", "nope", "x") == "EntityNotFoundError"
    assert err("comment", "delete", "nope") == "CommentNotFoundError"
    card = _card()
    assert err("comment", "add", card["id"], "  ") == "EmptyCommentError"


def test_tag_card_is_rejected(project):
    card = _card()
    assert err("tag", "add", card["id"], "x") == "NotTaggableError"
    assert err("tag", "add", "nope", "x") == "EntityNotFoundError"
    assert ok("tag", "list") == []


def test_explicit_refs_and_backlinks(project):
    a = _card("A")
    b = _card("B")
    ok("ref", "add", a["id"], b["id"])
    assert ok("show", a["id"])["refs"] == [
        {"id": b["id"], "kind": "card", "title": "B", "origin": "explicit"}
    ]
    assert ok("show", b["id"])["referenced_by"][0]["id"] == a["id"]
    ok("ref", "remove", a["id"], b["id"])
    assert ok("show", a["id"])["refs"] == []
    assert err("ref", "add", a["id"], a["id"]) == "SelfReferenceError"


def test_description_links_show_up_in_refs(project):
    b = _card("B")
    a = _card("A", description=f"depends on [[{b['id']}]]")
    assert ok("show", a["id"])["refs"][0]["origin"] == "link"


def test_show_and_delete_unknown_keep_card_error(project):
    assert err("show", "nope") == "CardNotFoundError"
    assert err("delete", "nope") == "CardNotFoundError"


def test_show_card_has_kind(project):
    assert ok("show", _card()["id"])["kind"] == "card"
