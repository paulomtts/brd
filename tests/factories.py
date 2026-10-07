from brd import db
from brd.models import Card, Project

NOW = "2026-09-24T00:00:00+00:00"

PROJECT = Project(
    id="11111111-1111-4111-8111-111111111111",
    name="test",
    root_path="/test",
    created_at=NOW,
)
OTHER_PROJECT = Project(
    id="22222222-2222-4222-8222-222222222222",
    name="other",
    root_path="/other",
    created_at=NOW,
)


def add_project(conn, project):
    """A second projects row in one board file: no command reaches this
    before story S3, so multi-project tests insert it directly."""
    conn.execute(
        "INSERT INTO projects (id, name, root_path, created_at) VALUES (?, ?, ?, ?)",
        (project.id, project.name, project.root_path, project.created_at),
    )
    conn.commit()
    return project.id


def make_card(
    conn, id_, title=None, description=None, parent_id=None, status="todo", project_id=PROJECT.id
):
    db.insert_card(
        conn, project_id, Card(id_, title or id_, description, status, parent_id, NOW, NOW)
    )
    return id_


def make_issue(conn, id_, title=None, body=None, status="open", project_id=PROJECT.id):
    with conn:
        db.insert_entity(conn, project_id, id_, "issue")
        conn.execute(
            "INSERT INTO issues (id, title, body, status, close_reason, created_at, "
            "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (id_, title or id_, body, status, "resolved" if status == "closed" else None, NOW, NOW),
        )
    return id_


def make_document(conn, id_, stem, content="", title=None, project_id=PROJECT.id):
    with conn:
        db.insert_entity(conn, project_id, id_, "document")
        conn.execute(
            "INSERT INTO documents (id, project_id, title, source_path, stem, content_hash, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (id_, project_id, title or stem, f"docs/{stem}.md", stem, "0" * 64, NOW, NOW),
        )
    backups = db.docs_dir(conn)
    backups.mkdir(parents=True, exist_ok=True)
    (backups / f"{id_}.md").write_text(content)
    return id_
