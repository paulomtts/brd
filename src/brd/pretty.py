import sqlite3

from brd import db, entities, links, refs


def text(conn: sqlite3.Connection, project_id: str | None, value: str | None) -> str:
    def display(token: links.LinkToken) -> str | None:
        dst = refs.resolve(conn, project_id, token.target)
        return entities.title_of(conn, dst) if dst else None

    return links.render(value, display)


def _stamp(iso: str) -> str:
    return iso[:16].replace("T", " ")


def _ref_line(label: str, items: list[dict]) -> str | None:
    seen: dict[str, dict] = {}
    for item in items:
        seen.setdefault(item["id"], item)
    if not seen:
        return None
    return f"{label}: " + ", ".join(f"{i['title']} ({i['kind']})" for i in seen.values())


def _blocker(conn: sqlite3.Connection, blocker_id: str) -> str:
    kind = entities.kind_of(conn, blocker_id)
    title = entities.title_of(conn, blocker_id)
    if kind == "issue":
        status = conn.execute("SELECT status FROM issues WHERE id = ?", (blocker_id,)).fetchone()
        return f"[[{title}]] (issue, {status['status']})"
    return f"[[{title}]] (card)"


def _owner_id(conn: sqlite3.Connection, entity_id: str) -> str | None:
    # Render stems against the project owning the text, as reindex resolves them.
    owner = db.owner_of(conn, entity_id)
    return owner.id if owner else None


def _comment_lines(conn: sqlite3.Connection, items: list[dict]) -> list[str]:
    lines = []
    for comment in items:
        lines.append(f"{comment['author']} · {_stamp(comment['created_at'])}")
        body = text(conn, _owner_id(conn, comment["entity_id"]), comment["body"])
        lines.extend(f"  {line}" for line in body.splitlines())
    return lines


def render_detail(conn: sqlite3.Connection, data: dict) -> str:
    kind = data["kind"]
    extra: list[str | None] = []
    if kind == "card":
        header = f"{data['title']}  [{data['status']}]  ({data['id']})"
        if data["blocked_by"]:
            extra.append("blocked by: " + ", ".join(_blocker(conn, b) for b in data["blocked_by"]))
        body = data["description"]
    elif kind == "issue":
        status = data["status"] + (f": {data['close_reason']}" if data["close_reason"] else "")
        header = f"{data['title']}  [{status}]  ({data['id']})"
        if data["blocks"]:
            extra.append("blocks: " + ", ".join(f"[[{entities.title_of(conn, c)}]]" for c in data["blocks"]))
        body = data["body"]
    else:
        header = f"{data['title']}  [{data['source_state']}]  ({data['id']})"
        extra.append(f"path: {data['source_path']}")
        if data["tags"]:
            extra.append("tags: " + " ".join(f"#{t}" for t in data["tags"]))
        body = data["content"]

    parts = [header, *[line for line in extra if line]]
    if body:
        parts += ["", text(conn, _owner_id(conn, data["id"]), body)]
    ref_lines = [
        line
        for line in (
            _ref_line("refs", data["refs"]),
            _ref_line("referenced by", data["referenced_by"]),
        )
        if line
    ]
    if ref_lines:
        parts += ["", *ref_lines]
    if data.get("comments"):
        parts += ["", "── comments ──", *_comment_lines(conn, data["comments"])]
    return "\n".join(parts)


def _list_line(item: dict) -> str:
    if item.get("kind") == "document":
        line = f"{item['id']}  [{item['source_state']}]  {item['title']}  ({item['source_path']})"
        if item["tags"]:
            line += "  " + " ".join(f"#{t}" for t in item["tags"])
        return line
    return f"{item['id']}  [{item['status']}]  {item['title']}"


def render_list(conn: sqlite3.Connection, items: list[dict]) -> str:
    return "\n".join(_list_line(item) for item in items)


def render_comments(conn: sqlite3.Connection, items: list[dict]) -> str:
    return "\n".join(_comment_lines(conn, items))
