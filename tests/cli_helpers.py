import json

from typer.testing import CliRunner

from brd.cli import app

runner = CliRunner()


def invoke(*args, input=None):
    return runner.invoke(app, [str(a) for a in args], input=input)


def ok(*args, input=None):
    result = invoke(*args, input=input)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True, payload
    return payload["data"]


def err(*args, input=None) -> str:
    result = invoke(*args, input=input)
    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is False, payload
    return payload["error"]["type"]


def human(*args) -> str:
    result = invoke(*args, "--pretty")
    assert result.exit_code == 0, result.output
    return result.stdout
