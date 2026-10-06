import pytest

from brd import core, documents, refs, tags
from brd.errors import (
    DocumentContentLostError,
    DocumentNotFoundError,
    DocumentSourceNotFoundError,
    DuplicatePathError,
    DuplicateStemError,
    NotMarkdownError,
    PathOutsideProjectError,
    RestoreConflictError,
)
from tests.factories import OTHER_PROJECT, PROJECT, add_project


@pytest.fixture
def root(tmp_path):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    return repo


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_add_registers_and_backs_up(pconn, root):
    path = write(root, "docs/parser-notes.md", "# Notes\n")
    doc = documents.add(pconn, PROJECT.id, root, path)
    assert (doc.source_path, doc.stem, doc.title) == ("docs/parser-notes.md", "parser-notes", "parser-notes")
    assert documents.backup_path(pconn, doc.id).read_text() == "# Notes\n"
    assert doc.content_hash == documents._hash(b"# Notes\n")
    assert documents.require(pconn, doc.id) == doc


def test_add_with_title_and_tags(pconn, root):
    doc = documents.add(pconn, PROJECT.id, root, write(root, "docs/a.md", ""), title="Alpha", tag_list=["#Design"])
    assert doc.title == "Alpha"
    assert tags.list_for(pconn, doc.id) == ["design"]


