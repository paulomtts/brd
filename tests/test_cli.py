import json

import pytest
from typer.testing import CliRunner

from brd import paths
from brd.cli import app

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
    assert "brd next" in result.output
    assert "--parent" in result.output
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
    assert (isolated_env / ".brd").is_file()
    assert paths.project_db_path(isolated_env).is_file()


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
    assert f"- Parent [todo] ({parent['id']})" in result.stdout
    assert f"  - Child [todo] ({child['id']})" in result.stdout


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
    assert payload["error"]["type"] == "CardAlreadyExistsError"


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
