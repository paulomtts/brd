import sys

import typer

from brd import comments, views
from brd import pretty as pretty_render
from brd.cli._app import app, pretty_option, run

comment_app = typer.Typer(help="Comment on cards and issues.", no_args_is_help=True)
app.add_typer(comment_app, name="comment")


@comment_app.command("add")
def add(
    entity_id: str = typer.Argument(..., help="Card or issue id."),
    body: str = typer.Argument(..., help='Comment text; "-" reads it from stdin.'),
    author: str | None = typer.Option(
        None, "--author", help="Author name (default: $BRD_AUTHOR, then the OS user)."
    ),
    pretty: bool = pretty_option(),
) -> None:
    """Add a comment."""
    text = sys.stdin.read() if body == "-" else body
    run(
        pretty,
        lambda ctx: views.comment_dict(
            comments.add(
                ctx.conn, ctx.project.id, entity_id, text, comments.resolve_author(author)
            )
        ),
    )


@comment_app.command("list")
def list_cmd(
    entity_id: str = typer.Argument(..., help="Card or issue id."),
    pretty: bool = pretty_option(),
) -> None:
    """List comments, oldest first."""
    run(
        pretty,
        lambda ctx: [
            views.comment_dict(c) for c in comments.list_for(ctx.conn, ctx.project.id, entity_id)
        ],
        render=lambda ctx, data: pretty_render.render_comments(ctx.conn, data),
    )


@comment_app.command("delete")
def delete(
    comment_id: str = typer.Argument(..., help="Comment id."),
    pretty: bool = pretty_option(),
) -> None:
    """Delete a comment."""
    run(
        pretty,
        lambda ctx: views.comment_dict(comments.delete(ctx.conn, ctx.project.id, comment_id)),
    )
