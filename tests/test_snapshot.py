import json

import pytest

from brd import paths
from tests.cli_helpers import err, invoke, ok


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def populated(project):
    card = ok("add", "--title", "Parser", "--description", "see [[notes]]")
    child = ok("add", "--title", "Lexer", "--parent", card["id"])
    write(project, "docs/notes.md", f"# Notes\nabout [[{card['id']}]]")
    doc = ok("doc", "add", "docs/notes.md", "--tag", "design")
    issue = ok("issue", "open", "--title", "Q", "--body", "hmm", "--ref", doc["id"], "--blocks", child["id"])
    ok("comment", "add", card["id"], "progress", "--author", "claude")
    return {"card": card, "child": child, "doc": doc, "issue": issue}


def _shows(ids):
    return {i: ok("show", i) for i in ids}


def _fresh_project(tmp_path, monkeypatch):
    """Init project `other` on a second install (its own data dir): one
    install's projects share brd.db, where the snapshot's ids already exist."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "other-data"))
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    ok("init")
    return other


def test_export_shape(populated):
    data = ok("export")
    assert data["brd_export"] == 1
    assert [c["id"] for c in data["cards"]] == [populated["card"]["id"]]
    assert data["documents"][0]["content"].startswith("# Notes")
    assert data["tags"] == [{"entity_id": populated["doc"]["id"], "tag": "design"}]
    assert all(r["origin"] == "explicit" for r in data["refs"])


def test_round_trip_into_fresh_project(populated, tmp_path, monkeypatch):
    ids = [populated[k]["id"] for k in ("card", "child", "doc", "issue")]
    before = _shows(ids)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(ok("export")))

    other = _fresh_project(tmp_path, monkeypatch)
    result = ok("import", snapshot)
    assert (result["cards"], result["issues"], result["documents"], result["comments"]) == (2, 1, 1, 1)

    after = _shows(ids)
    # The source file isn't in the new repo; brd serves the backup.
    assert after[populated["doc"]["id"]]["source_state"] == "missing"
    for data in (before, after):
        data[populated["doc"]["id"]].pop("source_state")
    # `show` names the owning project, which differs between the two boards.
    assert {s["project"]["id"] for s in before.values()}.isdisjoint(
        {s["project"]["id"] for s in after.values()}
    )
    # So does each blocker's; here every blocker is on its card's own board.
    child_id = populated["child"]["id"]
    assert [b["id"] for b in before[child_id]["blockers"]] == [populated["issue"]["id"]]
    for data in (before, after):
        for shown in data.values():
            for blocker in shown.get("blockers", []):
                assert blocker.pop("project") == shown["project"]
            shown.pop("project")
    assert before == after
    ok("doc", "restore", populated["doc"]["id"])
    assert (other / "docs" / "notes.md").read_text().startswith("# Notes")


def test_import_collision_touches_nothing(populated, tmp_path):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(ok("export")))
    before = len(ok("list"))
    assert err("import", snapshot) == "EntityAlreadyExistsError"
    assert len(ok("list")) == before


def test_import_accepts_wrapped_export_envelope(populated, tmp_path, monkeypatch):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"ok": True, "data": ok("export")}))
    other = _fresh_project(tmp_path, monkeypatch)
    assert ok("import", snapshot)["cards"] == 2


def test_old_tree_snapshot_still_imports(project, tmp_path, monkeypatch):
    a = ok("add", "--title", "A")
    ok("add", "--title", "B", "--blocked-by", a["id"])
    tree = ok("tree")
    # The tree output carries the derived `blockers`; import must ignore it.
    assert any(node["blockers"] for node in tree)
    snapshot = tmp_path / "tree.json"
    snapshot.write_text(json.dumps({"ok": True, "data": tree}))
    other = _fresh_project(tmp_path, monkeypatch)
    assert ok("import", snapshot) == {"imported": 2}
    assert err("import", snapshot) == "CardAlreadyExistsError"


def test_import_rejects_unknown_format(project, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"hello": 1}))
    assert err("import", bad) == "ImportFormatError"
    bad.write_text(json.dumps({"brd_export": 99}))
    assert err("import", bad) == "ImportFormatError"
    bad.write_text("not json")
    assert err("import", bad) == "ImportReadError"


def test_import_rolls_back_document_backup_on_integrity_error(populated, tmp_path, monkeypatch):
    data = ok("export")
    # A comment referencing an entity that doesn't exist in the snapshot (or
    # the target board) violates the comments.entity_id foreign key, so the
    # DB transaction fails after the document's backup was already written.
    data["comments"].append(
        {
            "id": "00000000-0000-0000-0000-000000000000",
            "entity_id": "does-not-exist",
            "author": "x",
            "body": "y",
            "created_at": "2020-01-01T00:00:00+00:00",
        }
    )
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(data))

    other = _fresh_project(tmp_path, monkeypatch)
    assert err("import", snapshot) == "ImportFormatError"
    assert ok("list") == [] and ok("issue", "list") == []
    doc_id = populated["doc"]["id"]
    assert not (paths.docs_dir() / f"{doc_id}.md").exists()


def test_import_stem_collision_touches_nothing(populated, tmp_path, monkeypatch):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(ok("export")))
    other = _fresh_project(tmp_path, monkeypatch)
    write(other, "docs/notes.md", "local")
    ok("doc", "add", "docs/notes.md")
    assert err("import", snapshot) == "DuplicatePathError"
    assert ok("list") == [] and ok("issue", "list") == []


def _import_into_fresh(tmp_path, monkeypatch, data):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(data))
    other = _fresh_project(tmp_path, monkeypatch)
    return other, err("import", snapshot)


@pytest.mark.parametrize(
    "source_path", ["/tmp/evil.md", "../evil.md", "docs/../../evil.md", "docs/notes.txt"]
)
def test_import_rejects_unsafe_document_source_path(populated, tmp_path, monkeypatch, source_path):
    data = ok("export")
    data["documents"][0]["source_path"] = source_path
    other, error = _import_into_fresh(tmp_path, monkeypatch, data)
    assert error == "ImportFormatError"
    assert ok("list") == [] and ok("issue", "list") == [] and ok("doc", "list") == []
    docs_dir = paths.docs_dir()
    assert not docs_dir.exists() or list(docs_dir.iterdir()) == []


def test_old_tree_snapshot_with_unknown_blocker_imports_nothing(project, tmp_path, monkeypatch):
    a = ok("add", "--title", "A")
    issue = ok("issue", "open", "--title", "Q", "--blocks", a["id"])
    ok("add", "--title", "B")
    tree = ok("tree")
    assert issue["id"] in tree[0]["blocked_by"]
    other, error = _import_into_fresh(tmp_path, monkeypatch, tree)
    assert error == "ImportFormatError"
    assert ok("list") == []


@pytest.mark.parametrize(
    "raw",
    [
        {"brd_export": 1, "issues": [{"id": "0b6f4c1e-1111-4222-8333-444455556666"}]},
        {"brd_export": 1, "cards": 5},
        {"brd_export": 1, "documents": [{"id": "d", "source_path": "a.md", "content": 3}]},
        {"brd_export": 1, "cards": [{"id": "c", "title": {"x": 1}, "status": "todo",
                                     "created_at": "t", "updated_at": "t"}]},
        [{"id": "c"}],
        ["not a node"],
    ],
)
def test_malformed_snapshot_is_an_envelope(project, tmp_path, monkeypatch, raw):
    other, error = _import_into_fresh(tmp_path, monkeypatch, raw)
    assert error == "ImportFormatError"
    assert ok("list") == [] and ok("issue", "list") == [] and ok("doc", "list") == []


GHOST = "0b6f4c1e-dead-4222-8333-444455556666"


def _import_error_into_fresh(tmp_path, monkeypatch, data):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(data))
    other = _fresh_project(tmp_path, monkeypatch)
    result = invoke("import", snapshot)
    assert result.exit_code == 1, result.output
    return other, json.loads(result.stdout)["error"]


def _assert_nothing_imported(other):
    assert ok("list") == [] and ok("issue", "list") == [] and ok("doc", "list") == []
    docs_dir = paths.docs_dir()
    assert not docs_dir.exists() or list(docs_dir.iterdir()) == []


def test_import_rejects_unknown_blocker(populated, tmp_path, monkeypatch):
    data = ok("export")
    data["cards"][0]["blocked_by"].append(GHOST)
    other, error = _import_error_into_fresh(tmp_path, monkeypatch, data)
    assert error["type"] == "ImportFormatError"
    assert GHOST in error["message"]
    _assert_nothing_imported(other)


def test_import_rejects_unknown_ref_target(populated, tmp_path, monkeypatch):
    data = ok("export")
    data["refs"].append({"src_id": populated["card"]["id"], "dst_id": GHOST, "origin": "explicit"})
    other, error = _import_error_into_fresh(tmp_path, monkeypatch, data)
    assert error["type"] == "ImportFormatError"
    assert GHOST in error["message"]
    _assert_nothing_imported(other)


def test_old_tree_snapshot_names_the_unknown_blocker(project, tmp_path, monkeypatch):
    a = ok("add", "--title", "A")
    issue = ok("issue", "open", "--title", "Q", "--blocks", a["id"])
    tree = ok("tree")
    other, error = _import_error_into_fresh(tmp_path, monkeypatch, tree)
    assert error["type"] == "ImportFormatError"
    assert issue["id"] in error["message"]
    assert ok("list") == []


@pytest.mark.parametrize("fmt", ["export", "tree"])
def test_import_blocker_already_on_board_is_accepted(project, tmp_path, fmt):
    issue = ok("issue", "open", "--title", "Q")
    card_id = "5d0f6a52-7c55-4a8e-9d0b-0c1f2e3a4b5c"
    node = {
        "id": card_id,
        "title": "Imported",
        "description": None,
        "status": "todo",
        "blocked_by": [issue["id"]],
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "children": [],
    }
    data = {"brd_export": 1, "cards": [node]} if fmt == "export" else [node]
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(data))
    ok("import", snapshot)
    assert ok("show", card_id)["blocked_by"] == [issue["id"]]


def test_round_trip_keeps_refs_between_snapshot_entities(populated, tmp_path, monkeypatch):
    data = ok("export")
    assert data["refs"], "populated has an explicit issue -> document ref"
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(data))
    other = _fresh_project(tmp_path, monkeypatch)
    ok("import", snapshot)
    assert ok("export")["refs"] == data["refs"]


def _card_nodes(nodes):
    for node in nodes:
        yield node
        yield from _card_nodes(node["children"])


def test_export_card_nodes_have_no_blockers(populated):
    nodes = list(_card_nodes(ok("export")["cards"]))
    assert {n["id"] for n in nodes} == {populated["card"]["id"], populated["child"]["id"]}
    assert all("blockers" not in n and "blocked_by" in n for n in nodes)
    (child,) = [n for n in nodes if n["id"] == populated["child"]["id"]]
    assert child["blocked_by"] == [populated["issue"]["id"]]
