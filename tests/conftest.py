import os

import pytest

from brd import db
from tests.factories import PROJECT

# GitHub Actions makes typer colour its help even when nobody is looking, and
# the codes split the text the help tests look for. typer reads this when it is
# first imported, so it is set before any test module loads the CLI.
os.environ["_TYPER_FORCE_DISABLE_TERMINAL"] = "1"


@pytest.fixture
def pconn(tmp_path):
    connection = db.connect(tmp_path / "project.db")
    db.migrate_project(connection, PROJECT)
    yield connection
    connection.close()


@pytest.fixture
def project(tmp_path, monkeypatch):
    from tests.cli_helpers import ok

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("BRD_AUTHOR", raising=False)
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    ok("init")
    return repo
