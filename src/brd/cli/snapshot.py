import json
from pathlib import Path

import typer

from brd import snapshot
from brd.cli._app import app, pretty_option, run
from brd.errors import ImportReadError


@app.command(name="export")
def export_cmd(pretty: bool = pretty_option()) -> None:
    """Print a full JSON snapshot: cards, issues, documents, comments, tags, refs."""
    run(pretty, lambda ctx: snapshot.export(ctx.conn, Path(ctx.project.root_path)))


@app.command(name="import")
def import_cmd(
    file: Path = typer.Argument(
        ..., help="Path to a `brd export` file (or an older `brd tree` snapshot)."
    ),
    pretty: bool = pretty_option(),
) -> None:
    """Restore a board from a snapshot; touches nothing if any id already exists."""

    def action(ctx):
        try:
            raw = json.loads(file.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ImportReadError(f"could not read a JSON snapshot from {file}: {exc}") from exc
        return snapshot.load(ctx.conn, Path(ctx.project.root_path), raw)

    run(pretty, action)
