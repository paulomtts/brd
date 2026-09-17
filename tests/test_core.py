import pytest

from brd import core, db
from brd.models import Card


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "project.db")
    db.init_project_schema(connection)
    yield connection
    connection.close()


def _card(id_, status="todo", parent_id=None):
    return Card(
        id=id_,
        title=id_,
        description=None,
        status=status,
        parent_id=parent_id,
        created_at="2026-09-17T00:00:00",
        updated_at="2026-09-17T00:00:00",
    )


def test_resolve_status_todo_with_no_blockers_is_todo(conn):
    db.insert_card(conn, _card("c1"))
    card = db.get_card(conn, "c1")
    assert core.resolve_status(conn, card) == "todo"


def test_resolve_status_todo_with_unresolved_blocker_is_blocked(conn):
    db.insert_card(conn, _card("c1"))
    db.insert_card(conn, _card("blocker", status="todo"))
    db.add_blocked_by_edge(conn, "c1", "blocker")
    card = db.get_card(conn, "c1")
    assert core.resolve_status(conn, card) == "blocked"


def test_resolve_status_todo_with_done_blocker_is_todo(conn):
    db.insert_card(conn, _card("c1"))
    db.insert_card(conn, _card("blocker", status="done"))
    db.add_blocked_by_edge(conn, "c1", "blocker")
    card = db.get_card(conn, "c1")
    assert core.resolve_status(conn, card) == "todo"


def test_resolve_status_todo_with_transitively_blocked_blocker_is_blocked(conn):
    db.insert_card(conn, _card("c1"))
    db.insert_card(conn, _card("mid", status="todo"))
    db.insert_card(conn, _card("root", status="todo"))
    db.add_blocked_by_edge(conn, "c1", "mid")
    db.add_blocked_by_edge(conn, "mid", "root")
    card = db.get_card(conn, "c1")
    assert core.resolve_status(conn, card) == "blocked"


def test_resolve_status_in_progress_is_unaffected_by_blockers(conn):
    db.insert_card(conn, _card("c1", status="in_progress"))
    db.insert_card(conn, _card("blocker", status="todo"))
    db.add_blocked_by_edge(conn, "c1", "blocker")
    card = db.get_card(conn, "c1")
    assert core.resolve_status(conn, card) == "in_progress"


def test_would_create_parent_cycle_direct(conn):
    db.insert_card(conn, _card("a"))
    db.insert_card(conn, _card("b", parent_id="a"))
    assert core.would_create_parent_cycle(conn, "a", "b") is True


def test_would_create_parent_cycle_indirect(conn):
    db.insert_card(conn, _card("a"))
    db.insert_card(conn, _card("b", parent_id="a"))
    db.insert_card(conn, _card("c", parent_id="b"))
    assert core.would_create_parent_cycle(conn, "a", "c") is True


def test_would_create_parent_cycle_false_for_unrelated_cards(conn):
    db.insert_card(conn, _card("a"))
    db.insert_card(conn, _card("b"))
    assert core.would_create_parent_cycle(conn, "a", "b") is False


def test_would_create_block_cycle_direct(conn):
    db.insert_card(conn, _card("a"))
    db.insert_card(conn, _card("b"))
    db.add_blocked_by_edge(conn, "a", "b")
    assert core.would_create_block_cycle(conn, "b", "a") is True


def test_would_create_block_cycle_indirect(conn):
    db.insert_card(conn, _card("a"))
    db.insert_card(conn, _card("b"))
    db.insert_card(conn, _card("c"))
    db.add_blocked_by_edge(conn, "a", "b")
    db.add_blocked_by_edge(conn, "b", "c")
    assert core.would_create_block_cycle(conn, "c", "a") is True


def test_would_create_block_cycle_false_for_unrelated_cards(conn):
    db.insert_card(conn, _card("a"))
    db.insert_card(conn, _card("b"))
    assert core.would_create_block_cycle(conn, "a", "b") is False


def test_resolve_status_skips_blocker_whose_card_is_missing(conn):
    db.insert_card(conn, _card("c1"))
    conn.execute("PRAGMA foreign_keys=OFF")
    db.add_blocked_by_edge(conn, "c1", "ghost")
    card = db.get_card(conn, "c1")
    assert core.resolve_status(conn, card) == "todo"


def test_resolve_status_terminates_on_persisted_blocking_cycle(conn):
    db.insert_card(conn, _card("a"))
    db.insert_card(conn, _card("b"))
    db.add_blocked_by_edge(conn, "a", "b")
    db.add_blocked_by_edge(conn, "b", "a")
    card = db.get_card(conn, "a")
    assert core.resolve_status(conn, card) == "blocked"


def test_would_create_parent_cycle_false_when_new_parent_is_missing(conn):
    db.insert_card(conn, _card("a"))
    assert core.would_create_parent_cycle(conn, "a", "ghost") is False


