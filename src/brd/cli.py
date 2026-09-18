import dataclasses
import json
import sqlite3
from pathlib import Path

import typer

from brd import core, db, master, output, prompt
from brd.models import Card

app = typer.Typer(
    name="brd",
    help="Local kanban board for tracking work, no visual UI.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    pass


@app.command(name="prompt")
def prompt_cmd() -> None:
    """Print a short CLAUDE.md snippet explaining how to use brd."""
    print(prompt.render(), end="")


@app.command()
def init(
    name: str | None = typer.Option(
        None, "--name", help="Override the default project name."
    ),
    pretty: bool = typer.Option(
        False, "--pretty", "--human", help="Human-readable output."
    ),
) -> None:
    """Register the current directory as a brd project."""
    project = master.init_project(Path.cwd(), name=name)
    output.print_result(output.ok_envelope(dataclasses.asdict(project)), pretty)


@app.command()
def projects(
    pretty: bool = typer.Option(
        False, "--pretty", "--human", help="Human-readable output."
    ),
) -> None:
    """List all registered projects."""
    all_projects = master.list_all_projects()
    envelope = output.ok_envelope([dataclasses.asdict(p) for p in all_projects])
    output.print_result(envelope, pretty)


def _project_conn() -> sqlite3.Connection:
    db_path = master.resolve_project_db(Path.cwd())
    return db.connect(db_path)


def _card_detail(conn: sqlite3.Connection, card: Card) -> dict:
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
    pretty: bool = typer.Option(
        False, "--pretty", "--human", help="Human-readable output."
    ),
) -> None:
    """Create a card."""
    try:
        conn = _project_conn()
    except master.ProjectNotFoundError as exc:
        output.print_result(
            output.error_envelope("ProjectNotFoundError", str(exc)), pretty
        )
        raise typer.Exit(code=1)

    try:
        card = core.create_card(
            conn,
            title=title,
            description=description,
            parent_id=parent,
            blocked_by=list(blocked_by),
        )
        envelope = output.ok_envelope(_card_detail(conn, card))
    except (core.CardNotFoundError, core.CycleError) as exc:
        output.print_result(
            output.error_envelope(type(exc).__name__, str(exc)), pretty
        )
        raise typer.Exit(code=1)
    finally:
        conn.close()

    output.print_result(envelope, pretty)


@app.command()
def show(
    card_id: str = typer.Argument(..., help="Id of the card to show."),
    pretty: bool = typer.Option(
        False, "--pretty", "--human", help="Human-readable output."
    ),
) -> None:
    """Show a single card's full detail."""
    try:
        conn = _project_conn()
    except master.ProjectNotFoundError as exc:
        output.print_result(
            output.error_envelope("ProjectNotFoundError", str(exc)), pretty
        )
        raise typer.Exit(code=1)

    try:
        card = db.get_card(conn, card_id)
        if card is None:
            raise core.CardNotFoundError(f"no card with id {card_id}")
        envelope = output.ok_envelope(_card_detail(conn, card))
    except core.CardNotFoundError as exc:
        output.print_result(
            output.error_envelope("CardNotFoundError", str(exc)), pretty
        )
        raise typer.Exit(code=1)
    finally:
        conn.close()

    output.print_result(envelope, pretty)


@app.command(name="list")
def list_cards_cmd(
    status: str | None = typer.Option(
        None, "--status", help="Filter by stored status."
    ),
    parent: str | None = typer.Option(
        None, "--parent", help="Only cards whose parent is this card id."
    ),
    pretty: bool = typer.Option(
        False, "--pretty", "--human", help="Human-readable output."
    ),
) -> None:
    """List cards, optionally filtered."""
    try:
        conn = _project_conn()
    except master.ProjectNotFoundError as exc:
        output.print_result(
            output.error_envelope("ProjectNotFoundError", str(exc)), pretty
        )
        raise typer.Exit(code=1)

    try:
        # db.list_cards uses an _UNSET sentinel for parent_id, so only pass the
        # kwarg when --parent was given; passing None means "parent IS NULL".
        kwargs: dict = {"status": status}
        if parent is not None:
            kwargs["parent_id"] = parent
        cards = db.list_cards(conn, **kwargs)
        envelope = output.ok_envelope(
            [_card_detail(conn, card) for card in cards]
        )
    finally:
        conn.close()

    output.print_result(envelope, pretty)


@app.command()
def update(
    card_id: str = typer.Argument(..., help="Id of the card to update."),
    title: str | None = typer.Option(None, "--title", help="New title."),
    description: str | None = typer.Option(
        None, "--description", help="New description."
    ),
    status: str | None = typer.Option(
        None, "--status", help="New stored status (cannot be 'blocked')."
    ),
    parent: str | None = typer.Option(None, "--parent", help="New parent card id."),
    clear_parent: bool = typer.Option(
        False, "--clear-parent", help="Detach the card from its parent."
    ),
    pretty: bool = typer.Option(
        False, "--pretty", "--human", help="Human-readable output."
    ),
) -> None:
    """Edit a card's fields."""
    try:
        conn = _project_conn()
    except master.ProjectNotFoundError as exc:
        output.print_result(
            output.error_envelope("ProjectNotFoundError", str(exc)), pretty
        )
        raise typer.Exit(code=1)

    try:
        parent_arg = core.CLEAR_PARENT if clear_parent else parent
        card = core.update_card(
            conn,
            card_id,
            title=title,
            description=description,
            status=status,
            parent_id=parent_arg,
        )
        envelope = output.ok_envelope(_card_detail(conn, card))
    except (core.CardNotFoundError, core.CycleError, core.InvalidStatusError) as exc:
        output.print_result(
            output.error_envelope(type(exc).__name__, str(exc)), pretty
        )
        raise typer.Exit(code=1)
    finally:
        conn.close()

    output.print_result(envelope, pretty)


