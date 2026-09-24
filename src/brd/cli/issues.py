import typer

from brd import issues, views
from brd.cli._app import app, pretty_option, run

issue_app = typer.Typer(help="Track bugs, questions, and findings.", no_args_is_help=True)
app.add_typer(issue_app, name="issue")


@issue_app.command("open")
def open_cmd(
    title: str = typer.Option(..., "--title", help="Issue title."),
    body: str | None = typer.Option(None, "--body", help="Issue body; may contain [[links]]."),
    ref: list[str] = typer.Option([], "--ref", help="Id of a card/issue/document it references (repeatable)."),
    blocks: list[str] = typer.Option([], "--blocks", help="Id of a card it blocks while open (repeatable)."),
    pretty: bool = pretty_option(),
) -> None:
    """Open an issue."""

    def action(ctx):
        issue = issues.open_issue(ctx.conn, title, body=body, ref_ids=list(ref), blocks=list(blocks))
        return views.issue_detail(ctx.conn, issue)

    run(pretty, action)


@issue_app.command("list")
def list_cmd(
    status: str | None = typer.Option(None, "--status", help="open or closed."),
    pretty: bool = pretty_option(),
) -> None:
    """List issues, oldest first."""
    run(
        pretty,
        lambda ctx: [views.issue_detail(ctx.conn, i) for i in issues.list_issues(ctx.conn, status)],
    )


@issue_app.command("update")
def update(
    issue_id: str = typer.Argument(..., help="Issue id."),
    title: str | None = typer.Option(None, "--title", help="New title."),
    body: str | None = typer.Option(None, "--body", help="New body."),
    pretty: bool = pretty_option(),
) -> None:
    """Edit an issue's title or body."""
    run(
        pretty,
        lambda ctx: views.issue_detail(ctx.conn, issues.update(ctx.conn, issue_id, title=title, body=body)),
    )


@issue_app.command("close")
def close(
    issue_id: str = typer.Argument(..., help="Issue id."),
    reason: str = typer.Option("resolved", "--reason", help="resolved, wontfix, or duplicate."),
    pretty: bool = pretty_option(),
) -> None:
    """Close an issue (unblocks any cards it blocks)."""
    run(pretty, lambda ctx: views.issue_detail(ctx.conn, issues.close(ctx.conn, issue_id, reason)))


@issue_app.command("reopen")
def reopen(
    issue_id: str = typer.Argument(..., help="Issue id."),
    pretty: bool = pretty_option(),
) -> None:
    """Reopen a closed issue."""
    run(pretty, lambda ctx: views.issue_detail(ctx.conn, issues.reopen(ctx.conn, issue_id)))
