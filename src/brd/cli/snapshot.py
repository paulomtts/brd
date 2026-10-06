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


def _run_global(
    pretty: bool,
    fn: Callable[[sqlite3.Connection], dict],
    render: Callable[[dict], str] = _indented,
) -> None:
    """Like run(), but never resolves the cwd project: for a command that
    works from any directory. --pretty prints render's text."""
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
        print(render(data))
    else:
        output.print_result(output.ok_envelope(data), pretty)


def _import_text(data: dict) -> str:
    lines = []
    for item in data["projects"]:
        project = item["project"]
        line = (
            f"{project['name']} ({project['root_path']}): +{item['cards']} cards, "
            f"+{item['issues']} issues, +{item['documents']} documents, "
            f"+{item['comments']} comments"
        )
        if item["registered"]:
            line += " [registered]"
        lines.append(line)
    lines.append(f"not-found edge targets: {data['not_found_edges']}")
    return "\n".join(lines)


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
    """Restore a snapshot. A one-project snapshot lands in the current project,
    registering the current directory if it is not in one. A multi-project
    snapshot places each entry in the registered project with its id, else
    registers it at its recorded root; it works from any directory. Refuses,
    writing nothing, if a target project already has entities."""

    def action(conn: sqlite3.Connection) -> dict:
        try:
            raw = json.loads(file.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ImportReadError(f"could not read a JSON snapshot from {file}: {exc}") from exc
        return snapshot.load(conn, Path.cwd(), raw)

    _run_global(pretty, action, _import_text)
