"""Leak guard: every listing and lookup command, run from one project, shows
nothing owned by another project in the same brd.db."""

import json
import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.cli_helpers import invoke

SIDES = ("alpha", "bravo")
MARKERS = {"alpha": "ALPHAMARK", "bravo": "BRAVOMARK"}


@dataclass
class Side:
    name: str
    marker: str
    root: Path
    project: str
    story: str
    task_one: str
    task_two: str
    issue: str
    doc: str
    comment: str

    @property
    def tag(self) -> str:
        return f"{self.marker.lower()}-tag"

    @property
    def ids(self) -> set[str]:
        return {
            self.project, self.story, self.task_one, self.task_two,
            self.issue, self.doc, self.comment,
        }


@dataclass
class Board:
    data: Path
    sides: dict[str, Side]

    def other(self, name: str) -> Side:
        return self.sides["bravo" if name == "alpha" else "alpha"]


def _ok(*args) -> dict:
    result = invoke(*args)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True, payload
    return payload["data"]


def _cards(nodes) -> list[dict]:
    return [n for node in nodes for n in [node, *_cards(node["children"])]]


def _seed(name: str, root: Path) -> Side:
    """B1: the same shape on both sides; only the marker differs."""
    m = MARKERS[name]
    root.mkdir()
    os.chdir(root)
    project = _ok("init")["id"]
    (root / "docs").mkdir()
    (root / "docs" / "notes.md").write_text(f"# {m} notes\n\nSee [[plan]].\n")
    doc = _ok("doc", "add", "docs/notes.md", "--title", f"{m} notes", "--tag", f"{m.lower()}-tag")
    story = _ok("add", "--title", f"{m} story")
    one = _ok(
        "add", "--title", f"{m} task one", "--parent", story["id"],
        "--description", f"{m} task links [[notes]]",
    )
    two = _ok(
        "add", "--title", f"{m} task two", "--parent", story["id"], "--blocked-by", one["id"]
    )
    issue = _ok(
        "issue", "open", "--title", f"{m} bug", "--body", f"{m} bug about [[notes]]",
        "--blocks", two["id"],
    )
    comment = _ok(
        "comment", "add", one["id"], f"{m} comment on [[notes]]", "--author", f"{m}-author"
    )
    _ok("ref", "add", one["id"], issue["id"])
    (root / "sub" / "deeper").mkdir(parents=True)
    return Side(
        name=name, marker=m, root=root, project=project, story=story["id"],
        task_one=one["id"], task_two=two["id"], issue=issue["id"], doc=doc["id"],
        comment=comment["id"],
    )


def _check_seed(side: Side) -> None:
    """T5, guarding the guard: a seed that silently failed would let every case pass."""
    os.chdir(side.root)
    exported = _ok("export")
    assert len(_cards(exported["cards"])) == 3
    assert [i["id"] for i in exported["issues"]] == [side.issue]
    assert [d["id"] for d in exported["documents"]] == [side.doc]
    assert [c["id"] for c in exported["comments"]] == [side.comment]
    assert exported["tags"] == [{"entity_id": side.doc, "tag": side.tag}]
    assert exported["refs"] == [
        {"src_id": side.task_one, "dst_id": side.issue, "origin": "explicit"}
    ]
    # [[notes]] mention refs are not exported; show proves the stem resolved.
    shown = _ok("show", side.task_one)
    assert side.doc in {r["id"] for r in shown["refs"]}


@pytest.fixture(scope="module")
def board(tmp_path_factory) -> Board:
    base = tmp_path_factory.mktemp("leak")
    data = base / "data"
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("XDG_DATA_HOME", str(data))
        mp.delenv("BRD_AUTHOR", raising=False)
        mp.chdir(base)
        sides = {name: _seed(name, base / name) for name in SIDES}
        for side in sides.values():
            _check_seed(side)
    return Board(data=data, sides=sides)


def _leaks(out: str, other: Side, exempt: frozenset[str] = frozenset()) -> list[str]:
    """B4: the other side's marker (any case) and every foreign id not exempt."""
    found = [other.marker] if other.marker.lower() in out.lower() else []
    return found + sorted(i for i in other.ids - exempt if i in out)


