import typer

from brd import refs
from brd.cli._app import app, pretty_option, run

ref_app = typer.Typer(help="Explicit references between entities.", no_args_is_help=True)
app.add_typer(ref_app, name="ref")


@ref_app.command("add")
def add(
    src_id: str = typer.Argument(..., help="Referencing entity id."),
    dst_id: str = typer.Argument(..., help="Referenced entity id."),
    pretty: bool = pretty_option(),
) -> None:
    """Add an explicit reference."""

    def action(ctx):
        refs.add_explicit(ctx.conn, src_id, dst_id)
        return {"id": src_id, "refs": refs.outgoing(ctx.conn, src_id)}

    run(pretty, action)


@ref_app.command("remove")
def remove(
    src_id: str = typer.Argument(..., help="Referencing entity id."),
    dst_id: str = typer.Argument(..., help="Referenced entity id."),
    pretty: bool = pretty_option(),
) -> None:
    """Remove an explicit reference ([[links]] are managed by editing text)."""

    def action(ctx):
        refs.remove_explicit(ctx.conn, src_id, dst_id)
        return {"id": src_id, "refs": refs.outgoing(ctx.conn, src_id)}

    run(pretty, action)
