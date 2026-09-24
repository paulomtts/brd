import pytest

from brd import links


def targets(text):
    return [(t.target, t.alias) for t in links.parse(text)]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("see [[notes]]", [("notes", None)]),
        ("[[notes#Intro]]", [("notes", None)]),
        ("[[notes|the notes]]", [("notes", "the notes")]),
        ("[[notes#Intro|the notes]]", [("notes", "the notes")]),
        ("[[docs/notes.md]]", [("docs/notes.md", None)]),
        ("[[ Design Notes ]]", [("Design Notes", None)]),
        ("[[a]] and [[b]] on one line", [("a", None), ("b", None)]),
        ("[[a [[b]]", [("b", None)]),
        ("[[]] [[#only-heading]] [[|alias]]", []),
        ("no links here", []),
        ("", []),
        (None, []),
        ("`[[in inline code]]` but [[out]]", [("out", None)]),
        ("```\n[[fenced]]\n```\n[[after]]", [("after", None)]),
        ("~~~\n[[tilde]]\n~~~\n[[after]]", [("after", None)]),
        ("```\n[[unclosed fence]]", []),
        ("````\n```\n[[still fenced]]\n````\n[[after]]", [("after", None)]),
    ],
)
def test_parse(text, expected):
    assert targets(text) == expected


def test_parse_positions_cover_the_whole_link():
    token = links.parse("x [[notes]] y")[0]
    assert "x [[notes]] y"[token.start : token.end] == "[[notes]]"


def test_render_uses_title_alias_and_marks_unresolved():
    titles = {"a": "Alpha"}
    rendered = links.render(
        "[[a]], [[a|custom]], [[ghost]], [[ghost|named]], `[[a]]`",
        lambda token: titles.get(token.target),
    )
    assert rendered == (
        "[[Alpha]], [[custom]], [[ghost]] (unresolved), [[named]] (unresolved), `[[a]]`"
    )


def test_render_empty():
    assert links.render(None, lambda t: None) == ""
