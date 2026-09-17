import json
from dataclasses import dataclass

import pytest

from brd import output


def test_ok_envelope():
    assert output.ok_envelope({"x": 1}) == {"ok": True, "data": {"x": 1}}


def test_error_envelope():
    assert output.error_envelope("CardNotFoundError", "no card") == {
        "ok": False,
        "error": {"type": "CardNotFoundError", "message": "no card"},
    }


def test_print_result_json_default(capsys):
    output.print_result(output.ok_envelope({"x": 1}), pretty=False)
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"ok": True, "data": {"x": 1}}


@dataclass
class _FakeCard:
    id: str
    title: str


def test_print_result_json_serializes_dataclasses(capsys):
    output.print_result(output.ok_envelope(_FakeCard(id="c1", title="Card")), pretty=False)
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"ok": True, "data": {"id": "c1", "title": "Card"}}


def test_print_result_pretty_error(capsys):
    output.print_result(
        output.error_envelope("CardNotFoundError", "no card"), pretty=True
    )
    captured = capsys.readouterr()
    assert captured.out.strip() == "Error (CardNotFoundError): no card"


def test_print_result_pretty_card_list(capsys):
    cards = [
        {"id": "c1", "title": "First", "status": "todo"},
        {"id": "c2", "title": "Second", "status": "done"},
    ]
    output.print_result(output.ok_envelope(cards), pretty=True)
    captured = capsys.readouterr()
    assert captured.out == "c1  [todo]  First\nc2  [done]  Second\n"


def test_print_result_pretty_card_list_missing_status(capsys):
    output.print_result(output.ok_envelope([{"id": "c1", "title": "First"}]), pretty=True)
    captured = capsys.readouterr()
    assert captured.out == "c1  []  First\n"


def test_print_result_pretty_non_card_payload(capsys):
    output.print_result(output.ok_envelope({"x": 1}), pretty=True)
    captured = capsys.readouterr()
    assert captured.out == "{'x': 1}\n"


def test_json_default_rejects_unserializable():
    with pytest.raises(TypeError):
        output._json_default(object())


def test_render_tree_text_empty():
    assert output.render_tree_text([]) == ""


def test_render_tree_text_nests_children():
    nodes = [
        {
            "id": "p1",
            "title": "Parent",
            "status": "todo",
            "blocked_by": [],
            "children": [
                {
                    "id": "c1",
                    "title": "Child",
                    "status": "blocked",
                    "blocked_by": ["x"],
                    "children": [],
                }
            ],
        }
    ]
    text = output.render_tree_text(nodes)
    lines = text.splitlines()
    assert lines[0] == "- Parent [todo] (p1)"
    assert lines[1] == "  - Child [blocked] (c1)"
