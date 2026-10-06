from pathlib import Path

import typer

from brd import documents, tags, views
from brd import pretty as pretty_render
from brd.cli._app import app, pretty_option, run

doc_app = typer.Typer(help="Register and track markdown documents.", no_args_is_help=True)
app.add_typer(doc_app, name="doc")


@doc_app.command("add")
def add(
    path: Path = typer.Argument(..., help="Path to a .md file inside the project."),
    title: str | None = typer.Option(None, "--title", help="Title (default: filename stem)."),
    tag_list: list[str] = typer.Option([], "--tag", help="Tag (repeatable)."),
    pretty: bool = pretty_option(),
) -> None:
    """Register a markdown file as a document; brd keeps a backup of it."""

    def action(ctx):
        doc = documents.add(
            ctx.conn, Path(ctx.project.root_path), path, title=title, tag_list=list(tag_list)
        )
        return views.document_summary(ctx.conn, doc, "ok")

    run(pretty, action)


@doc_app.command("list")
def list_cmd(
    tag_list: list[str] = typer.Option([], "--tag", help="Only documents with this tag (repeatable: all must match)."),
    missing: bool = typer.Option(False, "--missing", help="Only documents whose source file is gone."),
    pretty: bool = pretty_option(),
) -> None:
    """List documents, syncing each backup first."""

    def action(ctx):
        wanted = [tags.normalize(tag) for tag in tag_list]
        results = documents.sync_all(ctx.conn, Path(ctx.project.root_path))
        items = []
        for doc in documents.list_all(ctx.conn):
            state = results[doc.id].source_state
            if missing and state not in ("missing", "lost"):
                continue
            summary = views.document_summary(ctx.conn, doc, state)
            if all(tag in summary["tags"] for tag in wanted):
                items.append(summary)
        return items

    run(pretty, action, render=lambda ctx, data: pretty_render.render_list(ctx.conn, data))


@doc_app.command("update")
def update(
    doc_id: str = typer.Argument(..., help="Document id."),
    path: Path | None = typer.Option(None, "--path", help="Record a move/rename to this path."),
    title: str | None = typer.Option(None, "--title", help="New title."),
    pretty: bool = pretty_option(),
) -> None:
    """Sync brd's backup after editing a document (run this after every edit)."""

    def action(ctx):
        doc, result = documents.update(
            ctx.conn, Path(ctx.project.root_path), doc_id, new_path=path, title=title
        )
        return views.document_summary(ctx.conn, doc, result.source_state)

    run(pretty, action)


@doc_app.command("restore")
def restore(
    doc_id: str = typer.Argument(..., help="Document id."),
    force: bool = typer.Option(False, "--force", help="Overwrite a source file that differs."),
    pretty: bool = pretty_option(),
) -> None:
    """Write brd's backup back to the document's source path."""

    def action(ctx):
        doc = documents.restore(ctx.conn, Path(ctx.project.root_path), doc_id, force=force)
        return views.document_summary(ctx.conn, doc, "ok")

    run(pretty, action)
