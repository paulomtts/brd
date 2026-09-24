import json

import pytest

from tests.cli_helpers import err, ok


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

    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    ok("init")
    result = ok("import", snapshot)
    assert (result["cards"], result["issues"], result["documents"], result["comments"]) == (2, 1, 1, 1)

    after = _shows(ids)
    # The source file isn't in the new repo; brd serves the backup.
    assert after[populated["doc"]["id"]]["source_state"] == "missing"
    for data in (before, after):
        data[populated["doc"]["id"]].pop("source_state")
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
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    ok("init")
    assert ok("import", snapshot)["cards"] == 2


def test_old_tree_snapshot_still_imports(project, tmp_path, monkeypatch):
    a = ok("add", "--title", "A")
    ok("add", "--title", "B", "--blocked-by", a["id"])
    snapshot = tmp_path / "tree.json"
    snapshot.write_text(json.dumps({"ok": True, "data": ok("tree")}))
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    ok("init")
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


def test_import_stem_collision_touches_nothing(populated, tmp_path, monkeypatch):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(ok("export")))
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    ok("init")
    write(other, "docs/notes.md", "local")
    ok("doc", "add", "docs/notes.md")
    assert err("import", snapshot) == "DuplicatePathError"
    assert ok("list") == [] and ok("issue", "list") == []
