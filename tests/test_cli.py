import json
import shutil
import uuid

import pytest
from typer.testing import CliRunner

from brd import db, paths, prompt
from brd.cli import app
from brd.models import Project
from tests.cli_helpers import err, human, invoke, ok
from tests.factories import (
    NOW,
    OTHER_PROJECT,
    add_project,
    make_card,
    make_document,
    make_issue,
)

runner = CliRunner()

HELP_TEXT = "Local kanban board for tracking work, no visual UI."


def test_help_exits_zero():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0


def test_help_prints_program_description():
    result = runner.invoke(app, ["--help"])
    assert "Usage: brd" in result.output
    assert HELP_TEXT in result.output


def test_no_args_prints_help_instead_of_missing_command_error():
    result = runner.invoke(app, [])
    assert HELP_TEXT in result.output
    assert "Missing command" not in result.output


def test_prompt_prints_plain_markdown_not_json():
    result = runner.invoke(app, ["prompt"])
    assert result.exit_code == 0
    assert "## Task tracking with brd" in result.output
    assert "brd --help" in result.output
    assert result.output == prompt.render()
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.output)


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    return repo


def test_init_registers_project(isolated_env):
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["name"] == "myrepo"
    assert set(payload["data"]) == {"id", "name", "root_path", "created_at"}
    assert payload["data"]["root_path"] == str(isolated_env)
    assert list(isolated_env.iterdir()) == []
    conn = db.connect(paths.brd_db_path())
    try:
        stored = conn.execute("SELECT name, root_path FROM projects").fetchall()
    finally:
        conn.close()
    assert [tuple(r) for r in stored] == [("myrepo", str(isolated_env))]


def test_init_twice_succeeds_and_preserves_cards(isolated_env):
    runner.invoke(app, ["init"])
    add_result = runner.invoke(app, ["add", "--title", "Existing card"])
    card_id = json.loads(add_result.stdout)["data"]["id"]

    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True

    show_result = runner.invoke(app, ["show", card_id])
    assert json.loads(show_result.stdout)["data"]["id"] == card_id


