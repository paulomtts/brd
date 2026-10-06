import sqlite3
from pathlib import Path

import typer

from brd import core, db, documents, entities, output, views
from brd import pretty as pretty_render
from brd.cli._app import app, pretty_option, run
from brd.errors import CardNotFoundError
from brd.models import Card


def _require_card(conn: sqlite3.Connection, card_id: str) -> Card:
    card = db.get_card(conn, card_id)
    if card is None:
        raise CardNotFoundError(f"no card with id {card_id}")
    return card


@app.command()
def add(
    title: str = typer.Option(..., "--title", help="Card title."),
    description: str | None = typer.Option(
        None, "--description", help="Card description."
    ),
    parent: str | None = typer.Option(None, "--parent", help="Parent card id."),
    blocked_by: list[str] = typer.Option(
        [], "--blocked-by", help="Id of a card this one is blocked by (repeatable)."
    ),
    pretty: bool = pretty_option(),
) -> None:
    """Create a card."""

    def action(ctx):
        card = core.create_card(
            ctx.conn,
            ctx.project.id,
            title=title,
            description=description,
            parent_id=parent,
            blocked_by=list(blocked_by),
        )
        return views.card_detail(ctx.conn, card)

    run(pretty, action)


@app.command()
def show(
    entity_id: str = typer.Argument(..., help="Id of the card, issue, or document to show."),
    pretty: bool = pretty_option(),
) -> None:
    """Show a card, issue, or document in full."""
    run(
        pretty,
        lambda ctx: views.detail(ctx.conn, Path(ctx.project.root_path), entity_id),
        render=lambda ctx, data: pretty_render.render_detail(ctx.conn, data),
    )


@app.command(name="list")
def list_cards_cmd(
    status: str | None = typer.Option(None, "--status", help="Filter by stored status."),
    parent: str | None = typer.Option(
        None, "--parent", help="Only cards whose parent is this card id."
    ),
    pretty: bool = pretty_option(),
) -> None:
    """List cards, optionally filtered."""

    def action(ctx):
        # db.list_cards uses an _UNSET sentinel for parent_id, so only pass the
        # kwarg when --parent was given; passing None means "parent IS NULL".
        kwargs: dict = {"status": status}
        if parent is not None:
            kwargs["parent_id"] = parent
        return [views.card_detail(ctx.conn, card) for card in db.list_cards(ctx.conn, **kwargs)]

    run(pretty, action, render=lambda ctx, data: pretty_render.render_list(ctx.conn, data))


@app.command()
def update(
    card_id: str = typer.Argument(..., help="Id of the card to update."),
    title: str | None = typer.Option(None, "--title", help="New title."),
    description: str | None = typer.Option(
        None, "--description", help="New description."
    ),
    status: str | None = typer.Option(
        None,
        "--status",
        help="New stored status: todo, in_progress, done, merged, canceled or "
        "archived (cannot be 'blocked').",
    ),
    parent: str | None = typer.Option(None, "--parent", help="New parent card id."),
    clear_parent: bool = typer.Option(
        False, "--clear-parent", help="Detach the card from its parent."
    ),
    pretty: bool = pretty_option(),
) -> None:
    """Edit a card's fields."""

    def action(ctx):
        parent_arg = core.CLEAR_PARENT if clear_parent else parent
        card = core.update_card(
            ctx.conn,
            ctx.project.id,
            card_id,
            title=title,
            description=description,
            status=status,
            parent_id=parent_arg,
        )
        return views.card_detail(ctx.conn, card)

    run(pretty, action)


def delete_entity(conn: sqlite3.Connection, entity_id: str, cascade: bool) -> list[str]:
    kind = entities.kind_of(conn, entity_id)
    if kind is None:
        raise CardNotFoundError(f"no card, issue, or document with id {entity_id}")
    if kind == "card":
        return core.delete_card(conn, entity_id, cascade=cascade)
    if kind == "document":
        documents.delete(conn, entity_id)
        return [entity_id]
    entities.delete(conn, entity_id)
    return [entity_id]


@app.command()
def delete(
    entity_id: str = typer.Argument(..., help="Id of the card, issue, or document to delete."),
    cascade: bool = typer.Option(
        False, "--cascade", help="Also delete all descendant cards (cards only)."
    ),
    pretty: bool = pretty_option(),
) -> None:
    """Delete a card, issue, or document (a document's source file is kept)."""
    run(pretty, lambda ctx: {"deleted": delete_entity(ctx.conn, entity_id, cascade)})


@app.command()
def block(
    card_id: str = typer.Argument(..., help="Id of the card to block."),
    by: str = typer.Option(..., "--by", help="Id of the card or issue blocking it."),
    pretty: bool = pretty_option(),
) -> None:
    """Mark a card as blocked by another card or an open issue."""

    def action(ctx):
        core.block_card(ctx.conn, card_id, by)
        return views.card_detail(ctx.conn, _require_card(ctx.conn, card_id))

    run(pretty, action)


@app.command()
def unblock(
    card_id: str = typer.Argument(..., help="Id of the card to unblock."),
    by: str = typer.Option(..., "--by", help="Id of the blocker to remove."),
    pretty: bool = pretty_option(),
) -> None:
    """Remove a blocked-by relationship."""

    def action(ctx):
        core.unblock_card(ctx.conn, card_id, by)
        return views.card_detail(ctx.conn, _require_card(ctx.conn, card_id))

    run(pretty, action)


@app.command()
def tree(
    card_id: str | None = typer.Argument(
        None, help="Root the tree at this card id (default: whole board)."
    ),
    pretty: bool = pretty_option(),
) -> None:
    """Print the hierarchy and dependency tree."""
    run(
        pretty,
        lambda ctx: core.build_tree(ctx.conn, root_id=card_id),
        render=lambda ctx, data: output.render_tree_text(data),
    )


@app.command(name="next")
def next_cmd(
    limit: int | None = typer.Option(
        None, "--limit", help="Return at most this many cards."
    ),
    parent: str | None = typer.Option(
        None,
        "--parent",
        help="Ready direct children of this card id, instead of leaf cards "
        "across the whole board.",
    ),
    pretty: bool = pretty_option(),
) -> None:
    """List unblocked todo cards, oldest first."""

    def action(ctx):
        cards = core.next_cards(ctx.conn, limit=limit, parent_id=parent)
        return [views.card_detail(ctx.conn, card) for card in cards]

    run(pretty, action, render=lambda ctx, data: pretty_render.render_list(ctx.conn, data))
