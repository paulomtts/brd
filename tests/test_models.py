from brd.models import Card, Project


def test_project_fields():
    p = Project(
        id="0b5e7c1a-4a3e-4c7e-9a52-3f1d2b6c8e90",
        name="brd",
        root_path="/repo",
        created_at="2026-09-17T00:00:00",
    )
    assert p.id == "0b5e7c1a-4a3e-4c7e-9a52-3f1d2b6c8e90"
    assert p.name == "brd"
    assert p.root_path == "/repo"


def test_card_fields_and_optional_defaults():
    c = Card(
        id="c1",
        title="Do the thing",
        description=None,
        status="todo",
        parent_id=None,
        created_at="2026-09-17T00:00:00",
        updated_at="2026-09-17T00:00:00",
    )
    assert c.title == "Do the thing"
    assert c.description is None
    assert c.parent_id is None


def test_project_field_order_is_positional():
    p = Project(
        "0b5e7c1a-4a3e-4c7e-9a52-3f1d2b6c8e90",
        "brd",
        "/repo",
        "2026-09-17T00:00:00",
    )
    assert p.id == "0b5e7c1a-4a3e-4c7e-9a52-3f1d2b6c8e90"
    assert p.name == "brd"
    assert p.root_path == "/repo"
    assert p.created_at == "2026-09-17T00:00:00"


def test_card_field_order_is_positional():
    c = Card(
        "c1",
        "Do the thing",
        "details",
        "todo",
        "parent",
        "2026-09-17T00:00:00",
        "2026-09-18T00:00:00",
    )
    assert c.id == "c1"
    assert c.title == "Do the thing"
    assert c.description == "details"
    assert c.status == "todo"
    assert c.parent_id == "parent"
    assert c.created_at == "2026-09-17T00:00:00"
    assert c.updated_at == "2026-09-18T00:00:00"