def test_would_create_block_cycle_terminates_on_persisted_blocking_cycle(conn):
    db.insert_card(conn, _card("a"))
    db.insert_card(conn, _card("b"))
    db.insert_card(conn, _card("c"))
    db.add_blocked_by_edge(conn, "b", "c")
    db.add_blocked_by_edge(conn, "c", "b")
    assert core.would_create_block_cycle(conn, "a", "b") is False


def test_create_card_defaults_to_todo(conn):
    card = core.create_card(conn, title="New card")
    assert card.status == "todo"
    assert card.title == "New card"
    assert db.get_card(conn, card.id) == card


def test_create_card_with_parent_and_blocked_by(conn):
    parent = core.create_card(conn, title="Parent")
    blocker = core.create_card(conn, title="Blocker")
    child = core.create_card(
        conn, title="Child", parent_id=parent.id, blocked_by=[blocker.id]
    )
    assert child.parent_id == parent.id
    assert db.list_blockers_of(conn, child.id) == [blocker.id]


def test_create_card_rejects_unknown_parent(conn):
    with pytest.raises(core.CardNotFoundError):
        core.create_card(conn, title="Orphan", parent_id="nope")


def test_create_card_rejects_unknown_blocker(conn):
    with pytest.raises(core.CardNotFoundError):
        core.create_card(conn, title="Card", blocked_by=["nope"])


def test_update_card_changes_only_given_fields(conn):
    card = core.create_card(conn, title="Original", description="d")
    updated = core.update_card(conn, card.id, title="Updated")
    assert updated.title == "Updated"
    assert updated.description == "d"


def test_update_card_rejects_blocked_status(conn):
    card = core.create_card(conn, title="Card")
    with pytest.raises(core.InvalidStatusError):
        core.update_card(conn, card.id, status="blocked")


def test_update_card_rejects_parent_cycle(conn):
    a = core.create_card(conn, title="A")
    b = core.create_card(conn, title="B", parent_id=a.id)
    with pytest.raises(core.CycleError):
        core.update_card(conn, a.id, parent_id=b.id)


def test_update_card_can_clear_parent(conn):
    a = core.create_card(conn, title="A")
    b = core.create_card(conn, title="B", parent_id=a.id)
    updated = core.update_card(conn, b.id, parent_id=core.CLEAR_PARENT)
    assert updated.parent_id is None


def test_block_card_adds_edge(conn):
    a = core.create_card(conn, title="A")
    b = core.create_card(conn, title="B")
    core.block_card(conn, a.id, b.id)
    assert db.list_blockers_of(conn, a.id) == [b.id]


def test_block_card_rejects_cycle(conn):
    a = core.create_card(conn, title="A")
    b = core.create_card(conn, title="B")
    core.block_card(conn, a.id, b.id)
    with pytest.raises(core.CycleError):
        core.block_card(conn, b.id, a.id)


def test_unblock_card_removes_edge(conn):
    a = core.create_card(conn, title="A")
    b = core.create_card(conn, title="B")
    core.block_card(conn, a.id, b.id)
    core.unblock_card(conn, a.id, b.id)
    assert db.list_blockers_of(conn, a.id) == []


def test_update_card_rejects_unknown_card(conn):
    with pytest.raises(core.CardNotFoundError):
        core.update_card(conn, "nope", title="Updated")


def test_update_card_rejects_unknown_parent(conn):
    card = core.create_card(conn, title="Card")
    with pytest.raises(core.CardNotFoundError):
        core.update_card(conn, card.id, parent_id="nope")


def test_update_card_bumps_updated_at_and_leaves_created_at(conn, monkeypatch):
    card = core.create_card(conn, title="Card")
    monkeypatch.setattr(core, "_now", lambda: "2099-01-01T00:00:00+00:00")
    updated = core.update_card(conn, card.id, title="Updated")
    assert updated.updated_at == "2099-01-01T00:00:00+00:00"
    assert updated.created_at == card.created_at


def test_update_card_without_fields_does_not_touch_updated_at(conn, monkeypatch):
    card = core.create_card(conn, title="Card")
    monkeypatch.setattr(core, "_now", lambda: "2099-01-01T00:00:00+00:00")
    unchanged = core.update_card(conn, card.id)
    assert unchanged == card


def test_create_card_stamps_equal_created_and_updated_at(conn):
    card = core.create_card(conn, title="Card")
    assert card.created_at == card.updated_at


def test_block_card_rejects_unknown_card(conn):
    blocker = core.create_card(conn, title="Blocker")
    with pytest.raises(core.CardNotFoundError):
        core.block_card(conn, "nope", blocker.id)


def test_block_card_rejects_unknown_blocker(conn):
    card = core.create_card(conn, title="Card")
    with pytest.raises(core.CardNotFoundError):
        core.block_card(conn, card.id, "nope")


def test_unblock_card_rejects_unknown_card(conn):
    with pytest.raises(core.CardNotFoundError):
        core.unblock_card(conn, "nope", "also-nope")
