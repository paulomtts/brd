import json
import sqlite3
from collections.abc import Callable
from pathlib import Path

import typer

from brd import db, master, output, snapshot
from brd.cli._app import app, fail, pretty_option, run
from brd.errors import BrdError, ImportReadError


def _indented(data: dict) -> str:
    return json.dumps(data, indent=2)


def _run_global(pretty: bool, fn: Callable[[sqlite3.Connection], dict]) -> None:
    """Like run(), but never resolves the cwd project: for a command whose
    scope is every project, so it works from any directory."""
    try:
        conn = master.connect()
    except BrdError as exc:
        fail(exc, pretty)
    try:
        data = fn(conn)
    except BrdError as exc:
        fail(exc, pretty)
    finally:
        conn.close()
    if pretty:
        print(_indented(data))
    else:
        output.print_result(output.ok_envelope(data), pretty)


@app.command(name="export")
def export_cmd(
    all_projects: bool = typer.Option(
        False,
        "--all",
        help="Export every registered project, not just the current one; "
        "works from any directory.",
    ),
    pretty: bool = pretty_option(),
) -> None:
    """Print a JSON snapshot: a list of project entries, each with its cards, issues,
    documents, comments, tags and refs. Only the current project unless --all."""
    if all_projects:
        _run_global(pretty, lambda conn: snapshot.export_projects(conn, db.list_projects(conn)))
    else:
        run(
            pretty,
            lambda ctx: snapshot.export_projects(ctx.conn, [ctx.project]),
            lambda ctx, data: _indented(data),
        )


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
        return snapshot.load(ctx.conn, ctx.project.id, Path(ctx.project.root_path), raw)

    run(pretty, action)
