import dataclasses
from pathlib import Path

import typer

from brd import master, output, prompt
from brd.cli._app import app, fail, pretty_option
from brd.errors import BrdError


@app.command(name="prompt")
def prompt_cmd() -> None:
    """Print a short CLAUDE.md snippet explaining how to use brd."""
    print(prompt.render(), end="")


@app.command()
def init(
    name: str | None = typer.Option(
        None, "--name", help="Override the default project name."
    ),
    relink: str | None = typer.Option(
        None,
        "--relink",
        metavar="OLD-ROOT-OR-ID",
        help="Point an existing project (by id or old root path) at the current "
        "directory instead of registering a new one, e.g. after moving the repo.",
    ),
    pretty: bool = pretty_option(),
) -> None:
    """Register the current directory as a brd project."""
    try:
        if relink is not None:
            project = master.relink_project(Path.cwd(), relink, name=name)
        else:
            project = master.init_project(Path.cwd(), name=name)
    except BrdError as exc:
        fail(exc, pretty)
    output.print_result(output.ok_envelope(dataclasses.asdict(project)), pretty)


@app.command()
def projects(pretty: bool = pretty_option()) -> None:
    """List all registered projects."""
    try:
        all_projects = master.list_all_projects()
    except BrdError as exc:
        fail(exc, pretty)
    envelope = output.ok_envelope([dataclasses.asdict(p) for p in all_projects])
    output.print_result(envelope, pretty)


@app.command()
def forget(
    path: Path | None = typer.Argument(
        None,
        help="Root path of the project to forget, matched exactly (defaults to "
        "the project the current directory belongs to).",
    ),
    project_id: str | None = typer.Option(
        None,
        "--project",
        help="Id of the project to forget (see `brd projects`), e.g. one whose "
        "directory is gone.",
    ),
    pretty: bool = pretty_option(),
) -> None:
    """Un-register a project and delete its stored data. Forgets the current
    project unless a path or --project is given."""
    if path is not None and project_id is not None:
        output.print_result(
            output.error_envelope(
                "UsageError", "give either a path or --project, not both"
            ),
            pretty,
        )
        raise typer.Exit(code=1)
    try:
        if project_id is not None:
            project = master.forget_project_by_id(project_id)
        elif path is not None:
            project = master.forget_project(path)
        else:
            project = master.forget_current_project(Path.cwd())
    except BrdError as exc:
        fail(exc, pretty)
    output.print_result(output.ok_envelope(dataclasses.asdict(project)), pretty)


@app.command()
def purge(
    yes: bool = typer.Option(False, "--yes", help="Skip the confirmation prompt."),
    pretty: bool = pretty_option(),
) -> None:
    """Delete ALL brd data for every project. Cannot be undone."""
    # Never migrates: purge must work when a migration aborts.
    count = master.registry_count()
    if not yes:
        confirmed = typer.confirm(
            f"Delete all brd data for {count} project(s)? "
            "This cannot be undone."
        )
        if not confirmed:
            output.print_result(
                output.error_envelope("Aborted", "Purge cancelled."), pretty
            )
            raise typer.Exit(code=1)

    removed = master.purge_all()
    output.print_result(output.ok_envelope({"projects_removed": removed}), pretty)