def test_init_name_option_overrides_project_name(isolated_env):
    result = runner.invoke(app, ["init", "--name", "custom-name"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["data"]["name"] == "custom-name"


@pytest.mark.parametrize("flag", ["--pretty", "--human"])
def test_init_pretty_flag_switches_off_json(isolated_env, flag):
    result = runner.invoke(app, ["init", flag])
    assert result.exit_code == 0
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)
    assert "myrepo" in result.stdout


def _moved(tmp_path, monkeypatch):
    """init + one card in old/, then old/ renamed to new/ and the cwd moved there."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    monkeypatch.chdir(old)
    project = ok("init")
    ok("add", "--title", "Moved card")
    old.rename(new)
    monkeypatch.chdir(new)
    return project, old, new


def test_init_relink_by_old_root_brings_the_board_along(tmp_path, monkeypatch):
    project, old, new = _moved(tmp_path, monkeypatch)
    assert err("list") == "ProjectNotFoundError"

    relinked = ok("init", "--relink", old)

    assert relinked == {**project, "root_path": str(new)}
    assert [card["title"] for card in ok("list")] == ["Moved card"]


def test_init_relink_by_id_brings_the_board_along(tmp_path, monkeypatch):
    project, old, new = _moved(tmp_path, monkeypatch)

    relinked = ok("init", "--relink", project["id"], "--name", "renamed")

    assert relinked == {**project, "root_path": str(new), "name": "renamed"}
    assert [card["title"] for card in ok("list")] == ["Moved card"]
    assert ok("projects") == [relinked]


def test_init_relink_with_an_unknown_id_is_not_found(tmp_path, monkeypatch):
    project, old, new = _moved(tmp_path, monkeypatch)

    assert err("init", "--relink", str(uuid.uuid4())) == "ProjectNotFoundError"
    assert ok("projects") == [project]


def test_init_relink_onto_another_projects_root_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    monkeypatch.chdir(a)
    project_a = ok("init")
    monkeypatch.chdir(b)
    ok("init")
    before = ok("projects")

    assert err("init", "--relink", project_a["id"]) == "ProjectAlreadyExistsError"
    assert ok("projects") == before


def test_init_relink_pretty_flag_switches_off_json(tmp_path, monkeypatch):
    project, old, new = _moved(tmp_path, monkeypatch)

    result = invoke("init", "--relink", old, "--pretty")

    assert result.exit_code == 0, result.output
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)
    assert str(new) in result.stdout


def test_init_help_mentions_relink():
    result = invoke("init", "--help")
    assert result.exit_code == 0
    assert "--relink" in result.output


def test_projects_lists_registered_projects(isolated_env):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["projects"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"][0]["name"] == "myrepo"


def test_projects_with_empty_registry_returns_empty_list(isolated_env):
    result = runner.invoke(app, ["projects"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"] == []


@pytest.mark.parametrize("flag", ["--pretty", "--human"])
def test_projects_pretty_flag_switches_off_json(isolated_env, flag):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["projects", flag])
    assert result.exit_code == 0
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)
    assert "myrepo" in result.stdout


def test_forget_removes_current_project(isolated_env):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["forget"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["name"] == "myrepo"
    assert not (isolated_env / ".brd").exists()
    conn = db.connect(paths.brd_db_path())
    try:
        assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0
    finally:
        conn.close()

    projects_result = runner.invoke(app, ["projects"])
    assert json.loads(projects_result.stdout)["data"] == []


def test_forget_accepts_explicit_path_argument(isolated_env, tmp_path, monkeypatch):
    runner.invoke(app, ["init"])
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["forget", str(isolated_env)])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["name"] == "myrepo"


def test_forget_errors_when_not_registered(isolated_env):
    result = runner.invoke(app, ["forget"])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "ProjectNotFoundError"


@pytest.mark.parametrize("flag", ["--pretty", "--human"])
def test_forget_pretty_flag_switches_off_json(isolated_env, flag):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["forget", flag])
    assert result.exit_code == 0
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)
    assert "myrepo" in result.stdout


def test_forget_project_option_works_after_the_repo_is_deleted(
    isolated_env, tmp_path, monkeypatch
):
    project = ok("init")
    monkeypatch.chdir(tmp_path)
    shutil.rmtree(isolated_env)

    assert ok("forget", "--project", project["id"]) == project
    assert ok("projects") == []


def test_forget_project_option_with_an_unknown_id_is_not_found(isolated_env):
    project = ok("init")

    assert err("forget", "--project", str(uuid.uuid4())) == "ProjectNotFoundError"
    assert ok("projects") == [project]


def test_forget_from_a_subdirectory_forgets_the_enclosing_project(
    isolated_env, monkeypatch
):
    project = ok("init")
    sub = isolated_env / "sub"
    sub.mkdir()
    monkeypatch.chdir(sub)

    assert ok("forget") == project
    assert ok("projects") == []


def test_forget_refuses_both_a_path_and_project(isolated_env):
    project = ok("init")

    assert err("forget", isolated_env, "--project", project["id"]) == "UsageError"
    assert ok("projects") == [project]


def test_forget_help_mentions_project_option():
    result = invoke("forget", "--help")
    assert result.exit_code == 0
    assert "--project" in result.output


def _last_json_line(output: str) -> dict:
    return json.loads(output.strip().splitlines()[-1])


def test_purge_requires_confirmation_and_aborts_on_decline(isolated_env):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["purge"], input="n\n")
    assert result.exit_code != 0
    payload = _last_json_line(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "Aborted"

    projects_result = runner.invoke(app, ["projects"])
    assert json.loads(projects_result.stdout)["data"] != []


def test_purge_deletes_everything_on_confirmation(isolated_env):
    runner.invoke(app, ["init"])
    data_dir = paths.data_dir()
    result = runner.invoke(app, ["purge"], input="y\n")
    assert result.exit_code == 0
    payload = _last_json_line(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["projects_removed"] == 1
    assert not data_dir.exists()


def test_purge_yes_flag_skips_confirmation(isolated_env):
    runner.invoke(app, ["init"])
    data_dir = paths.data_dir()
    result = runner.invoke(app, ["purge", "--yes"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["projects_removed"] == 1
    assert not data_dir.exists()


@pytest.fixture
def initialized_project(isolated_env):
    runner.invoke(app, ["init"])
    return isolated_env


def test_add_creates_card(initialized_project):
    result = runner.invoke(app, ["add", "--title", "My card"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["title"] == "My card"
    assert payload["data"]["status"] == "todo"


def test_add_with_unknown_parent_errors(initialized_project):
    result = runner.invoke(app, ["add", "--title", "Child", "--parent", "nope"])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "CardNotFoundError"


def test_add_stores_description(initialized_project):
    result = runner.invoke(
        app, ["add", "--title", "My card", "--description", "the details"]
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout)["data"]["description"] == "the details"


def test_add_with_blocked_by_records_edge_and_blocks_card(initialized_project):
    blocker_result = runner.invoke(app, ["add", "--title", "Blocker"])
    blocker_id = json.loads(blocker_result.stdout)["data"]["id"]

    result = runner.invoke(
        app, ["add", "--title", "Blocked", "--blocked-by", blocker_id]
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["data"]["blocked_by"] == [blocker_id]
    assert payload["data"]["status"] == "blocked"


def test_add_with_unknown_blocked_by_errors(initialized_project):
    result = runner.invoke(app, ["add", "--title", "X", "--blocked-by", "nope"])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "CardNotFoundError"


@pytest.mark.parametrize(
    "args",
    [
        ["add", "--title", "X"],
        ["show", "some-id"],
        ["list"],
        ["update", "some-id", "--title", "X"],
        ["block", "some-id", "--by", "other-id"],
        ["unblock", "some-id", "--by", "other-id"],
        ["tree"],
        ["next"],
    ],
)
def test_commands_outside_project_error(tmp_path, monkeypatch, args):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)

    result = runner.invoke(app, args)
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "ProjectNotFoundError"


def test_show_returns_card_detail(initialized_project):
    add_result = runner.invoke(app, ["add", "--title", "My card"])
    card_id = json.loads(add_result.stdout)["data"]["id"]

    result = runner.invoke(app, ["show", card_id])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["id"] == card_id
    assert payload["data"]["status"] == "todo"
    assert payload["data"]["children"] == []
    assert payload["data"]["blocked_by"] == []


def test_show_reports_children_and_blockers(initialized_project):
    parent_result = runner.invoke(app, ["add", "--title", "Parent"])
    parent_id = json.loads(parent_result.stdout)["data"]["id"]
    blocker_result = runner.invoke(app, ["add", "--title", "Blocker"])
    blocker_id = json.loads(blocker_result.stdout)["data"]["id"]
    child_result = runner.invoke(
        app,
        ["add", "--title", "Child", "--parent", parent_id, "--blocked-by", blocker_id],
    )
    child_id = json.loads(child_result.stdout)["data"]["id"]

    parent_payload = json.loads(runner.invoke(app, ["show", parent_id]).stdout)
    assert parent_payload["data"]["children"] == [child_id]
    assert parent_payload["data"]["blocked_by"] == []

    child_payload = json.loads(runner.invoke(app, ["show", child_id]).stdout)
    assert child_payload["data"]["parent_id"] == parent_id
    assert child_payload["data"]["children"] == []
    assert child_payload["data"]["blocked_by"] == [blocker_id]
    assert child_payload["data"]["status"] == "blocked"


def test_show_unknown_card_errors(initialized_project):
    result = runner.invoke(app, ["show", "nope"])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "CardNotFoundError"


def test_list_returns_all_cards(initialized_project):
    runner.invoke(app, ["add", "--title", "A"])
    runner.invoke(app, ["add", "--title", "B"])
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert len(payload["data"]) == 2


def test_list_with_no_parent_filter_includes_child_cards(initialized_project):
    parent_result = runner.invoke(app, ["add", "--title", "Parent"])
    parent_id = json.loads(parent_result.stdout)["data"]["id"]
    runner.invoke(app, ["add", "--title", "Child", "--parent", parent_id])

    result = runner.invoke(app, ["list"])
    payload = json.loads(result.stdout)
    assert {item["title"] for item in payload["data"]} == {"Parent", "Child"}


def test_list_filters_by_parent(initialized_project):
    parent_result = runner.invoke(app, ["add", "--title", "Parent"])
    parent_id = json.loads(parent_result.stdout)["data"]["id"]
    runner.invoke(app, ["add", "--title", "Child", "--parent", parent_id])

    result = runner.invoke(app, ["list", "--parent", parent_id])
    payload = json.loads(result.stdout)
    assert [item["title"] for item in payload["data"]] == ["Child"]


def test_list_filters_by_status(initialized_project):
    # Only `add` exists at this point, so every stored status is "todo";
    # `brd update` (issue #15) is what lets a card reach "done". The filter
    # itself is still fully exercised: a matching status returns the cards, a
    # non-matching one returns none.
    runner.invoke(app, ["add", "--title", "A"])
    runner.invoke(app, ["add", "--title", "B"])

    todo_result = runner.invoke(app, ["list", "--status", "todo"])
    assert todo_result.exit_code == 0
    assert {item["title"] for item in json.loads(todo_result.stdout)["data"]} == {
        "A",
        "B",
    }

    done_result = runner.invoke(app, ["list", "--status", "done"])
    assert done_result.exit_code == 0
    assert json.loads(done_result.stdout)["data"] == []


def test_update_changes_title(initialized_project):
    add_result = runner.invoke(app, ["add", "--title", "Old"])
    card_id = json.loads(add_result.stdout)["data"]["id"]

    result = runner.invoke(app, ["update", card_id, "--title", "New"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["title"] == "New"


def test_update_rejects_blocked_status(initialized_project):
    add_result = runner.invoke(app, ["add", "--title", "A"])
    card_id = json.loads(add_result.stdout)["data"]["id"]

    result = runner.invoke(app, ["update", card_id, "--status", "blocked"])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "InvalidStatusError"


def test_delete_removes_card(initialized_project):
    a = json.loads(runner.invoke(app, ["add", "--title", "A"]).stdout)["data"]

    result = runner.invoke(app, ["delete", a["id"]])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["deleted"] == [a["id"]]

    show_result = runner.invoke(app, ["show", a["id"]])
    assert json.loads(show_result.stdout)["error"]["type"] == "CardNotFoundError"


def test_delete_missing_card(initialized_project):
    result = runner.invoke(app, ["delete", "nope"])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "CardNotFoundError"


def test_delete_with_children_requires_cascade(initialized_project):
    parent = json.loads(runner.invoke(app, ["add", "--title", "P"]).stdout)["data"]
    runner.invoke(app, ["add", "--title", "C", "--parent", parent["id"]])

    result = runner.invoke(app, ["delete", parent["id"]])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "CardHasChildrenError"


def test_delete_cascade_removes_children(initialized_project):
    parent = json.loads(runner.invoke(app, ["add", "--title", "P"]).stdout)["data"]
    child = json.loads(
        runner.invoke(app, ["add", "--title", "C", "--parent", parent["id"]]).stdout
    )["data"]

    result = runner.invoke(app, ["delete", parent["id"], "--cascade"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert set(payload["data"]["deleted"]) == {parent["id"], child["id"]}

    show_result = runner.invoke(app, ["show", child["id"]])
    assert json.loads(show_result.stdout)["error"]["type"] == "CardNotFoundError"


def test_block_and_unblock(initialized_project):
    a = json.loads(runner.invoke(app, ["add", "--title", "A"]).stdout)["data"]
    b = json.loads(runner.invoke(app, ["add", "--title", "B"]).stdout)["data"]

    block_result = runner.invoke(app, ["block", a["id"], "--by", b["id"]])
    assert block_result.exit_code == 0
    assert json.loads(block_result.stdout)["data"]["blocked_by"] == [b["id"]]
    show_result = runner.invoke(app, ["show", a["id"]])
    assert json.loads(show_result.stdout)["data"]["status"] == "blocked"

    unblock_result = runner.invoke(app, ["unblock", a["id"], "--by", b["id"]])
    assert unblock_result.exit_code == 0
    show_result = runner.invoke(app, ["show", a["id"]])
    assert json.loads(show_result.stdout)["data"]["status"] == "todo"


def test_block_rejects_cycle(initialized_project):
    a = json.loads(runner.invoke(app, ["add", "--title", "A"]).stdout)["data"]
    b = json.loads(runner.invoke(app, ["add", "--title", "B"]).stdout)["data"]
    runner.invoke(app, ["block", a["id"], "--by", b["id"]])

    result = runner.invoke(app, ["block", b["id"], "--by", a["id"]])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "CycleError"


def test_update_reparents_and_clears_parent(initialized_project):
    parent = json.loads(runner.invoke(app, ["add", "--title", "P"]).stdout)["data"]
    child = json.loads(runner.invoke(app, ["add", "--title", "C"]).stdout)["data"]

    reparent = runner.invoke(app, ["update", child["id"], "--parent", parent["id"]])
    assert reparent.exit_code == 0
    assert json.loads(reparent.stdout)["data"]["parent_id"] == parent["id"]

    cleared = runner.invoke(app, ["update", child["id"], "--clear-parent"])
    assert cleared.exit_code == 0
    assert json.loads(cleared.stdout)["data"]["parent_id"] is None

    both = runner.invoke(
        app, ["update", child["id"], "--parent", parent["id"], "--clear-parent"]
    )
    assert both.exit_code == 0
    assert json.loads(both.stdout)["data"]["parent_id"] is None


def test_update_rejects_parent_cycle(initialized_project):
    parent = json.loads(runner.invoke(app, ["add", "--title", "P"]).stdout)["data"]
    child = json.loads(runner.invoke(app, ["add", "--title", "C"]).stdout)["data"]
    runner.invoke(app, ["update", child["id"], "--parent", parent["id"]])

    result = runner.invoke(app, ["update", parent["id"], "--parent", child["id"]])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "CycleError"


def test_tree_whole_board(initialized_project):
    runner.invoke(app, ["add", "--title", "Root card"])

    result = runner.invoke(app, ["tree"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert [node["title"] for node in payload["data"]] == ["Root card"]
    assert payload["data"][0]["children"] == []


def test_tree_rooted_at_card(initialized_project):
    parent = json.loads(runner.invoke(app, ["add", "--title", "Parent"]).stdout)["data"]
    runner.invoke(app, ["add", "--title", "Child", "--parent", parent["id"]])

    result = runner.invoke(app, ["tree", parent["id"]])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert len(payload["data"]) == 1
    node = payload["data"][0]
    assert node["title"] == "Parent"
    assert [child["title"] for child in node["children"]] == ["Child"]


@pytest.mark.parametrize("flag", ["--pretty", "--human"])
def test_tree_pretty_renders_indented_text(initialized_project, flag):
    parent = json.loads(runner.invoke(app, ["add", "--title", "Parent"]).stdout)["data"]
    child = json.loads(
        runner.invoke(app, ["add", "--title", "Child", "--parent", parent["id"]]).stdout
    )["data"]

    result = runner.invoke(app, ["tree", flag])
    assert result.exit_code == 0
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)
    assert f"└── Parent [todo] ({parent['id']})" in result.stdout
    assert f"    └── Child [todo] ({child['id']})" in result.stdout


def test_tree_missing_card_errors(initialized_project):
    result = runner.invoke(app, ["tree", "nope"])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "CardNotFoundError"


def test_import_round_trips_a_board_into_a_fresh_project(isolated_env, monkeypatch):
    runner.invoke(app, ["init"])
    parent = json.loads(runner.invoke(app, ["add", "--title", "Parent"]).stdout)["data"]
    runner.invoke(app, ["add", "--title", "Child", "--parent", parent["id"]])

    tree_result = runner.invoke(app, ["tree"])
    snapshot_file = isolated_env.parent / "snapshot.json"
    snapshot_file.write_text(tree_result.stdout)

    # A second install: one install's projects share brd.db, where these ids exist.
    monkeypatch.setenv("XDG_DATA_HOME", str(isolated_env.parent / "other-data"))
    other_repo = isolated_env.parent / "other-repo"
    other_repo.mkdir()
    monkeypatch.chdir(other_repo)
    runner.invoke(app, ["init"])

    result = runner.invoke(app, ["import", str(snapshot_file)])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["imported"] == 2

    tree_after = json.loads(runner.invoke(app, ["tree"]).stdout)
    assert tree_after["data"][0]["id"] == parent["id"]
    assert tree_after["data"][0]["children"][0]["id"] != ""


def test_import_rejects_colliding_ids(isolated_env):
    runner.invoke(app, ["init"])
    runner.invoke(app, ["add", "--title", "Card"])
    snapshot_file = isolated_env.parent / "snapshot.json"
    snapshot_file.write_text(runner.invoke(app, ["tree"]).stdout)

    result = runner.invoke(app, ["import", str(snapshot_file)])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["error"]["type"] == "ProjectNotEmptyError"


def test_import_missing_file_errors(isolated_env):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["import", str(isolated_env / "nope.json")])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False


def test_next_returns_ready_cards(initialized_project):
    first = json.loads(runner.invoke(app, ["add", "--title", "First"]).stdout)["data"]
    second = json.loads(runner.invoke(app, ["add", "--title", "Second"]).stdout)["data"]

    result = runner.invoke(app, ["next"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert [item["id"] for item in payload["data"]] == [first["id"], second["id"]]
    assert payload["data"][0]["status"] == "todo"


def test_next_respects_limit(initialized_project):
    first = json.loads(runner.invoke(app, ["add", "--title", "First"]).stdout)["data"]
    runner.invoke(app, ["add", "--title", "Second"])

    result = runner.invoke(app, ["next", "--limit", "1"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert [item["id"] for item in payload["data"]] == [first["id"]]


def test_next_child_of_blocked_parent_is_excluded(initialized_project):
    story = json.loads(runner.invoke(app, ["add", "--title", "Story"]).stdout)["data"]
    blocker = json.loads(runner.invoke(app, ["add", "--title", "Blocker"]).stdout)["data"]
    runner.invoke(app, ["block", story["id"], "--by", blocker["id"]])
    subtask = json.loads(
        runner.invoke(
            app, ["add", "--title", "Subtask", "--parent", story["id"]]
        ).stdout
    )["data"]

    result = runner.invoke(app, ["next"])
    ready_ids = {item["id"] for item in json.loads(result.stdout)["data"]}
    assert subtask["id"] not in ready_ids
    assert blocker["id"] in ready_ids


def test_next_with_parent_returns_ready_direct_children(initialized_project):
    milestone = json.loads(
        runner.invoke(app, ["add", "--title", "Milestone"]).stdout
    )["data"]
    story_a = json.loads(
        runner.invoke(
            app, ["add", "--title", "Story A", "--parent", milestone["id"]]
        ).stdout
    )["data"]
    story_b = json.loads(
        runner.invoke(
            app, ["add", "--title", "Story B", "--parent", milestone["id"]]
        ).stdout
    )["data"]
    runner.invoke(app, ["block", story_b["id"], "--by", story_a["id"]])

    result = runner.invoke(app, ["next", "--parent", milestone["id"]])
    assert result.exit_code == 0
    ready_ids = {item["id"] for item in json.loads(result.stdout)["data"]}
    assert ready_ids == {story_a["id"]}


def test_next_with_unknown_parent_errors(initialized_project):
    result = runner.invoke(app, ["next", "--parent", "nope"])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["error"]["type"] == "CardNotFoundError"


@pytest.mark.parametrize("flag", ["--pretty", "--human"])
def test_next_pretty_flag_switches_off_json(initialized_project, flag):
    card = json.loads(runner.invoke(app, ["add", "--title", "First"]).stdout)["data"]

    result = runner.invoke(app, ["next", flag])
    assert result.exit_code == 0
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)
    assert card["id"] in result.stdout
    assert "First" in result.stdout


def test_end_to_end_workflow(isolated_env):
    assert runner.invoke(app, ["init"]).exit_code == 0

    story = json.loads(
        runner.invoke(app, ["add", "--title", "Story: ship feature"]).stdout
    )["data"]
    blocker = json.loads(
        runner.invoke(app, ["add", "--title", "Subtask: write migration"]).stdout
    )["data"]
    subtask = json.loads(
        runner.invoke(
            app,
            [
                "add",
                "--title",
                "Subtask: write endpoint",
                "--parent",
                story["id"],
                "--blocked-by",
                blocker["id"],
            ],
        ).stdout
    )["data"]

    next_payload = json.loads(runner.invoke(app, ["next"]).stdout)
    ready_ids = {c["id"] for c in next_payload["data"]}
    assert story["id"] not in ready_ids  # has a child, so it's a container, not work
    assert blocker["id"] in ready_ids
    assert subtask["id"] not in ready_ids  # blocked

    runner.invoke(app, ["update", blocker["id"], "--status", "done"])

    next_payload = json.loads(runner.invoke(app, ["next"]).stdout)
    ready_ids = {c["id"] for c in next_payload["data"]}
    assert subtask["id"] in ready_ids  # unblocked now

    tree_payload = json.loads(runner.invoke(app, ["tree", story["id"]]).stdout)
    assert tree_payload["data"][0]["children"][0]["id"] == subtask["id"]

    projects_payload = json.loads(runner.invoke(app, ["projects"]).stdout)
    assert projects_payload["data"][0]["name"] == "myrepo"


def _is_uuid4(value):
    return uuid.UUID(value).version == 4 and str(uuid.UUID(value)) == value


def test_init_reports_project_with_id_first(isolated_env):
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)["data"]
    assert list(data) == ["id", "name", "root_path", "created_at"]
    assert _is_uuid4(data["id"])
    assert data["root_path"] == str(isolated_env)


def test_projects_reports_the_id_init_assigned_and_rerun_keeps_it(isolated_env):
    first = json.loads(runner.invoke(app, ["init"]).stdout)["data"]
    second = json.loads(runner.invoke(app, ["init", "--name", "renamed"]).stdout)["data"]

    listed = json.loads(runner.invoke(app, ["projects"]).stdout)["data"]

    assert second["id"] == first["id"]
    assert second["created_at"] == first["created_at"]
    assert listed == [second]
    assert list(listed[0]) == ["id", "name", "root_path", "created_at"]


def test_projects_pretty_includes_the_id(isolated_env):
    project_id = json.loads(runner.invoke(app, ["init"]).stdout)["data"]["id"]
    result = runner.invoke(app, ["projects", "--pretty"])
    assert result.exit_code == 0
    assert project_id in result.stdout


def test_forget_reports_the_forgotten_project_id(isolated_env):
    project_id = json.loads(runner.invoke(app, ["init"]).stdout)["data"]["id"]
    result = runner.invoke(app, ["forget"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["data"]["id"] == project_id


FOREIGN = "f0f0f0f0-0000-4000-8000-000000000000"


@pytest.fixture
def foreign(project):
    """Seed another project and its card FOREIGN into the current board file.
    No command can do this until every project shares one database."""
    conn = db.connect(paths.brd_db_path())
    try:
        add_project(conn, OTHER_PROJECT)
        make_card(conn, FOREIGN, title="Foreign", project_id=OTHER_PROJECT.id)
    finally:
        conn.close()
    return FOREIGN


FOREIGN_ISSUE = "f1f1f1f1-0000-4000-8000-000000000000"
FOREIGN_DOC = "f2f2f2f2-0000-4000-8000-000000000000"


@pytest.fixture
def foreign_entities(project, foreign):
    """Besides card FOREIGN, the other project owns the open issue
    FOREIGN_ISSUE and the document FOREIGN_DOC (stem `notes`, tag `t`)."""
    conn = db.connect(paths.brd_db_path())
    try:
        make_issue(conn, FOREIGN_ISSUE, title="Foreign issue", project_id=OTHER_PROJECT.id)
        make_document(
            conn, FOREIGN_DOC, "notes", content="foreign body", project_id=OTHER_PROJECT.id
        )
        conn.execute("INSERT INTO tags (entity_id, tag) VALUES (?, 't')", (FOREIGN_DOC,))
        conn.commit()
    finally:
        conn.close()
    return {"card": foreign, "issue": FOREIGN_ISSUE, "document": FOREIGN_DOC}


def _refused(*args, error_type: str = "CardNotFoundError") -> None:
    result = invoke(*args)
    assert result.exit_code == 1, result.output
    error = json.loads(result.stdout)["error"]
    assert error["type"] == error_type
    assert f"belongs to project {OTHER_PROJECT.name} ({OTHER_PROJECT.id})" in error["message"]


def test_update_refuses_a_foreign_card(foreign):
    _refused("update", foreign, "--title", "x")
    assert ok("show", foreign)["title"] == "Foreign"


def test_add_and_update_refuse_a_foreign_parent(foreign):
    _refused("add", "--title", "t", "--parent", foreign)
    mine = ok("add", "--title", "mine")["id"]
    _refused("update", mine, "--parent", foreign)
    assert ok("show", mine)["parent_id"] is None


def test_delete_refuses_a_foreign_card(foreign):
    _refused("delete", foreign)
    _refused("delete", foreign, "--cascade")
    assert ok("show", foreign)["id"] == foreign


def test_block_and_unblock_refuse_a_foreign_card(foreign):
    mine = ok("add", "--title", "mine")["id"]
    _refused("block", foreign, "--by", mine)
    _refused("unblock", foreign, "--by", mine)
    assert ok("show", foreign)["blocked_by"] == []


def test_blocker_targets_may_live_in_another_project(foreign_entities):
    mine = ok("add", "--title", "mine")["id"]
    ok("block", mine, "--by", FOREIGN)
    blocked = ok("block", mine, "--by", FOREIGN_ISSUE)
    assert sorted(blocked["blocked_by"]) == sorted([FOREIGN, FOREIGN_ISSUE])
    assert blocked["status"] == "blocked"
    added = ok("add", "--title", "t", "--blocked-by", FOREIGN)
    assert (added["blocked_by"], added["status"]) == ([FOREIGN], "blocked")
    assert err("block", mine, "--by", FOREIGN_DOC) == "InvalidBlockerError"
    next_ids = [c["id"] for c in ok("next")]
    assert mine not in next_ids and added["id"] not in next_ids
    ok("unblock", mine, "--by", FOREIGN)
    unblocked = ok("unblock", mine, "--by", FOREIGN_ISSUE)
    assert (unblocked["blocked_by"], unblocked["status"]) == ([], "todo")
    assert mine in [c["id"] for c in ok("next")]


def test_show_pretty_renders_a_foreign_blocker(foreign):
    mine = ok("add", "--title", "mine")["id"]
    ok("block", mine, "--by", foreign)
    assert "blocked by: other: Foreign" in human("show", mine).splitlines()


def _seed_edges(card_id, *blocker_ids):
    """blocked_by rows no command would write (a missing or document target,
    or one from another project's card)."""
    conn = db.connect(paths.brd_db_path())
    try:
        for blocker_id in blocker_ids:
            db.add_blocked_by_edge(conn, card_id, blocker_id)
    finally:
        conn.close()


def test_show_pretty_renders_a_foreign_issue_blocker(foreign_entities):
    mine = ok("add", "--title", "mine", "--blocked-by", FOREIGN_ISSUE)["id"]
    assert "blocked by: other: Foreign issue" in human("show", mine).splitlines()


def test_a_foreign_document_blocker_renders_and_never_blocks(foreign_entities):
    mine = ok("add", "--title", "mine")["id"]
    _seed_edges(mine, FOREIGN_DOC)
    shown = ok("show", mine)
    assert shown["status"] == "todo"
    assert shown["blockers"] == [
        {
            "id": FOREIGN_DOC,
            "kind": "document",
            "project": {"id": OTHER_PROJECT.id, "name": OTHER_PROJECT.name},
            "title": "notes",
            "status": None,
            "released": True,
        }
    ]
    assert "blocked by: other: notes" in human("show", mine).splitlines()


def test_show_pretty_mixed_blockers_keep_order(foreign):
    lexer = ok("add", "--title", "Lexer")["id"]
    mine = ok("add", "--title", "mine", "--blocked-by", lexer, "--blocked-by", foreign)["id"]
    _seed_edges(mine, "ghost")
    rendered = {lexer: "[[Lexer]] (card)", foreign: "other: Foreign", "ghost": "not-found ghost"}
    blocked_by = ok("show", mine)["blocked_by"]
    assert sorted(blocked_by) == sorted(rendered)
    expected = "blocked by: " + ", ".join(rendered[b] for b in blocked_by)
    assert expected in human("show", mine).splitlines()


def test_show_pretty_of_a_foreign_card_treats_its_own_project_as_local(foreign):
    here = ok("add", "--title", "Here")
    conn = db.connect(paths.brd_db_path())
    try:
        make_card(conn, "F2", title="F2", project_id=OTHER_PROJECT.id)
    finally:
        conn.close()
    _seed_edges("F2", foreign, here["id"])
    # Shown from this project's cwd, but F2 belongs to `other`: its sibling
    # card is local and this project's card is the foreign one.
    here_name = ok("show", here["id"])["project"]["name"]
    rendered = {foreign: "[[Foreign]] (card)", here["id"]: f"{here_name}: Here"}
    blocked_by = ok("show", "F2")["blocked_by"]
    expected = "blocked by: " + ", ".join(rendered[b] for b in blocked_by)
    assert expected in human("show", "F2").splitlines()


def test_show_pretty_tells_a_same_named_project_apart_by_id(project):
    mine = ok("add", "--title", "mine")["id"]
    twin = Project(
        id="33333333-3333-4333-8333-333333333333",
        name=ok("show", mine)["project"]["name"],  # the cwd project's own name
        root_path="/twin",
        created_at=NOW,
    )
    conn = db.connect(paths.brd_db_path())
    try:
        add_project(conn, twin)
        make_card(conn, "twin-card", title="Twin", project_id=twin.id)
    finally:
        conn.close()
    ok("block", mine, "--by", "twin-card")
    assert f"blocked by: {twin.name}: Twin" in human("show", mine).splitlines()


def _blocker_entry(id_, kind, title, status, released, project=OTHER_PROJECT):
    return {
        "id": id_,
        "kind": kind,
        "project": {"id": project.id, "name": project.name},
        "title": title,
        "status": status,
        "released": released,
    }


def test_card_outputs_carry_foreign_blockers(foreign_entities):
    expected = {
        FOREIGN: _blocker_entry(FOREIGN, "card", "Foreign", "todo", False),
        FOREIGN_ISSUE: _blocker_entry(FOREIGN_ISSUE, "issue", "Foreign issue", "open", False),
    }
    mine = ok("add", "--title", "mine")["id"]
    ok("block", mine, "--by", FOREIGN)
    blocked = ok("block", mine, "--by", FOREIGN_ISSUE)
    (listed,) = [c for c in ok("list") if c["id"] == mine]
    (node,) = [n for n in ok("tree") if n["id"] == mine]
    for card in (blocked, ok("show", mine), listed, node):
        # blocked_by is still the plain list of ids; blockers follows its order.
        assert sorted(card["blocked_by"]) == sorted([FOREIGN, FOREIGN_ISSUE])
        assert card["blockers"] == [expected[b] for b in card["blocked_by"]]

    added = ok("add", "--title", "t", "--blocked-by", FOREIGN)
    assert (added["blocked_by"], added["blockers"]) == ([FOREIGN], [expected[FOREIGN]])
    assert ok("update", added["id"], "--title", "t2")["blockers"] == [expected[FOREIGN]]
    unblocked = ok("unblock", mine, "--by", FOREIGN)
    assert (unblocked["blocked_by"], unblocked["blockers"]) == (
        [FOREIGN_ISSUE],
        [expected[FOREIGN_ISSUE]],
    )
    free = ok("add", "--title", "free")["id"]
    assert [c["blockers"] for c in ok("next") if c["id"] == free] == [[]]


def test_a_finished_foreign_blocker_is_released(foreign):
    mine = ok("add", "--title", "mine", "--blocked-by", foreign)["id"]
    conn = db.connect(paths.brd_db_path())
    try:
        conn.execute("UPDATE cards SET status = 'done' WHERE id = ?", (foreign,))
        conn.commit()
    finally:
        conn.close()

    shown = ok("show", mine)
    assert shown["status"] == "todo"
    assert shown["blockers"] == [_blocker_entry(foreign, "card", "Foreign", "done", True)]
    assert mine in [c["id"] for c in ok("next")]


def test_issue_open_can_block_a_foreign_card(foreign):
    issue = ok("issue", "open", "--title", "q", "--blocks", foreign)
    assert issue["blocks"] == [foreign]
    shown = ok("show", foreign)
    assert (shown["blocked_by"], shown["status"]) == ([issue["id"]], "blocked")
    ok("issue", "close", issue["id"])
    assert ok("show", foreign)["status"] == "todo"


def test_forget_leaves_a_foreign_card_blocked_until_unblocked(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
    monkeypatch.chdir(tmp_path / "a")
    project_a = ok("init")
    theirs = ok("add", "--title", "theirs")["id"]
    monkeypatch.chdir(tmp_path / "b")
    ok("init")
    mine = ok("add", "--title", "mine")["id"]
    ok("block", mine, "--by", theirs)
    ok("ref", "add", mine, theirs)

    ok("forget", "--project", project_a["id"])

    shown = ok("show", mine)
    assert (shown["status"], shown["blocked_by"]) == ("blocked", [theirs])
    assert shown["refs"] == [
        {"id": theirs, "kind": None, "title": None, "origin": "explicit"}
    ]
    assert mine not in [c["id"] for c in ok("next")]
    assert [(c["id"], c["status"]) for c in ok("list")] == [(mine, "blocked")]
    assert [(n["id"], n["status"]) for n in ok("tree")] == [(mine, "blocked")]
    gone = [
        {
            "id": theirs,
            "kind": None,
            "project": None,
            "title": None,
            "status": "not-found",
            "released": False,
        }
    ]
    assert shown["blockers"] == gone
    assert [c["blockers"] for c in ok("list")] == [gone]
    assert [n["blockers"] for n in ok("tree")] == [gone]
    assert f"blocked by: not-found {theirs}" in human("show", mine).splitlines()
    # list, next and tree --pretty print no blockers, and still none.
    assert "blocked by" not in human("list") + human("tree")

    unblocked = ok("unblock", mine, "--by", theirs)
    assert (unblocked["blocked_by"], unblocked["status"]) == ([], "todo")
    assert mine in [c["id"] for c in ok("next")]
    assert ok("ref", "remove", mine, theirs)["refs"] == []

    # Commands still refuse to add an edge to a missing id.
    assert err("block", mine, "--by", theirs) == "CardNotFoundError"
    assert err("ref", "add", mine, theirs) == "EntityNotFoundError"


def test_comment_add_refuses_a_foreign_card(foreign):
    _refused("comment", "add", foreign, "hi")
    assert ok("show", foreign)["comments"] == []


def test_listings_exclude_a_foreign_card(foreign):
    mine = ok("add", "--title", "mine")["id"]
    assert [c["id"] for c in ok("list")] == [mine]
    assert [c["id"] for c in ok("list", "--status", "todo")] == [mine]
    assert ok("list", "--parent", foreign) == []
    assert [c["id"] for c in ok("next")] == [mine]
    assert [node["id"] for node in ok("tree")] == [mine]
    assert [node["id"] for node in ok("export")["projects"][0]["cards"]] == [mine]


def test_next_and_tree_refuse_a_foreign_root(foreign):
    _refused("next", "--parent", foreign)
    _refused("tree", foreign)


def test_show_is_global_and_names_the_owner(foreign):
    mine = ok("add", "--title", "mine")["id"]
    assert ok("show", foreign)["project"] == {
        "id": OTHER_PROJECT.id,
        "name": OTHER_PROJECT.name,
    }
    registered = next(p for p in ok("projects") if p["id"] != OTHER_PROJECT.id)
    assert ok("show", mine)["project"] == {"id": registered["id"], "name": registered["name"]}
    assert "project" not in ok("list")[0]
    assert err("show", "nope") == "CardNotFoundError"


def test_issue_commands_are_scoped_to_this_project(foreign_entities):
    issue = foreign_entities["issue"]
    mine = ok("issue", "open", "--title", "mine")["id"]
    assert [i["id"] for i in ok("issue", "list")] == [mine]
    assert [i["id"] for i in ok("issue", "list", "--status", "open")] == [mine]
    _refused("issue", "update", issue, "--title", "x", error_type="IssueNotFoundError")
    _refused("issue", "close", issue, error_type="IssueNotFoundError")
    _refused("issue", "reopen", issue, error_type="IssueNotFoundError")
    _refused("delete", issue, error_type="IssueNotFoundError")
    shown = ok("show", issue)
    assert (shown["title"], shown["status"]) == ("Foreign issue", "open")
    assert [i["id"] for i in ok("issue", "list")] == [mine]


def test_document_commands_are_scoped_to_this_project(project, foreign_entities):
    doc = foreign_entities["document"]
    (project / "docs").mkdir()
    (project / "docs" / "notes.md").write_text("mine")
    mine = ok("doc", "add", "docs/notes.md")["id"]  # the other project also has `notes`
    assert [d["id"] for d in ok("doc", "list")] == [mine]
    _refused("doc", "update", doc, "--title", "x", error_type="DocumentNotFoundError")
    _refused("doc", "restore", doc, error_type="DocumentNotFoundError")
    _refused("delete", doc, error_type="DocumentNotFoundError")
    assert ok("show", doc)["title"] == "notes"
    assert (project / "docs" / "notes.md").read_text() == "mine"
    assert [d["id"] for d in ok("export")["projects"][0]["documents"]] == [mine]


def test_ref_commands_are_scoped_to_this_project(foreign_entities):
    mine = ok("add", "--title", "mine")["id"]
    _refused("ref", "add", foreign_entities["card"], mine)
    _refused("ref", "remove", foreign_entities["card"], mine)
    assert ok("show", mine)["refs"] == []
    assert ok("show", foreign_entities["card"])["refs"] == []


def test_ref_targets_may_live_in_another_project(foreign_entities):
    mine = ok("add", "--title", "mine")["id"]
    added = ok("ref", "add", mine, FOREIGN_ISSUE)
    assert added == {
        "id": mine,
        "refs": [
            {"id": FOREIGN_ISSUE, "kind": "issue", "title": "Foreign issue", "origin": "explicit"}
        ],
    }
    assert [r["id"] for r in ok("show", mine)["refs"]] == [FOREIGN_ISSUE]
    assert [r["id"] for r in ok("show", FOREIGN_ISSUE)["referenced_by"]] == [mine]
    issue = ok("issue", "open", "--title", "q", "--ref", FOREIGN)
    assert [r["id"] for r in ok("show", issue["id"])["refs"]] == [FOREIGN]


def test_tag_commands_are_scoped_to_this_project(foreign_entities):
    doc = foreign_entities["document"]
    assert ok("tag", "list") == []
    _refused("tag", "add", doc, "x", error_type="DocumentNotFoundError")
    _refused("tag", "remove", doc, "t", error_type="DocumentNotFoundError")
    _refused("tag", "list", doc, error_type="DocumentNotFoundError")
    assert ok("show", doc)["tags"] == ["t"]


def test_comment_commands_are_scoped_to_this_project(project, foreign_entities):
    conn = db.connect(paths.brd_db_path())
    try:
        conn.execute(
            "INSERT INTO comments (id, entity_id, author, body, created_at) "
            "VALUES ('k-foreign', ?, 'them', 'theirs', '2026-09-24T00:00:00+00:00')",
            (foreign_entities["card"],),
        )
        conn.commit()
    finally:
        conn.close()
    _refused("comment", "list", foreign_entities["card"])
    _refused("comment", "add", foreign_entities["issue"], "hi", error_type="IssueNotFoundError")
    _refused(
        "comment", "add", foreign_entities["document"], "hi", error_type="DocumentNotFoundError"
    )
    _refused("comment", "delete", "k-foreign", error_type="CommentNotFoundError")
    assert ok("show", foreign_entities["issue"])["comments"] == []
    assert [c["id"] for c in ok("show", foreign_entities["card"])["comments"]] == ["k-foreign"]


def test_forget_removes_only_the_current_projects_rows_and_backups(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    ids = {}
    for name in ("keep", "gone"):
        root = tmp_path / name
        root.mkdir()
        monkeypatch.chdir(root)
        ok("init")
        (root / "notes.md").write_text(f"{name} notes")
        parent = ok("add", "--title", "Parent")
        child = ok("add", "--title", "Child", "--parent", parent["id"])
        issue = ok("issue", "open", "--title", "Q", "--blocks", child["id"])
        ok("comment", "add", child["id"], "progress")
        doc = ok("doc", "add", "notes.md", "--tag", "design")
        ids[name] = {"parent": parent["id"], "child": child["id"], "issue": issue["id"], "doc": doc["id"]}

    monkeypatch.chdir(tmp_path / "gone")
    assert ok("forget")["name"] == "gone"

    assert not (paths.docs_dir() / f"{ids['gone']['doc']}.md").exists()
    assert (paths.docs_dir() / f"{ids['keep']['doc']}.md").read_text() == "keep notes"
    gone = list(ids["gone"].values())
    marks = ", ".join("?" for _ in gone)
    conn = db.connect(paths.brd_db_path())
    try:
        assert [r[0] for r in conn.execute("SELECT root_path FROM projects")] == [
            str(tmp_path / "keep")
        ]
        for table, column in (
            ("entities", "id"),
            ("comments", "entity_id"),
            ("tags", "entity_id"),
            ("blocked_by", "card_id"),
            ("blocked_by", "blocks_on_id"),
            ("refs", "src_id"),
        ):
            count = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {column} IN ({marks})", gone
            ).fetchone()[0]
            assert count == 0, (table, column)
    finally:
        conn.close()
    monkeypatch.chdir(tmp_path / "keep")
    assert {c["id"] for c in ok("list")} == {ids["keep"]["parent"], ids["keep"]["child"]}
    assert ok("show", ids["keep"]["doc"])["tags"] == ["design"]
    assert len(ok("show", ids["keep"]["child"])["comments"]) == 1
