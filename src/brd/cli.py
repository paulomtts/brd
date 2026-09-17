import dataclasses
import sqlite3
from pathlib import Path

import typer

from brd import core, db, master, output
from brd.models import Card

app = typer.Typer(
    name="brd",
    help="Local kanban board for tracking work, no visual UI.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    pass


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
    try:
        project = master.init_project(Path.cwd(), name=name)
    except master.ProjectAlreadyExistsError as exc:
        output.print_result(
            output.error_envelope("ProjectAlreadyExistsError", str(exc)), pretty
        )
        raise typer.Exit(code=1)

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


def _project_conn() -> tuple[sqlite3.Connection, master.Project]:
    project = master.resolve_current_project(Path.cwd())
    conn = db.connect(Path(project.db_path))
    return conn, project


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
        conn, _ = _project_conn()
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
        conn, _ = _project_conn()
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
        conn, _ = _project_conn()
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


if __name__ == "__main__":
    app()
