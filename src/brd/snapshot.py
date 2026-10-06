import dataclasses
import sqlite3
from pathlib import Path, PurePosixPath

from brd import core, db, documents, entities, issues, master, refs
from brd.errors import (
    EntityAlreadyExistsError,
    ImportFormatError,
    ProjectAlreadyExistsError,
    ProjectNotEmptyError,
    ProjectNotFoundError,
    ProjectRootNotFoundError,
)
from brd.models import Project

FORMAT_VERSION = 2
V1_FORMAT_VERSION = 1
ENTRY_BODY_KEYS = ("cards", "issues", "documents", "comments", "tags", "refs")
PROJECT_KEYS = ("id", "name", "root_path", "created_at")
COUNT_KEYS = ("imported", "cards", "issues", "documents", "comments")


def export_projects(conn: sqlite3.Connection, projects: list[Project]) -> dict:
    """The v2 snapshot: one entry per project, in the order given."""
    return {
        "brd_export": FORMAT_VERSION,
        "projects": [export_project(conn, project) for project in projects],
    }


def export_project(conn: sqlite3.Connection, project: Project) -> dict:
    """One project's entry: its row plus today's v1 body, edges as stored."""
    project_id = project.id
    results = documents.sync_all(conn, project_id, Path(project.root_path))
    return {
        "project": dataclasses.asdict(project),
        "cards": core.build_tree(conn, project_id, with_blockers=False),
        "issues": [dataclasses.asdict(i) for i in issues.list_issues(conn, project_id)],
        "documents": [
            {
                "id": d.id,
                "title": d.title,
                "source_path": d.source_path,
                "content": results[d.id].content,
                "content_hash": d.content_hash,
                "created_at": d.created_at,
                "updated_at": d.updated_at,
            }
            for d in documents.list_all(conn, project_id)
        ],
        "comments": [
            dict(row)
            for row in conn.execute(
                "SELECT comments.id, comments.entity_id, comments.author, comments.body, "
                f"comments.created_at FROM comments {db.in_project('comments.entity_id')} "
                "ORDER BY comments.created_at, comments.rowid",
                (project_id,),
            )
        ],
        "tags": [
            dict(row)
            for row in conn.execute(
                f"SELECT tags.entity_id, tags.tag FROM tags {db.in_project('tags.entity_id')} "
                "ORDER BY tags.entity_id, tags.tag",
                (project_id,),
            )
        ],
        "refs": [
            dict(row)
            # Scoped by source only: edges are exported as stored, so a ref
            # to another project's entity stays.
            for row in conn.execute(
                "SELECT refs.src_id, refs.dst_id, refs.origin FROM refs "
                f"{db.in_project('refs.src_id')} WHERE refs.origin = 'explicit' "
                "ORDER BY refs.src_id, refs.dst_id",
                (project_id,),
            )
        ],
    }


@dataclasses.dataclass
class _Entry:
    """One project's part of a snapshot, whatever format it came in. A v1
    export or a `brd tree` list has no recorded project."""

    project: dict | None
    cards: list[tuple[dict, str | None]]  # flattened (node, parent id), parents first
    issues: list[dict]
    documents: list[dict]
    comments: list[dict]
    tags: list[dict]
    refs: list[dict]

    def entity_ids(self) -> list[str]:
        return (
            [node["id"] for node, _ in self.cards]
            + [i["id"] for i in self.issues]
            + [d["id"] for d in self.documents]
        )

    def explicit_refs(self) -> list[dict]:
        return [r for r in self.refs if r.get("origin", "explicit") == "explicit"]

    def edge_targets(self) -> list[str]:
        """Every imported edge's target: blocked_by rows, then explicit refs."""
        return [
            blocker_id for node, _ in self.cards for blocker_id in node.get("blocked_by", [])
        ] + [r["dst_id"] for r in self.explicit_refs()]

    def counts(self) -> dict:
        return {
            "imported": len(self.entity_ids()),
            "cards": len(self.cards),
            "issues": len(self.issues),
            "documents": len(self.documents),
            "comments": len(self.comments),
        }


@dataclasses.dataclass
class _Target:
    """Where an entry lands: a registered project, or one this import registers."""

    project: Project
    registered: bool


