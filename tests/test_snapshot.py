import json
import shutil

import pytest

from brd import paths
from tests.cli_helpers import err, human, invoke, ok


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


ENTRY_KEYS = {"project", "cards", "issues", "documents", "comments", "tags", "refs"}


def _entry(data):
    """The single project entry of a one-project export."""
    (entry,) = data["projects"]
    return entry


def _another_project(tmp_path, monkeypatch, name):
    """Init project `name` in the same install as `project` (same data dir,
    unlike _fresh_project) and chdir into it."""
    root = tmp_path / name
    root.mkdir()
    monkeypatch.chdir(root)
    return root, ok("init")


def test_export_is_a_one_entry_project_list(populated):
    data = ok("export")
    assert set(data) == {"brd_export", "projects"}
    assert data["brd_export"] == 2
    entry = _entry(data)
    assert set(entry) == ENTRY_KEYS
    (registered,) = ok("projects")
    assert entry["project"] == registered
    assert set(entry["project"]) == {"id", "name", "root_path", "created_at"}
    assert [c["id"] for c in entry["cards"]] == [populated["card"]["id"]]
    assert entry["documents"][0]["content"].startswith("# Notes")
    assert entry["tags"] == [{"entity_id": populated["doc"]["id"], "tag": "design"}]
    assert entry["refs"] and all(r["origin"] == "explicit" for r in entry["refs"])


def test_export_of_an_empty_project_has_empty_lists(project):
    entry = _entry(ok("export"))
    assert {k: v for k, v in entry.items() if k != "project"} == {
        "cards": [], "issues": [], "documents": [], "comments": [], "tags": [], "refs": []
    }


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
    _entry(data)["comments"].append(
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
    _entry(data)["documents"][0]["source_path"] = source_path
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
        {"brd_export": 2, "projects": "x"},
        {"brd_export": 2, "projects": [5]},
        {"brd_export": 2},
        {"brd_export": 2, "projects": [{"project": {}, "cards": []}]},
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
    _entry(data)["cards"][0]["blocked_by"].append(GHOST)
    other, error = _import_error_into_fresh(tmp_path, monkeypatch, data)
    assert error["type"] == "ImportFormatError"
    assert GHOST in error["message"]
    _assert_nothing_imported(other)


def test_import_rejects_unknown_ref_target(populated, tmp_path, monkeypatch):
    data = ok("export")
    _entry(data)["refs"].append(
        {"src_id": populated["card"]["id"], "dst_id": GHOST, "origin": "explicit"}
    )
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
    assert _entry(data)["refs"], "populated has an explicit issue -> document ref"
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(data))
    other = _fresh_project(tmp_path, monkeypatch)
    ok("import", snapshot)
    assert _entry(ok("export"))["refs"] == _entry(data)["refs"]


def _card_nodes(nodes):
    for node in nodes:
        yield node
        yield from _card_nodes(node["children"])


def test_export_card_nodes_have_no_blockers(populated):
    nodes = list(_card_nodes(_entry(ok("export"))["cards"]))
    assert {n["id"] for n in nodes} == {populated["card"]["id"], populated["child"]["id"]}
    assert all("blockers" not in n and "blocked_by" in n for n in nodes)
    (child,) = [n for n in nodes if n["id"] == populated["child"]["id"]]
    assert child["blocked_by"] == [populated["issue"]["id"]]


@pytest.mark.parametrize("count", [0, 2])
def test_import_refuses_a_multi_entry_export(project, tmp_path, monkeypatch, count):
    ok("add", "--title", "A")
    entries = [_entry(ok("export"))]
    _another_project(tmp_path, monkeypatch, "second")
    ok("add", "--title", "B")
    entries.append(_entry(ok("export")))
    data = {"brd_export": 2, "projects": entries[:count]}
    other, error = _import_error_into_fresh(tmp_path, monkeypatch, data)
    assert error["type"] == "ImportFormatError"
    assert f"{count} project entries" in error["message"]
    assert "not supported yet" in error["message"]
    _assert_nothing_imported(other)


