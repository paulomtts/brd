import copy
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
    assert err("import", snapshot) == "ProjectNotEmptyError"
    assert len(ok("list")) == before
    assert len(ok("projects")) == 1


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
    result = ok("import", snapshot)
    assert (result["imported"], result["cards"]) == (2, 2)
    assert len(result["projects"]) == 1 and result["not_found_edges"] == 0
    assert err("import", snapshot) == "ProjectNotEmptyError"
    assert ok("import", snapshot, "--yes")["projects"][0]["removed"]["cards"] == 2


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
    assert err("import", snapshot) == "ProjectNotEmptyError"
    assert ok("list") == [] and ok("issue", "list") == []
    assert len(ok("doc", "list")) == 1
    assert len(ok("projects")) == 1


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

_EMPTY_BODY = {key: [] for key in ("cards", "issues", "documents", "comments", "tags", "refs")}


@pytest.mark.parametrize(
    "raw",
    [
        {"brd_export": 2, "projects": "x"},
        {"brd_export": 2, "projects": [5]},
        {"brd_export": 2},
        {"brd_export": 2, "projects": [{"project": {}, "cards": []}]},
        {"brd_export": 2, "projects": [dict(_EMPTY_BODY)]},
        {"brd_export": 2, "projects": [{"project": 5, **_EMPTY_BODY}]},
        {"brd_export": 2, "projects": [
            {"project": {"id": "x", "name": "n", "created_at": "t"}, **_EMPTY_BODY}
        ]},
    ],
)
def test_malformed_v2_snapshot_says_malformed(project, tmp_path, monkeypatch, raw):
    other, error = _import_error_into_fresh(tmp_path, monkeypatch, raw)
    assert error["type"] == "ImportFormatError"
    assert error["message"].startswith("malformed snapshot: ")
    _assert_nothing_imported(other)


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



@pytest.mark.parametrize("fmt", ["export", "tree"])
def test_import_blocker_already_on_board_is_accepted(project, tmp_path, monkeypatch, fmt):
    issue = ok("issue", "open", "--title", "Q")
    node = _card_node(CARD_1, blocked_by=[issue["id"]])
    data = {"brd_export": 1, "cards": [node]} if fmt == "export" else [node]
    snapshot = _snapshot_file(tmp_path, data)
    # The issue lives in another project of this install; the target is empty.
    _another_project(tmp_path, monkeypatch, "second")
    result = ok("import", snapshot)
    assert result["not_found_edges"] == 0
    shown = ok("show", CARD_1)
    assert shown["blocked_by"] == [issue["id"]]
    assert [b["status"] for b in shown["blockers"]] == ["open"]


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


def test_import_refuses_a_snapshot_with_no_entries(project, tmp_path, monkeypatch):
    other, error = _import_error_into_fresh(tmp_path, monkeypatch, _v2())
    assert error["type"] == "ImportFormatError"
    assert "no project entries" in error["message"]
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

    # Re-importing places both entries back in their (non-empty) projects:
    # refused, and nothing is written.
    snapshot = tmp_path / "all.json"
    snapshot.write_text(json.dumps(from_a))
    assert err("import", snapshot) == "ProjectNotEmptyError"
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


T = "2026-01-01T00:00:00+00:00"
CARD_1 = "c1000000-0000-4000-8000-000000000001"
CARD_2 = "c2000000-0000-4000-8000-000000000002"
PROJECT_X = "aaaaaaaa-0000-4000-8000-00000000000a"
PROJECT_Y = "bbbbbbbb-0000-4000-8000-00000000000b"


def _unregistered_dir(tmp_path, monkeypatch, name, data_home=None):
    """chdir into a new directory that no `brd init` registered; with
    data_home, on a fresh install whose data lives there. Returns the
    resolved path, the string `brd init` would store for it."""
    if data_home is not None:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / data_home))
    path = tmp_path / name
    path.mkdir(parents=True)
    monkeypatch.chdir(path)
    return path.resolve()


