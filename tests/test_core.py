import pytest

from brd import core, db, issues
from brd import refs as _refs
from brd.models import Card
from tests.factories import OTHER_PROJECT, PROJECT, add_project, make_issue


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "project.db")
    db.init_project_schema(connection, PROJECT)
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
    db.insert_card(conn, PROJECT.id, _card("c1"))
    card = db.get_card(conn, "c1")
    assert core.resolve_status(conn, card) == "todo"


def test_resolve_status_todo_with_unresolved_blocker_is_blocked(conn):
    db.insert_card(conn, PROJECT.id, _card("c1"))
    db.insert_card(conn, PROJECT.id, _card("blocker", status="todo"))
    db.add_blocked_by_edge(conn, "c1", "blocker")
    card = db.get_card(conn, "c1")
    assert core.resolve_status(conn, card) == "blocked"


def test_resolve_status_todo_with_done_blocker_is_todo(conn):
    db.insert_card(conn, PROJECT.id, _card("c1"))
    db.insert_card(conn, PROJECT.id, _card("blocker", status="done"))
    db.add_blocked_by_edge(conn, "c1", "blocker")
    card = db.get_card(conn, "c1")
    assert core.resolve_status(conn, card) == "todo"


def test_resolve_status_todo_with_transitively_blocked_blocker_is_blocked(conn):
    db.insert_card(conn, PROJECT.id, _card("c1"))
    db.insert_card(conn, PROJECT.id, _card("mid", status="todo"))
    db.insert_card(conn, PROJECT.id, _card("root", status="todo"))
    db.add_blocked_by_edge(conn, "c1", "mid")
    db.add_blocked_by_edge(conn, "mid", "root")
    card = db.get_card(conn, "c1")
    assert core.resolve_status(conn, card) == "blocked"


def test_resolve_status_in_progress_is_unaffected_by_blockers(conn):
    db.insert_card(conn, PROJECT.id, _card("c1", status="in_progress"))
    db.insert_card(conn, PROJECT.id, _card("blocker", status="todo"))
    db.add_blocked_by_edge(conn, "c1", "blocker")
    card = db.get_card(conn, "c1")
    assert core.resolve_status(conn, card) == "in_progress"


def test_resolve_status_todo_child_of_blocked_parent_is_blocked(conn):
    db.insert_card(conn, PROJECT.id, _card("parent"))
    db.insert_card(conn, PROJECT.id, _card("parent_blocker"))
    db.add_blocked_by_edge(conn, "parent", "parent_blocker")
    db.insert_card(conn, PROJECT.id, _card("child", parent_id="parent"))

    card = db.get_card(conn, "child")
    assert core.resolve_status(conn, card) == "blocked"


def test_resolve_status_grandchild_of_blocked_grandparent_is_blocked(conn):
    db.insert_card(conn, PROJECT.id, _card("grandparent"))
    db.insert_card(conn, PROJECT.id, _card("blocker"))
    db.add_blocked_by_edge(conn, "grandparent", "blocker")
    db.insert_card(conn, PROJECT.id, _card("parent", parent_id="grandparent"))
    db.insert_card(conn, PROJECT.id, _card("child", parent_id="parent"))

    card = db.get_card(conn, "child")
    assert core.resolve_status(conn, card) == "blocked"


def test_resolve_status_child_of_unblocked_parent_is_todo(conn):
    db.insert_card(conn, PROJECT.id, _card("parent"))
    db.insert_card(conn, PROJECT.id, _card("child", parent_id="parent"))

    card = db.get_card(conn, "child")
    assert core.resolve_status(conn, card) == "todo"


def test_resolve_status_child_of_in_progress_parent_is_unaffected(conn):
    db.insert_card(conn, PROJECT.id, _card("parent", status="in_progress"))
    db.insert_card(conn, PROJECT.id, _card("child", parent_id="parent"))

    card = db.get_card(conn, "child")
    assert core.resolve_status(conn, card) == "todo"


def test_resolve_status_in_progress_child_of_blocked_parent_is_unaffected(conn):
    db.insert_card(conn, PROJECT.id, _card("parent"))
    db.insert_card(conn, PROJECT.id, _card("blocker"))
    db.add_blocked_by_edge(conn, "parent", "blocker")
    db.insert_card(conn, PROJECT.id, _card("child", status="in_progress", parent_id="parent"))

    card = db.get_card(conn, "child")
    assert core.resolve_status(conn, card) == "in_progress"


def test_would_create_parent_cycle_direct(conn):
    db.insert_card(conn, PROJECT.id, _card("a"))
    db.insert_card(conn, PROJECT.id, _card("b", parent_id="a"))
    assert core.would_create_parent_cycle(conn, "a", "b") is True


