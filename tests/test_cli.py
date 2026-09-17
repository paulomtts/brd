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