def _snapshot_file(tmp_path, data, name="snapshot.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return path


def _import_error(snapshot):
    result = invoke("import", snapshot)
    assert result.exit_code == 1, result.output
    return json.loads(result.stdout)["error"]


def _card_node(card_id, blocked_by=()):
    return {
        "id": card_id,
        "title": f"card {card_id[:2]}",
        "description": None,
        "status": "todo",
        "blocked_by": list(blocked_by),
        "created_at": T,
        "updated_at": T,
        "children": [],
    }


def _hand_entry(project_id, root_path, name="hand", cards=(), issues=(), refs=()):
    """A v2 project entry built by hand: a recorded project plus its body."""
    return {
        "project": {"id": project_id, "name": name, "root_path": str(root_path), "created_at": T},
        "cards": list(cards),
        "issues": list(issues),
        "documents": [],
        "comments": [],
        "tags": [],
        "refs": list(refs),
    }


def _v2(*entries):
    return {"brd_export": 2, "projects": list(entries)}


def test_one_entry_import_registers_an_unregistered_cwd_with_the_entry_id(
    populated, tmp_path, monkeypatch
):
    data = ok("export")
    recorded = _entry(data)["project"]
    snapshot = _snapshot_file(tmp_path, data)
    restored = _unregistered_dir(tmp_path, monkeypatch, "restored", data_home="other-data")
    result = ok("import", snapshot)
    (registered,) = ok("projects")
    assert registered == {
        "id": recorded["id"],
        "name": recorded["name"],
        "root_path": str(restored),
        "created_at": recorded["created_at"],
    }
    (item,) = result["projects"]
    assert item["registered"] is True
    assert item["project"] == registered
    assert populated["card"]["id"] in {c["id"] for c in ok("list")}


def test_one_entry_import_mints_an_id_when_the_entry_id_is_taken(project, tmp_path, monkeypatch):
    (a,) = ok("projects")
    snapshot = _snapshot_file(
        tmp_path, _v2(_hand_entry(a["id"], tmp_path / "nowhere", cards=[_card_node(CARD_1)]))
    )
    restored = _unregistered_dir(tmp_path, monkeypatch, "restored")
    result = ok("import", snapshot)
    (item,) = result["projects"]
    assert item["registered"] is True
    assert item["project"]["id"] != a["id"]
    assert item["project"]["root_path"] == str(restored)
    assert item["project"]["name"] == "hand"
    projects = {p["id"]: p for p in ok("projects")}
    assert projects == {a["id"]: a, item["project"]["id"]: item["project"]}
    assert [c["id"] for c in ok("list")] == [CARD_1]


@pytest.mark.parametrize("fmt", ["v1", "tree"])
def test_v1_and_tree_import_register_an_unregistered_cwd(tmp_path, monkeypatch, fmt):
    node = _card_node(CARD_1)
    data = {"brd_export": 1, "cards": [node]} if fmt == "v1" else [node]
    snapshot = _snapshot_file(tmp_path, data)
    restored = _unregistered_dir(tmp_path, monkeypatch, "restored", data_home="data")
    result = ok("import", snapshot)
    (registered,) = ok("projects")
    assert registered["name"] == "restored"
    assert registered["root_path"] == str(restored)
    assert registered["id"]
    (item,) = result["projects"]
    assert item["project"] == registered and item["registered"] is True
    assert [c["id"] for c in ok("list")] == [CARD_1]


def test_one_entry_import_lands_in_the_cwd_project_from_a_subdirectory(
    project, tmp_path, monkeypatch
):
    (a,) = ok("projects")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()  # an existing directory, still ignored for a one-entry file
    snapshot = _snapshot_file(
        tmp_path, _v2(_hand_entry(PROJECT_X, elsewhere, cards=[_card_node(CARD_1)]))
    )
    sub = project / "src" / "deep"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    result = ok("import", snapshot)
    assert ok("projects") == [a]
    (item,) = result["projects"]
    assert item["project"] == a and item["registered"] is False
    assert [c["id"] for c in ok("list")] == [CARD_1]


@pytest.mark.parametrize("fmt", ["export", "tree"])
def test_unknown_edge_targets_are_kept_and_counted(tmp_path, monkeypatch, fmt):
    node = _card_node(CARD_1, blocked_by=[GHOST])
    if fmt == "export":
        ghost_ref = {"src_id": CARD_1, "dst_id": GHOST, "origin": "explicit"}
        data = _v2(_hand_entry(PROJECT_X, tmp_path / "x", cards=[node], refs=[ghost_ref]))
        expected = 2
    else:
        data = [node]
        expected = 1
    snapshot = _snapshot_file(tmp_path, data)
    _unregistered_dir(tmp_path, monkeypatch, "restored", data_home="data")
    assert ok("import", snapshot)["not_found_edges"] == expected
    shown = ok("show", CARD_1)
    assert [(b["id"], b["status"]) for b in shown["blockers"]] == [(GHOST, "not-found")]
    assert shown["status"] == "blocked"
    if fmt == "export":
        assert [r["id"] for r in shown["refs"] if r["origin"] == "explicit"] == [GHOST]


def test_importing_the_missing_project_later_reconnects_edges(project, tmp_path, monkeypatch):
    a1 = ok("add", "--title", "a1")["id"]
    second, _ = _another_project(tmp_path, monkeypatch, "second")
    b1 = ok("add", "--title", "b1")["id"]
    b_snapshot = _snapshot_file(tmp_path, ok("export"), "b.json")
    monkeypatch.chdir(project)
    ok("block", a1, "--by", b1)
    a_snapshot = _snapshot_file(tmp_path, ok("export"), "a.json")

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "other-data"))
    assert ok("import", a_snapshot)["not_found_edges"] == 1
    assert [(b["id"], b["status"]) for b in ok("show", a1)["blockers"]] == [(b1, "not-found")]
    monkeypatch.chdir(second)
    assert ok("import", b_snapshot)["not_found_edges"] == 0
    monkeypatch.chdir(project)
    assert [(b["id"], b["status"]) for b in ok("show", a1)["blockers"]] == [(b1, "todo")]


