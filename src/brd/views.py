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
        "comments": [comment_dict(c) for c in comments.list_for(conn, issue.id)],
        **links_of(conn, issue.id),
    }


def document_summary(conn: sqlite3.Connection, doc: documents.Document, source_state: str) -> dict:
    return {
        "id": doc.id,
        "kind": "document",
        "title": doc.title,
        "source_path": doc.source_path,
        "source_state": source_state,
        "tags": tags.list_for(conn, doc.id),
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


def detail(conn: sqlite3.Connection, root: Path, entity_id: str) -> dict:
    kind = entities.kind_of(conn, entity_id)
    if kind is None:
        raise CardNotFoundError(f"no card, issue, or document with id {entity_id}")
    # Documents may have been edited on disk; sync them all so backlinks
    # (referenced_by) reflect their current content.
    results = documents.sync_all(conn, root)
    if kind == "document":
        return document_detail(conn, documents.require(conn, entity_id), results[entity_id])
    if kind == "issue":
        return issue_detail(conn, issues.require(conn, entity_id))
    return card_detail(conn, db.get_card(conn, entity_id))
