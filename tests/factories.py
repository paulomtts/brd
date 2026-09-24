from brd import db
from brd.models import Card

NOW = "2026-09-24T00:00:00+00:00"


def make_card(conn, id_, title=None, description=None, parent_id=None, status="todo"):
    db.insert_card(
        conn, Card(id_, title or id_, description, status, parent_id, NOW, NOW)
    )
    return id_


def make_issue(conn, id_, title=None, body=None, status="open"):
    conn.execute(
        "INSERT INTO issues (id, title, body, status, close_reason, created_at, "
        "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (id_, title or id_, body, status, "resolved" if status == "closed" else None, NOW, NOW),
    )
    conn.commit()
    return id_


def make_document(conn, id_, stem, content="", title=None):
    conn.execute(
        "INSERT INTO documents (id, title, source_path, stem, content_hash, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (id_, title or stem, f"docs/{stem}.md", stem, "0" * 64, NOW, NOW),
    )
    conn.commit()
    backups = db.docs_dir(conn)
    backups.mkdir(parents=True, exist_ok=True)
    (backups / f"{id_}.md").write_text(content)
    return id_
