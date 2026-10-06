import dataclasses
import sqlite3
from pathlib import Path

from brd import comments, core, db, documents, entities, issues, refs, tags
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
    # One read, so blocked_by and blockers keep the same order.
    blockers = core.blockers_of(conn, card.id)
    return {
        "id": card.id,
        "kind": "card",
        "title": card.title,
        "description": card.description,
        "status": core.resolve_status(conn, card),
        "parent_id": card.parent_id,
        "created_at": card.created_at,
        "updated_at": card.updated_at,
        "blocked_by": [blocker["id"] for blocker in blockers],
        "blockers": blockers,
        "children": [child.id for child in db.list_children(conn, card.id)],
        "comments": [comment_dict(c) for c in comments.for_entity(conn, card.id)],
        **links_of(conn, card.id),
    }


def issue_detail(conn: sqlite3.Connection, issue: issues.Issue) -> dict:
    return {
        "id": issue.id,
        "kind": "issue",
        "title": issue.title,
        "body": issue.body,
        "status": issue.status,
        "close_reason": issue.close_reason,
        "blocks": issues.blocks_of(conn, issue.id),
        "created_at": issue.created_at,
        "updated_at": issue.updated_at,
        "comments": [comment_dict(c) for c in comments.for_entity(conn, issue.id)],
        **links_of(conn, issue.id),
    }


def document_summary(conn: sqlite3.Connection, doc: documents.Document, source_state: str) -> dict:
    return {
        "id": doc.id,
        "kind": "document",
        "title": doc.title,
        "source_path": doc.source_path,
        "source_state": source_state,
        "tags": tags.for_entity(conn, doc.id),
        "created_at": doc.created_at,
        "updated_at": doc.updated_at,
    }


def document_detail(
    conn: sqlite3.Connection, doc: documents.Document, result: documents.SyncResult
) -> dict:
    return {
        **document_summary(conn, doc, result.source_state),
        "content": result.content,
        **links_of(conn, doc.id),
    }


def detail(conn: sqlite3.Connection, entity_id: str) -> dict:
    kind = entities.kind_of(conn, entity_id)
    if kind is None:
        raise CardNotFoundError(f"no card, issue, or document with id {entity_id}")
    # show is global: any project's entity, labelled with the project owning it.
    owner = db.owner_of(conn, entity_id)
    # Documents may have been edited on disk; sync the owning project's
    # documents against its own root so backlinks (referenced_by) reflect
    # their current content.
    results = documents.sync_all(conn, owner.id, Path(owner.root_path))
    if kind == "document":
        shown = document_detail(
            conn, documents.require(conn, owner.id, entity_id), results[entity_id]
        )
    elif kind == "issue":
        shown = issue_detail(conn, issues.require(conn, owner.id, entity_id))
    else:
        shown = card_detail(conn, db.get_card(conn, entity_id))
    return {**shown, "project": {"id": owner.id, "name": owner.name}}
