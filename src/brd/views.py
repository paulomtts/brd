import dataclasses
import sqlite3
from pathlib import Path

from brd import comments, core, db, entities, refs
from brd.errors import CardNotFoundError
from brd.models import Card


def comment_dict(comment: comments.Comment) -> dict:
    return dataclasses.asdict(comment)


def links_of(conn: sqlite3.Connection, entity_id: str) -> dict:
    return {
        "refs": refs.outgoing(conn, entity_id),
        "referenced_by": refs.incoming(conn, entity_id),
    }


def card_detail(conn: sqlite3.Connection, card: Card) -> dict:
    return {
        "id": card.id,
        "kind": "card",
        "title": card.title,
        "description": card.description,
        "status": core.resolve_status(conn, card),
        "parent_id": card.parent_id,
        "created_at": card.created_at,
        "updated_at": card.updated_at,
        "blocked_by": db.list_blockers_of(conn, card.id),
        "children": [child.id for child in db.list_children(conn, card.id)],
        "comments": [comment_dict(c) for c in comments.list_for(conn, card.id)],
        **links_of(conn, card.id),
    }


def detail(conn: sqlite3.Connection, root: Path, entity_id: str) -> dict:
    kind = entities.kind_of(conn, entity_id)
    if kind == "card":
        return card_detail(conn, db.get_card(conn, entity_id))
    raise CardNotFoundError(f"no card, issue, or document with id {entity_id}")
