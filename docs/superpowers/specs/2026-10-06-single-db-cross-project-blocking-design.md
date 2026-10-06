# Single database, cross-project blocking, container release

Status: approved design (2026-10-06). Source: brd issue 7498e9a8 "Allow blocked_by
across every boundary: stories, milestones and projects".

## Goal

`blocked_by` should mean exactly "B cannot start until A's output exists", whatever
board A lives on. Today that fails in two ways:

1. **Cross-project edges are impossible.** Each project is its own SQLite file and
   `blocked_by.blocks_on_id` is a foreign key into that file's `entities`. Dependent
   boards fake it with a hand-made gate issue.
2. **Containers never release.** A story or milestone's stored status stays `todo`
   when all its children finish, so anything blocked on it stays blocked until
   someone closes the container by hand. This is why authors over-serialize.

Edges across stories and milestones *within* one board already work (verified: no
sibling restriction exists in `block_card`); they are out of scope except as they
benefit from container release.

The chosen direction: replace the per-project databases with one brd database that
holds every project, make edge targets free-standing ids (so they may point into
another project or at nothing), and make export/import a list of projects so boards
move between machines without losing hierarchy or edges.

## Decisions

| # | Decision |
|---|----------|
| D1 | A container (card with children) releases its dependents when its stored status is releasing **or** every child resolves to a releasing status (recursive). Its own stored/displayed status is unchanged. Childless cards behave as today. |
| D2 | One database, `$XDG_DATA_HOME/brd/brd.db`, for all projects. `master.db` and `projects/<hash>.db` go away. |
| D3 | Commands are scoped to the current project; only edges (and `show`, edge targets, `[[uuid]]` links) cross projects. |
| D4 | Ownership lives on `entities.project_id` (cascade from `projects`). `documents` duplicates it for per-project uniqueness. |
| D5 | The `.brd` marker is dropped. The current project is the deepest registered `root_path` that is the cwd or an ancestor. `brd init --relink` handles moved repos. |
| D6 | Edge targets (`blocked_by.blocks_on_id`, `refs.dst_id`) carry no foreign key. An edge whose target is not in the database is kept and reported as `not-found`. |
| D7 | A `not-found` blocker blocks (fail closed). |
| D8 | `brd delete` removes edges pointing at the deleted entity (today's behaviour). `brd forget` and import's project replacement do **not** remove incoming edges from other projects; they become `not-found` and reconnect if the ids return. |
| D9 | Export format v2 is always a list of project entries; one-project and all-project exports share one code path. |
| D10 | Import of a project that has local state replaces that whole project, after confirmation (`--yes` to skip; refuse when no TTY and no `--yes`). |
| D11 | Import placement: a one-project file lands in the cwd project; a multi-project file matches by project id, else registers at the recorded `root_path` if that directory exists, else refuses. |

## 1. Schema

One file, `brd.db`, `PRAGMA user_version = 4`. Doc backups move to
`$XDG_DATA_HOME/brd/docs/<doc_id>.md` (doc ids are UUIDs, globally unique).

```sql
CREATE TABLE projects (
    id TEXT PRIMARY KEY,              -- uuid4
    name TEXT NOT NULL,
    root_path TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE entities (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('card', 'issue', 'document')),
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE
);
CREATE INDEX entities_project ON entities(project_id, kind);
-- cards: unchanged columns; parent_id REFERENCES cards(id).
--   Trigger: parent must belong to the same project as the card.
-- issues: unchanged.
-- documents: + project_id TEXT NOT NULL;
--   UNIQUE(project_id, source_path), UNIQUE(project_id, stem COLLATE NOCASE);
--   trigger: documents.project_id = entities.project_id for the row.
-- comments, tags: unchanged (scoped through entity_id).
CREATE TABLE blocked_by (
    card_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    blocks_on_id TEXT NOT NULL,       -- no FK: may be another project or not-found
    PRIMARY KEY (card_id, blocks_on_id)
);
CREATE INDEX blocked_by_target ON blocked_by(blocks_on_id);
CREATE TABLE refs (
    src_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    dst_id TEXT NOT NULL,             -- no FK
    origin TEXT NOT NULL CHECK (origin IN ('explicit', 'link')),
    PRIMARY KEY (src_id, dst_id, origin)
);
CREATE INDEX refs_target ON refs(dst_id);
```

The entity-registration triggers (`<table>_register_entity`) can no longer insert
the `entities` row by themselves because they don't know the project. Inserts go
through code that writes `entities(id, kind, project_id)` first; the triggers are
removed. Raw inserts in tests use a factory that does the same.

Deletion rules:

- Deleting an entity cascades its own rows: card/issue/document row, comments,
  tags, outgoing `blocked_by` and `refs`.
- `core.delete_card`, `issues.delete` and `documents.delete` additionally run
  `DELETE FROM blocked_by WHERE blocks_on_id = ?` and
  `DELETE FROM refs WHERE dst_id = ?` (D8).
- `brd forget` deletes the `projects` row (cascading everything owned) and does not
  touch incoming edges from other projects (D8).

## 2. Scoping and project resolution

**Resolution.** `master.resolve_project(cwd)` selects, in one query, the registered
project whose `root_path` is the cwd or its deepest ancestor; none → 
`ProjectNotFoundError`. `Ctx` becomes `(conn, project)`.

**`brd init`** registers the cwd with a new UUID and writes nothing into the repo
(no marker, no `.gitignore` edit). Re-running in a registered root only updates the
name. `brd init --relink <old-root-or-project-id>` sets that project's `root_path`
to the cwd. Nested projects are allowed; the deepest root wins.

**Scoped** (filtered by `entities.project_id` through one helper in `db.py`):
`list`, `next`, `tree`, `issue list`, `doc list`/`sync`, `[[stem]]` link resolution,
`refs.reindex_mentions` scans, document uniqueness checks, `export` without `--all`.
Mutating commands (`update`, `delete`, `block`/`unblock` source, `comment`, `tag`,
`issue update/close/reopen`, `doc` mutations, `ref` source) require the entity to
belong to the current project; otherwise `EntityNotFoundError` naming the owning
project.

**Global** (ids are UUIDs): `brd show <id>` (output includes the owning project);
blocker targets of `brd block --by`, `add --blocked-by`, `issue open --blocks`;
`brd ref add` targets; `[[<uuid>]]` links; status resolution and the cycle check,
which follow edges across projects.

**`brd projects`** lists `id`, `name`, `root_path`. **`brd forget`** takes the cwd
project, or `--project <id>` for a project whose directory no longer exists.

## 3. Migration from the per-project layout

Runs once, from any command, when `master.db` exists and `brd.db` does not.

1. Create `brd.db` and take `BEGIN IMMEDIATE`; re-check that the migration hasn't
   already happened (concurrent first runs queue on the busy timeout).
2. For each project in `master.db`: open `projects/<sha256(root)>.db`, bring it to
   v3 with the existing `migrate_project`, assign a new project UUID, copy every
   row preserving ids and timestamps, and copy `<hash>.docs/<id>.md` to
   `docs/<id>.md`. A registered project with no db file is registered empty.
3. All projects in one transaction. An id present in two boards aborts the
   migration with both project names and the ids; nothing is renamed, so the next
   run retries.
4. After commit, rename `master.db`, each migrated `*.db` and `*.docs` with a
   `.migrated` suffix (never delete). A failed rename leaves a stray file but does
   not re-run the migration, because `brd.db` exists.
5. Report on stderr: `brd: migrated N projects into brd.db (old files kept as
   *.migrated)`, plus any unregistered `projects/*.db` files that were skipped.

Dropped: `init`'s in-repo `.brd/` directory and UUID-marker migrations, and the
`.gitignore` edit. Existing `.brd` files and `.gitignore` lines are left alone and
ignored. Release notes: boards in those very old formats must be opened once with
the last per-project release first; upgrade every installed copy of brd together.

## 4. Blocking: cross-project edges, not-found, container release

`core.resolve_status` becomes:

```
resolve_status(card):
    if card.status != 'todo': return card.status
    for blocker_id in blockers_of(card):
        if not is_released(blocker_id): return 'blocked'
    if parent is blocked: return 'blocked'
    return 'todo'

is_released(entity_id):
    kind = kind_of(entity_id)                 # global lookup, any project
    None   -> False                           # not-found blocks (D7)
    issue  -> status != 'open'
    card   -> resolve_status(card) in RELEASING
              or (has children and every child is_released)   # D1
```

`RELEASING` stays `{done, merged, canceled, archived}`. Recursion keeps the
existing `seen` guard. The cycle check walks `blocked_by` across projects;
not-found ids end a path.

**Output.** `blocked_by` stays a list of ids everywhere it appears today (card
detail, list, tree, export) so existing consumers keep parsing it. Card detail,
list items and tree nodes gain:

```json
"blockers": [
  {"id": "…", "kind": "card", "project": {"id": "…", "name": "agent-manager"},
   "title": "…", "status": "done", "released": true},
  {"id": "…", "kind": null, "project": null, "title": null,
   "status": "not-found", "released": false}
]
```

`--pretty` renders a same-project blocker as today, a foreign one as
`<project>: <title>`, and a missing one as `not-found <id>`.

## 5. Export and import (format v2)

```json
{
  "brd_export": 2,
  "projects": [
    {
      "project": {"id": "…", "name": "brd", "root_path": "/home/…/brd",
                  "created_at": "…"},
      "cards": [], "issues": [], "documents": [],
      "comments": [], "tags": [], "refs": []
    }
  ]
}
```

Each entry has exactly today's v1 body plus `project`. Edges are exported as stored,
including cross-project and not-found targets.

**Export.** `brd export` → `[current project]`; `brd export --all` → every project.
Both call `export_project(conn, project)` per entry.

**Import.** `brd import <file> [--yes]`:

1. Normalize: a v1 export or legacy `brd tree` snapshot is wrapped as one entry
   with no project metadata.
2. Place each entry (D11):
   - One entry: the cwd project. If the cwd is not registered, register it, reusing
     the entry's project id when present and unused.
   - Several entries: the registered project with the same id; else register at the
     recorded `root_path` if that directory exists; else refuse, listing the paths.
     A recorded `root_path` already registered under a different id is refused with
     a hint to import that entry alone from its directory.
3. Validate: duplicate ids within the file; ids already in the database outside
   the projects being replaced (refuse, naming the owner); document paths and stems
   as today.
4. Confirm (D10): if any target project has entities, print per-project counts to
   stderr (`brd: -42 cards, -3 issues, … / +40 cards, +3 issues, …`) and ask y/N on a
   TTY. `--yes` skips the prompt; no TTY and no `--yes` → refuse.
5. One transaction: wipe each target project's entities (same deletion as
   `forget`, so incoming edges from other projects survive, D8), insert all
   entities of all entries, then all edges, comments, tags and refs. Backups are
   written before and removed on failure, as today.