def test_id_owned_by_another_project_is_refused(populated, tmp_path, monkeypatch):
    (owner,) = ok("projects")
    snapshot = _snapshot_file(tmp_path, ok("export"))
    _another_project(tmp_path, monkeypatch, "second")
    error = _import_error(snapshot)
    assert error["type"] == "EntityAlreadyExistsError"
    assert populated["card"]["id"] in error["message"]
    assert f"in project {owner['name']} ({owner['id']})" in error["message"]
    assert ok("list") == [] and ok("issue", "list") == [] and ok("doc", "list") == []
    assert len(ok("projects")) == 2


def test_tree_id_owned_by_another_project_is_refused(project, tmp_path, monkeypatch):
    (owner,) = ok("projects")
    card_id = ok("add", "--title", "A")["id"]
    snapshot = _snapshot_file(tmp_path, ok("tree"))
    _another_project(tmp_path, monkeypatch, "second")
    error = _import_error(snapshot)
    assert error["type"] == "EntityAlreadyExistsError"
    assert card_id in error["message"]
    assert f"in project {owner['name']} ({owner['id']})" in error["message"]
    assert ok("list") == []


def test_import_report_shape_and_pretty(populated, tmp_path, monkeypatch):
    snapshot = _snapshot_file(tmp_path, ok("export"))
    _fresh_project(tmp_path, monkeypatch)
    result = ok("import", snapshot)
    assert set(result) == {
        "imported", "cards", "issues", "documents", "comments", "projects", "not_found_edges"
    }
    assert (
        result["imported"], result["cards"], result["issues"], result["documents"],
        result["comments"],
    ) == (4, 2, 1, 1, 1)
    (registered,) = ok("projects")
    assert result["projects"] == [
        {
            "project": registered,
            "registered": False,
            "imported": 4,
            "cards": 2,
            "issues": 1,
            "documents": 1,
            "comments": 1,
            "removed": {"cards": 0, "issues": 0, "documents": 0, "comments": 0},
        }
    ]
    assert result["not_found_edges"] == 0

    restored = _unregistered_dir(tmp_path, monkeypatch, "restored", data_home="third-data")
    text = human("import", snapshot)
    assert text.splitlines() == [
        f"repo ({restored}): +2 cards, +1 issues, +1 documents, +1 comments [registered]",
        "not-found edge targets: 0",
    ]


def test_failed_import_registers_no_project(populated, tmp_path, monkeypatch):
    data = ok("export")
    _entry(data)["comments"].append(
        {
            "id": "00000000-0000-0000-0000-000000000000",
            "entity_id": "does-not-exist",
            "author": "x",
            "body": "y",
            "created_at": T,
        }
    )
    snapshot = _snapshot_file(tmp_path, data)
    _unregistered_dir(tmp_path, monkeypatch, "restored", data_home="other-data")
    error = _import_error(snapshot)
    assert error["type"] == "ImportFormatError"
    assert "internally inconsistent" in error["message"]
    assert ok("projects") == []
    docs_dir = paths.docs_dir()
    assert not docs_dir.exists() or list(docs_dir.iterdir()) == []


def test_import_refuses_two_documents_with_one_path(populated, tmp_path, monkeypatch):
    data = ok("export")
    docs = _entry(data)["documents"]
    docs.append({**docs[0], "id": "d0c00000-0000-4000-8000-000000000001"})
    snapshot = _snapshot_file(tmp_path, data)
    _unregistered_dir(tmp_path, monkeypatch, "restored", data_home="other-data")
    error = _import_error(snapshot)
    assert error["type"] == "ImportFormatError"
    assert ok("projects") == []
    docs_dir = paths.docs_dir()
    assert not docs_dir.exists() or list(docs_dir.iterdir()) == []


def test_multi_entry_import_matches_registered_projects_by_id(project, tmp_path, monkeypatch):
    (a,) = ok("projects")
    new_root = tmp_path / "new-root"
    new_root.mkdir()
    snapshot = _snapshot_file(tmp_path, _v2(
        _hand_entry(a["id"], tmp_path / "gone", name="a", cards=[_card_node(CARD_1)]),
        _hand_entry(PROJECT_X, new_root.resolve(), name="x", cards=[_card_node(CARD_2)]),
    ))
    _unregistered_dir(tmp_path, monkeypatch, "elsewhere")
    result = ok("import", snapshot)
    first, second = result["projects"]
    assert first["project"] == a and first["registered"] is False and first["cards"] == 1
    assert second["project"] == {
        "id": PROJECT_X, "name": "x", "root_path": str(new_root.resolve()), "created_at": T
    }
    assert second["registered"] is True and second["cards"] == 1
    assert {p["id"]: p for p in ok("projects")} == {a["id"]: a, PROJECT_X: second["project"]}
    monkeypatch.chdir(project)
    assert [c["id"] for c in ok("list")] == [CARD_1]
    monkeypatch.chdir(new_root)
    assert [c["id"] for c in ok("list")] == [CARD_2]


