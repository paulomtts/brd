import pytest

from brd import db


@pytest.fixture
def pconn(tmp_path):
    connection = db.connect(tmp_path / "project.db")
    db.migrate_project(connection)
    yield connection
    connection.close()