def test_export_all_lists_every_project_in_creation_order(project, tmp_path, monkeypatch):
    a_card = ok("add", "--title", "A card")["id"]
    a_issue = ok("issue", "open", "--title", "A issue")["id"]
    a_entry = _entry(ok("export"))
    _another_project(tmp_path, monkeypatch, "second")
    b_card = ok("add", "--title", "B card")["id"]
    b_entry = _entry(ok("export"))

    from_b = ok("export", "--all")
    monkeypatch.chdir(project)
    from_a = ok("export", "--all")
    assert from_a == from_b
    assert set(from_a) == {"brd_export", "projects"} and from_a["brd_export"] == 2
    assert [e["project"] for e in from_a["projects"]] == ok("projects")
    assert from_a["projects"] == [a_entry, b_entry]
    assert [c["id"] for c in a_entry["cards"]] == [a_card]
    assert [i["id"] for i in a_entry["issues"]] == [a_issue]
    assert [c["id"] for c in b_entry["cards"]] == [b_card]
    assert b_entry["issues"] == []
    # Without --all, still only the current project.
    assert ok("export")["projects"] == [a_entry]

    # A two-project snapshot does not import yet (5.2), and writes nothing.
    snapshot = tmp_path / "all.json"
    snapshot.write_text(json.dumps(from_a))
    assert err("import", snapshot) == "ImportFormatError"
    assert [c["id"] for c in ok("list")] == [a_card]


def test_export_all_works_outside_any_project(project, tmp_path, monkeypatch):
    ok("add", "--title", "A")
    _another_project(tmp_path, monkeypatch, "second")
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)
    data = ok("export", "--all")
    assert [e["project"] for e in data["projects"]] == ok("projects")
    assert len(data["projects"]) == 2
    assert err("export") == "ProjectNotFoundError"


def test_export_all_with_no_projects_is_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    assert ok("export", "--all") == {"brd_export": 2, "projects": []}


def test_export_all_with_a_missing_project_root(project, tmp_path, monkeypatch):
    second, registered = _another_project(tmp_path, monkeypatch, "second")
    write(second, "docs/plan.md", "# Plan\nkept in the backup")
    doc = ok("doc", "add", "docs/plan.md")
    monkeypatch.chdir(project)
    shutil.rmtree(second)

    data = ok("export", "--all")
    (entry,) = [e for e in data["projects"] if e["project"]["id"] == registered["id"]]
    assert [d["id"] for d in entry["documents"]] == [doc["id"]]
    assert entry["documents"][0]["content"] == "# Plan\nkept in the backup"


def test_export_keeps_cross_project_and_not_found_edges(project, tmp_path, monkeypatch):
    _, b = _another_project(tmp_path, monkeypatch, "b")
    b_card = ok("add", "--title", "B card")["id"]
    b_issue = ok("issue", "open", "--title", "B issue")["id"]
    _, g = _another_project(tmp_path, monkeypatch, "g")
    ghost = ok("add", "--title", "ghost")["id"]
    monkeypatch.chdir(project)
    a1 = ok("add", "--title", "a1")["id"]
    a2 = ok("add", "--title", "a2")["id"]
    ok("block", a1, "--by", b_card)
    ok("block", a1, "--by", ghost)
    ok("block", a2, "--by", b_issue)
    ok("ref", "add", a1, b_card)
    ok("ref", "add", a1, ghost)
    ok("forget", "--project", g["id"])  # ghost is now not-found

    entry = _entry(ok("export"))
    nodes = {n["id"]: n for n in _card_nodes(entry["cards"])}
    assert set(nodes[a1]["blocked_by"]) == {b_card, ghost}
    assert nodes[a2]["blocked_by"] == [b_issue]
    assert {"src_id": a1, "dst_id": b_card, "origin": "explicit"} in entry["refs"]
    assert {"src_id": a1, "dst_id": ghost, "origin": "explicit"} in entry["refs"]

    everything = ok("export", "--all")
    assert [e["project"]["id"] for e in everything["projects"]] == [
        entry["project"]["id"], b["id"]
    ]
    assert everything["projects"][0] == entry
    b_entry = everything["projects"][1]
    assert b_entry["refs"] == []
    assert all(n["blocked_by"] == [] for n in _card_nodes(b_entry["cards"]))
    assert a1 not in json.dumps(b_entry) and a2 not in json.dumps(b_entry)


def test_export_pretty_is_indented_json(project, tmp_path, monkeypatch):
    ok("add", "--title", "A")
    _another_project(tmp_path, monkeypatch, "second")
    for args in (["export"], ["export", "--all"]):
        text = human(*args)
        assert text.startswith("{\n  ")
        assert json.loads(text) == ok(*args)


def test_export_help_mentions_all():
    result = invoke("export", "--help")
    assert result.exit_code == 0, result.output
    # Rich wraps help inside a bordered panel; compare with borders and
    # line breaks folded away.
    text = " ".join(result.stdout.replace("│", " ").split())
    assert "--all" in text
    assert "every registered project" in text