# B2: (id, argv builder). The builder gets the current side.
GUARDED = [
    ("list", lambda s: ["list"]),
    ("list-status", lambda s: ["list", "--status", "todo"]),
    ("list-parent", lambda s: ["list", "--parent", s.story]),
    ("next", lambda s: ["next"]),
    ("next-parent", lambda s: ["next", "--parent", s.story]),
    ("tree", lambda s: ["tree"]),
    ("tree-root", lambda s: ["tree", s.story]),
    ("issue-list", lambda s: ["issue", "list"]),
    ("doc-list", lambda s: ["doc", "list"]),
    ("doc-list-tag", lambda s: ["doc", "list", "--tag", s.tag]),
    ("tag-counts", lambda s: ["tag", "list"]),
    ("tag-list", lambda s: ["tag", "list", s.doc]),
    ("comment-list", lambda s: ["comment", "list", s.task_one]),
    ("show-card", lambda s: ["show", s.task_one]),
    ("show-issue", lambda s: ["show", s.issue]),
    ("show-doc", lambda s: ["show", s.doc]),
    ("export", lambda s: ["export"]),
]
CWDS = {"root": Path("."), "sub/deeper": Path("sub/deeper")}
MODES = {"json": [], "pretty": ["--pretty"]}


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(("command", "build"), GUARDED, ids=[g[0] for g in GUARDED])
@pytest.mark.parametrize("cwd", CWDS)
@pytest.mark.parametrize("side", SIDES)
def test_nothing_from_the_other_project_leaks(
    board, monkeypatch, side, cwd, command, build, mode
):
    me, other = board.sides[side], board.other(side)
    monkeypatch.setenv("XDG_DATA_HOME", str(board.data))
    monkeypatch.chdir(me.root / CWDS[cwd])
    result = invoke(*build(me), *MODES[mode])
    where = f"{command} from {side} at {cwd} ({mode})"
    assert result.exit_code == 0, f"{where}: {result.output}"
    assert me.marker.lower() in result.stdout.lower(), f"{where}: own data missing"
    assert _leaks(result.stdout, other) == [], f"{where} leaks"


# B3: (id, argv builder, expected error type or None for ok + []).
# The builder gets the other side.
FOREIGN = [
    ("list-parent-foreign", lambda o: ["list", "--parent", o.story], None),
    ("next-parent-foreign", lambda o: ["next", "--parent", o.story], "CardNotFoundError"),
    ("tree-root-foreign", lambda o: ["tree", o.story], "CardNotFoundError"),
    ("comment-list-foreign", lambda o: ["comment", "list", o.task_one], "CardNotFoundError"),
    ("tag-list-foreign", lambda o: ["tag", "list", o.doc], "DocumentNotFoundError"),
]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(("command", "build", "error"), FOREIGN, ids=[f[0] for f in FOREIGN])
@pytest.mark.parametrize("side", SIDES)
def test_a_foreign_id_reveals_no_foreign_content(
    board, monkeypatch, side, command, build, error, mode
):
    me, other = board.sides[side], board.other(side)
    monkeypatch.setenv("XDG_DATA_HOME", str(board.data))
    monkeypatch.chdir(me.root)
    args = build(other)
    result = invoke(*args, *MODES[mode])
    where = f"{command} from {side} ({mode})"
    if error is None:
        assert result.exit_code == 0, f"{where}: {result.output}"
        if mode == "json":
            assert json.loads(result.stdout) == {"ok": True, "data": []}, where
    else:
        assert result.exit_code == 1, f"{where}: {result.output}"
        if mode == "json":
            assert json.loads(result.stdout)["error"]["type"] == error, where
        else:
            assert result.stdout.startswith(f"Error ({error}): "), where
    # The refusal names the id it was given and the owning project by design.
    exempt = frozenset({other.project, *args})
    assert _leaks(result.stdout, other, exempt) == [], f"{where} leaks"
