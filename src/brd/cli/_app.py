import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

import typer

from brd import db, master, output, paths
from brd.errors import BrdError
from brd.models import Project

GUIDE = """\
Cards are units of work. There are no Epic/Story/Task types: a card with children \
(`--parent <its-id>`) is a container, not work, so `brd next` skips it and surfaces its leaves.

Issues are bugs, questions, and findings that aren't work yet. An open issue can block a card \
(`brd block <card> --by <issue>`); closing it, for any reason, unblocks the card.

Documents are registered `.md` files that brd backs up. Whenever you edit a registered document, \
run `brd doc update <id>` right after; after moving or renaming one, run \
`brd doc update <id> --path <new>`.

Links: write \\[\\[doc-stem]] or \\[\\[<id>]] in card descriptions, issue bodies, and comments; \
`brd show` lists refs and backlinks.

Comments record progress or decisions on cards and issues. The author is --author, else \
$BRD_AUTHOR, else the OS user; agents should set BRD_AUTHOR to their name.

Board data lives outside the repo (~/.local/share/brd/), keyed to the project's path. \
`brd export > docs/board/snapshot.json` gives a committable snapshot; `brd import <file>` restores it.

Output is JSON by default; add --pretty for human-readable text. \
Run `brd <command> --help` for a command's options."""

app = typer.Typer(
    name="brd",
    help="Local kanban board for tracking work, no visual UI.",
    epilog=GUIDE,
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    pass


def pretty_option():
    return typer.Option(False, "--pretty", "--human", help="Human-readable output.")


@dataclass
class Ctx:
    conn: sqlite3.Connection
    project: Project


def fail(exc: BrdError, pretty: bool) -> NoReturn:
    output.print_result(output.error_envelope(type(exc).__name__, str(exc)), pretty)
    raise typer.Exit(code=1)


def open_project() -> Ctx:
    root = master.resolve_project_root(Path.cwd())
    project = master.registered_project(root)
    conn = db.connect(paths.project_db_path(root))
    try:
        db.migrate_project(conn)
    except BaseException:
        conn.close()
        raise
    return Ctx(conn=conn, project=project)


def run(
    pretty: bool,
    fn: Callable[[Ctx], Any],
    render: Callable[[Ctx, Any], str] | None = None,
) -> None:
    """Open the current project, run fn, and print its result as an envelope
    (or as render's text in --pretty mode). Any BrdError becomes an error
    envelope and exit code 1."""
    try:
        ctx = open_project()
    except BrdError as exc:
        fail(exc, pretty)
    try:
        data = fn(ctx)
        text = render(ctx, data) if pretty and render is not None else None
    except BrdError as exc:
        fail(exc, pretty)
    finally:
        ctx.conn.close()
    if text is not None:
        print(text)
    else:
        output.print_result(output.ok_envelope(data), pretty)
