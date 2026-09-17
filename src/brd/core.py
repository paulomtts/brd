import sqlite3
import uuid
from datetime import datetime, timezone

from brd import db
from brd.models import Card


class CycleError(Exception):
    pass


def resolve_status(conn: sqlite3.Connection, card: Card, _seen: set[str] | None = None) -> str:
    if card.status != "todo":
        return card.status

    seen = _seen or set()
    if card.id in seen:
        # Defensive: a blocked_by cycle should never be persisted, but avoid
        # infinite recursion if one somehow exists.
        return "todo"
    seen = seen | {card.id}

    for blocker_id in db.list_blockers_of(conn, card.id):
        blocker = db.get_card(conn, blocker_id)
        if blocker is None:
            continue
        if resolve_status(conn, blocker, seen) != "done":
            return "blocked"

    return "todo"


def would_create_parent_cycle(conn: sqlite3.Connection, card_id: str, new_parent_id: str) -> bool:
    current_id: str | None = new_parent_id
    while current_id is not None:
        if current_id == card_id:
            return True
        parent = db.get_card(conn, current_id)
        current_id = parent.parent_id if parent else None
    return False


def would_create_block_cycle(conn: sqlite3.Connection, card_id: str, new_blocker_id: str) -> bool:
    stack = [new_blocker_id]
    visited: set[str] = set()
    while stack:
        current = stack.pop()
        if current == card_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        stack.extend(db.list_blockers_of(conn, current))
    return False


class CardNotFoundError(Exception):
    pass


class InvalidStatusError(Exception):
    pass


CLEAR_PARENT = object()  # sentinel: "explicitly set parent_id to None"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_card(conn: sqlite3.Connection, card_id: str) -> Card:
    card = db.get_card(conn, card_id)
    if card is None:
        raise CardNotFoundError(f"no card with id {card_id}")
    return card


def create_card(
    conn: sqlite3.Connection,
    title: str,
    description: str | None = None,
    parent_id: str | None = None,
    blocked_by: list[str] | None = None,
) -> Card:
    if parent_id is not None:
        _require_card(conn, parent_id)

    blocked_by = blocked_by or []
    for blocker_id in blocked_by:
        _require_card(conn, blocker_id)

    now = _now()
    card = Card(
        id=str(uuid.uuid4()),
        title=title,
        description=description,
        status="todo",
        parent_id=parent_id,
        created_at=now,
        updated_at=now,
    )
    db.insert_card(conn, card)

    for blocker_id in blocked_by:
        if would_create_block_cycle(conn, card.id, blocker_id):
            raise CycleError(f"blocking {card.id} on {blocker_id} would create a cycle")
        db.add_blocked_by_edge(conn, card.id, blocker_id)

    return card


def update_card(
    conn: sqlite3.Connection,
    card_id: str,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
    parent_id: str | object | None = None,
) -> Card:
    _require_card(conn, card_id)

    if status == "blocked":
        raise InvalidStatusError("status cannot be set to 'blocked' directly; it is derived")

    fields: dict[str, str | None] = {}
    if title is not None:
        fields["title"] = title
    if description is not None:
        fields["description"] = description
    if status is not None:
        fields["status"] = status

    if parent_id is CLEAR_PARENT:
        fields["parent_id"] = None
    elif parent_id is not None:
        _require_card(conn, parent_id)
        if would_create_parent_cycle(conn, card_id, parent_id):
            raise CycleError(f"setting {card_id}'s parent to {parent_id} would create a cycle")
        fields["parent_id"] = parent_id

    if fields:
        fields["updated_at"] = _now()
        db.update_card_fields(conn, card_id, **fields)

    return _require_card(conn, card_id)


def block_card(conn: sqlite3.Connection, card_id: str, blocker_id: str) -> None:
    _require_card(conn, card_id)
    _require_card(conn, blocker_id)
    if would_create_block_cycle(conn, card_id, blocker_id):
        raise CycleError(f"blocking {card_id} on {blocker_id} would create a cycle")
    db.add_blocked_by_edge(conn, card_id, blocker_id)


def unblock_card(conn: sqlite3.Connection, card_id: str, blocker_id: str) -> None:
    _require_card(conn, card_id)
    db.remove_blocked_by_edge(conn, card_id, blocker_id)


def next_cards(conn: sqlite3.Connection, limit: int | None = None) -> list[Card]:
    todo_cards = db.list_cards(conn, status="todo")
    ready = [
        card
        for card in todo_cards
        if resolve_status(conn, card) == "todo" and not db.list_children(conn, card.id)
    ]
    return ready[:limit] if limit is not None else ready


def _build_node(conn: sqlite3.Connection, card: Card) -> dict:
    return {
        "id": card.id,
        "title": card.title,
        "status": resolve_status(conn, card),
        "blocked_by": db.list_blockers_of(conn, card.id),
        "children": [
            _build_node(conn, child) for child in db.list_children(conn, card.id)
        ],
    }


def build_tree(conn: sqlite3.Connection, root_id: str | None = None) -> list[dict]:
    if root_id is not None:
        card = _require_card(conn, root_id)
        return [_build_node(conn, card)]

    top_level = db.list_cards(conn, parent_id=None)
    return [_build_node(conn, card) for card in top_level]