def test_multi_entry_import_registers_at_recorded_roots(project, tmp_path, monkeypatch):
    a_card = ok("add", "--title", "A card")["id"]
    second, _ = _another_project(tmp_path, monkeypatch, "second")
    b_card = ok("add", "--title", "B card")["id"]
    data = ok("export", "--all")
    snapshot = _snapshot_file(tmp_path, data)
    _unregistered_dir(tmp_path, monkeypatch, "elsewhere", data_home="other-data")
    result = ok("import", snapshot)
    recorded = [e["project"] for e in data["projects"]]
    assert ok("projects") == recorded
    assert [item["project"] for item in result["projects"]] == recorded
    assert [item["registered"] for item in result["projects"]] == [True, True]
    monkeypatch.chdir(project)
    assert [c["id"] for c in ok("list")] == [a_card]
    monkeypatch.chdir(second)
    assert [c["id"] for c in ok("list")] == [b_card]


def test_multi_entry_import_lists_every_missing_root(tmp_path, monkeypatch):
    gone_a, gone_b = tmp_path / "gone-a", tmp_path / "gone-b"
    a_file = tmp_path / "a-file"
    a_file.write_text("not a directory")
    snapshot = _snapshot_file(tmp_path, _v2(
        _hand_entry(PROJECT_X, gone_a, name="x", cards=[_card_node(CARD_1)]),
        _hand_entry(PROJECT_Y, gone_b, name="y", cards=[_card_node(CARD_2)]),
        _hand_entry("cccccccc-0000-4000-8000-00000000000c", a_file, name="f"),
        _hand_entry("dddddddd-0000-4000-8000-00000000000d", "relative/dir", name="r"),
    ))
    _unregistered_dir(tmp_path, monkeypatch, "elsewhere", data_home="data")
    error = _import_error(snapshot)
    assert error["type"] == "ProjectRootNotFoundError"
    for root in (str(gone_a), str(gone_b), str(a_file), "relative/dir"):
        assert root in error["message"]
    for name, root in (("x", gone_a), ("y", gone_b)):
        assert f"{name} ({root})" in error["message"]
    assert ok("projects") == []


def test_multi_entry_import_succeeds_once_the_roots_exist(tmp_path, monkeypatch):
    gone_a, gone_b = tmp_path / "gone-a", tmp_path / "gone-b"
    snapshot = _snapshot_file(tmp_path, _v2(
        _hand_entry(PROJECT_X, gone_a, name="x", cards=[_card_node(CARD_1)]),
        _hand_entry(PROJECT_Y, gone_b, name="y", cards=[_card_node(CARD_2)]),
    ))
    _unregistered_dir(tmp_path, monkeypatch, "elsewhere", data_home="data")
    assert _import_error(snapshot)["type"] == "ProjectRootNotFoundError"
    gone_a.mkdir()
    gone_b.mkdir()
    result = ok("import", snapshot)
    assert [item["registered"] for item in result["projects"]] == [True, True]
    assert {p["id"] for p in ok("projects")} == {PROJECT_X, PROJECT_Y}


def test_multi_entry_import_ignores_the_cwd_project(project, tmp_path, monkeypatch):
    (a,) = ok("projects")
    root_x, root_y = tmp_path / "x", tmp_path / "y"
    root_x.mkdir()
    root_y.mkdir()
    snapshot = _snapshot_file(tmp_path, _v2(
        _hand_entry(PROJECT_X, root_x.resolve(), name="x", cards=[_card_node(CARD_1)]),
        _hand_entry(PROJECT_Y, root_y.resolve(), name="y", cards=[_card_node(CARD_2)]),
    ))
    result = ok("import", snapshot)  # cwd is project's root
    assert [item["project"]["id"] for item in result["projects"]] == [PROJECT_X, PROJECT_Y]
    assert ok("list") == []
    assert {p["id"] for p in ok("projects")} == {a["id"], PROJECT_X, PROJECT_Y}


def test_multi_entry_import_refuses_a_root_registered_under_another_id(
    project, tmp_path, monkeypatch
):
    ok("add", "--title", "A")
    _another_project(tmp_path, monkeypatch, "second")
    ok("add", "--title", "B")
    data = ok("export", "--all")
    snapshot = _snapshot_file(tmp_path, data)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "other-data"))
    monkeypatch.chdir(project)
    squatter = ok("init")
    error = _import_error(snapshot)
    assert error["type"] == "ProjectAlreadyExistsError"
    assert data["projects"][0]["project"]["root_path"] in error["message"]
    assert squatter["id"] in error["message"]
    assert "alone" in error["message"]
    assert ok("projects") == [squatter]
    assert ok("list") == []


@pytest.mark.parametrize("entries", [1, 2])
def test_import_refuses_a_non_empty_target(project, tmp_path, monkeypatch, entries):
    (a,) = ok("projects")
    if entries == 1:
        ok("add", "--title", "existing")
    else:
        ok("issue", "open", "--title", "existing")
    before = (ok("list"), ok("issue", "list"))
    new_root = tmp_path / "new-root"
    new_root.mkdir()
    hand = [
        _hand_entry(a["id"], project, cards=[_card_node(CARD_1)]),
        _hand_entry(PROJECT_X, new_root.resolve(), cards=[_card_node(CARD_2)]),
    ]
    snapshot = _snapshot_file(tmp_path, _v2(*hand[:entries]))
    if entries == 2:
        _unregistered_dir(tmp_path, monkeypatch, "elsewhere")
    result = invoke("import", snapshot)
    assert result.exit_code == 1, result.output
    error = json.loads(result.stdout)["error"]
    assert error["type"] == "ProjectNotEmptyError"
    assert a["id"] in error["message"] and a["name"] in error["message"]
    assert "--yes" in error["message"]
    assert "not supported yet" not in error["message"]
    assert result.stderr == ""
    assert ok("projects") == [a]
    monkeypatch.chdir(project)
    assert (ok("list"), ok("issue", "list")) == before