def load(conn: sqlite3.Connection, cwd: Path, raw) -> dict:
    """Import a snapshot: place each entry in its project (registering
    projects where needed), check the whole file, then write it in one
    transaction. cwd matters only for a one-entry snapshot."""
    try:
        return _load(conn, cwd, raw)
    except (KeyError, TypeError, AttributeError, sqlite3.ProgrammingError) as exc:
        # Missing keys or wrong value types in the snapshot. Any backups the
        # import wrote were already cleaned up by the time this is caught.
        raise ImportFormatError(f"malformed snapshot: {type(exc).__name__}: {exc}") from exc


def _load(conn: sqlite3.Connection, cwd: Path, raw) -> dict:
    entries = _entries(raw)
    targets = _place(conn, cwd, entries)
    _require_empty(conn, targets)
    _validate(conn, entries, targets)
    _write(conn, entries, targets)
    # After commit, so [[stem]] and [[uuid]] links resolve against the whole import.
    for entry in entries:
        for entity_id in entry.entity_ids():
            refs.reindex(conn, entity_id)
    return _report(conn, entries, targets)


def _entries(raw) -> list[_Entry]:
    """The snapshot as a list of entries: v2 has one per project; a v1
    export or a `brd tree` list is one entry with no recorded project."""
    # `brd export > file` writes the whole envelope; accept it unwrapped too.
    if isinstance(raw, dict) and isinstance(raw.get("data"), dict):
        raw = raw["data"]
    if isinstance(raw, dict) and "brd_export" in raw:
        if raw["brd_export"] == FORMAT_VERSION:
            return _v2_entries(raw)
        if raw["brd_export"] != V1_FORMAT_VERSION:
            raise ImportFormatError(f"unsupported brd_export version {raw['brd_export']!r}")
        return [_entry(None, raw)]
    nodes = raw["data"] if isinstance(raw, dict) and "data" in raw else raw
    if not isinstance(nodes, list):
        raise ImportFormatError("expected a `brd export` object or a `brd tree` snapshot list")
    # Tree nodes carry a derived `blockers` key; nothing below reads it.
    return [_entry(None, {"cards": nodes})]


def _entry(project: dict | None, body: dict) -> _Entry:
    return _Entry(
        project=project,
        cards=core._flatten_tree(body.get("cards", [])),
        issues=body.get("issues", []),
        documents=body.get("documents", []),
        comments=body.get("comments", []),
        tags=body.get("tags", []),
        refs=body.get("refs", []),
    )


def _v2_entries(snap: dict) -> list[_Entry]:
    items = snap.get("projects")
    if not isinstance(items, list):
        raise ImportFormatError(
            f"malformed snapshot: `projects` must be a list, got {type(items).__name__}"
        )
    entries = [_v2_entry(item) for item in items]
    if not entries:
        raise ImportFormatError("snapshot has no project entries")
    for key in ("id", "root_path"):
        seen: set[str] = set()
        for entry in entries:
            value = entry.project[key]
            if value in seen:
                raise ImportFormatError(f"snapshot has two project entries with {key} {value}")
            seen.add(value)
    return entries


def _v2_entry(item) -> _Entry:
    if not isinstance(item, dict) or not all(key in item for key in ("project", *ENTRY_BODY_KEYS)):
        raise ImportFormatError(
            "malformed snapshot: a project entry must be an object with project, "
            + ", ".join(ENTRY_BODY_KEYS)
        )
    project = item["project"]
    if not isinstance(project, dict) or not all(
        isinstance(project.get(key), str) for key in PROJECT_KEYS
    ):
        raise ImportFormatError(
            "malformed snapshot: an entry's project must be an object with string "
            + ", ".join(PROJECT_KEYS)
        )
    return _entry(project, item)


def _place(conn: sqlite3.Connection, cwd: Path, entries: list[_Entry]) -> list[_Target]:
    if len(entries) == 1:
        return [_place_in_cwd(conn, cwd, entries[0].project)]
    return _place_by_record(conn, [entry.project for entry in entries])


