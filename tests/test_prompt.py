from brd import prompt


def test_prompt_covers_new_features():
    snippet = prompt.render()
    assert "Whenever you edit a registered document, run `brd doc update <id>`" in snippet
    assert "BRD_AUTHOR" in snippet
    assert "brd issue open" in snippet
    assert "brd block <card> --by <issue>" in snippet
    assert "brd export" in snippet
    assert "brd tree > docs/board/snapshot.json" not in snippet