def test_cross_entry_edges_connect_in_either_order(project, tmp_path, monkeypatch):
    a_issue = ok("issue", "open", "--title", "A issue")["id"]
    a1 = ok("add", "--title", "a1")["id"]
    second, _ = _another_project(tmp_path, monkeypatch, "second")
    b1 = ok("add", "--title", "b1")["id"]
    b_issue = ok("issue", "open", "--title", "B issue")["id"]
    ok("block", b1, "--by", a_issue)
    monkeypatch.chdir(project)
    ok("block", a1, "--by", b1)
    ok("ref", "add", a1, b_issue)
    data = ok("export", "--all")
    data["projects"].reverse()
    snapshot = _snapshot_file(tmp_path, data)
    _unregistered_dir(tmp_path, monkeypatch, "elsewhere", data_home="other-data")
    assert ok("import", snapshot)["not_found_edges"] == 0
    monkeypatch.chdir(project)
    shown = ok("show", a1)
    assert [(b["id"], b["status"]) for b in shown["blockers"]] == [(b1, "blocked")]
    explicit = [r for r in shown["refs"] if r["origin"] == "explicit"]
    assert [(r["id"], r["kind"]) for r in explicit] == [(b_issue, "issue")]
    monkeypatch.chdir(second)
    assert [(b["id"], b["status"]) for b in ok("show", b1)["blockers"]] == [(a_issue, "open")]


def test_duplicate_ids_across_entries_are_refused(tmp_path, monkeypatch):
    root_x, root_y = tmp_path / "x", tmp_path / "y"
    root_x.mkdir()
    root_y.mkdir()
    x = _hand_entry(PROJECT_X, root_x.resolve(), name="x", cards=[_card_node(CARD_1)])
    y = _hand_entry(PROJECT_Y, root_y.resolve(), name="y", cards=[_card_node(CARD_2)])
    same_card = _hand_entry(PROJECT_Y, root_y.resolve(), name="y", cards=[_card_node(CARD_1)])
    same_id = {**y, "project": {**y["project"], "id": PROJECT_X}}
    same_root = {**y, "project": {**y["project"], "root_path": x["project"]["root_path"]}}
    _unregistered_dir(tmp_path, monkeypatch, "elsewhere", data_home="data")
    for second, words in [
        (same_card, "duplicate ids"),
        (same_id, PROJECT_X),
        (same_root, x["project"]["root_path"]),
    ]:
        snapshot = _snapshot_file(tmp_path, _v2(x, second))
        error = _import_error(snapshot)
        assert error["type"] == "ImportFormatError"
        assert words in error["message"]
        assert ok("projects") == []


def test_import_help_describes_placement():
    result = invoke("import", "--help")
    assert result.exit_code == 0, result.output
    # Rich wraps help inside a bordered panel; compare with borders and
    # line breaks folded away.
    text = " ".join(result.stdout.replace("│", " ").split())
    assert "current project" in text
    assert "multi-project" in text
    assert "already has entities" in text


def _board():
    """What a replacing import could change, as the CLI shows it from the cwd."""
    return {
        "projects": ok("projects"),
        "cards": ok("list"),
        "issues": ok("issue", "list"),
        "docs": ok("doc", "list"),
        "export": ok("export"),
    }


def _backups():
    """Every document backup file in this install, with its bytes."""
    docs_dir = paths.docs_dir()
    if not docs_dir.exists():
        return {}
    return {path.name: path.read_bytes() for path in docs_dir.iterdir()}


def test_replace_without_tty_or_yes_refuses(populated, tmp_path):
    snapshot = _snapshot_file(tmp_path, ok("export"))
    (registered,) = ok("projects")
    before, backups = _board(), _backups()
    result = invoke("import", snapshot)
    assert result.exit_code == 1, result.output
    error = json.loads(result.stdout)["error"]
    assert error["type"] == "ProjectNotEmptyError"
    assert registered["name"] in error["message"] and registered["id"] in error["message"]
    assert "--yes" in error["message"]
    assert "not supported yet" not in error["message"]
    assert result.stderr == ""
    assert _board() == before and _backups() == backups


def _import_on_tty(monkeypatch, snapshot, answer, *args):
    """`brd import` as if stdin were a terminal, typing answer. The runner
    echoes the typed answer into stdout before the envelope, so the
    envelope is parsed from its first `{`."""
    monkeypatch.setattr("brd.cli.snapshot._stdin_is_tty", lambda: True)
    result = invoke("import", snapshot, *args, input=answer)
    out = result.stdout
    return result.exit_code, json.loads(out[out.index("{"):]), result.stderr


