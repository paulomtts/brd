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