def test_would_create_parent_cycle_indirect(conn):
    db.insert_card(conn, PROJECT.id, _card("a"))
    db.insert_card(conn, PROJECT.id, _card("b", parent_id="a"))
    db.insert_card(conn, PROJECT.id, _card("c", parent_id="b"))
    assert core.would_create_parent_cycle(conn, "a", "c") is True


def test_would_create_parent_cycle_false_for_unrelated_cards(conn):
    db.insert_card(conn, PROJECT.id, _card("a"))
    db.insert_card(conn, PROJECT.id, _card("b"))
    assert core.would_create_parent_cycle(conn, "a", "b") is False


def test_would_create_block_cycle_direct(conn):
    db.insert_card(conn, PROJECT.id, _card("a"))
    db.insert_card(conn, PROJECT.id, _card("b"))
    db.add_blocked_by_edge(conn, "a", "b")
    assert core.would_create_block_cycle(conn, "b", "a") is True


def test_would_create_block_cycle_indirect(conn):
    db.insert_card(conn, PROJECT.id, _card("a"))
    db.insert_card(conn, PROJECT.id, _card("b"))
    db.insert_card(conn, PROJECT.id, _card("c"))
    db.add_blocked_by_edge(conn, "a", "b")
    db.add_blocked_by_edge(conn, "b", "c")
    assert core.would_create_block_cycle(conn, "c", "a") is True


def test_would_create_block_cycle_false_for_unrelated_cards(conn):
    db.insert_card(conn, PROJECT.id, _card("a"))
    db.insert_card(conn, PROJECT.id, _card("b"))
    assert core.would_create_block_cycle(conn, "a", "b") is False


def _status(conn, card_id):
    return core.resolve_status(conn, db.get_card(conn, card_id))


def test_resolve_status_blocks_on_a_blocker_that_is_not_found(conn):
    db.insert_card(conn, PROJECT.id, _card("c1"))
    db.add_blocked_by_edge(conn, "c1", "ghost")
    assert _status(conn, "c1") == "blocked"


def test_resolve_status_not_found_blocker_wins_over_released_ones(conn):
    db.insert_card(conn, PROJECT.id, _card("c1"))
    db.insert_card(conn, PROJECT.id, _card("d", status="done"))
    make_issue(conn, "i", status="closed")
    db.add_blocked_by_edge(conn, "c1", "d")
    db.add_blocked_by_edge(conn, "c1", "i")
    db.add_blocked_by_edge(conn, "c1", "ghost")
    assert _status(conn, "c1") == "blocked"

    db.remove_blocked_by_edge(conn, "c1", "ghost")
    assert _status(conn, "c1") == "todo"


def test_resolve_status_not_found_blocker_blocks_children_and_spares_non_todo(conn):
    db.insert_card(conn, PROJECT.id, _card("p"))
    db.insert_card(conn, PROJECT.id, _card("ch", parent_id="p"))
    db.add_blocked_by_edge(conn, "p", "ghost")
    assert _status(conn, "ch") == "blocked"

    db.insert_card(conn, PROJECT.id, _card("wip", status="in_progress"))
    db.add_blocked_by_edge(conn, "wip", "ghost")
    assert _status(conn, "wip") == "in_progress"

    db.insert_card(conn, PROJECT.id, _card("x", status="done"))
    db.insert_card(conn, PROJECT.id, _card("y"))
    db.add_blocked_by_edge(conn, "x", "ghost")
    db.add_blocked_by_edge(conn, "y", "x")
    assert _status(conn, "x") == "done"
    assert _status(conn, "y") == "todo"


def test_resolve_status_not_found_blocker_inside_a_persisted_cycle_ends_blocked(conn):
    db.insert_card(conn, PROJECT.id, _card("a"))
    db.insert_card(conn, PROJECT.id, _card("b"))
    db.add_blocked_by_edge(conn, "a", "b")
    db.add_blocked_by_edge(conn, "b", "a")
    db.add_blocked_by_edge(conn, "a", "ghost")
    assert _status(conn, "a") == "blocked"
    assert _status(conn, "b") == "blocked"


def test_block_cycle_check_treats_a_not_found_id_as_a_dead_end(conn):
    db.insert_card(conn, PROJECT.id, _card("a"))
    db.insert_card(conn, PROJECT.id, _card("b"))
    db.add_blocked_by_edge(conn, "a", "ghost")

    assert core.would_create_block_cycle(conn, "b", "a") is False
    assert core.would_create_block_cycle(conn, "ghost", "a") is True

    core.block_card(conn, PROJECT.id, "b", "a")
    assert db.list_blockers_of(conn, "b") == ["a"]
    assert _status(conn, "b") == "blocked"
    assert _status(conn, "a") == "blocked"