@pytest.mark.parametrize("answer", ["y\n", "yes\n"])
def test_replace_on_tty_answer_yes_replaces_the_project(populated, tmp_path, monkeypatch, answer):
    data = ok("export")
    snapshot = _snapshot_file(tmp_path, data)
    extra = ok("add", "--title", "extra")["id"]
    ok("update", populated["card"]["id"], "--title", "Renamed")
    (registered,) = ok("projects")

    code, envelope, stderr = _import_on_tty(monkeypatch, snapshot, answer)
    assert code == 0 and envelope["ok"] is True
    assert (
        f"brd: replacing {registered['name']} ({registered['root_path']}): "
        "-3 cards, -1 issues, -1 documents, -1 comments / "
        "+2 cards, +1 issues, +1 documents, +1 comments"
    ) in stderr
    assert "Replace 1 project(s)? This cannot be undone. [y/N]" in stderr
    (item,) = envelope["data"]["projects"]
    assert item["registered"] is False
    assert item["removed"] == {"cards": 3, "issues": 1, "documents": 1, "comments": 1}
    assert extra not in {card["id"] for card in ok("list")}
    assert ok("show", populated["card"]["id"])["title"] == "Parser"
    assert ok("export") == data


@pytest.mark.parametrize("answer", ["n\n", "\n", ""], ids=["no", "empty", "eof"])
def test_replace_on_tty_answer_no_changes_nothing(populated, tmp_path, monkeypatch, answer):
    snapshot = _snapshot_file(tmp_path, ok("export"))
    ok("add", "--title", "extra")
    before, backups = _board(), _backups()
    code, envelope, stderr = _import_on_tty(monkeypatch, snapshot, answer)
    assert code == 1
    assert envelope["error"]["type"] == "Aborted"
    assert "cancelled" in envelope["error"]["message"]
    assert "brd: replacing " in stderr
    assert _board() == before and _backups() == backups


def test_replace_with_yes_skips_the_prompt(populated, tmp_path):
    data = ok("export")
    snapshot = _snapshot_file(tmp_path, data)
    extra = ok("add", "--title", "extra")["id"]
    result = invoke("import", snapshot, "--yes")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["ok"] is True
    assert "brd: replacing " in result.stderr
    assert "[y/N]" not in result.stderr
    assert extra not in {card["id"] for card in ok("list")}
    assert ok("export") == data

    ok("add", "--title", "extra again")
    result = invoke("import", snapshot, "--yes", "--pretty")
    assert result.exit_code == 0, result.output
    project_line, _ = result.stdout.splitlines()
    assert project_line.endswith(" [replaced]")
    # The summary is stderr's, never part of the pretty report.
    assert "brd: replacing " in result.stderr
    assert "brd: replacing " not in result.stdout


def test_validation_refusals_come_before_the_prompt(populated, tmp_path, monkeypatch):
    data = ok("export")
    entry = _entry(data)
    entry["cards"].append(copy.deepcopy(entry["cards"][0]))
    snapshot = _snapshot_file(tmp_path, data)
    before, backups = _board(), _backups()
    code, envelope, stderr = _import_on_tty(monkeypatch, snapshot, "y\n")
    assert code == 1
    assert envelope["error"]["type"] == "ImportFormatError"
    assert "duplicate ids" in envelope["error"]["message"]
    assert stderr == ""
    assert _board() == before and _backups() == backups


def test_ids_may_move_between_two_replaced_projects(project, tmp_path, monkeypatch):
    a1 = ok("add", "--title", "a1")["id"]
    b_root, _ = _another_project(tmp_path, monkeypatch, "bproj")
    b1 = ok("add", "--title", "b1")["id"]
    data = ok("export", "--all")
    a_entry, b_entry = data["projects"]
    a_entry["cards"], b_entry["cards"] = b_entry["cards"], a_entry["cards"]
    snapshot = _snapshot_file(tmp_path, data)
    _unregistered_dir(tmp_path, monkeypatch, "elsewhere")
    result = ok("import", snapshot, "--yes")
    assert [item["removed"]["cards"] for item in result["projects"]] == [1, 1]
    monkeypatch.chdir(project)
    assert [card["id"] for card in ok("list")] == [b1]
    monkeypatch.chdir(b_root)
    assert [card["id"] for card in ok("list")] == [a1]


def test_replace_of_a_registered_but_empty_target_does_not_ask(project, tmp_path, monkeypatch):
    snapshot = _snapshot_file(tmp_path, [_card_node(CARD_1)])
    code, envelope, stderr = _import_on_tty(monkeypatch, snapshot, "")
    assert code == 0 and envelope["ok"] is True
    assert stderr == ""
    (item,) = envelope["data"]["projects"]
    assert item["registered"] is False
    assert item["removed"] == {"cards": 0, "issues": 0, "documents": 0, "comments": 0}

    _another_project(tmp_path, monkeypatch, "second")
    text = human("import", _snapshot_file(tmp_path, [_card_node(CARD_2)], "second.json"))
    assert "[replaced]" not in text