def test_add_rejects_outside_root(pconn, root, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("x")
    with pytest.raises(PathOutsideProjectError):
        documents.add(pconn, PROJECT.id, root, outside)
    with pytest.raises(PathOutsideProjectError):
        documents.add(pconn, PROJECT.id, root, root / "docs" / ".." / ".." / "outside.md")


def test_add_rejects_symlink_escape(pconn, root, tmp_path):
    outside = tmp_path / "secret.md"
    outside.write_text("x")
    (root / "docs" / "link.md").symlink_to(outside)
    with pytest.raises(PathOutsideProjectError):
        documents.add(pconn, PROJECT.id, root, root / "docs" / "link.md")


def test_add_rejects_non_markdown_and_missing(pconn, root):
    with pytest.raises(NotMarkdownError):
        documents.add(pconn, PROJECT.id, root, write(root, "notes.txt", "x"))
    with pytest.raises(DocumentSourceNotFoundError):
        documents.add(pconn, PROJECT.id, root, root / "docs" / "ghost.md")


def test_add_rejects_duplicate_path_and_stem(pconn, root):
    documents.add(pconn, PROJECT.id, root, write(root, "docs/notes.md", ""))
    with pytest.raises(DuplicatePathError):
        documents.add(pconn, PROJECT.id, root, root / "docs" / "notes.md")
    with pytest.raises(DuplicateStemError, match="rename"):
        documents.add(pconn, PROJECT.id, root, write(root, "other/Notes.md", ""))


def test_add_with_invalid_tag_writes_nothing(pconn, root):
    from brd.errors import InvalidTagError

    with pytest.raises(InvalidTagError):
        documents.add(pconn, PROJECT.id, root, write(root, "docs/a.md", ""), tag_list=["bad tag"])
    assert documents.list_all(pconn) == []


def test_sync_states(pconn, root):
    path = write(root, "docs/a.md", "v1")
    doc = documents.add(pconn, PROJECT.id, root, path)
    assert documents.sync(pconn, root, doc) == documents.SyncResult("v1", "ok")

    path.write_text("v2")
    assert documents.sync(pconn, root, doc) == documents.SyncResult("v2", "updated")
    assert documents.backup_path(pconn, doc.id).read_text() == "v2"
    assert documents.require(pconn, doc.id).content_hash == documents._hash(b"v2")
    assert documents.sync(pconn, root, documents.require(pconn, doc.id)).source_state == "ok"

    path.unlink()
    assert documents.sync(pconn, root, doc) == documents.SyncResult("v2", "missing")

    documents.backup_path(pconn, doc.id).unlink()
    assert documents.sync(pconn, root, doc) == documents.SyncResult(None, "lost")


def test_sync_rewrites_deleted_backup(pconn, root):
    doc = documents.add(pconn, PROJECT.id, root, write(root, "docs/a.md", "v1"))
    documents.backup_path(pconn, doc.id).unlink()
    assert documents.sync(pconn, root, doc).source_state == "updated"
    assert documents.backup_path(pconn, doc.id).read_text() == "v1"


def test_sync_reindexes_changed_links(pconn, root):
    card = core.create_card(pconn, PROJECT.id, title="Target")
    path = write(root, "docs/a.md", "nothing")
    doc = documents.add(pconn, PROJECT.id, root, path)
    path.write_text(f"see [[{card.id}]]")
    documents.sync(pconn, root, doc)
    assert [r["id"] for r in refs.outgoing(pconn, doc.id)] == [card.id]


def test_non_utf8_content_does_not_crash(pconn, root):
    path = root / "docs" / "bin.md"
    path.write_bytes(b"ok \xff\xfe [[x]]")
    doc = documents.add(pconn, PROJECT.id, root, path)
    result = documents.sync(pconn, root, doc)
    assert result.source_state == "ok"
    assert "�" in result.content


def test_add_resolves_forward_links(pconn, root):
    card = core.create_card(pconn, PROJECT.id, title="Early", description="see [[Design Notes]]")
    assert refs.outgoing(pconn, card.id) == []
    doc = documents.add(pconn, PROJECT.id, root, write(root, "docs/design notes.md", ""))
    assert [r["id"] for r in refs.outgoing(pconn, card.id)] == [doc.id]


def test_sync_all_and_no_temp_files_left(pconn, root):
    a = documents.add(pconn, PROJECT.id, root, write(root, "docs/a.md", "a"))
    b = documents.add(pconn, PROJECT.id, root, write(root, "docs/b.md", "b"))
    (root / "docs" / "b.md").write_text("b2")
    results = documents.sync_all(pconn, root)
    assert {k: v.source_state for k, v in results.items()} == {a.id: "ok", b.id: "updated"}
    assert sorted(p.suffix for p in documents.backup_path(pconn, a.id).parent.iterdir()) == [".md", ".md"]


def test_update_rename_path_and_stem(pconn, root):
    old = write(root, "docs/old.md", "x")
    doc = documents.add(pconn, PROJECT.id, root, old)
    old.rename(root / "docs" / "new.md")
    updated, result = documents.update(pconn, root, doc.id, new_path=root / "docs" / "new.md")
    assert (updated.source_path, updated.stem, result.source_state) == ("docs/new.md", "new", "ok")


def test_update_rename_moves_link_resolution(pconn, root):
    old_card = core.create_card(pconn, PROJECT.id, title="Old", description="[[old]]")
    new_card = core.create_card(pconn, PROJECT.id, title="New", description="[[new]]")
    old = write(root, "docs/old.md", "x")
    doc = documents.add(pconn, PROJECT.id, root, old)
    old.rename(root / "docs" / "new.md")
    documents.update(pconn, root, doc.id, new_path=root / "docs" / "new.md")
    assert refs.outgoing(pconn, old_card.id) == []
    assert [r["id"] for r in refs.outgoing(pconn, new_card.id)] == [doc.id]


def test_update_rename_to_taken_stem(pconn, root):
    documents.add(pconn, PROJECT.id, root, write(root, "docs/a.md", ""))
    b = documents.add(pconn, PROJECT.id, root, write(root, "docs/b.md", ""))
    write(root, "other/a.md", "")
    with pytest.raises(DuplicateStemError):
        documents.update(pconn, root, b.id, new_path=root / "other" / "a.md")


def test_update_title_only(pconn, root):
    doc = documents.add(pconn, PROJECT.id, root, write(root, "docs/a.md", ""))
    updated, _ = documents.update(pconn, root, doc.id, title="Better")
    assert updated.title == "Better"


def test_update_unknown(pconn, root):
    with pytest.raises(DocumentNotFoundError):
        documents.update(pconn, root, "nope")


def test_restore_missing_source(pconn, root):
    path = write(root, "docs/a.md", "keep me")
    doc = documents.add(pconn, PROJECT.id, root, path)
    path.unlink()
    documents.restore(pconn, root, doc.id)
    assert path.read_text() == "keep me"


def test_restore_recreates_parent_dirs(pconn, root):
    path = write(root, "deep/dir/a.md", "x")
    doc = documents.add(pconn, PROJECT.id, root, path)
    path.unlink()
    path.parent.rmdir()
    documents.restore(pconn, root, doc.id)
    assert path.read_text() == "x"


def test_restore_conflict_and_force(pconn, root):
    path = write(root, "docs/a.md", "v1")
    doc = documents.add(pconn, PROJECT.id, root, path)
    path.write_text("local edit")
    with pytest.raises(RestoreConflictError):
        documents.restore(pconn, root, doc.id)
    documents.restore(pconn, root, doc.id, force=True)
    assert path.read_text() == "v1"


def test_restore_matching_is_noop(pconn, root):
    path = write(root, "docs/a.md", "v1")
    doc = documents.add(pconn, PROJECT.id, root, path)
    documents.restore(pconn, root, doc.id)
    assert path.read_text() == "v1"


def test_restore_lost(pconn, root):
    path = write(root, "docs/a.md", "v1")
    doc = documents.add(pconn, PROJECT.id, root, path)
    path.unlink()
    documents.backup_path(pconn, doc.id).unlink()
    with pytest.raises(DocumentContentLostError):
        documents.restore(pconn, root, doc.id)


def test_delete_removes_backup_keeps_source(pconn, root):
    path = write(root, "docs/a.md", "v1")
    doc = documents.add(pconn, PROJECT.id, root, path)
    documents.delete(pconn, doc.id)
    assert documents.get(pconn, doc.id) is None
    assert not documents.backup_path(pconn, doc.id).exists()
    assert path.read_text() == "v1"


@pytest.mark.parametrize("escape", ["../outside.md", "docs/../../outside.md"])
def test_restore_and_sync_refuse_a_source_path_outside_root(pconn, root, escape):
    doc = documents.add(pconn, PROJECT.id, root, write(root, "docs/a.md", "backup"))
    pconn.execute("UPDATE documents SET source_path = ? WHERE id = ?", (escape, doc.id))
    pconn.commit()
    outside = root.parent / "outside.md"
    outside.write_text("secret")
    with pytest.raises(PathOutsideProjectError):
        documents.restore(pconn, root, doc.id, force=True)
    assert outside.read_text() == "secret"
    with pytest.raises(PathOutsideProjectError):
        documents.sync(pconn, root, documents.require(pconn, doc.id))
    assert documents.backup_path(pconn, doc.id).read_text() == "backup"


def test_delete_document_removes_incoming_refs_without_fk_cascade(pconn, root):
    path = write(root, "docs/a.md", "v1")
    doc = documents.add(pconn, PROJECT.id, root, path)
    explicit = core.create_card(pconn, PROJECT.id, title="Explicit")
    refs.add_explicit(pconn, explicit.id, doc.id)
    linker = core.create_card(pconn, PROJECT.id, title="Linker", description="see [[a]]")
    assert pconn.execute(
        "SELECT COUNT(*) FROM refs WHERE dst_id = ?", (doc.id,)
    ).fetchone()[0] == 2
    pconn.commit()
    pconn.execute("PRAGMA foreign_keys=OFF")

    documents.delete(pconn, doc.id)

    assert pconn.execute(
        "SELECT COUNT(*) FROM refs WHERE dst_id = ?", (doc.id,)
    ).fetchone()[0] == 0
    assert refs.outgoing(pconn, explicit.id) == []
    assert refs.outgoing(pconn, linker.id) == []
    assert not documents.backup_path(pconn, doc.id).exists()
    assert path.read_text() == "v1"


def test_add_records_its_project(pconn, root):
    add_project(pconn, OTHER_PROJECT)
    doc = documents.add(pconn, OTHER_PROJECT.id, root, write(root, "docs/a.md", "x"))
    entity = pconn.execute(
        "SELECT kind, project_id FROM entities WHERE id = ?", (doc.id,)
    ).fetchone()
    assert tuple(entity) == ("document", OTHER_PROJECT.id)
    stored = pconn.execute("SELECT project_id FROM documents WHERE id = ?", (doc.id,)).fetchone()
    assert stored[0] == OTHER_PROJECT.id