def test_unblock_card_removes_a_not_found_edge(conn):
    db.insert_card(conn, PROJECT.id, _card("c1"))
    db.add_blocked_by_edge(conn, "c1", "ghost")
    assert _status(conn, "c1") == "blocked"

    core.unblock_card(conn, PROJECT.id, "c1", "ghost")

    assert db.list_blockers_of(conn, "c1") == []
    assert _status(conn, "c1") == "todo"


def test_resolve_status_terminates_on_persisted_blocking_cycle(conn):
    db.insert_card(conn, PROJECT.id, _card("a"))
    db.insert_card(conn, PROJECT.id, _card("b"))
    db.add_blocked_by_edge(conn, "a", "b")
    db.add_blocked_by_edge(conn, "b", "a")
    card = db.get_card(conn, "a")
    assert core.resolve_status(conn, card) == "blocked"


def test_would_create_parent_cycle_false_when_new_parent_is_missing(conn):
    db.insert_card(conn, PROJECT.id, _card("a"))
    assert core.would_create_parent_cycle(conn, "a", "ghost") is False


def test_would_create_block_cycle_terminates_on_persisted_blocking_cycle(conn):
    db.insert_card(conn, PROJECT.id, _card("a"))
    db.insert_card(conn, PROJECT.id, _card("b"))
    db.insert_card(conn, PROJECT.id, _card("c"))
    db.add_blocked_by_edge(conn, "b", "c")
    db.add_blocked_by_edge(conn, "c", "b")
    assert core.would_create_block_cycle(conn, "a", "b") is False


def test_create_card_defaults_to_todo(conn):
    card = core.create_card(conn, PROJECT.id, title="New card")
    assert card.status == "todo"
    assert card.title == "New card"
    assert db.get_card(conn, card.id) == card


def test_create_card_with_parent_and_blocked_by(conn):
    parent = core.create_card(conn, PROJECT.id, title="Parent")
    blocker = core.create_card(conn, PROJECT.id, title="Blocker")
    child = core.create_card(conn, PROJECT.id, title="Child", parent_id=parent.id, blocked_by=[blocker.id]
    )
    assert child.parent_id == parent.id
    assert db.list_blockers_of(conn, child.id) == [blocker.id]


def test_create_card_rejects_unknown_parent(conn):
    with pytest.raises(core.CardNotFoundError):
        core.create_card(conn, PROJECT.id, title="Orphan", parent_id="nope")


def test_create_card_rejects_unknown_blocker(conn):
    with pytest.raises(core.CardNotFoundError):
        core.create_card(conn, PROJECT.id, title="Card", blocked_by=["nope"])


def test_update_card_changes_only_given_fields(conn):
    card = core.create_card(conn, PROJECT.id, title="Original", description="d")
    updated = core.update_card(conn, PROJECT.id, card.id, title="Updated")
    assert updated.title == "Updated"
    assert updated.description == "d"


def test_update_card_rejects_blocked_status(conn):
    card = core.create_card(conn, PROJECT.id, title="Card")
    with pytest.raises(core.InvalidStatusError):
        core.update_card(conn, PROJECT.id, card.id, status="blocked")


def test_update_card_rejects_parent_cycle(conn):
    a = core.create_card(conn, PROJECT.id, title="A")
    b = core.create_card(conn, PROJECT.id, title="B", parent_id=a.id)
    with pytest.raises(core.CycleError):
        core.update_card(conn, PROJECT.id, a.id, parent_id=b.id)


def test_update_card_can_clear_parent(conn):
    a = core.create_card(conn, PROJECT.id, title="A")
    b = core.create_card(conn, PROJECT.id, title="B", parent_id=a.id)
    updated = core.update_card(conn, PROJECT.id, b.id, parent_id=core.CLEAR_PARENT)
    assert updated.parent_id is None


def test_block_card_adds_edge(conn):
    a = core.create_card(conn, PROJECT.id, title="A")
    b = core.create_card(conn, PROJECT.id, title="B")
    core.block_card(conn, PROJECT.id, a.id, b.id)
    assert db.list_blockers_of(conn, a.id) == [b.id]


def test_block_card_rejects_cycle(conn):
    a = core.create_card(conn, PROJECT.id, title="A")
    b = core.create_card(conn, PROJECT.id, title="B")
    core.block_card(conn, PROJECT.id, a.id, b.id)
    with pytest.raises(core.CycleError):
        core.block_card(conn, PROJECT.id, b.id, a.id)


def test_unblock_card_removes_edge(conn):
    a = core.create_card(conn, PROJECT.id, title="A")
    b = core.create_card(conn, PROJECT.id, title="B")
    core.block_card(conn, PROJECT.id, a.id, b.id)
    core.unblock_card(conn, PROJECT.id, a.id, b.id)
    assert db.list_blockers_of(conn, a.id) == []


def test_update_card_rejects_unknown_card(conn):
    with pytest.raises(core.CardNotFoundError):
        core.update_card(conn, PROJECT.id, "nope", title="Updated")


