# Hacking on brd

Dev loop: `uv sync`, then `uv run pytest` to run the test suite.

Project layout: the CLI package lives under `src/brd/` (`cli.py`, `core.py`,
`db.py`, `master.py`, `models.py`, `output.py`, `paths.py`), with tests
mirrored under `tests/`.
