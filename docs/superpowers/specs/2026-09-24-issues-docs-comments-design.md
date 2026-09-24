# brd — issues, documents, comments, tags, and references

Date: 2026-09-24

## Purpose

Extend brd beyond cards with three new capabilities, built on shared
abstractions rather than re-implemented per shape:

1. **Issues** on a project: bugs, questions, and findings that are not (yet)
   work. Issues carry comments, reference cards and documents (as explicit
   metadata and as Obsidian-style `[[links]]`), and an open issue can block a
   card.
2. **Documents**: `.md` files in the repo registered with brd. Cards and
   issues can reference them (explicitly and via `[[links]]`). Documents can
   be tagged. brd keeps a backup copy of each document and keeps it in sync
   with the source file.
3. **Comments on cards**, using the same comment system as issues.

Comments, tags, and references are generic over "entities" (cards, issues,
documents), so enabling a feature for another kind later is a one-line
change.

Success criteria:
- An agent can open an issue, comment on it and on cards (as itself or as
  the OS user), link issues/cards/documents with `[[...]]`, and block a card
  on an open issue.
- An agent can register a markdown file, tag it, edit it, and run
  `brd doc update` to refresh brd's backup; brd serves the backup if the
  source goes missing.
- `--pretty` output renders links as the target's title, so a human can
  read it without resolving UUIDs.
- A single `brd export` snapshot restores the full board (cards, issues,
  documents, comments, tags, refs) on another machine.
- Every existing command keeps working unchanged for existing callers.

## Non-goals

- Editing comments (append-only: add, list, delete).
- Tags on cards or issues, or comments on documents (a capability map
  change away, but not enabled now).
- Comments as entities (cannot be tagged, commented on, or linked to).
- Short/prefix ids.
- Watching the filesystem; sync happens on brd reads and on explicit
  `brd doc update`.
- Writing to document source files, except `brd doc restore`.

## Decisions (and rejected alternatives)

- **Documents live in the repo as real files**, registered explicitly with
  `brd doc add <path>`. Rejected: content only in the db (loses
  "edit anywhere / Obsidian vault"), folder auto-scan (a plain `git mv`
  silently orphans metadata), frontmatter ids (brd would write to user files).
- **brd keeps a backup of each document** next to the project db and
  syncs it by content hash.
- **Issues** have an open/closed lifecycle, stay out of the card tree and
  `brd next`, **and** can block cards.
- **Generic features hang off a global `entities` registry** with real
  foreign keys and `ON DELETE CASCADE`. Rejected: polymorphic
  `(entity_type, entity_id)` columns without FKs (integrity by hand,
  `--type` flags everywhere), per-kind tables (N kinds × M features).
- **Rendered output shows titles in place of link targets.** Stored text is
  always raw.

## 1. Data model

