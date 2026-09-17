import typer

app = typer.Typer(
    name="brd",
    help="Local kanban board for tracking work, no visual UI.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    pass


if __name__ == "__main__":
    app()