def _place_in_cwd(conn: sqlite3.Connection, cwd: Path, recorded: dict | None) -> _Target:
    """A one-entry snapshot lands in the cwd project, whatever it records.
    Outside one, the cwd is registered as `brd init` would, keeping the
    recorded id when no project has it."""
    try:
        return _Target(master.resolve_project(conn, cwd), registered=False)
    except ProjectNotFoundError:
        pass
    if recorded is None:
        project = Project(
            id=db.new_project_id(), name=cwd.name, root_path=str(cwd), created_at=core._now()
        )
        return _Target(project, registered=True)
    project_id = recorded["id"]
    if db.get_project_by_id(conn, project_id) is not None:
        project_id = db.new_project_id()
    project = Project(
        id=project_id,
        name=recorded["name"],
        root_path=str(cwd),
        created_at=recorded["created_at"],
    )
    return _Target(project, registered=True)


def _place_by_record(conn: sqlite3.Connection, recorded: list[dict]) -> list[_Target]:
    """A multi-entry snapshot ignores the cwd: each entry goes to the project
    with its id, else to a new project at its recorded root. A root held by
    another id refuses at once; otherwise every missing root is listed."""
    targets: list[_Target] = []
    missing: list[dict] = []
    for project in recorded:
        existing = db.get_project_by_id(conn, project["id"])
        if existing is not None:
            targets.append(_Target(existing, registered=False))
            continue
        holder = db.get_project(conn, project["root_path"])
        if holder is not None:
            raise ProjectAlreadyExistsError(
                f"{project['root_path']} is already the root of project {holder.name} "
                f"({holder.id}), not of the snapshot's {project['name']} ({project['id']}); "
                "import that entry alone from its directory"
            )
        root = Path(project["root_path"])
        if not (root.is_absolute() and root.is_dir()):
            missing.append(project)
            continue
        new = Project(**{key: project[key] for key in PROJECT_KEYS})
        targets.append(_Target(new, registered=True))
    if missing:
        raise ProjectRootNotFoundError(
            "no directory at the recorded root of "
            + ", ".join(f"{p['name']} ({p['root_path']})" for p in missing)
            + "; create those directories, or import each entry alone from its directory"
        )
    return targets


def _require_empty(conn: sqlite3.Connection, targets: list[_Target]) -> None:
    """A registered target that already owns entities is refused: replacing
    its contents is not supported yet. New targets are empty."""
    busy = []
    for target in targets:
        if target.registered:
            continue
        counts = {
            row["kind"]: row["n"]
            for row in conn.execute(
                "SELECT kind, COUNT(*) AS n FROM entities WHERE project_id = ? GROUP BY kind",
                (target.project.id,),
            )
        }
        if counts:
            project = target.project
            busy.append(
                f"{project.name} ({project.id}) has {counts.get('card', 0)} cards, "
                f"{counts.get('issue', 0)} issues and {counts.get('document', 0)} documents"
            )
    if busy:
        raise ProjectNotEmptyError(
            "target project already has entities: "
            + "; ".join(busy)
            + "; replacing a project's contents is not supported yet"
        )


def _check_source_path(source_path) -> None:
    """A snapshot's source_path must stay inside the project: `doc restore`
    writes to it and sync/export read from it."""
    if not isinstance(source_path, str):
        raise ImportFormatError(f"document source_path must be a string, got {source_path!r}")
    path = PurePosixPath(source_path)
    if path.is_absolute() or ".." in path.parts or path.suffix.lower() != ".md":
        raise ImportFormatError(
            f"document source_path {source_path!r} must be a relative .md path "
            "inside the project"
        )


def _validate(conn: sqlite3.Connection, entries: list[_Entry], targets: list[_Target]) -> None:
    """Every check before anything is written, over the whole file. Edge
    targets are not checked: one that is not in the database is kept and
    reported as not-found."""
    entity_ids = [entity_id for entry in entries for entity_id in entry.entity_ids()]
    if len(set(entity_ids)) != len(entity_ids):
        raise ImportFormatError("snapshot contains duplicate ids")
    for entity_id in entity_ids:
        if entities.kind_of(conn, entity_id) is not None:
            raise EntityAlreadyExistsError(f"entity {entity_id} already exists in another project")
    for entry in entries:
        for comment in entry.comments:
            if conn.execute("SELECT 1 FROM comments WHERE id = ?", (comment["id"],)).fetchone():
                raise EntityAlreadyExistsError(f"comment {comment['id']} already exists")
    for entry, target in zip(entries, targets):
        for doc in entry.documents:
            _check_source_path(doc["source_path"])
        for doc in entry.documents:
            documents._check_unique(
                conn, target.project.id, doc["source_path"], PurePosixPath(doc["source_path"]).stem
            )