Project db schema is versioned with `PRAGMA user_version`. This spec
defines version 1 (today's schema is version 0).

```sql
CREATE TABLE entities (
    id   TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('card', 'issue', 'document'))
);

CREATE TABLE cards (
    id          TEXT PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    description TEXT,
    status      TEXT NOT NULL CHECK (status IN ('todo', 'in_progress', 'done')),
    parent_id   TEXT REFERENCES cards(id),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE blocked_by (
    card_id      TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    blocks_on_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    PRIMARY KEY (card_id, blocks_on_id)
);

CREATE TABLE issues (
    id           TEXT PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    body         TEXT,
    status       TEXT NOT NULL CHECK (status IN ('open', 'closed')),
    close_reason TEXT CHECK (close_reason IN ('resolved', 'wontfix', 'duplicate')),
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE documents (
    id           TEXT PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    source_path  TEXT NOT NULL UNIQUE,              -- relative to project root, POSIX separators
    stem         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    content_hash TEXT NOT NULL,                     -- sha256 hex of the backup's bytes
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE comments (
    id         TEXT PRIMARY KEY,
    entity_id  TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    author     TEXT NOT NULL,
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE tags (
    entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    tag       TEXT NOT NULL,
    PRIMARY KEY (entity_id, tag)
);

CREATE TABLE refs (
    src_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    dst_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    origin TEXT NOT NULL CHECK (origin IN ('explicit', 'link')),
    PRIMARY KEY (src_id, dst_id, origin)
);
```

Rules:
- All ids are UUID4 strings (comments included).
- Creating a card, issue, or document inserts its `entities` row and its
  kind row in one transaction, via a single helper in `entities.py`.
- Deleting any entity is `DELETE FROM entities WHERE id = ?`; cascades
  remove its kind row, comments, tags, refs (both directions), and block
  edges (both directions). Card `--cascade` over children stays in `core`
  (it recursively deletes children first, as today).
- `issues.close_reason` is non-null iff `status = 'closed'` (enforced in
  `issues.py`); reopening clears it.
- `documents.title` defaults to the filename stem. `stem` is the filename
  without `.md`, unique case-insensitively.
- Tags are normalized to lowercase and must match `^[a-z0-9][a-z0-9_/-]*$`
  (Obsidian-style nesting such as `design/parser` allowed). A leading `#`
  on input is stripped.
- `refs` never contains `src_id = dst_id`.

### Capability map (`entities.py`)

```python
COMMENTABLE = {"card", "issue"}
TAGGABLE    = {"document"}
BLOCKERS    = {"card", "issue"}   # kinds allowed as blocked_by.blocks_on_id
REF_SOURCES = {"card", "issue", "document"}
```

Only cards can be blocked (`blocked_by.card_id` must be a card), enforced
in `core`.

### Migration 0 → 1

Runs on every project connection (`_project_conn()` and `brd init`), only
when `user_version < 1`:

1. `PRAGMA foreign_keys=OFF` (issued *before* `BEGIN`; SQLite ignores it
   inside a transaction), then `BEGIN`.
2. Create `entities`; insert `(id, 'card')` for every existing card.
3. Rebuild `cards` and `blocked_by` with the new FKs (create `*_new`, copy,
   drop, rename).
4. Create `issues`, `documents`, `comments`, `tags`, `refs`.
5. `PRAGMA foreign_key_check` must return no rows, else roll back and raise
   `MigrationError`.
6. Set `user_version = 1`, `COMMIT`, then `PRAGMA foreign_keys=ON`.

A fresh `brd init` creates the version 1 schema directly (same code path:
empty version 0 → 1). The legacy `_copy_cards` paths in `master.py` insert
through the new card-insert helper so migrated cards get `entities` rows.

## 2. Storage of document backups

- Backup directory: `<data_dir>/projects/<digest>.docs/`, next to
  `<digest>.db` (`paths.project_docs_dir(root_path)`).
- One file per document: `<doc-id>.md`. The backup path is derived from the
  id, never stored.
- `brd forget` deletes the directory; `brd purge` already removes the whole
  data dir.

### Sync algorithm (`documents.sync(conn, root, doc) -> SyncResult`)

`SyncResult = (content: str | None, source_state: 'ok' | 'updated' | 'missing' | 'lost')`

1. `src = root / source_path`. If `src` is not a file:
   - backup exists → return its content, `missing`;
   - backup absent → `None`, `lost`.
2. Read `src` bytes, compute sha256.
   - Equal to `content_hash` and backup exists → return content, `ok`.
   - Otherwise → write backup atomically (temp file in the same dir, then
     `os.replace`), set `content_hash` and `updated_at`, `refs.reindex`
     the document, return content, `updated`.

A differing hash always means the source advanced: the backup changes only
by copying from the source (or from an import snapshot).

Content is stored and compared as bytes; parsing decodes UTF-8 with
`errors="replace"`.

Sync runs on: `doc show`, `doc update`, `doc list` (every listed doc), and
before computing `referenced_by` for any `show` (all docs are synced so
backlinks from edited documents are current).

### Path rules

- Input paths are resolved against the current working directory, then must
  resolve (following symlinks) to a file inside the project root →
  otherwise `PathOutsideProjectError`.
- Must end in `.md` (case-insensitive) → otherwise `NotMarkdownError`.
- Must exist at `doc add` / `doc update --path` time → otherwise
  `DocumentSourceNotFoundError`.
- Stored relative to the project root with POSIX separators.
- `source_path` unique → `DuplicatePathError`; stem unique
  (case-insensitive) → `DuplicateStemError` (message suggests renaming one
  file).

## 3. Links and references

### Parsing (`links.py`, pure, no db)

`parse(text) -> list[LinkToken(target, alias | None)]`

- Syntax: `[[target]]`, `[[target#heading]]`, `[[target|alias]]`,
  `[[target#heading|alias]]`. The heading is dropped.
- Skipped: anything inside fenced code blocks (```` ``` ```` or `~~~`)
  and inline code spans.
- `target` is stripped of whitespace; empty targets are ignored.

### Resolution (`refs.py`)

`resolve(conn, target) -> entity_id | None`:
1. If `target` is a UUID and exists in `entities` → that id.
2. Otherwise normalize: drop a trailing `.md` (case-insensitive), take the
   last `/`-separated component, match `documents.stem` case-insensitively.
3. Else unresolved (`None`). Unresolved links are not errors.

### Reindex

`refs.reindex(conn, entity_id)` (idempotent):
1. Gather the entity's text: card description, issue body, or document
   backup content; plus bodies of all comments on it.
2. Parse, resolve, drop self-links and unresolved targets.
3. Replace all `origin='link'` rows with `src_id = entity_id` in one
   transaction. `origin='explicit'` rows are never touched.

Called after: card create/update (when description is set), issue
open/update, comment add/delete, document sync that changed content,
import (every imported entity).

**Forward links:** on `doc add` and on `doc update --path` (stem change),
find entities whose text contains `[[<stem>` (case-insensitive) and
reindex them: cards/issues/comments via SQL `LIKE` (a comment's owning
entity is reindexed), and documents by scanning their backup files.
Without the document scan, a document linking `[[x]]` before `x` is
registered would stay unresolved until its own content changed.

### Explicit refs

`brd ref add <src> <dst>` / `brd ref remove <src> <dst>` and `--ref <id>`
on `issue open` manage `origin='explicit'` rows. Both ids must exist;
`src` kind must be in `REF_SOURCES`; self-refs rejected
(`SelfReferenceError`).

### Rendering

- JSON output keeps text raw and adds `refs` (outgoing) and
  `referenced_by` (incoming) arrays of `{id, kind, title, origin}`,
  deduplicated per `(id, origin)`.
- `--pretty` output rewrites each link in displayed text to
  `[[<display>]]` where display is the alias if present, else the target
  entity's title; unresolved links render as `[[<target>]] (unresolved)`.
  Links inside code are left as-is.

## 4. Issues and blocking

- `open` on create; `close [--reason]` sets `closed` and the reason
  (default `resolved`); `reopen` sets `open` and clears the reason.
- An issue blocks while `open`. Closing it with any reason unblocks.
- `core.resolve_status`: for each `blocks_on_id` of a card, if it is a card
  apply today's rule; if it is an issue, blocking iff `status = 'open'`.
- Issues have no blockers, so they are always leaves in the block graph;
  `would_create_block_cycle` is unchanged (it only walks from cards).
- `brd block <card> <blocker>` / `--blocked-by`: `<card>` must be a card
  (`CardNotFoundError`), `<blocker>` must be a kind in `BLOCKERS`
  (`InvalidBlockerError` for documents, `EntityNotFoundError` if absent).
- Issues never appear in `brd tree` or `brd next`.

## 5. Comments and tags

- `comments.add(conn, entity_id, body, author)`: entity kind must be in
  `COMMENTABLE` (`NotCommentableError`); body non-empty.
- Author resolution: `--author` → `$BRD_AUTHOR` → `getpass.getuser()`.
- Comments listed oldest first.
- `tags.add/remove(conn, entity_id, tags)`: kind in `TAGGABLE`
  (`NotTaggableError`); invalid tags → `InvalidTagError` (nothing written).
  Adding an existing tag / removing an absent one is a no-op.

## 6. CLI surface

Existing commands keep their names, flags, and output shapes. Changes:
- `brd show <id>` and `brd delete <id>` dispatch on `entities.kind`.
  `delete --cascade` applies only to cards. Deleting a document removes its
  backup file and never touches the source file.
- `--blocked-by` / `brd block` / `brd unblock` accept issue ids as blockers.
- `brd show <card>` output gains `refs`, `referenced_by`, `comments`;
  `blocked_by` may contain issue ids.

New commands:

```
brd issue open  --title T [--body B] [--ref <id>]... [--blocks <card-id>]...
brd issue list  [--status open|closed]
brd issue update <id> [--title T] [--body B]
brd issue close <id> [--reason resolved|wontfix|duplicate]
brd issue reopen <id>

brd doc add <path> [--title T] [--tag t]...
brd doc list [--tag t]... [--missing]          # --tag repeated = must have all; --missing = missing|lost
brd doc update <id> [--path P] [--title T]
brd doc restore <id> [--force]

brd comment add <entity-id> <body> [--author A]   # body "-" reads stdin
brd comment list <entity-id>
brd comment delete <comment-id>

brd tag add <entity-id> <tag>...
brd tag remove <entity-id> <tag>...
brd tag list [<entity-id>]                     # no id: all tags with counts

brd ref add <src-id> <dst-id>
brd ref remove <src-id> <dst-id>

brd export
```

`brd doc restore`: writes the backup to `root / source_path`, creating
parent dirs. If the source exists and its hash differs from `content_hash`
→ `RestoreConflictError` unless `--force`. If source exists and matches →
no-op. If backup is absent → `DocumentContentLostError`.

### Output shapes (JSON `data`)

- Issue: `{id, kind: "issue", title, body, status, close_reason, blocks,
  refs, referenced_by, comments, created_at, updated_at}`; `blocks` lists
  card ids blocked on it.
- Document (`show`): `{id, kind: "document", title, source_path,
  source_state, content, tags, refs, referenced_by, created_at,
  updated_at}`. `doc list` items omit `content`, `refs`, `referenced_by`.
- Card (`show`): today's fields plus `kind: "card"`, `refs`,
  `referenced_by`, `comments`.
- Comment: `{id, entity_id, author, body, created_at}`.

### Pretty renderers (`output.py`)

- `show` per kind: title line with status and id; blockers; rendered
  body; `refs` / `referenced by` as titles with kinds; comments as
  `author · YYYY-MM-DD HH:MM` followed by the indented rendered body.
- Lists: issues `id  [open]  title`; documents
  `id  [ok|missing|lost]  title  (path)  #tag1 #tag2`; comments as in show.

### Errors

Same envelope as today. New types: `EntityNotFoundError`,
`IssueNotFoundError`, `DocumentNotFoundError`, `CommentNotFoundError`,
`DuplicateStemError`, `DuplicatePathError`, `PathOutsideProjectError`,
`NotMarkdownError`, `DocumentSourceNotFoundError`,
`DocumentContentLostError`, `RestoreConflictError`, `NotTaggableError`,
`NotCommentableError`, `InvalidBlockerError`, `InvalidTagError`,
`SelfReferenceError`, `MigrationError`, `ImportFormatError`,
`EntityAlreadyExistsError`.
`CardNotFoundError` stays for card-only commands.

## 7. Export and import

`brd export` emits:

```json
{
  "brd_export": 1,
  "cards":     [<brd tree node shape>],
  "issues":    [{"id", "title", "body", "status", "close_reason", "created_at", "updated_at"}],
  "documents": [{"id", "title", "source_path", "content", "content_hash", "created_at", "updated_at"}],
  "comments":  [{"id", "entity_id", "author", "body", "created_at"}],
  "tags":      [{"entity_id", "tag"}],
  "refs":      [{"src_id", "dst_id", "origin": "explicit"}]
}
```

- Documents are synced before export; `content` is the backup content
  (null for `lost` documents, which are exported with their last hash).
- Link refs are not exported; import rebuilds them by reindexing.
- `brd import <file>` accepts the new format (object with `brd_export`) or
  the old tree format (list, or envelope wrapping a list). Anything else →
  `ImportFormatError`.
- Import is all-or-nothing in one transaction: if any id in the snapshot
  exists in `entities`, nothing is written and the error is
  `CardAlreadyExistsError` for the old tree format (unchanged) or
  `EntityAlreadyExistsError` for the new format. Document backups are written
  from `content`; source files are never written. A stem/path collision with
  an existing document → the corresponding duplicate error, nothing written.
- After inserting, every imported entity is reindexed.
- README's snapshot section switches to `brd export`; `brd tree` remains a
  view.

## 8. Agent prompt (`brd prompt`)

Add to the snippet:

> **Documents:** registered `.md` files (`brd doc list`) are tracked by brd,
> which keeps a backup. **Whenever you edit a registered document, run
> `brd doc update <id>` right after.** If you move or rename one, run
> `brd doc update <id> --path <new>`. Use `[[doc-stem]]` or `[[<id>]]` in
> card descriptions, issue bodies, and comments to link things.
>
> **Comments:** `brd comment add <id> "..."` records progress or decisions
> on a card or issue. Set `BRD_AUTHOR` to your agent name once per session.
>
> **Issues:** for bugs, questions, and findings that aren't work yet
> (`brd issue open --title ...`). Link cards to them, or block a card on an
> open issue with `brd block <card> <issue>`.

Also update the snapshot line to `brd export` / `brd import`.

## 9. Code layout

```
brd/cli/__init__.py      app, sub-app registration, run(pretty, fn) helper that
                         opens the migrated conn and maps domain exceptions
                         to error envelopes
brd/cli/cards.py         existing card commands (moved), generic show/delete
brd/cli/{issues,docs,comments,tags,refs,snapshot}.py
brd/entities.py          kind lookup, create/delete entity, capability map
brd/links.py             pure parser
brd/refs.py              resolve, reindex, explicit refs, backlinks
brd/comments.py, brd/tags.py
brd/issues.py
brd/documents.py         add, sync, rename, restore, backup io
brd/snapshot.py          export/import (import_tree moves here)
brd/core.py              cards: status (learns issue blockers), tree, next
brd/db.py                connect, migrations, thin per-table SQL
brd/errors.py            all domain exception types
```

The `brd` console script entry point stays `brd.cli:app` (now resolving to
the package's `__init__.py`).

## 10. Testing

One test module per source module; data dir isolated via
`XDG_DATA_HOME=tmp_path`.

- `test_links.py`: table-driven; plain, heading, alias, heading+alias,
  `.md`, directory prefix, UUID, inline code, fenced blocks (both fence
  styles), unbalanced brackets, multiple links per line.
- `test_migration.py`: real v0 db with cards and edges → migrate →
  entities backfilled, rows/edges intact, `user_version = 1`, delete
  cascades; second migration is a no-op; legacy `.brd/` in-repo and UUID
  marker migrations still work.
- `test_documents.py`: each sync state (`ok`, `updated`, `missing`,
  `lost`, backup-deleted-source-present); atomic write; add/rename path
  and stem rules; symlink and `..` escapes; restore normal, conflict,
  `--force`, lost; delete leaves source file.
- `test_refs.py`: reindex idempotent; explicit refs preserved; comment
  links attributed to parent; backlinks; forward link resolves on
  `doc add` and on rename; dangling link after target delete; self-links
  dropped.
- `test_comments.py`, `test_tags.py`: capability enforcement, author
  precedence, tag normalization and rejection.
- `test_issues.py` / `test_core.py`: open issue blocks card, close (each
  reason) unblocks, card leaves/re-enters `next`; reopen re-blocks;
  document as blocker rejected; existing cycle tests pass.
- `test_cli.py`: a happy path and an error envelope per new command;
  `show`/`delete` dispatch; pretty output renders titles for links.
- `test_snapshot.py`: `export → import` into a fresh project reproduces
  `show` output for every entity; old tree snapshot still imports;
  collision leaves the db untouched.
- `test_prompt.py`: snippet contains the `brd doc update` rule.

## 11. Build order

One plan, five milestones; each leaves the suite green:

1. **Foundation:** `errors.py`, migrations/`user_version`, `entities`,
   `entities.py`, `cli.py` → `cli/` package with `run()`. No behavior
   change; existing tests pass unmodified (only import paths may change).
2. **Comments, tags, refs, links:** `links.py`, `refs.py`, `comments.py`,
   `tags.py`, their commands, generic `show`/`delete`. Card comments work.
3. **Documents:** backups, sync, `doc` commands, forward-link reindex,
   `forget` cleanup.
4. **Issues:** `issue` commands, issue blockers in `core`.
5. **Snapshot + presentation:** `export`/`import` v2, pretty renderers,
   prompt, README.