@app.command()
def block(
    card_id: str = typer.Argument(..., help="Id of the card to block."),
    by: str = typer.Option(..., "--by", help="Id of the card blocking it."),
    pretty: bool = typer.Option(
        False, "--pretty", "--human", help="Human-readable output."
    ),
) -> None:
    """Mark a card as blocked by another card."""
    try:
        conn = _project_conn()
    except master.ProjectNotFoundError as exc:
        output.print_result(
            output.error_envelope("ProjectNotFoundError", str(exc)), pretty
        )
        raise typer.Exit(code=1)

    try:
        core.block_card(conn, card_id, by)
        card = db.get_card(conn, card_id)
        if card is None:
            raise core.CardNotFoundError(f"no card with id {card_id}")
        envelope = output.ok_envelope(_card_detail(conn, card))
    except (core.CardNotFoundError, core.CycleError) as exc:
        output.print_result(
            output.error_envelope(type(exc).__name__, str(exc)), pretty
        )
        raise typer.Exit(code=1)
    finally:
        conn.close()

    output.print_result(envelope, pretty)


@app.command()
def unblock(
    card_id: str = typer.Argument(..., help="Id of the card to unblock."),
    by: str = typer.Option(..., "--by", help="Id of the blocker to remove."),
    pretty: bool = typer.Option(
        False, "--pretty", "--human", help="Human-readable output."
    ),
) -> None:
    """Remove a blocked-by relationship."""
    try:
        conn = _project_conn()
    except master.ProjectNotFoundError as exc:
        output.print_result(
            output.error_envelope("ProjectNotFoundError", str(exc)), pretty
        )
        raise typer.Exit(code=1)

    try:
        core.unblock_card(conn, card_id, by)
        card = db.get_card(conn, card_id)
        if card is None:
            raise core.CardNotFoundError(f"no card with id {card_id}")
        envelope = output.ok_envelope(_card_detail(conn, card))
    except core.CardNotFoundError as exc:
        output.print_result(
            output.error_envelope("CardNotFoundError", str(exc)), pretty
        )
        raise typer.Exit(code=1)
    finally:
        conn.close()

    output.print_result(envelope, pretty)


@app.command()
def tree(
    card_id: str | None = typer.Argument(
        None, help="Root the tree at this card id (default: whole board)."
    ),
    pretty: bool = typer.Option(
        False, "--pretty", "--human", help="Human-readable output."
    ),
) -> None:
    """Print the hierarchy and dependency tree."""
    try:
        conn = _project_conn()
    except master.ProjectNotFoundError as exc:
        output.print_result(
            output.error_envelope("ProjectNotFoundError", str(exc)), pretty
        )
        raise typer.Exit(code=1)

    try:
        envelope = output.ok_envelope(core.build_tree(conn, root_id=card_id))
    except core.CardNotFoundError as exc:
        output.print_result(
            output.error_envelope("CardNotFoundError", str(exc)), pretty
        )
        raise typer.Exit(code=1)
    finally:
        conn.close()

    if pretty:
        print(output.render_tree_text(envelope["data"]))
    else:
        output.print_result(envelope, pretty)


@app.command(name="import")
def import_cmd(
    file: Path = typer.Argument(
        ..., help="Path to a JSON file in `brd tree`'s output shape."
    ),
    pretty: bool = typer.Option(
        False, "--pretty", "--human", help="Human-readable output."
    ),
) -> None:
    """Restore cards from a brd tree JSON snapshot."""
    try:
        conn = _project_conn()
    except master.ProjectNotFoundError as exc:
        output.print_result(
            output.error_envelope("ProjectNotFoundError", str(exc)), pretty
        )
        raise typer.Exit(code=1)

    try:
        try:
            raw = json.loads(file.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            output.print_result(
                output.error_envelope(
                    "ImportReadError", f"could not read a JSON snapshot from {file}: {exc}"
                ),
                pretty,
            )
            raise typer.Exit(code=1)

        nodes = raw["data"] if isinstance(raw, dict) and "data" in raw else raw
        count = core.import_tree(conn, nodes)
        envelope = output.ok_envelope({"imported": count})
    except core.CardAlreadyExistsError as exc:
        output.print_result(
            output.error_envelope(type(exc).__name__, str(exc)), pretty
        )
        raise typer.Exit(code=1)
    finally:
        conn.close()

    output.print_result(envelope, pretty)


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
    pretty: bool = typer.Option(
        False, "--pretty", "--human", help="Human-readable output."
    ),
) -> None:
    """List unblocked todo cards, oldest first."""
    try:
        conn = _project_conn()
    except master.ProjectNotFoundError as exc:
        output.print_result(
            output.error_envelope("ProjectNotFoundError", str(exc)), pretty
        )
        raise typer.Exit(code=1)

    try:
        cards = core.next_cards(conn, limit=limit, parent_id=parent)
        envelope = output.ok_envelope([_card_detail(conn, card) for card in cards])
    except core.CardNotFoundError as exc:
        output.print_result(
            output.error_envelope("CardNotFoundError", str(exc)), pretty
        )
        raise typer.Exit(code=1)
    finally:
        conn.close()

    output.print_result(envelope, pretty)


if __name__ == "__main__":
    app()
