import sqlite3

from brd import core, db
from brd.models import Card


def card_detail(conn: sqlite3.Connection, card: Card) -> dict:
    return {
        "id": card.id,
        "title": card.title,
        "description": card.description,
        "status": core.resolve_status(conn, card),
        "parent_id": card.parent_id,
        "created_at": card.created_at,
        "updated_at": card.updated_at,
        "blocked_by": db.list_blockers_of(conn, card.id),
        "children": [child.id for child in db.list_children(conn, card.id)],
    }
