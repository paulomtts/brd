import sqlite3
import uuid
from datetime import datetime, timezone

from brd import db, entities, refs
from brd.models import Card
from brd.errors import (  # noqa: F401  (re-exported for existing callers)
    CardAlreadyExistsError,
    CardHasChildrenError,
    CardNotFoundError,
    CycleError,
    ImportFormatError,
    InvalidBlockerError,
    InvalidStatusError,
)


# A blocker in one of these statuses no longer holds its dependents back:
# finished work (done, merged), abandoned work (canceled) and set-aside work
# (archived) all release them.
_RELEASING_STATUSES = frozenset({"done", "merged", "canceled", "archived"})


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
            # Issues block while open, whatever reason they are later closed with.
            issue = conn.execute(
                "SELECT status FROM issues WHERE id = ?", (blocker_id,)
            ).fetchone()
            if issue is not None and issue["status"] == "open":
                return "blocked"
            continue
        if not _is_released(conn, blocker, seen):
            return "blocked"

    if card.parent_id is not None:
        parent = db.get_card(conn, card.parent_id)
        if parent is not None and resolve_status(conn, parent, seen) == "blocked":
            return "blocked"

    return "todo"


def _is_released(conn: sqlite3.Connection, card: Card, seen: set[str]) -> bool:
    # A card stops holding its dependents once it resolves to a releasing
    # status, or once it has children and every one of them is released.
    # Its own status is left alone either way.
    if resolve_status(conn, card, seen) in _RELEASING_STATUSES:
        return True
    if card.id in seen:
        # Already on this resolution path (a loop through blocked_by or
        # containment): fail closed rather than recurse forever.
        return False
    children = db.list_children(conn, card.id)
    seen = seen | {card.id}
    return bool(children) and all(_is_released(conn, child, seen) for child in children)


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


CLEAR_PARENT = object()  # sentinel: "explicitly set parent_id to None"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_card(conn: sqlite3.Connection, card_id: str) -> Card:
    card = db.get_card(conn, card_id)
    if card is None:
        raise CardNotFoundError(f"no card with id {card_id}")
    return card


def _require_blocker(conn: sqlite3.Connection, blocker_id: str) -> None:
    kind = entities.kind_of(conn, blocker_id)
    if kind is None:
        raise CardNotFoundError(f"no card or issue with id {blocker_id}")
    if kind not in entities.BLOCKERS:
        raise InvalidBlockerError(f"a {kind} can't block a card; only cards and issues can")


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
        _require_blocker(conn, blocker_id)

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

    if description:
        refs.reindex(conn, card.id)

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
        if status not in db.CARD_STATUSES:
            raise InvalidStatusError(
                f"invalid card status {status!r}; use one of {', '.join(db.CARD_STATUSES)}"
            )
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
        if description is not None:
            refs.reindex(conn, card_id)

    return _require_card(conn, card_id)


def block_card(conn: sqlite3.Connection, card_id: str, blocker_id: str) -> None:
    _require_card(conn, card_id)
    _require_blocker(conn, blocker_id)
    if would_create_block_cycle(conn, card_id, blocker_id):
        raise CycleError(f"blocking {card_id} on {blocker_id} would create a cycle")
    db.add_blocked_by_edge(conn, card_id, blocker_id)


def unblock_card(conn: sqlite3.Connection, card_id: str, blocker_id: str) -> None:
    _require_card(conn, card_id)
    db.remove_blocked_by_edge(conn, card_id, blocker_id)


def delete_card(conn: sqlite3.Connection, card_id: str, cascade: bool = False) -> list[str]:
    _require_card(conn, card_id)

    children = db.list_children(conn, card_id)
    if children and not cascade:
        raise CardHasChildrenError(
            f"card {card_id} has children; use --cascade to delete them too"
        )

    deleted: list[str] = []
    for child in children:
        deleted.extend(delete_card(conn, child.id, cascade=True))

    db.delete_card(conn, card_id)
    deleted.append(card_id)
    return deleted


def next_cards(
    conn: sqlite3.Connection, limit: int | None = None, parent_id: str | None = None
) -> list[Card]:
    if parent_id is not None:
        _require_card(conn, parent_id)
        candidates = db.list_children(conn, parent_id)
        ready = [card for card in candidates if resolve_status(conn, card) == "todo"]
    else:
        todo_cards = db.list_cards(conn, status="todo")
        ready = [
            card
            for card in todo_cards
            if resolve_status(conn, card) == "todo"
            and not db.list_children(conn, card.id)
        ]
    return ready[:limit] if limit is not None else ready


def _build_node(conn: sqlite3.Connection, card: Card) -> dict:
    return {
        "id": card.id,
        "title": card.title,
        "description": card.description,
        "status": resolve_status(conn, card),
        "blocked_by": db.list_blockers_of(conn, card.id),
        "created_at": card.created_at,
        "updated_at": card.updated_at,
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


def _flatten_tree(
    nodes: list[dict], parent_id: str | None = None
) -> list[tuple[dict, str | None]]:
    flattened: list[tuple[dict, str | None]] = []
    for node in nodes:
        flattened.append((node, parent_id))
        flattened.extend(_flatten_tree(node.get("children", []), node["id"]))
    return flattened


def import_tree(conn: sqlite3.Connection, nodes: list[dict]) -> int:
    """Restore cards from a brd tree JSON snapshot (build_tree's own output
    shape). Preserves original ids, descriptions, and timestamps. Fails
    before creating anything if any id already exists in this board."""
    flattened = _flatten_tree(nodes)

    for node, _ in flattened:
        if entities.kind_of(conn, node["id"]) is not None:
            raise CardAlreadyExistsError(
                f"card {node['id']} already exists in this board"
            )

    try:
        with conn:  # one transaction: all cards and edges, or nothing
            for node, parent_id in flattened:
                status = "todo" if node["status"] == "blocked" else node["status"]
                conn.execute(
                    "INSERT INTO cards (id, title, description, status, parent_id, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (node["id"], node["title"], node.get("description"), status,
                     parent_id, node["created_at"], node["updated_at"]),
                )
            for node, _ in flattened:
                for blocker_id in node.get("blocked_by", []):
                    conn.execute(
                        "INSERT INTO blocked_by (card_id, blocks_on_id) VALUES (?, ?)",
                        (node["id"], blocker_id),
                    )
    except sqlite3.IntegrityError as exc:
        raise ImportFormatError(
            "snapshot references a blocker or parent id that isn't in the snapshot, "
            f"or is otherwise inconsistent: {exc}"
        ) from exc

    for node, _ in flattened:
        refs.reindex(conn, node["id"])

    return len(flattened)