def test_delete_card_removes_leaf_card(conn):
    card = core.create_card(conn, PROJECT.id, title="A")
    deleted = core.delete_card(conn, PROJECT.id, card.id)
    assert deleted == [card.id]
    assert db.get_card(conn, card.id) is None


def test_delete_card_rejects_unknown_card(conn):
    with pytest.raises(core.CardNotFoundError):
        core.delete_card(conn, PROJECT.id, "nope")


def test_delete_card_with_children_without_cascade_raises(conn):
    parent = core.create_card(conn, PROJECT.id, title="P")
    core.create_card(conn, PROJECT.id, title="C", parent_id=parent.id)
    with pytest.raises(core.CardHasChildrenError):
        core.delete_card(conn, PROJECT.id, parent.id)
    assert db.get_card(conn, parent.id) is not None


def test_delete_card_with_cascade_removes_subtree(conn):
    parent = core.create_card(conn, PROJECT.id, title="P")
    child = core.create_card(conn, PROJECT.id, title="C", parent_id=parent.id)
    grandchild = core.create_card(conn, PROJECT.id, title="GC", parent_id=child.id)

    deleted = core.delete_card(conn, PROJECT.id, parent.id, cascade=True)

    assert set(deleted) == {parent.id, child.id, grandchild.id}
    assert db.get_card(conn, parent.id) is None
    assert db.get_card(conn, child.id) is None
    assert db.get_card(conn, grandchild.id) is None


def test_delete_card_removes_blocked_by_edges(conn):
    a = core.create_card(conn, PROJECT.id, title="A")
    b = core.create_card(conn, PROJECT.id, title="B")
    core.block_card(conn, PROJECT.id, a.id, b.id)

    core.delete_card(conn, PROJECT.id, b.id)

    assert db.list_blockers_of(conn, a.id) == []


def test_delete_card_cascade_removes_incoming_edges_of_every_deleted_card(conn):
    parent = core.create_card(conn, PROJECT.id, title="P")
    child = core.create_card(conn, PROJECT.id, title="C", parent_id=parent.id)
    grandchild = core.create_card(conn, PROJECT.id, title="G", parent_id=child.id)
    outsider = core.create_card(conn, PROJECT.id, title="O")
    unrelated = core.create_card(conn, PROJECT.id, title="U")
    core.block_card(conn, PROJECT.id, outsider.id, child.id)
    core.block_card(conn, PROJECT.id, outsider.id, grandchild.id)
    core.block_card(conn, PROJECT.id, outsider.id, unrelated.id)
    _refs.add_explicit(conn, PROJECT.id, outsider.id, parent.id)
    _refs.add_explicit(conn, PROJECT.id, outsider.id, grandchild.id)
    conn.commit()
    conn.execute("PRAGMA foreign_keys=OFF")

    deleted = core.delete_card(conn, PROJECT.id, parent.id, cascade=True)

    assert set(deleted) == {parent.id, child.id, grandchild.id}
    for card_id in deleted:
        assert conn.execute(
            "SELECT COUNT(*) FROM blocked_by WHERE blocks_on_id = ?", (card_id,)
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM refs WHERE dst_id = ?", (card_id,)
        ).fetchone()[0] == 0
    assert db.list_blockers_of(conn, outsider.id) == [unrelated.id]


def test_update_card_rejects_unknown_parent(conn):
    card = core.create_card(conn, PROJECT.id, title="Card")
    with pytest.raises(core.CardNotFoundError):
        core.update_card(conn, PROJECT.id, card.id, parent_id="nope")


def test_update_card_bumps_updated_at_and_leaves_created_at(conn, monkeypatch):
    card = core.create_card(conn, PROJECT.id, title="Card")
    monkeypatch.setattr(core, "_now", lambda: "2099-01-01T00:00:00+00:00")
    updated = core.update_card(conn, PROJECT.id, card.id, title="Updated")
    assert updated.updated_at == "2099-01-01T00:00:00+00:00"
    assert updated.created_at == card.created_at


def test_update_card_without_fields_does_not_touch_updated_at(conn, monkeypatch):
    card = core.create_card(conn, PROJECT.id, title="Card")
    monkeypatch.setattr(core, "_now", lambda: "2099-01-01T00:00:00+00:00")
    unchanged = core.update_card(conn, PROJECT.id, card.id)
    assert unchanged == card


def test_create_card_stamps_equal_created_and_updated_at(conn):
    card = core.create_card(conn, PROJECT.id, title="Card")
    assert card.created_at == card.updated_at


def test_block_card_rejects_unknown_card(conn):
    blocker = core.create_card(conn, PROJECT.id, title="Blocker")
    with pytest.raises(core.CardNotFoundError):
        core.block_card(conn, PROJECT.id, "nope", blocker.id)