def _write(conn: sqlite3.Connection, entries: list[_Entry], targets: list[_Target]) -> None:
    """One transaction: new projects, then every entry's entities, then every
    entry's edges, comments, tags and refs, so an edge or comment into another
    entry finds its target whatever the entry order."""
    contents = {
        d["id"]: d["content"].encode("utf-8")
        for entry in entries
        for d in entry.documents
        if d.get("content") is not None
    }
    # Write backups before touching the DB, so a DB failure never leaves a
    # document row with no backup: if the transaction below fails, we delete
    # exactly the backups we just wrote.
    for doc_id, data in contents.items():
        documents._write_backup(conn, doc_id, data)
    try:
        with conn:  # one transaction: commits on success, rolls back on error
            for target in targets:
                if target.registered:
                    db.insert_project(conn, target.project)
            for entry, target in zip(entries, targets):
                _insert_entities(conn, target.project.id, entry, contents)
            for entry in entries:
                _insert_links(conn, entry)
    except BaseException as exc:
        for doc_id in contents:
            documents.backup_path(conn, doc_id).unlink(missing_ok=True)
        if isinstance(exc, sqlite3.IntegrityError):
            raise ImportFormatError(f"snapshot is internally inconsistent: {exc}") from exc
        raise


def _insert_entities(
    conn: sqlite3.Connection, project_id: str, entry: _Entry, contents: dict[str, bytes]
) -> None:
    for node, parent_id in entry.cards:
        status = "todo" if node["status"] == "blocked" else node["status"]
        db.insert_entity(conn, project_id, node["id"], "card")
        conn.execute(
            "INSERT INTO cards (id, title, description, status, parent_id, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (node["id"], node["title"], node.get("description"), status,
             parent_id, node["created_at"], node["updated_at"]),
        )
    for i in entry.issues:
        db.insert_entity(conn, project_id, i["id"], "issue")
        conn.execute(
            "INSERT INTO issues (id, title, body, status, close_reason, created_at, "
            "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (i["id"], i["title"], i.get("body"), i["status"], i.get("close_reason"),
             i["created_at"], i["updated_at"]),
        )
    for d in entry.documents:
        digest = documents._hash(contents[d["id"]]) if d["id"] in contents else d["content_hash"]
        db.insert_entity(conn, project_id, d["id"], "document")
        conn.execute(
            "INSERT INTO documents (id, project_id, title, source_path, stem, "
            "content_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (d["id"], project_id, d["title"], d["source_path"],
             PurePosixPath(d["source_path"]).stem, digest, d["created_at"],
             d["updated_at"]),
        )


def _insert_links(conn: sqlite3.Connection, entry: _Entry) -> None:
    for node, _ in entry.cards:
        for blocker_id in node.get("blocked_by", []):
            conn.execute(
                "INSERT INTO blocked_by (card_id, blocks_on_id) VALUES (?, ?)",
                (node["id"], blocker_id),
            )
    for c in entry.comments:
        conn.execute(
            "INSERT INTO comments (id, entity_id, author, body, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (c["id"], c["entity_id"], c["author"], c["body"], c["created_at"]),
        )
    for t in entry.tags:
        conn.execute(
            "INSERT INTO tags (entity_id, tag) VALUES (?, ?)", (t["entity_id"], t["tag"])
        )
    for r in entry.explicit_refs():
        conn.execute(
            "INSERT INTO refs (src_id, dst_id, origin) VALUES (?, ?, 'explicit')",
            (r["src_id"], r["dst_id"]),
        )


def _report(conn: sqlite3.Connection, entries: list[_Entry], targets: list[_Target]) -> dict:
    per_project = [
        {
            "project": dataclasses.asdict(db.get_project_by_id(conn, target.project.id)),
            "registered": target.registered,
            **entry.counts(),
        }
        for entry, target in zip(entries, targets)
    ]
    totals = {key: sum(item[key] for item in per_project) for key in COUNT_KEYS}
    not_found = sum(
        1
        for entry in entries
        for target_id in entry.edge_targets()
        if entities.kind_of(conn, target_id) is None
    )
    return {**totals, "projects": per_project, "not_found_edges": not_found}
