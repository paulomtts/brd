# 2.5 Scope issues, documents and [[stem]] links to the current project

Card: `43ff4aca-f1e6-445b-8e4a-1e486aa1eba2` (subtask of story `54de5e9d` "Project-scoped
schema", milestone `6aa7043a` "Single database and cross-project blocking"). Blocked by
2.4 (`7e1ec729`, done on this branch's parent: `db.in_project`, `db.owner_of`,
`core.require_card` and the foreign-card error, `src/brd/db.py:480-492`,
`src/brd/core.py:102-120`).

Parent design spec: `docs/superpowers/specs/2026-10-06-single-db-cross-project-blocking-design.md`
(in the main checkout; not in this branch's history). Cited by section and line as
**[P §n Lx]**. The 2.4 spec (`docs/superpowers/specs/2-4-scope-card-listings-7e1ec729.md`)
is cited as **[2.4 Bn]**.

## Goal

Issue, document, ref, tag and comment commands only see and change entities of the
project they run in (`ctx.project`, `src/brd/cli/_app.py:53-56`), the way 2.4 did for
cards:

- `brd issue list`, `brd doc list` (and the sync it runs), `brd tag list` (counts) list only
  the current project's rows.
- Document uniqueness (path and stem) is checked per project, so two projects may register
  documents with the same stem.
- `[[stem]]` links resolve to a document of the project that owns the text containing the
  link. `[[<uuid>]]` links stay global.
- When a document is added or renamed, `refs.reindex_mentions` rescans only the current
  project's texts.
- `brd issue update/close/reopen`, `brd doc update/restore`, `brd delete` of an issue or a
  document, `brd ref add/remove` (source; and target of `add`), `brd tag add/remove/list
  <id>`, `brd comment add/list` on an issue (cards are already done), `brd comment delete`,
  and `brd issue open --ref` refuse an entity from another project with an error that names
  the owning project.

There is still one board file per project. Users see no difference until S3 puts every
project in one `brd.db`. Tests seed a second project into one connection
(`tests/factories.add_project`, `tests/factories.py:21-29`).

## Inherited constraints

| Constraint | Source |
|---|---|
| Commands are scoped to the current project. Only edges, `show`, edge targets and `[[uuid]]` links cross projects. | [P D3 L33] |
| `documents` duplicates the project id for per-project uniqueness. | [P D4 L34]; schema `UNIQUE(project_id, source_path)`, `UNIQUE(project_id, stem COLLATE NOCASE)` [P §1 L64-66] |
| Comments and tags are scoped through `entity_id`. | [P §1 L67] |
| Scoped through the one `db.py` helper: `issue list`, `doc list`/`sync`, `[[stem]]` link resolution, `refs.reindex_mentions` scans, document uniqueness checks. | [P §2 L109-111]; `db.in_project` [2.4 B1] |
| Mutating commands (`comment`, `tag`, `issue update/close/reopen`, `doc` mutations, `ref` source, `delete`) require the entity to belong to the current project; otherwise `EntityNotFoundError` naming the owning project. | [P §2 L112-115] |
| `brd show <id>` is global and names the owner; `[[<uuid>]]` links are global. | [P §2 L117-119] |
| In phase 2, edge targets are still validated as same-project by code (lifted in S4). | [P Implementation order L276-280]; [2.4 B5] |
| `issues.delete` / `documents.delete` remove incoming edges. | [P §1 L92-94] (already implemented by `entities.delete`, `src/brd/entities.py:58-61`) |
| New project parameters are a **required** positional `project_id: str`, second after `conn`. No fallback to "the board's only project". | [2.4 Inherited constraints, last row] |
| A refused command writes nothing. | [2.4 B4] |
| Do not change the schema; `SCHEMA_VERSION` stays 4. | 2.3 (schema v4 already carries `documents.project_id` and the per-project UNIQUE constraints) |

## Behaviour

"P" is the current project, "Q" another project in the same connection. "Foreign" means
owned by Q (`entities.project_id = Q`).

### B1. The foreign-entity error

One helper, `entities.require_in_project(conn, project_id, entity_id) -> str` (returns the
kind), is the check every path below uses (2.4's `core._require_in_project` keeps its own
message variants for cards and blockers and may delegate to it):

1. Id not in `entities`: `EntityNotFoundError("no entity with id <id>")` (today's
   `entities.require` message).
2. Owned by another project: the kind-specific subclass of `EntityNotFoundError` —
   `CardNotFoundError` / `IssueNotFoundError` / `DocumentNotFoundError` — with the message
   `no <kind> with id <id> in this project; it belongs to project <owner name> (<owner id>)`.
   This is the 2.4 message format [2.4 B4] with the entity's own kind word.
3. Otherwise returns the kind.

**Ownership is checked before capability.** A foreign card passed to `brd tag add` gets the
foreign-card error, not `NotTaggableError`; a foreign document passed to `brd comment add`
gets the foreign-document error, not `NotCommentableError` (consistent with [2.4 B5]).

Kind-specific lookups keep their existing "missing" message and add the foreign case:

- `issues.require(conn, project_id, issue_id)`: no issue row → `IssueNotFoundError("no issue
  with id <id>")` (today; also when the id is a card or document of any project); a foreign
  issue → `IssueNotFoundError` foreign message.
- `documents.require(conn, project_id, doc_id)`: same with `DocumentNotFoundError` and
  `no document with id <id>`.

The CLI envelope `type` is the exception class name (`src/brd/cli/_app.py:59-61`).

### B2. Issues

| Command / function | Behaviour |
|---|---|
| `brd issue list [--status]` / `issues.list_issues(conn, project_id, status=None)` | Only P's issues, ordered by `created_at, rowid` as today. Invalid status still raises `InvalidStatusError` first. |
| `brd issue update/close/reopen` / `issues.update(conn, project_id, issue_id, ...)`, `issues.close(conn, project_id, issue_id, reason)`, `issues.reopen(conn, project_id, issue_id)` | Foreign issue → B1 error; the row (including `updated_at`) is unchanged and refs are not reindexed. `issues.update` with no fields on a foreign issue also refuses. `close` with an invalid reason still raises `InvalidCloseReasonError` first (no id lookup needed to reject the reason, as today). |
| `brd issue open --ref <id>` / `issues.open_issue(conn, project_id, ...)` | Each `--ref` target must be in P (same-project edge targets in phase 2): missing → `EntityNotFoundError` as today; foreign → B1 error. Checked **before** the issue is inserted, so no issue, entity or ref row is left behind. `--blocks` is unchanged from 2.4. |
| `brd delete <issue id>` / `cli.cards.delete_entity` issue branch | Foreign issue → `IssueNotFoundError` foreign message; nothing deleted. A P issue is deleted with its incoming edges, as today. |

`issues.get(conn, issue_id)` stays an unscoped read by id. `issues.blocks_of` is unchanged.

### B3. Documents

| Command / function | Behaviour |
|---|---|
| `brd doc list [--tag] [--missing]` / `documents.list_all(conn, project_id)`, `documents.sync_all(conn, project_id, root)` | Only P's documents are synced and listed. Q's backups and `content_hash`/`updated_at` are untouched. Order `created_at, source_path` as today. |
| `brd doc add` / `documents.add(conn, project_id, root, path, ...)` | Uniqueness is per project: `DuplicatePathError` / `DuplicateStemError` only when a **P** document has the same `source_path` / stem (case-insensitive, as the schema's `COLLATE NOCASE`). A Q document with the same path or stem does not block the add. Messages unchanged. |
| `brd doc update` / `documents.update(conn, project_id, root, doc_id, new_path=None, title=None)` | Foreign document → B1 error, nothing changes (no row update, no backup write). `--path` uniqueness is per project, excluding the document itself, as today. |
| `brd doc restore` / `documents.restore(conn, project_id, root, doc_id, force=False)` | Foreign document → B1 error; no file is written. |
| `brd delete <document id>` / `documents.delete(conn, project_id, doc_id)` | Foreign document → `DocumentNotFoundError` foreign message; the row and the backup file stay. |

`documents.get(conn, doc_id)` stays an unscoped read by id.

### B4. `[[stem]]` links and mention rescans

- `refs.resolve(conn, project_id, target)`: a UUID target resolves globally to any existing
  entity (unchanged); a stem target resolves only to a document of `project_id`. When P and
  Q both have stem `notes`, `resolve(conn, P, "notes")` is P's document and
  `resolve(conn, Q, "notes")` is Q's. A stem only Q has → `None` for P.
- `refs.reindex(conn, entity_id)` keeps its signature. Stem links in the entity's own text
  and its comments resolve against **the project that owns `entity_id`**. So a P card whose
  description says `[[notes]]` links to P's `notes`, never Q's; a P card writing
  `[[<Q card uuid>]]` still gets a link ref to the Q card.
- `refs.reindex_mentions(conn, project_id, stem)`: candidates are only P's cards (by
  description), P's issues (by body), comments on P's entities, and P's documents (by backup
  content). Q entities that mention the stem are not reindexed (their `refs` rows are
  untouched). Callers: `documents.add` and `documents.update` pass their `project_id`.
- `pretty.text(conn, project_id, value)` renders stem links against `project_id`. The
  `--pretty` renderers use the project owning the entity being rendered:
  `render_detail` the owner of `data["id"]`, `render_comments` the owner of each comment's
  `entity_id` (found with `db.owner_of`; an unknown owner renders stem links as
  unresolved). So `brd show <Q card> --pretty` renders `[[notes]]` with Q's `notes` title.

### B5. Refs

| Command / function | Behaviour |
|---|---|
| `brd ref add <src> <dst>` / `refs.add_explicit(conn, project_id, src_id, dst_id)` | `src` must be in P (B1). `dst` must also be in P in this phase (same-project edge targets, lifted in S4): missing → `EntityNotFoundError` as today; foreign → B1 error. `SelfReferenceError` as today. No row added on refusal. |
| `brd ref remove <src> <dst>` / `refs.remove_explicit(conn, project_id, src_id, dst_id)` | `src` must be in P (B1). `dst` is not checked; the edge is removed if it exists, as today (mirrors `unblock --by`, [2.4 B5]). |

`refs.outgoing` / `refs.incoming` and the `refs` / `referenced_by` output keys are
unchanged: they list every edge of the entity, including a `[[uuid]]` link to another
project.

### B6. Tags

| Command / function | Behaviour |
|---|---|
| `brd tag add/remove <id> TAG...` / `tags.add(conn, project_id, entity_id, tag_list)`, `tags.remove(...)` | Foreign entity → B1 error (before the taggable and tag-format checks); no tag row changes. |
| `brd tag list <id>` / `tags.list_for(conn, project_id, entity_id)` | Foreign entity → B1 error. |
| `brd tag list` / `tags.counts(conn, project_id)` | Counts only tags on P's entities. A tag used by P once and Q twice is `{"tag": t, "count": 1}`; a tag only Q uses is absent. |

`tags.for_entity(conn, entity_id) -> list[str]` is a new unscoped, unchecked read (the
current `list_for` query) used by `views.document_summary` and by `add`/`remove` for their
return value, so `brd show` of a foreign document still lists its tags.
`documents.add` passes its `project_id` to `tags.add`.

### B7. Comments

| Command / function | Behaviour |
|---|---|
| `brd comment add <id>` / `comments.add(conn, project_id, entity_id, body, author)` | Any foreign entity → B1 error, checked before capability and empty-body checks. A foreign card keeps 2.4's `CardNotFoundError` and message; a foreign issue now raises `IssueNotFoundError`. No comment written. |
| `brd comment list <id>` / `comments.list_for(conn, project_id, entity_id)` | Foreign entity → B1 error. |
| `brd comment delete <comment id>` / `comments.delete(conn, project_id, comment_id)` | Missing comment → `CommentNotFoundError("no comment with id <id>")` as today. A comment on a foreign entity → `CommentNotFoundError` with `no comment with id <id> in this project; it belongs to project <owner name> (<owner id>)`; the comment stays and refs are not reindexed. |

`comments.for_entity(conn, entity_id) -> list[Comment]` is a new unscoped, unchecked read
used by `views.card_detail` / `views.issue_detail`, so `brd show` of a foreign card or
issue still lists its comments.

### B8. `brd show` stays global

`views.detail` still shows any entity of any project with its `project` key [2.4 B7]. It
syncs the documents of the **owning** project against that project's `root_path`
(`owner.root_path`), instead of every document against the current root: for a P entity
this is exactly today's behaviour; for a Q entity, P's documents are not touched and Q's
are never synced against P's root. The `root` argument becomes unnecessary; the planner may
drop it (`views.detail(conn, entity_id)`) and update the one caller
(`src/brd/cli/cards.py:48`). Issue and document lookups inside `detail` pass the owner's id
to `issues.require` / `documents.require`. Output shape is unchanged.

### B9. Export keeps working

`snapshot.export(conn, project_id, root)` passes `project_id` to `documents.sync_all`,
`documents.list_all` and `issues.list_issues`. As a side effect its `issues` and
`documents` sections hold only P's rows. Its `comments`, `tags` and `refs` sections keep
their raw global queries (S5). `snapshot.load` keeps calling `refs.reindex(conn, id)`,
which now resolves stems against the imported entity's project (B4). `snapshot._load_export`
also calls the private `documents._check_unique` for each imported document; it passes its
`project_id`, so the import's duplicate check is per project like `documents.add`'s. No other
export or import behaviour changes.

### B10. Signatures (callers pass `ctx.project.id`)

| Function | New signature |
|---|---|
| `entities.require_in_project` (new) | `(conn, project_id, entity_id) -> str` |
| `issues.require` | `(conn, project_id, issue_id) -> Issue` |
| `issues.list_issues` | `(conn, project_id, status=None)` |
| `issues.update` | `(conn, project_id, issue_id, title=None, body=None)` |
| `issues.close` | `(conn, project_id, issue_id, reason="resolved")` |
| `issues.reopen` | `(conn, project_id, issue_id)` |
| `documents.require` | `(conn, project_id, doc_id) -> Document` |
| `documents.list_all` | `(conn, project_id)` |
| `documents.sync_all` | `(conn, project_id, root)` |
| `documents.update` | `(conn, project_id, root, doc_id, new_path=None, title=None)` |
| `documents.restore` | `(conn, project_id, root, doc_id, force=False)` |
| `documents.delete` | `(conn, project_id, doc_id)` |
| `documents._check_unique` (private; callers `documents.add`, `documents.update`, `snapshot._load_export`) | `(conn, project_id, rel, stem, exclude_id=None)` |
| `refs.resolve` | `(conn, project_id, target)` |
| `refs.reindex_mentions` | `(conn, project_id, stem)` |
| `refs.add_explicit` / `refs.remove_explicit` | `(conn, project_id, src_id, dst_id)` |
| `tags.add` / `tags.remove` | `(conn, project_id, entity_id, tag_list)` |
| `tags.list_for` | `(conn, project_id, entity_id)` |
| `tags.counts` | `(conn, project_id)` |
| `tags.for_entity` (new) | `(conn, entity_id) -> list[str]` |
| `comments.list_for` | `(conn, project_id, entity_id)` |
| `comments.delete` | `(conn, project_id, comment_id)` |
| `comments.for_entity` (new) | `(conn, entity_id) -> list[Comment]` |
| `pretty.text` | `(conn, project_id, value)` |

Unchanged: `refs.reindex(conn, entity_id)`, `issues.open_issue`, `documents.add`,
`comments.add`, `issues.get`, `documents.get`, `pretty.render_detail/render_list/
render_comments`. JSON output shapes of every command are unchanged.

## Tests

Two tiers, as in 2.4:

- **Unit** (`tests/test_project_scope.py`): in-process calls on `pconn`
  (`tests/conftest.py`) with `add_project(pconn, OTHER_PROJECT)` and
  `make_card/make_issue/make_document(..., project_id=OTHER_PROJECT.id)`. Only here can two
  projects share a connection and the database be read directly after a refusal.
- **CLI** (`tests/test_cli.py`, `tests/cli_helpers.py`, `project` fixture): the test opens
  the board file, seeds OTHER_PROJECT and foreign entities, closes it, then invokes. Pins
  that `ctx.project.id` reaches each command and the envelope consumers parse.

| # | Test | Tier | Why this tier |
|---|---|---|---|
| T1 | `entities.require_in_project`: P entity → its kind; missing id → `EntityNotFoundError("no entity with id …")`; Q card / issue / document → `CardNotFoundError` / `IssueNotFoundError` / `DocumentNotFoundError` with message containing `in this project`, `OTHER_PROJECT.name` and `OTHER_PROJECT.id` | Unit | The helper alone; needs two projects |
| T2 | `issues.list_issues(conn, P)` and `(conn, P, "open")` return only P's issues when P and Q both have open issues | Unit | Two projects in one connection |
| T3 | Parametrised over `issues.update` (title), `issues.update` (no fields), `issues.close`, `issues.reopen` on a Q issue: `IssueNotFoundError` naming Q; the Q issue row is byte-identical afterwards (status, close_reason, updated_at) | Unit | Needs to read the row after refusal |
| T4 | `issues.require(conn, P, <missing>)` and `(conn, P, <P card id>)` still say `no issue with id <id>` | Unit | Unchanged error path |
| T5 | `issues.open_issue(conn, P, "t", ref_ids=[<Q card>])` raises `CardNotFoundError` naming Q; `issues`, `entities` and `refs` gain no row | Unit | Pins check-before-insert |
| T6 | `documents.list_all(conn, P)` returns only P's documents; `documents.sync_all(conn, P, root)` returns keys for P's documents only and does not modify Q's row or backup file | Unit | Two projects; reads Q's state directly |
| T7 | Same stem in two projects: with a Q document stem `notes` at `docs/notes.md`, `documents.add(conn, P, tmp_root, tmp_root/"docs/notes.md")` succeeds. A second P document with stem `Notes` (other directory) raises `DuplicateStemError`; the same P path again raises `DuplicatePathError`. `documents.update(conn, P, root, <P doc>, new_path=<file with Q's stem>)` succeeds | Unit | Uniqueness per project needs two projects and real files (`tmp_path` root) |
| T8 | Parametrised over `documents.update` (title), `documents.restore`, `documents.delete` on a Q document: `DocumentNotFoundError` naming Q; the row, backup file, and (for restore) the target path are unchanged | Unit | Refusal writes nothing, checked on disk and in db |
| T9 | `refs.resolve`: P and Q both have stem `notes` → `resolve(conn, P, "notes")` is P's id, `(conn, Q, "notes")` Q's; stem only in Q → `None` for P; `resolve(conn, P, <Q card uuid>)` → Q card id | Unit | The resolution rule itself |
| T10 | `refs.reindex` on a P card describing `[[notes]]` (both projects have `notes`) creates a link ref to P's doc only; on a Q card with the same text, to Q's doc; a P card with `[[<Q card uuid>]]` gets a link ref to the Q card | Unit | Owner-derived resolution |
| T11 | `refs.reindex_mentions(conn, P, "notes")`: a P card and a Q card both mention `[[notes]]` and only a P doc `notes` is (newly) seeded; after the call the P card has the link ref, the Q card's `refs` rows are unchanged. Also covers an issue body, a comment on a P entity, and a P document backup as candidates | Unit | LIKE scans scoped; needs Q rows to stay untouched |
| T12 | `documents.add` in P of stem `notes` does not reindex a Q card that mentions `[[notes]]` (no ref from the Q card to the new P doc) | Unit | End-to-end through the caller |
| T13 | `refs.add_explicit(conn, P, <Q card>, <P card>)` and `(conn, P, <P card>, <Q issue>)` raise the B1 error naming Q, no ref row added; `refs.remove_explicit(conn, P, <Q card>, x)` raises and leaves an existing seeded Q edge; `remove_explicit(conn, P, <P card>, <Q card>)` with a seeded edge removes it | Unit | Source/target rules need two projects |
| T14 | `tags.add/remove/list_for` on a Q document → `DocumentNotFoundError` naming Q, tags table unchanged; on a Q card → `CardNotFoundError` (ownership before `NotTaggableError`); on a P card still `NotTaggableError` | Unit | Ordering of checks |
| T15 | `tags.counts(conn, P)` with tag `x` on one P doc and two Q docs, and tag `y` only on a Q doc → `[{"tag": "x", "count": 1}]` | Unit | Aggregate across two projects |
| T16 | `comments.add` on a Q issue → `IssueNotFoundError` naming Q, no comment row; on a Q document → `DocumentNotFoundError` (not `NotCommentableError`); `comments.list_for(conn, P, <Q issue>)` → `IssueNotFoundError`; `comments.delete(conn, P, <comment on Q card>)` → `CommentNotFoundError` naming Q, comment still present; missing comment → `no comment with id <id>` | Unit | Writes and refusals checked in db |
| T17 | `views.detail` of a Q card / Q issue / Q document still returns its comments, tags and `project` == Q; showing a P entity does not change any Q document row or backup; showing a Q document does not change any P document row | Unit | Show stays global; sync uses the owner's project |
| T18 | `pretty.render_detail` of a Q card whose description is `[[notes]]` (both projects have `notes` with different titles) renders Q's title; `pretty.text(conn, P, "[[notes]]")` renders P's | Unit | Owner-based rendering |
| T19 | `cli.cards.delete_entity(conn, P, <Q issue>)` → `IssueNotFoundError` naming Q; `(conn, P, <Q document>)` → `DocumentNotFoundError` naming Q; both rows remain | Unit | The delete branches |
| T20 | `snapshot.export(conn, P, root)` has no Q issue or Q document and does not sync Q's documents | Unit | Export still compiles and calls scoped functions |
| T21 | Regression: existing `test_issues.py`, `test_documents.py`, `test_refs.py`, `test_tags.py`, `test_comments.py`, `test_pretty.py`, `test_snapshot.py`, `test_project_scope.py`, `test_cli*.py` pass with call sites updated to the new signatures (517 passing at the start of this card) | Unit + CLI | Regression |
| T22 | CLI: with a seeded foreign issue I, foreign document D (with tag `t`) and foreign card F: `brd issue list` excludes I; `brd doc list` excludes D; `brd tag list` has no `t`. `brd issue update I --title x`, `brd issue close I`, `brd issue reopen I`, `brd delete I` → envelope type `IssueNotFoundError`; `brd doc update D`, `brd doc restore D`, `brd delete D`, `brd tag add D x`, `brd tag list D` → `DocumentNotFoundError`; `brd ref add F <P card>`, `brd comment list F` → `CardNotFoundError`; `brd comment add I hi` → `IssueNotFoundError`. Each exits 1 with a message naming `other` | CLI | Proves `ctx.project.id` reaches every command; pins envelope types |
| T23 | CLI: a P `docs/notes.md` registers with `brd doc add` while a Q document with stem `notes` is seeded | CLI | The user-visible "same stem in two projects" promise |

## Out of scope

- Export/import scoping beyond what B9 implies: the `comments`, `tags`, `refs` sections of
  `snapshot.export`, the export format, and import placement/validation (S5).
- Lifting the same-project check on `ref add` / `issue open --ref` targets (S4), and the
  `blockers` output (S4).
- Filtering or labelling `refs` / `referenced_by` lists by project.
- Card listings and card mutations, blocker targets, `issue open --blocks` (done in 2.4).
- Moving to one `brd.db`, project resolution without the marker, `forget`, and the
  all-commands leak guard [P Testing L255-257] (S3 / story level).
- `--pretty` rendering of the owning project.
- Any schema change.

## Notes for the planner

- Put `require_in_project` in `src/brd/entities.py` (it already imports `db`; `issues`,
  `documents`, `refs`, `tags` and `comments` all import `entities`), mapping kind →
  error class; this avoids an import cycle through `core`.
- `list_issues` must `SELECT issues.*` and qualify `ORDER BY issues.created_at,
  issues.rowid` because the scope join brings `entities.id`. Bind the project before the
  status. Documents carry their own `project_id` column; filtering with
  `WHERE documents.project_id = ?` or `db.in_project('documents.id')` are equivalent —
  prefer the helper for consistency with [P §2 L109].
- `reindex_mentions` scans: `cards` with `in_project('cards.id')`, `issues` with
  `in_project('issues.id')`, `comments` with `in_project('comments.entity_id')`, and the
  documents loop filtered to P.
- `refs.reindex` derives the project with one lookup of `entities.project_id` for
  `entity_id`; if the entity is unknown, stem links resolve to nothing.
- Existing tests that call changed signatures are in `tests/test_issues.py`,
  `test_documents.py`, `test_refs.py`, `test_tags.py`, `test_comments.py`,
  `test_pretty.py`, `test_snapshot.py`, `test_project_scope.py` and `test_cli*.py`. Update
  each in the task that changes the signature, passing `PROJECT.id`, so the suite stays
  green task by task.
- `cli.cards.delete_entity`'s issue branch calls `issues.require(conn, project_id, id)`
  before `entities.delete`; its document branch calls `documents.delete(conn, project_id,
  id)`. The "no card, issue, or document" message for an unknown id stays.
- `OTHER_PROJECT.root_path` is `/other` (does not exist): syncing a Q document reports
  `missing` (backup present), which T17 may rely on.
- Verification: `uv run pytest`. No typecheck or lint is configured.