def test_block_card_rejects_unknown_blocker(conn):
    card = core.create_card(conn, PROJECT.id, title="Card")
    with pytest.raises(core.CardNotFoundError):
        core.block_card(conn, PROJECT.id, card.id, "nope")


def test_unblock_card_rejects_unknown_card(conn):
    with pytest.raises(core.CardNotFoundError):
        core.unblock_card(conn, PROJECT.id, "nope", "also-nope")


def test_next_cards_returns_unblocked_todo_oldest_first(conn):
    a = core.create_card(conn, PROJECT.id, title="A")
    b = core.create_card(conn, PROJECT.id, title="B")
    blocker = core.create_card(conn, PROJECT.id, title="Blocker")
    core.block_card(conn, PROJECT.id, b.id, blocker.id)

    result = core.next_cards(conn, PROJECT.id)
    assert [c.id for c in result] == [a.id, blocker.id]


def test_next_cards_excludes_in_progress_and_done(conn):
    a = core.create_card(conn, PROJECT.id, title="A")
    core.update_card(conn, PROJECT.id, a.id, status="in_progress")
    b = core.create_card(conn, PROJECT.id, title="B")
    core.update_card(conn, PROJECT.id, b.id, status="done")
    c = core.create_card(conn, PROJECT.id, title="C")

    result = core.next_cards(conn, PROJECT.id)
    assert [card.id for card in result] == [c.id]


def test_next_cards_respects_limit(conn):
    core.create_card(conn, PROJECT.id, title="A")
    core.create_card(conn, PROJECT.id, title="B")
    core.create_card(conn, PROJECT.id, title="C")

    result = core.next_cards(conn, PROJECT.id, limit=2)
    assert len(result) == 2


def test_build_tree_single_root_with_children_and_blockers(conn):
    parent = core.create_card(conn, PROJECT.id, title="Parent")
    blocker = core.create_card(conn, PROJECT.id, title="Blocker")
    child = core.create_card(conn, PROJECT.id, title="Child", parent_id=parent.id, blocked_by=[blocker.id]
    )

    tree = core.build_tree(conn, PROJECT.id, root_id=parent.id)
    assert len(tree) == 1
    root_node = tree[0]
    assert root_node["id"] == parent.id
    assert root_node["title"] == "Parent"
    assert root_node["status"] == "todo"
    assert len(root_node["children"]) == 1
    child_node = root_node["children"][0]
    assert child_node["id"] == child.id
    assert child_node["title"] == "Child"
    assert child_node["status"] == "blocked"
    assert child_node["blocked_by"] == [blocker.id]
    assert child_node["children"] == []


def test_build_tree_node_includes_description_and_timestamps(conn):
    card = core.create_card(conn, PROJECT.id, title="Card", description="details")

    tree = core.build_tree(conn, PROJECT.id, root_id=card.id)
    node = tree[0]
    assert node["description"] == "details"
    assert node["created_at"] == card.created_at
    assert node["updated_at"] == card.updated_at


def test_build_tree_whole_board_returns_all_top_level_roots(conn):
    root1 = core.create_card(conn, PROJECT.id, title="Root1")
    root2 = core.create_card(conn, PROJECT.id, title="Root2")
    parent = core.create_card(conn, PROJECT.id, title="Root3")
    nested = core.create_card(conn, PROJECT.id, title="Nested", parent_id=parent.id)

    tree = core.build_tree(conn, PROJECT.id)
    assert [node["id"] for node in tree] == [root1.id, root2.id, parent.id]
    assert [node["id"] for node in tree[2]["children"]] == [nested.id]
    assert [node["title"] for node in tree] == ["Root1", "Root2", "Root3"]


def test_build_tree_rejects_unknown_root_id(conn):
    with pytest.raises(core.CardNotFoundError):
        core.build_tree(conn, PROJECT.id, root_id="nope")


def test_next_cards_limit_zero_returns_empty(conn):
    core.create_card(conn, PROJECT.id, title="A")
    core.create_card(conn, PROJECT.id, title="B")

    assert core.next_cards(conn, PROJECT.id, limit=0) == []


def test_next_cards_excludes_cards_with_children(conn):
    epic = core.create_card(conn, PROJECT.id, title="Epic")
    child = core.create_card(conn, PROJECT.id, title="Child", parent_id=epic.id)

    result = core.next_cards(conn, PROJECT.id)
    assert [c.id for c in result] == [child.id]


def test_next_cards_with_parent_returns_ready_direct_children(conn):
    milestone = core.create_card(conn, PROJECT.id, title="Milestone")
    story_a = core.create_card(conn, PROJECT.id, title="Story A", parent_id=milestone.id)
    story_b = core.create_card(conn, PROJECT.id, title="Story B", parent_id=milestone.id)
    core.block_card(conn, PROJECT.id, story_b.id, story_a.id)
    core.create_card(conn, PROJECT.id, title="A.1", parent_id=story_a.id)  # unrelated leaf

    result = core.next_cards(conn, PROJECT.id, parent_id=milestone.id)
    assert [c.id for c in result] == [story_a.id]


