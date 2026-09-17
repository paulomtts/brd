import json

import pytest
from typer.testing import CliRunner

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
    assert (isolated_env / ".brd").exists()


def test_init_twice_fails_second_time(isolated_env):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "ProjectAlreadyExistsError"


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
