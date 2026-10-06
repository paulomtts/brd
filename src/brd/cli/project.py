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
    pretty: bool = pretty_option(),
) -> None:
    """Register the current directory as a brd project."""
    project = master.init_project(Path.cwd(), name=name)
    output.print_result(output.ok_envelope(dataclasses.asdict(project)), pretty)


@app.command()
def projects(pretty: bool = pretty_option()) -> None:
    """List all registered projects."""
    all_projects = master.list_all_projects()
    envelope = output.ok_envelope([dataclasses.asdict(p) for p in all_projects])
    output.print_result(envelope, pretty)


@app.command()
def forget(
    path: Path | None = typer.Argument(
        None,
        help="Root path of the project to forget (defaults to the current "
        "directory).",
    ),
    pretty: bool = pretty_option(),
) -> None:
    """Un-register a project and delete its stored data."""
    root_path = path if path is not None else Path.cwd()
    try:
        project = master.forget_project(root_path)
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