def test_next_cards_with_parent_includes_ready_children_even_with_grandchildren(conn):
    story = core.create_card(conn, PROJECT.id, title="Story")
    subtask = core.create_card(conn, PROJECT.id, title="Subtask", parent_id=story.id)
    core.create_card(conn, PROJECT.id, title="Sub-subtask", parent_id=subtask.id)

    result = core.next_cards(conn, PROJECT.id, parent_id=story.id)
    assert [c.id for c in result] == [subtask.id]


def test_next_cards_with_parent_excludes_blocked_children(conn):
    story = core.create_card(conn, PROJECT.id, title="Story")
    blocker = core.create_card(conn, PROJECT.id, title="Blocker")
    core.create_card(conn, PROJECT.id, title="Subtask", parent_id=story.id, blocked_by=[blocker.id])

    result = core.next_cards(conn, PROJECT.id, parent_id=story.id)
    assert result == []


def test_next_cards_with_unknown_parent_raises(conn):
    with pytest.raises(core.CardNotFoundError):
        core.next_cards(conn, PROJECT.id, parent_id="nope")


def test_import_tree_round_trips_a_whole_board(conn):
    parent = core.create_card(conn, PROJECT.id, title="Parent", description="p desc")
    blocker = core.create_card(conn, PROJECT.id, title="Blocker")
    core.create_card(conn, PROJECT.id, title="Child",
        description="c desc",
        parent_id=parent.id,
        blocked_by=[blocker.id],
    )
    original_tree = core.build_tree(conn, PROJECT.id)

    fresh_conn = db.connect(":memory:")
    db.init_project_schema(fresh_conn, PROJECT)
    count = core.import_tree(fresh_conn, PROJECT.id, original_tree)

    assert count == 3
    assert core.build_tree(fresh_conn, PROJECT.id) == original_tree


def test_import_tree_maps_derived_blocked_status_back_to_todo(conn):
    blocker = core.create_card(conn, PROJECT.id, title="Blocker")
    blocked = core.create_card(conn, PROJECT.id, title="Blocked", blocked_by=[blocker.id])
    tree = core.build_tree(conn, PROJECT.id)

    fresh_conn = db.connect(":memory:")
    db.init_project_schema(fresh_conn, PROJECT)
    core.import_tree(fresh_conn, PROJECT.id, tree)

    stored = db.get_card(fresh_conn, blocked.id)
    assert stored.status == "todo"  # not "blocked" -- that's derived, not stored
    assert core.resolve_status(fresh_conn, stored) == "blocked"


def test_import_tree_preserves_in_progress_and_done_status(conn):
    a = core.create_card(conn, PROJECT.id, title="A")
    core.update_card(conn, PROJECT.id, a.id, status="in_progress")
    b = core.create_card(conn, PROJECT.id, title="B")
    core.update_card(conn, PROJECT.id, b.id, status="done")
    tree = core.build_tree(conn, PROJECT.id)

    fresh_conn = db.connect(":memory:")
    db.init_project_schema(fresh_conn, PROJECT)
    core.import_tree(fresh_conn, PROJECT.id, tree)

    assert db.get_card(fresh_conn, a.id).status == "in_progress"
    assert db.get_card(fresh_conn, b.id).status == "done"


def test_import_tree_rejects_colliding_id_without_partial_import(conn):
    existing = core.create_card(conn, PROJECT.id, title="Existing")
    other = core.create_card(conn, PROJECT.id, title="Other")
    tree = [
        {
            "id": existing.id,
            "title": "Existing",
            "description": None,
            "status": "todo",
            "blocked_by": [],
            "created_at": existing.created_at,
            "updated_at": existing.updated_at,
            "children": [],
        }
    ]

    with pytest.raises(core.CardAlreadyExistsError):
        core.import_tree(conn, PROJECT.id, tree)

    # nothing else got touched
    assert db.get_card(conn, other.id) is not None


def test_create_card_indexes_description_links(conn):
    target = core.create_card(conn, PROJECT.id, title="Target")
    source = core.create_card(conn, PROJECT.id, title="Source", description=f"see [[{target.id}]]")
    assert [r["id"] for r in _refs.outgoing(conn, source.id)] == [target.id]


def test_update_card_removing_link_drops_link_ref_but_keeps_explicit(conn):
    target = core.create_card(conn, PROJECT.id, title="Target")
    other = core.create_card(conn, PROJECT.id, title="Other")
    source = core.create_card(conn, PROJECT.id, title="Source", description=f"[[{target.id}]] [[{other.id}]]")
    _refs.add_explicit(conn, PROJECT.id, source.id, other.id)
    core.update_card(conn, PROJECT.id, source.id, description="no links now")
    assert {(r["id"], r["origin"]) for r in _refs.outgoing(conn, source.id)} == {
        (other.id, "explicit")
    }


