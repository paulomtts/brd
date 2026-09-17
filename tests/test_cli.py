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
