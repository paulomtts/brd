from typer.testing import CliRunner

from brd import core, prompt
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


def _help_text(*args: str) -> str:
    result = CliRunner().invoke(app, [*args, "--help"], terminal_width=200)
    assert result.exit_code == 0, result.output
    # Rich wraps the help, so a phrase may straddle a line break.
    return " ".join(result.output.split())


def test_help_states_the_blocking_contract():
    text = _help_text()
    for phrase in (
        "is authoritative",
        "other projects",
        "not-found",
        "brd next",
        "can start now",
        "blocked_by",
        "blockers",
        "released",
        "waits for all of its children",
    ):
        assert phrase in text, phrase


def test_help_names_every_releasing_status():
    text = _help_text()
    for status in sorted(core._RELEASING_STATUSES):
        assert status in text, status


def test_prompt_states_the_blocking_contract():
    snippet = prompt.render()
    for phrase in (
        "authoritative",
        "other projects",
        "not-found",
        "brd next",
        "blocked_by",
        "blockers",
        "released",
        "all of its children",
    ):
        assert phrase in snippet, phrase


def test_block_help_says_the_blocker_may_be_in_another_project():
    assert "another project" in _help_text("block")