@pytest.mark.parametrize("blocker_status", ["done", "merged", "canceled", "archived"])
def test_resolve_status_terminal_blocker_releases_dependent(conn, blocker_status):
    db.insert_card(conn, PROJECT.id, _card("blocker", status=blocker_status))
    db.insert_card(conn, PROJECT.id, _card("c1"))
    db.add_blocked_by_edge(conn, "c1", "blocker")

    assert core.resolve_status(conn, db.get_card(conn, "c1")) == "todo"


@pytest.mark.parametrize("status", ["merged", "canceled", "archived"])
def test_update_card_accepts_every_terminal_status(conn, status):
    db.insert_card(conn, PROJECT.id, _card("c1"))

    assert core.update_card(conn, PROJECT.id, "c1", status=status).status == status
    assert core.resolve_status(conn, db.get_card(conn, "c1")) == status


def test_update_card_rejects_unknown_status(conn):
    db.insert_card(conn, PROJECT.id, _card("c1"))

    with pytest.raises(core.InvalidStatusError):
        core.update_card(conn, PROJECT.id, "c1", status="cancelled")


def _story_with_children(conn, story_id, child_statuses, story_status="todo"):
    db.insert_card(conn, PROJECT.id, _card(story_id, status=story_status))
    for index, status in enumerate(child_statuses):
        db.insert_card(conn, PROJECT.id, _card(f"{story_id}-c{index}", status=status, parent_id=story_id))


def _blocked_on(conn, card_id, blocker_id):
    db.insert_card(conn, PROJECT.id, _card(card_id))
    db.add_blocked_by_edge(conn, card_id, blocker_id)
    return db.get_card(conn, card_id)


def test_resolve_status_dependent_of_story_with_all_children_releasing_is_todo(conn):
    _story_with_children(conn, "s", ["done", "merged", "canceled", "archived"])
    dependent = _blocked_on(conn, "d", "s")

    assert core.resolve_status(conn, dependent) == "todo"


def test_resolve_status_dependent_of_story_with_one_todo_child_is_blocked(conn):
    _story_with_children(conn, "s", ["done", "merged", "canceled", "archived", "todo"])
    dependent = _blocked_on(conn, "d", "s")

    assert core.resolve_status(conn, dependent) == "blocked"


def test_resolve_status_dependent_of_story_with_in_progress_child_is_blocked(conn):
    _story_with_children(conn, "s", ["done", "in_progress"])
    dependent = _blocked_on(conn, "d", "s")

    assert core.resolve_status(conn, dependent) == "blocked"


def test_resolve_status_dependent_of_story_with_blocked_child_is_blocked(conn):
    _story_with_children(conn, "s", ["done", "todo"])
    issue = issues.open_issue(conn, PROJECT.id, "q")
    core.block_card(conn, PROJECT.id, "s-c1", issue.id)
    dependent = _blocked_on(conn, "d", "s")
    assert core.resolve_status(conn, db.get_card(conn, "s-c1")) == "blocked"

    assert core.resolve_status(conn, dependent) == "blocked"

    issues.close(conn, PROJECT.id, issue.id)
    db.update_card_fields(conn, "s-c1", status="done")
    assert core.resolve_status(conn, db.get_card(conn, "d")) == "todo"


def test_resolve_status_dependent_of_milestone_releases_only_when_every_story_does(conn):
    db.insert_card(conn, PROJECT.id, _card("m"))
    db.insert_card(conn, PROJECT.id, _card("s1", parent_id="m"))
    db.insert_card(conn, PROJECT.id, _card("s1-c0", status="done", parent_id="s1"))
    db.insert_card(conn, PROJECT.id, _card("s1-c1", status="done", parent_id="s1"))
    db.insert_card(conn, PROJECT.id, _card("s2", parent_id="m"))
    db.insert_card(conn, PROJECT.id, _card("s2-c0", status="done", parent_id="s2"))
    db.insert_card(conn, PROJECT.id, _card("s2-c1", status="todo", parent_id="s2"))
    dependent = _blocked_on(conn, "d", "m")

    assert core.resolve_status(conn, dependent) == "blocked"

    db.update_card_fields(conn, "s2-c1", status="done")
    assert core.resolve_status(conn, db.get_card(conn, "d")) == "todo"


def test_resolve_status_dependent_of_milestone_with_done_story_releases(conn):
    db.insert_card(conn, PROJECT.id, _card("m"))
    db.insert_card(conn, PROJECT.id, _card("s1", status="done", parent_id="m"))
    db.insert_card(conn, PROJECT.id, _card("s1-c0", status="todo", parent_id="s1"))
    db.insert_card(conn, PROJECT.id, _card("s2", parent_id="m"))
    db.insert_card(conn, PROJECT.id, _card("s2-c0", status="done", parent_id="s2"))
    db.insert_card(conn, PROJECT.id, _card("s2-c1", status="done", parent_id="s2"))
    dependent = _blocked_on(conn, "d", "m")

    assert core.resolve_status(conn, dependent) == "todo"


