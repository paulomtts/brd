from tests.cli_helpers import err, ok


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_doc_add_from_subdirectory_stores_root_relative_path(project, monkeypatch):
    write(project, "docs/a.md", "x")
    (project / "src").mkdir()
    monkeypatch.chdir(project / "src")
    doc = ok("doc", "add", "../docs/a.md")
    assert doc["source_path"] == "docs/a.md"
    assert doc["source_state"] == "ok"
    assert doc["kind"] == "document"


def test_doc_add_with_tags_and_title(project):
    write(project, "docs/a.md", "x")
    doc = ok("doc", "add", "docs/a.md", "--title", "Alpha", "--tag", "design", "--tag", "#WIP")
    assert (doc["title"], doc["tags"]) == ("Alpha", ["design", "wip"])


def test_doc_add_errors(project):
    write(project, "notes.txt", "x")
    assert err("doc", "add", "notes.txt") == "NotMarkdownError"
    assert err("doc", "add", "ghost.md") == "DocumentSourceNotFoundError"


def test_doc_list_filters(project):
    write(project, "docs/a.md", "")
    write(project, "docs/b.md", "")
    a = ok("doc", "add", "docs/a.md", "--tag", "x", "--tag", "y")
    b = ok("doc", "add", "docs/b.md", "--tag", "x")
    assert [d["id"] for d in ok("doc", "list")] == [a["id"], b["id"]]
    assert [d["id"] for d in ok("doc", "list", "--tag", "x", "--tag", "y")] == [a["id"]]
    (project / "docs" / "b.md").unlink()
    assert [(d["id"], d["source_state"]) for d in ok("doc", "list", "--missing")] == [
        (b["id"], "missing")
    ]


def test_doc_update_reports_sync_and_rename(project):
    path = write(project, "docs/a.md", "v1")
    doc = ok("doc", "add", "docs/a.md")
    path.write_text("v2")
    assert ok("doc", "update", doc["id"])["source_state"] == "updated"
    path.rename(project / "docs" / "b.md")
    renamed = ok("doc", "update", doc["id"], "--path", "docs/b.md", "--title", "Bee")
    assert (renamed["source_path"], renamed["title"]) == ("docs/b.md", "Bee")


def test_doc_restore(project):
    path = write(project, "docs/a.md", "v1")
    doc = ok("doc", "add", "docs/a.md")
    path.write_text("edited")
    assert err("doc", "restore", doc["id"]) == "RestoreConflictError"
    ok("doc", "restore", doc["id"], "--force")
    assert path.read_text() == "v1"


def test_show_document_includes_content_and_tags(project):
    write(project, "docs/a.md", "hello")
    doc = ok("doc", "add", "docs/a.md", "--tag", "x")
    shown = ok("show", doc["id"])
    assert (shown["content"], shown["tags"], shown["source_state"]) == ("hello", ["x"], "ok")


def test_show_card_sees_backlink_from_document_edited_on_disk(project):
    card = ok("add", "--title", "Target")
    path = write(project, "docs/a.md", "nothing yet")
    doc = ok("doc", "add", "docs/a.md")
    path.write_text(f"now links [[{card['id']}]]")  # no `doc update` run
    assert [r["id"] for r in ok("show", card["id"])["referenced_by"]] == [doc["id"]]


def test_delete_document_keeps_source(project):
    path = write(project, "docs/a.md", "x")
    doc = ok("doc", "add", "docs/a.md")
    assert ok("delete", doc["id"]) == {"deleted": [doc["id"]]}
    assert path.exists()
    assert ok("doc", "list") == []


def test_tag_commands_on_document(project):
    write(project, "docs/a.md", "")
    doc = ok("doc", "add", "docs/a.md")
    assert ok("tag", "add", doc["id"], "one", "two")["tags"] == ["one", "two"]
    assert ok("tag", "remove", doc["id"], "one")["tags"] == ["two"]
    assert ok("tag", "list") == [{"tag": "two", "count": 1}]
