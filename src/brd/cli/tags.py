import typer

from brd import tags
from brd.cli._app import app, pretty_option, run

tag_app = typer.Typer(help="Tag documents.", no_args_is_help=True)
app.add_typer(tag_app, name="tag")


@tag_app.command("add")
def add(
    entity_id: str = typer.Argument(..., help="Document id."),
    tag_list: list[str] = typer.Argument(..., metavar="TAG...", help="Tags to add."),
    pretty: bool = pretty_option(),
) -> None:
    """Add tags."""
    run(
        pretty,
        lambda ctx: {
            "id": entity_id,
            "tags": tags.add(ctx.conn, ctx.project.id, entity_id, tag_list),
        },
    )


@tag_app.command("remove")
def remove(
    entity_id: str = typer.Argument(..., help="Document id."),
    tag_list: list[str] = typer.Argument(..., metavar="TAG...", help="Tags to remove."),
    pretty: bool = pretty_option(),
) -> None:
    """Remove tags."""
    run(
        pretty,
        lambda ctx: {
            "id": entity_id,
            "tags": tags.remove(ctx.conn, ctx.project.id, entity_id, tag_list),
        },
    )


@tag_app.command("list")
def list_cmd(
    entity_id: str | None = typer.Argument(None, help="Only this entity's tags."),
    pretty: bool = pretty_option(),
) -> None:
    """List one entity's tags, or every tag in the project with counts."""

    def action(ctx):
        if entity_id is None:
            return tags.counts(ctx.conn, ctx.project.id)
        return {"id": entity_id, "tags": tags.list_for(ctx.conn, ctx.project.id, entity_id)}

    run(pretty, action)
