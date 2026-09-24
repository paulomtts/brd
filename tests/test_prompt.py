from typer.testing import CliRunner

from brd import prompt
from brd.cli import app

DOC_UPDATE_RULE = "Whenever you edit a registered document, run `brd doc update <id>` right after."


def test_prompt_points_agents_at_help_and_memory():
    snippet = prompt.render()
    assert "`brd --help`" in snippet
    assert "`brd <command> --help`" in snippet
    assert "memory" in snippet


def test_prompt_keeps_the_doc_update_rule_inline():
    assert f"**{DOC_UPDATE_RULE}**" in prompt.render()


def test_help_carries_the_usage_guidance():
    output = CliRunner().invoke(app, ["--help"], terminal_width=200).output
    for phrase in (
        "brd doc update <id>",
        "[[doc-stem]]",
        "[[<id>]]",
        "BRD_AUTHOR",
        "container",
        "brd export",
        "--pretty",
    ):
        assert phrase in output, phrase
