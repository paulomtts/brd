import sqlite3

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
