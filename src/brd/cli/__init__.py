from brd.cli._app import app
from brd.cli import project, cards, comments, tags, refs, docs, issues, snapshot  # noqa: E402,F401  (registers commands)

__all__ = ["app"]
