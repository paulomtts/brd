import dataclasses
from pathlib import Path

import typer

from brd import master, output

app = typer.Typer(
    name="brd",
    help="Local kanban board for tracking work, no visual UI.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    pass


@app.command()
def init(
    name: str | None = typer.Option(
        None, "--name", help="Override the default project name."
    ),
    pretty: bool = typer.Option(
        False, "--pretty", "--human", help="Human-readable output."
    ),
) -> None:
    """Register the current directory as a brd project."""
    try:
        project = master.init_project(Path.cwd(), name=name)
    except master.ProjectAlreadyExistsError as exc:
        output.print_result(
            output.error_envelope("ProjectAlreadyExistsError", str(exc)), pretty
        )
        raise typer.Exit(code=1)

    output.print_result(output.ok_envelope(dataclasses.asdict(project)), pretty)


@app.command()
def projects(
    pretty: bool = typer.Option(
        False, "--pretty", "--human", help="Human-readable output."
    ),
) -> None:
    """List all registered projects."""
    all_projects = master.list_all_projects()
    envelope = output.ok_envelope([dataclasses.asdict(p) for p in all_projects])
    output.print_result(envelope, pretty)


if __name__ == "__main__":
    app()