def test_id_owned_by_a_project_not_being_replaced_is_refused_naming_the_owner(
    project, tmp_path, monkeypatch
):
    a1 = ok("add", "--title", "a1")["id"]
    a_entry = _entry(ok("export"))
    c_root, c = _another_project(tmp_path, monkeypatch, "cproj")
    c1 = ok("add", "--title", "c1")["id"]
    ok("comment", "add", c1, "c note")
    c_entry = _entry(ok("export"))
    before_c, backups = _board(), _backups()
    monkeypatch.chdir(project)
    before_a = _board()

    with_card = copy.deepcopy(a_entry)
    with_card["cards"].append(c_entry["cards"][0])
    c_comment = c_entry["comments"][0]
    with_comment = copy.deepcopy(a_entry)
    with_comment["comments"].append({**c_comment, "entity_id": a1})
    for entry, owned_id, what in (
        (with_card, c1, "entity"),
        (with_comment, c_comment["id"], "comment"),
    ):
        snapshot = _snapshot_file(tmp_path, _v2(entry))
        result = invoke("import", snapshot, "--yes")
        assert result.exit_code == 1, result.output
        error = json.loads(result.stdout)["error"]
        assert error["type"] == "EntityAlreadyExistsError"
        assert f"{what} {owned_id} already exists in project {c['name']} ({c['id']})" in (
            error["message"]
        )
        assert result.stderr == ""
        assert _board() == before_a and _backups() == backups
    monkeypatch.chdir(c_root)
    assert _board() == before_c


@pytest.mark.parametrize("clash", ["path", "stem"])
def test_duplicate_document_paths_in_a_replacing_entry_refuse_before_the_prompt(
    populated, tmp_path, monkeypatch, clash
):
    data = ok("export")
    docs = _entry(data)["documents"]
    twin = {**docs[0], "id": "d0c00000-0000-4000-8000-000000000001"}
    if clash == "stem":
        twin["source_path"] = "other/NOTES.md"  # stem `NOTES`, same as `notes` ignoring case
    docs.append(twin)
    snapshot = _snapshot_file(tmp_path, data)
    before, backups = _board(), _backups()
    code, envelope, stderr = _import_on_tty(monkeypatch, snapshot, "y\n")
    assert code == 1
    assert envelope["error"]["type"] == "ImportFormatError"
    assert clash in envelope["error"]["message"]
    assert stderr == ""
    assert _board() == before and _backups() == backups


def test_replace_removes_old_document_backups_after_commit(
    project, populated, tmp_path, monkeypatch
):
    d1 = populated["doc"]["id"]
    write(project, "docs/second.md", "# Second")
    d2 = ok("doc", "add", "docs/second.md")["id"]
    data = ok("export")
    entry = _entry(data)
    entry["documents"] = [d for d in entry["documents"] if d["id"] != d2]
    (d1_doc,) = entry["documents"]
    snapshot = _snapshot_file(tmp_path, data)
    keeper_root, _ = _another_project(tmp_path, monkeypatch, "keeper")
    write(keeper_root, "docs/kept.md", "# Kept")
    kept = ok("doc", "add", "docs/kept.md")["id"]
    monkeypatch.chdir(project)
    backups = _backups()
    assert {f"{d1}.md", f"{d2}.md", f"{kept}.md"} <= set(backups)

    ok("import", snapshot, "--yes")
    after = _backups()
    assert f"{d2}.md" not in after
    assert after[f"{d1}.md"] == d1_doc["content"].encode()
    assert after[f"{kept}.md"] == b"# Kept"

    # An entry with no content writes no backup, so d1's old one goes too.
    del d1_doc["content"]
    ok("import", _snapshot_file(tmp_path, data, "no-content.json"), "--yes")
    after = _backups()
    assert f"{d1}.md" not in after
    assert after[f"{kept}.md"] == b"# Kept"


def test_failed_replace_leaves_old_state_and_backups_intact(populated, tmp_path):
    data = ok("export")
    entry = _entry(data)
    d1 = populated["doc"]["id"]
    next(d for d in entry["documents"] if d["id"] == d1)["content"] = "# Notes\nchanged"
    d9 = "d9000000-0000-4000-8000-000000000009"
    entry["documents"].append(
        {"id": d9, "title": "Nine", "source_path": "docs/nine.md", "content": "nine",
         "content_hash": "h", "created_at": T, "updated_at": T}
    )
    entry["comments"].append(
        {"id": "00000000-0000-0000-0000-000000000000", "entity_id": "does-not-exist",
         "author": "x", "body": "y", "created_at": T}
    )
    snapshot = _snapshot_file(tmp_path, data)
    before, backups = _board(), _backups()
    assert f"{d1}.md" in backups
    result = invoke("import", snapshot, "--yes")
    assert result.exit_code == 1, result.output
    error = json.loads(result.stdout)["error"]
    assert error["type"] == "ImportFormatError"
    assert "internally inconsistent" in error["message"]
    assert _backups() == backups
    assert _board() == before