6. Reindex link refs per project. Report per-project counts plus the number of
   edges whose targets are still not-found.

Cross-machine round trip: `brd export --all` on machine 1, `brd import --yes` on
machine 2 restores every project whose root exists there, with ids, hierarchy and
edges intact. Importing B after A reconnects A's not-found edges automatically.

## 6. Consumer contract

`brd --help` and `brd prompt` gain a short section stating:

- `status` is authoritative: `blocked` already accounts for cross-project blockers,
  not-found blockers and container release. `brd next` lists only cards that can
  start now.
- `blocked_by` is a list of ids that may belong to other projects or be not-found;
  `blockers` carries project, title, status and `released` for each.
- Blocking a story or milestone means waiting for all of its children.

Changes to the orchestrator and agent-manager (e.g. `am`'s one-blocker rule for
stories) are out of scope here; they read the contract above.

## Testing

- **Leak guard:** one parametrised test seeds two projects with similar content and
  runs every listing and lookup command from each root, asserting nothing from the
  other project appears.
- Resolution: subdirectory, nested projects, unregistered dir, `--relink`.
- Migration: multiple legacy boards at v0–v3, missing db file, unregistered db,
  duplicate id across boards (aborts, nothing renamed), concurrent first runs,
  doc backups moved, old files renamed.
- Blocking: cross-project card and issue blockers, not-found blocks, container
  releases when all children finish (including canceled/archived and nested
  containers), childless containers unchanged, cycle across projects rejected.
- Deletion: `delete` removes incoming edges; `forget` keeps incoming edges as
  not-found; re-import reconnects them.
- Export/import: one-project and `--all` round trips; v1 and `brd tree` inputs;
  placement rules; replacement with confirmation, `--yes`, and no-TTY refusal;
  incoming edges survive replacement; id owned by another project refused.

## Implementation order

Each phase is its own plan and lands independently:

1. **Container release** (D1): `resolve_status` only, on the current schema.
2. **Single database**: the full section 1 schema (edge targets already FK-free),
   scoping helper, resolution without marker, `init --relink`, `forget --project`,
   migration, leak guard, and the explicit incoming-edge cleanup in `delete` so
   in-board behaviour is unchanged. Edge targets are still validated as
   same-project by code.
3. **Cross-project edges**: lift the same-project check on edge targets, not-found
   resolution, `blockers` output, `forget` keeping incoming edges, consumer
   contract text.
4. **Export/import v2**: format, placement, replacement with confirmation.