def test_resolve_status_container_own_status_unchanged_when_children_done(conn):
    _story_with_children(conn, "s", ["done", "done"])

    assert core.resolve_status(conn, db.get_card(conn, "s")) == "todo"
    assert db.get_card(conn, "s").status == "todo"


def test_resolve_status_childless_todo_blocker_still_blocks(conn):
    db.insert_card(conn, PROJECT.id, _card("b"))
    dependent = _blocked_on(conn, "d", "b")

    assert core.resolve_status(conn, dependent) == "blocked"


def test_resolve_status_in_progress_container_with_all_children_done_releases(conn):
    _story_with_children(conn, "s", ["done", "done"], story_status="in_progress")
    dependent = _blocked_on(conn, "d", "s")

    assert core.resolve_status(conn, dependent) == "todo"


def test_resolve_status_blocked_container_with_all_children_done_releases(conn):
    db.insert_card(conn, PROJECT.id, _card("x"))
    _story_with_children(conn, "s", ["done", "done"])
    db.add_blocked_by_edge(conn, "s", "x")
    dependent = _blocked_on(conn, "d", "s")

    assert core.resolve_status(conn, dependent) == "todo"
    assert core.resolve_status(conn, db.get_card(conn, "s")) == "blocked"


def test_resolve_status_done_container_with_unfinished_child_releases(conn):
    _story_with_children(conn, "s", ["todo"], story_status="done")
    dependent = _blocked_on(conn, "d", "s")

    assert core.resolve_status(conn, dependent) == "todo"


def test_resolve_status_child_blocked_by_own_container_terminates_blocked(conn):
    _story_with_children(conn, "s", ["done", "todo"])
    db.add_blocked_by_edge(conn, "s-c1", "s")

    assert core.resolve_status(conn, db.get_card(conn, "s-c1")) == "blocked"


def test_resolve_status_container_child_blocked_by_dependent_terminates_blocked(conn):
    _story_with_children(conn, "s", ["todo"])
    db.insert_card(conn, PROJECT.id, _card("a"))
    db.add_blocked_by_edge(conn, "a", "s")
    db.add_blocked_by_edge(conn, "s-c0", "a")

    assert core.resolve_status(conn, db.get_card(conn, "a")) == "blocked"
    assert core.resolve_status(conn, db.get_card(conn, "s-c0")) == "blocked"


def test_next_cards_includes_dependent_of_finished_container(conn):
    story = core.create_card(conn, PROJECT.id, title="story")
    first = core.create_card(conn, PROJECT.id, title="first", parent_id=story.id)
    second = core.create_card(conn, PROJECT.id, title="second", parent_id=story.id)
    dependent = core.create_card(conn, PROJECT.id, title="dependent", blocked_by=[story.id])
    core.update_card(conn, PROJECT.id, first.id, status="done")
    core.update_card(conn, PROJECT.id, second.id, status="done")

    ready_ids = [card.id for card in core.next_cards(conn, PROJECT.id)]

    assert dependent.id in ready_ids
    assert story.id not in ready_ids


def test_resolve_status_terminates_on_persisted_parent_cycle(conn):
    db.insert_card(conn, PROJECT.id, _card("p"))
    db.insert_card(conn, PROJECT.id, _card("q", parent_id="p"))
    db.update_card_fields(conn, "p", parent_id="q")
    dependent = _blocked_on(conn, "d", "p")

    assert core.resolve_status(conn, dependent) == "blocked"


def _entity_project(conn, entity_id):
    return conn.execute(
        "SELECT project_id FROM entities WHERE id = ?", (entity_id,)
    ).fetchone()[0]


def test_create_card_records_its_project(conn):
    add_project(conn, OTHER_PROJECT)
    card = core.create_card(conn, OTHER_PROJECT.id, "Card")
    assert _entity_project(conn, card.id) == OTHER_PROJECT.id


def test_import_tree_records_its_project(conn):
    parent = core.create_card(conn, PROJECT.id, "Parent")
    core.create_card(conn, PROJECT.id, "Child", parent_id=parent.id)
    tree = core.build_tree(conn, PROJECT.id)

    fresh_conn = db.connect(":memory:")
    db.init_project_schema(fresh_conn, OTHER_PROJECT)
    core.import_tree(fresh_conn, OTHER_PROJECT.id, tree)

    projects = {r[0] for r in fresh_conn.execute("SELECT project_id FROM entities")}
    assert projects == {OTHER_PROJECT.id}