def test_malformed_entity_in_a_replace_leaves_old_state_and_backups_intact(populated, tmp_path):
    data = ok("export")
    entry = _entry(data)
    next(d for d in entry["documents"])["content"] = "# Notes\nchanged"
    del entry["issues"][0]["title"]  # only the insert inside the transaction reads it
    snapshot = _snapshot_file(tmp_path, data)
    before, backups = _board(), _backups()
    result = invoke("import", snapshot, "--yes")
    assert result.exit_code == 1, result.output
    error = json.loads(result.stdout)["error"]
    assert error["type"] == "ImportFormatError"
    assert error["message"].startswith("malformed snapshot: ")
    assert _backups() == backups
    assert _board() == before


def test_incoming_edges_survive_replacement_and_reconnect(project, tmp_path, monkeypatch):
    a1 = ok("add", "--title", "a1")["id"]
    b_root, _ = _another_project(tmp_path, monkeypatch, "bproj")
    b1 = ok("add", "--title", "b1")["id"]
    ok("block", b1, "--by", a1)
    ok("ref", "add", b1, a1)
    monkeypatch.chdir(project)
    ok("update", a1, "--status", "done")  # a finished blocker: b1 resolves todo
    full = ok("export")
    without = copy.deepcopy(full)
    _entry(without)["cards"] = []
    full_file = _snapshot_file(tmp_path, full, "full.json")
    without_file = _snapshot_file(tmp_path, without, "without.json")

    def b1_view():
        monkeypatch.chdir(b_root)
        shown = ok("show", b1)
        monkeypatch.chdir(project)
        return (
            [(b["id"], b["status"]) for b in shown["blockers"]],
            shown["status"],
            [r["id"] for r in shown["refs"] if r["origin"] == "explicit"],
        )

    assert b1_view() == ([(a1, "done")], "todo", [a1])
    result = ok("import", without_file, "--yes")
    assert result["projects"][0]["removed"]["cards"] == 1
    assert result["not_found_edges"] == 0  # b1's edge is not from the file
    assert b1_view() == ([(a1, "not-found")], "blocked", [a1])

    ok("import", full_file, "--yes")
    assert b1_view() == ([(a1, "done")], "todo", [a1])


def test_replace_keeps_the_project_row(populated, tmp_path):
    data = ok("export")
    _entry(data)["project"].update(name="renamed", created_at=T)
    snapshot = _snapshot_file(tmp_path, data)
    before = ok("projects")
    result = ok("import", snapshot, "--yes")
    assert ok("projects") == before
    assert result["projects"][0]["project"] == before[0]


def test_replace_never_touches_doc_source_files(project, populated, tmp_path):
    data = ok("export")
    _entry(data)["documents"].append(
        {"id": "d9000000-0000-4000-8000-000000000009", "title": "Absent",
         "source_path": "docs/absent.md", "content": "absent", "content_hash": "h",
         "created_at": T, "updated_at": T}
    )
    snapshot = _snapshot_file(tmp_path, data)
    write(project, "docs/notes.md", "local edits")
    write(project, "docs/other.md", "keep")
    ok("import", snapshot, "--yes")
    assert (project / "docs" / "notes.md").read_bytes() == b"local edits"
    assert (project / "docs" / "other.md").read_bytes() == b"keep"
    assert not (project / "docs" / "absent.md").exists()


def test_replacing_a_project_frees_its_document_paths_and_stems(populated, tmp_path, monkeypatch):
    snapshot = _snapshot_file(tmp_path, ok("export"))
    other = _fresh_project(tmp_path, monkeypatch)
    write(other, "docs/notes.md", "local")
    ok("doc", "add", "docs/notes.md")
    result = ok("import", snapshot, "--yes")
    assert result["projects"][0]["removed"]["documents"] == 1
    assert [d["id"] for d in ok("doc", "list")] == [populated["doc"]["id"]]
    assert (other / "docs" / "notes.md").read_text() == "local"


def test_round_trip_across_two_machines(project, populated, tmp_path, monkeypatch):
    a_card = populated["card"]["id"]
    _another_project(tmp_path, monkeypatch, "bproj")
    b_card = ok("add", "--title", "B card")["id"]
    b_issue = ok("issue", "open", "--title", "B issue")["id"]
    ok("block", b_card, "--by", a_card)
    monkeypatch.chdir(project)
    ok("ref", "add", a_card, b_issue)
    machine1 = ok("export", "--all")
    snapshot = _snapshot_file(tmp_path, machine1, "all.json")

    def by_id(data):
        return sorted(data["projects"], key=lambda entry: entry["project"]["id"])

    # Machine 2: an empty install; the recorded roots exist on this disk.
    _unregistered_dir(tmp_path, monkeypatch, "elsewhere", data_home="machine2")
    result = invoke("import", snapshot, "--yes")
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)["data"]
    assert [item["registered"] for item in report["projects"]] == [True, True]
    assert all(not any(item["removed"].values()) for item in report["projects"])
    assert report["not_found_edges"] == 0
    assert "replacing" not in result.stderr
    assert by_id(ok("export", "--all")) == by_id(machine1)

    # Re-importing the same file replaces both projects with themselves.
    again = ok("import", snapshot, "--yes")
    for item in again["projects"]:
        assert item["registered"] is False
        assert item["removed"] == {key: item[key] for key in ("cards", "issues", "documents", "comments")}
    assert by_id(ok("export", "--all")) == by_id(machine1)
