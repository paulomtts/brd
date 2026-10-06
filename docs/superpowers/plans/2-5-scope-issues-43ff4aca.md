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

---

# 2.5 Scope issues, documents and [[stem]] links to the current project Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Issue, document, ref, tag and comment commands only see and change entities of the current project (`ctx.project`), `[[stem]]` links resolve within the project that owns the text, and every refusal names the owning project.

**Architecture:** One new gate, `entities.require_in_project(conn, project_id, entity_id) -> str`, raises the kind-specific `*NotFoundError` naming the owner. `core._require_in_project` reuses its message builder, `entities.foreign_message`. Every listing and scan (`issues.list_issues`, `documents.list_all`/`_check_unique`, `refs.resolve`'s stem branch, `refs.reindex_mentions`, `tags.counts`) filters through the existing `db.in_project(id_column)` join. `refs.reindex` and the `--pretty` renderers work out the project from the entity that owns the text. Changed functions take `project_id: str` as a required positional parameter, second after `conn`. The CLI passes `ctx.project.id`.

**Tech Stack:** Python ≥ 3.12, sqlite3, typer, pytest, run through `uv`.

**Spec:** `docs/superpowers/specs/2-5-scope-issues-43ff4aca.md` (reproduced above this plan).

## Global Constraints

- New project parameters are a **required** positional `project_id: str`, second after `conn`. No fallback to "the board's only project".
- The foreign-entity message is exactly `no <kind> with id <id> in this project; it belongs to project <owner name> (<owner id>)`, raised as `CardNotFoundError` / `IssueNotFoundError` / `DocumentNotFoundError` for card / issue / document. A comment on a foreign entity raises `CommentNotFoundError` with `no comment with id <comment id> in this project; it belongs to project <owner name> (<owner id>)`.
- Missing ids keep today's messages: `no entity with id <id>`, `no issue with id <id>`, `no document with id <id>`, `no comment with id <id>`, `no card, issue, or document with id <id>`.
- Ownership is checked before capability, tag-format and empty-body checks.
- A refused command writes nothing: no row, no `updated_at`, no backup file, no restored source file, no `refs` reindex.
- Scoped queries go through `db.in_project(...)`; no new hand-written `entities.project_id` join.
- `[[<uuid>]]` links, `brd show`, `refs.outgoing`/`refs.incoming`, `issues.get`, `documents.get`, `issues.blocks_of` stay global.
- Do not change the schema; `SCHEMA_VERSION` stays 4.
- JSON output shapes of every command are unchanged.
- `snapshot.export`'s `comments`, `tags` and `refs` sections keep their raw global queries (S5).
- Verification: `uv run pytest` (517 passing at the start). No typecheck or lint.
- Do not touch the stale `TypeError` lambdas in `tests/test_project_scope.py:36-56`.

## Review Focus

- `brd issue open --ref <P id> --ref <foreign id>`: the command fails and writes no issue, entity or ref row. Pinned by `open_issue_mixed_refs` in `SCOPED_REFUSED` (Task 2).
- Renaming a P document to a stem a Q document also has (`brd doc update --path`): Q texts mentioning that stem are not reindexed and gain no ref. Pinned by `test_adding_or_renaming_a_document_rescans_only_its_project` (Task 4).
- A `[[stem]]` that only another project has, written in a comment on a P card: no ref, and `--pretty` shows it `(unresolved)`. Pinned by `test_a_stem_only_another_project_has_stays_unresolved` (Task 4).
- `brd tag add <foreign doc> "bad tag"`: the foreign-document error, not `InvalidTagError`. Pinned by `tag_add_invalid_tag` in `SCOPED_REFUSED` (Task 6).
- `brd comment add <foreign issue> "   "`: the foreign-issue error, not `EmptyCommentError`. Pinned by `comments_add_foreign_issue_empty_body` in `SCOPED_REFUSED` (Task 7).

## File Structure

- `src/brd/entities.py`: add `foreign_message`, `require_in_project`.
- `src/brd/core.py`: `_require_in_project` builds its message with `entities.foreign_message`.
- `src/brd/issues.py`: `require`, `list_issues`, `_set`, `update`, `close`, `reopen` take `project_id`. `open_issue` checks `--ref` targets before inserting.
- `src/brd/documents.py`: `require`, `list_all`, `sync_all`, `_check_unique`, `update`, `restore`, `delete` take `project_id`. `add` passes it on.
- `src/brd/refs.py`: `resolve`, `reindex_mentions`, `add_explicit`, `remove_explicit` take `project_id`. `reindex` looks up the owner.
- `src/brd/tags.py`: `list_for`, `add`, `remove`, `counts` take `project_id`. New `for_entity`.
- `src/brd/comments.py`: `add` checks ownership first. `list_for` and `delete` take `project_id`. New `for_entity`.
- `src/brd/pretty.py`: `text` takes `project_id`. The renderers use the owner of the rendered entity.
- `src/brd/views.py`: `detail(conn, entity_id)` syncs the owner's documents against the owner's root. Comments and tags are read with the unscoped `for_entity` functions.
- `src/brd/snapshot.py`: `export` and `_load_export` pass `project_id`.
- `src/brd/cli/{cards,issues,docs,refs,tags,comments}.py`: pass `ctx.project.id`.
- Tests: `tests/test_project_scope.py` (unit), `tests/test_cli.py` (CLI), and call-site updates in `tests/test_issues.py`, `test_documents.py`, `test_refs.py`, `test_tags.py`, `test_comments.py`, `test_entities.py`, `test_core.py`.

---

### Task 1: `entities.require_in_project`, the foreign-entity error

**Files:**
- Modify: `src/brd/entities.py:1-4` (imports), add functions after `require` (`:21-25`)
- Modify: `src/brd/core.py:102-112` (`_require_in_project`)
- Test: `tests/test_project_scope.py`

**Interfaces:**
- Consumes: `db.owner_of(conn, entity_id) -> Project | None` (`src/brd/db.py:486`).
- Produces: `entities.foreign_message(what: str, item_id: str, owner: Project) -> str`; `entities.require_in_project(conn, project_id: str, entity_id: str) -> str` (returns the kind).

- [ ] **Step 1: Write the failing tests**

In `tests/test_project_scope.py`, change the imports at the top to:

```python
import re
import sqlite3

import pytest

from brd import comments, core, db, documents, entities, issues, snapshot, views
from brd.cli import cards as cli_cards
from brd.errors import (
    CardNotFoundError,
    DocumentNotFoundError,
    EntityNotFoundError,
    InvalidBlockerError,
    IssueNotFoundError,
)
from brd.models import Card
```

(the `from tests.factories import (...)` block below stays as it is). Append at the end of the file:

```python
@pytest.mark.parametrize(
    ("entity_id", "error", "what"),
    [
        ("q1", CardNotFoundError, "card"),
        ("qi", IssueNotFoundError, "issue"),
        ("qd", DocumentNotFoundError, "document"),
    ],
)
def test_require_in_project_names_the_owner_of_a_foreign_entity(two, entity_id, error, what):
    with pytest.raises(error, match=_foreign(entity_id, what)):
        entities.require_in_project(two, P, entity_id)


def test_require_in_project_returns_the_kind_of_an_own_entity(two):
    make_issue(two, "pi")
    make_document(two, "pd", "pnotes")
    assert entities.require_in_project(two, P, "p1") == "card"
    assert entities.require_in_project(two, P, "pi") == "issue"
    assert entities.require_in_project(two, P, "pd") == "document"
    assert entities.require_in_project(two, Q, "q1") == "card"


def test_require_in_project_on_a_missing_id_is_unchanged(two):
    with pytest.raises(EntityNotFoundError, match=r"^no entity with id nope$") as raised:
        entities.require_in_project(two, P, "nope")
    assert type(raised.value) is EntityNotFoundError
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_project_scope.py -k require_in_project -v`
Expected: FAIL with `AttributeError: module 'brd.entities' has no attribute 'require_in_project'`.

- [ ] **Step 3: Implement**

In `src/brd/entities.py`, replace the imports (lines 1-4) with:

```python
import sqlite3

from brd import db
from brd.errors import (
    BrdError,
    CardNotFoundError,
    DocumentNotFoundError,
    EntityNotFoundError,
    IssueNotFoundError,
)
from brd.models import Project
```

Below `_KIND_TABLES = {...}` add:

```python
_NOT_FOUND = {
    "card": CardNotFoundError,
    "issue": IssueNotFoundError,
    "document": DocumentNotFoundError,
}
```

Directly after `def require(...)` add:

```python
def foreign_message(what: str, item_id: str, owner: Project) -> str:
    return (
        f"no {what} with id {item_id} in this project; "
        f"it belongs to project {owner.name} ({owner.id})"
    )


def require_in_project(conn: sqlite3.Connection, project_id: str, entity_id: str) -> str:
    """The entity's kind, refusing one another project owns. Commands act on
    the current project only; the error names the owner, so an id copied
    from another project's board says where it lives."""
    kind = require(conn, entity_id)
    owner = db.owner_of(conn, entity_id)
    if owner is not None and owner.id != project_id:
        raise _NOT_FOUND[kind](foreign_message(kind, entity_id, owner))
    return kind
```

In `src/brd/core.py`, replace the body of `_require_in_project` (lines 102-112) with:

```python
def _require_in_project(
    conn: sqlite3.Connection, project_id: str, entity_id: str, what: str
) -> None:
    # Commands act on the current project only. Name the owner, so an id
    # copied from another project's board says where it lives.
    owner = db.owner_of(conn, entity_id)
    if owner is not None and owner.id != project_id:
        raise CardNotFoundError(entities.foreign_message(what, entity_id, owner))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_project_scope.py -v`
Expected: PASS. The 2.4 `REFUSED` cases still pass with the shared message.

Run: `uv run pytest`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/brd/entities.py src/brd/core.py tests/test_project_scope.py
git commit -m "Add entities.require_in_project for the foreign-entity error"
```

---

### Task 2: Scoped issues: listing, update/close/reopen, `open --ref`, delete

**Files:**
- Modify: `src/brd/issues.py:51-141`
- Modify: `src/brd/views.py:89` (inside `detail`)
- Modify: `src/brd/snapshot.py:16` (inside `export`)
- Modify: `src/brd/cli/issues.py:38,53,64,73`
- Modify: `src/brd/cli/cards.py:4,114-124` (imports, `delete_entity`)
- Test: `tests/test_project_scope.py`, `tests/test_cli.py`, call sites in `tests/test_issues.py`, `tests/test_core.py:662`

**Interfaces:**
- Consumes: `entities.require_in_project(conn, project_id, entity_id) -> str` (Task 1); `db.in_project(id_column) -> str`.
- Produces: `issues.require(conn, project_id, issue_id) -> Issue`; `issues.list_issues(conn, project_id, status=None) -> list[Issue]`; `issues.update(conn, project_id, issue_id, title=None, body=None) -> Issue`; `issues.close(conn, project_id, issue_id, reason="resolved") -> Issue`; `issues.reopen(conn, project_id, issue_id) -> Issue`. Test helpers used by later tasks: `SCOPED_REFUSED` list and `test_scoped_refusal_names_the_owner_and_writes_nothing` in `tests/test_project_scope.py`; `_state(conn)` now also covers `documents`, `tags`, `refs`; in `tests/test_cli.py` the `foreign_entities` fixture (returns `{"card": FOREIGN, "issue": FOREIGN_ISSUE, "document": FOREIGN_DOC}`; the document has stem `notes` and tag `t`) and `_refused(*args, error_type="CardNotFoundError")`.

- [ ] **Step 1: Write the failing unit tests**

In `tests/test_project_scope.py`, replace `_state` with:

```python
def _state(conn):
    return {
        table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2")]
        for table in (
            "entities", "cards", "issues", "documents", "blocked_by", "comments", "tags", "refs"
        )
    }
```

Append at the end of the file:

```python
def test_list_issues_returns_only_the_projects_issues(two):
    make_issue(two, "pi")
    make_issue(two, "pi-closed", status="closed")
    assert [i.id for i in issues.list_issues(two, P)] == ["pi", "pi-closed"]
    assert [i.id for i in issues.list_issues(two, P, "open")] == ["pi"]
    assert [i.id for i in issues.list_issues(two, Q)] == ["qi"]


def test_require_issue_returns_the_projects_issue(two):
    make_issue(two, "pi")
    assert issues.require(two, P, "pi").id == "pi"


@pytest.mark.parametrize("missing", ["nope", "p1", "q1"])
def test_require_issue_on_a_missing_or_non_issue_id_is_unchanged(two, missing):
    with pytest.raises(IssueNotFoundError, match=rf"^no issue with id {missing}$"):
        issues.require(two, P, missing)


SCOPED_REFUSED = [
    pytest.param(
        lambda c: issues.update(c, P, "qi", title="x"), IssueNotFoundError, "qi", "issue",
        id="issue_update",
    ),
    pytest.param(
        lambda c: issues.update(c, P, "qi"), IssueNotFoundError, "qi", "issue",
        id="issue_update_no_fields",
    ),
    pytest.param(
        lambda c: issues.update(c, P, "qi", body="[[qnotes]]"), IssueNotFoundError, "qi",
        "issue", id="issue_update_body",
    ),
    pytest.param(
        lambda c: issues.close(c, P, "qi"), IssueNotFoundError, "qi", "issue", id="issue_close"
    ),
    pytest.param(
        lambda c: issues.reopen(c, P, "qi"), IssueNotFoundError, "qi", "issue",
        id="issue_reopen",
    ),
    pytest.param(
        lambda c: issues.open_issue(c, P, "t", ref_ids=["q1"]), CardNotFoundError, "q1", "card",
        id="open_issue_foreign_ref",
    ),
    pytest.param(
        lambda c: issues.open_issue(c, P, "t", ref_ids=["p1", "qd"]), DocumentNotFoundError,
        "qd", "document", id="open_issue_mixed_refs",
    ),
    pytest.param(
        lambda c: cli_cards.delete_entity(c, P, "qi", False), IssueNotFoundError, "qi", "issue",
        id="delete_entity_issue",
    ),
]


@pytest.mark.parametrize(("call", "error", "foreign_id", "what"), SCOPED_REFUSED)
def test_scoped_refusal_names_the_owner_and_writes_nothing(two, call, error, foreign_id, what):
    before = _state(two)
    with pytest.raises(error, match=_foreign(foreign_id, what)):
        call(two)
    assert _state(two) == before
```

In the same file, in `test_detail_is_global_and_names_the_owner`'s parameter list, change
`lambda c, root: views.issue_detail(c, issues.require(c, "qi"))` to
`lambda c, root: views.issue_detail(c, issues.require(c, Q, "qi"))`.

- [ ] **Step 2: Write the failing CLI test**

In `tests/test_cli.py`, change the factories import (line 10) to:

```python
from tests.factories import OTHER_PROJECT, add_project, make_card, make_document, make_issue
```

Replace `_refused` with:

```python
def _refused(*args, error_type: str = "CardNotFoundError") -> None:
    result = invoke(*args)
    assert result.exit_code == 1, result.output
    error = json.loads(result.stdout)["error"]
    assert error["type"] == error_type
    assert f"belongs to project {OTHER_PROJECT.name} ({OTHER_PROJECT.id})" in error["message"]
```

Directly after the `foreign` fixture add:

```python
FOREIGN_ISSUE = "f1f1f1f1-0000-4000-8000-000000000000"
FOREIGN_DOC = "f2f2f2f2-0000-4000-8000-000000000000"


@pytest.fixture
def foreign_entities(project, foreign):
    """Besides card FOREIGN, the other project owns the open issue
    FOREIGN_ISSUE and the document FOREIGN_DOC (stem `notes`, tag `t`)."""
    conn = db.connect(paths.project_db_path(project))
    try:
        make_issue(conn, FOREIGN_ISSUE, title="Foreign issue", project_id=OTHER_PROJECT.id)
        make_document(
            conn, FOREIGN_DOC, "notes", content="foreign body", project_id=OTHER_PROJECT.id
        )
        conn.execute("INSERT INTO tags (entity_id, tag) VALUES (?, 't')", (FOREIGN_DOC,))
        conn.commit()
    finally:
        conn.close()
    return {"card": foreign, "issue": FOREIGN_ISSUE, "document": FOREIGN_DOC}
```

Append at the end of the file:

```python
def test_issue_commands_are_scoped_to_this_project(foreign_entities):
    issue = foreign_entities["issue"]
    mine = ok("issue", "open", "--title", "mine")["id"]
    assert [i["id"] for i in ok("issue", "list")] == [mine]
    assert [i["id"] for i in ok("issue", "list", "--status", "open")] == [mine]
    _refused("issue", "update", issue, "--title", "x", error_type="IssueNotFoundError")
    _refused("issue", "close", issue, error_type="IssueNotFoundError")
    _refused("issue", "reopen", issue, error_type="IssueNotFoundError")
    _refused("delete", issue, error_type="IssueNotFoundError")
    _refused("issue", "open", "--title", "q", "--ref", foreign_entities["card"])
    shown = ok("show", issue)
    assert (shown["title"], shown["status"]) == ("Foreign issue", "open")
    assert [i["id"] for i in ok("issue", "list")] == [mine]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_project_scope.py tests/test_cli.py -k "issue or scoped_refusal" -v`
Expected: FAIL. The new tests fail with `TypeError` (extra positional argument), `DID NOT RAISE`, or a regex mismatch (`no issue with id 11111111-...`). `test_issue_commands_are_scoped_to_this_project` fails on the `issue list` assertion.

- [ ] **Step 4: Implement `issues.py`**

In `src/brd/issues.py`, replace `require` and `list_issues` with:

```python
def require(conn: sqlite3.Connection, project_id: str, issue_id: str) -> Issue:
    issue = get(conn, issue_id)
    if issue is None:
        raise IssueNotFoundError(f"no issue with id {issue_id}")
    entities.require_in_project(conn, project_id, issue_id)
    return issue


def list_issues(
    conn: sqlite3.Connection, project_id: str, status: str | None = None
) -> list[Issue]:
    if status is not None and status not in STATUSES:
        raise InvalidStatusError(
            f"invalid issue status {status!r}; use one of {', '.join(STATUSES)}"
        )
    query = f"SELECT issues.* FROM issues {db.in_project('issues.id')}"
    params = [project_id]
    if status is not None:
        query += " WHERE issues.status = ?"
        params.append(status)
    rows = conn.execute(query + " ORDER BY issues.created_at, issues.rowid", params).fetchall()
    return [_row(row) for row in rows]
```

In `open_issue`, replace

```python
    for ref_id in ref_ids:
        entities.require(conn, ref_id)
```

with

```python
    for ref_id in ref_ids:
        # Ref targets stay in the current project until S4 lifts the check.
        entities.require_in_project(conn, project_id, ref_id)
```

Replace `_set`, `update`, `close` and `reopen` with:

```python
def _set(conn: sqlite3.Connection, project_id: str, issue_id: str, **fields) -> Issue:
    require(conn, project_id, issue_id)
    fields["updated_at"] = _now()
    columns = ", ".join(f"{key} = ?" for key in fields)
    conn.execute(f"UPDATE issues SET {columns} WHERE id = ?", [*fields.values(), issue_id])
    conn.commit()
    return require(conn, project_id, issue_id)


def update(
    conn: sqlite3.Connection,
    project_id: str,
    issue_id: str,
    title: str | None = None,
    body: str | None = None,
) -> Issue:
    fields = {key: value for key, value in (("title", title), ("body", body)) if value is not None}
    if not fields:
        return require(conn, project_id, issue_id)
    issue = _set(conn, project_id, issue_id, **fields)
    if body is not None:
        refs.reindex(conn, issue_id)
    return issue


def close(
    conn: sqlite3.Connection, project_id: str, issue_id: str, reason: str = "resolved"
) -> Issue:
    if reason not in CLOSE_REASONS:
        raise InvalidCloseReasonError(
            f"invalid close reason {reason!r}; use one of {', '.join(CLOSE_REASONS)}"
        )
    return _set(conn, project_id, issue_id, status="closed", close_reason=reason)


def reopen(conn: sqlite3.Connection, project_id: str, issue_id: str) -> Issue:
    return _set(conn, project_id, issue_id, status="open", close_reason=None)
```

- [ ] **Step 5: Update the callers**

`src/brd/views.py`, in `detail`: change `shown = issue_detail(conn, issues.require(conn, entity_id))` to

```python
        shown = issue_detail(conn, issues.require(conn, owner.id, entity_id))
```

`src/brd/snapshot.py`, in `export`: change `issues.list_issues(conn)` to `issues.list_issues(conn, project_id)`.

`src/brd/cli/issues.py`:

```python
# list_cmd
        lambda ctx: [
            views.issue_detail(ctx.conn, i)
            for i in issues.list_issues(ctx.conn, ctx.project.id, status)
        ],
# update
        lambda ctx: views.issue_detail(
            ctx.conn,
            issues.update(ctx.conn, ctx.project.id, issue_id, title=title, body=body),
        ),
# close
    run(
        pretty,
        lambda ctx: views.issue_detail(
            ctx.conn, issues.close(ctx.conn, ctx.project.id, issue_id, reason)
        ),
    )
# reopen
    run(
        pretty,
        lambda ctx: views.issue_detail(ctx.conn, issues.reopen(ctx.conn, ctx.project.id, issue_id)),
    )
```

`src/brd/cli/cards.py`: change the import to `from brd import core, db, documents, entities, issues, output, views` and the end of `delete_entity` to:

```python
    if kind == "document":
        documents.delete(conn, entity_id)
        return [entity_id]
    issues.require(conn, project_id, entity_id)
    entities.delete(conn, entity_id)
    return [entity_id]
```

- [ ] **Step 6: Update existing call sites in tests**

```bash
sed -i -E 's/issues\.(require|list_issues|update|close|reopen)\(pconn, /issues.\1(pconn, PROJECT.id, /g; s/issues\.list_issues\(pconn\)/issues.list_issues(pconn, PROJECT.id)/g' tests/test_issues.py
sed -i 's/    issues.close(conn, issue.id)$/    issues.close(conn, PROJECT.id, issue.id)/' tests/test_core.py
```

Check with `grep -nE "issues\.(require|list_issues|update|close|reopen)\(" tests/test_issues.py tests/test_core.py`: every hit passes `PROJECT.id` second.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_project_scope.py tests/test_cli.py tests/test_issues.py -v`
Expected: PASS.

Run: `uv run pytest`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/brd/issues.py src/brd/views.py src/brd/snapshot.py src/brd/cli/issues.py src/brd/cli/cards.py tests/test_project_scope.py tests/test_cli.py tests/test_issues.py tests/test_core.py
git commit -m "Scope issue listing and mutations to the current project"
```

---

### Task 3: Scoped documents: listing, sync, per-project uniqueness, mutations, and `show` syncing the owner's documents

**Files:**
- Modify: `src/brd/documents.py:88-253` (`require`, `list_all`, `_check_unique`, `add`, `sync_all`, `update`, `restore`, `delete`)
- Modify: `src/brd/views.py:79-92` (`detail`)
- Modify: `src/brd/snapshot.py:11-28` (`export`), `:108` (`_load_export`)
- Modify: `src/brd/cli/docs.py:46-48,70-72,87`
- Modify: `src/brd/cli/cards.py:2,46-50,122-124` (drop `Path` import, `show`, `delete_entity`)
- Test: `tests/test_project_scope.py`, `tests/test_cli.py`, call sites in `tests/test_documents.py`

**Interfaces:**
- Consumes: `entities.require_in_project` (Task 1); `issues.require(conn, project_id, issue_id)`, `issues.list_issues(conn, project_id)` (Task 2); `foreign_entities`, `_refused(..., error_type=...)` in `tests/test_cli.py` (Task 2).
- Produces: `documents.require(conn, project_id, doc_id) -> Document`; `documents.list_all(conn, project_id) -> list[Document]`; `documents.sync_all(conn, project_id, root) -> dict[str, SyncResult]`; `documents._check_unique(conn, project_id, rel, stem, exclude_id=None) -> None`; `documents.update(conn, project_id, root, doc_id, new_path=None, title=None) -> tuple[Document, SyncResult]`; `documents.restore(conn, project_id, root, doc_id, force=False) -> Document`; `documents.delete(conn, project_id, doc_id) -> None`; `views.detail(conn, entity_id) -> dict` (no `root`). Test helpers used later: the `root` fixture, `_write(root, rel, text) -> Path` and `_doc_state(conn, doc_id)` in `tests/test_project_scope.py`.

- [ ] **Step 1: Write the failing unit tests**

In `tests/test_project_scope.py`, add `from pathlib import Path` after `import sqlite3`, and extend the errors import to:

```python
from brd.errors import (
    CardNotFoundError,
    DocumentNotFoundError,
    DuplicatePathError,
    DuplicateStemError,
    EntityNotFoundError,
    InvalidBlockerError,
    IssueNotFoundError,
)
```

Replace `test_detail_is_global_and_names_the_owner` and `test_detail_of_a_missing_id_is_unchanged` (with the parametrize decorator) with:

```python
@pytest.mark.parametrize(
    ("entity_id", "owner", "expected"),
    [
        ("p1", PROJECT, lambda c: views.card_detail(c, db.get_card(c, "p1"))),
        ("q1", OTHER_PROJECT, lambda c: views.card_detail(c, db.get_card(c, "q1"))),
        ("qi", OTHER_PROJECT, lambda c: views.issue_detail(c, issues.require(c, Q, "qi"))),
        (
            "qd",
            OTHER_PROJECT,
            lambda c: views.document_detail(
                c,
                documents.require(c, Q, "qd"),
                documents.sync(c, Path(OTHER_PROJECT.root_path), documents.require(c, Q, "qd")),
            ),
        ),
    ],
    ids=["own_card", "foreign_card", "foreign_issue", "foreign_document"],
)
def test_detail_is_global_and_names_the_owner(two, entity_id, owner, expected):
    shown = views.detail(two, entity_id)
    assert shown.pop("project") == {"id": owner.id, "name": owner.name}
    assert shown == expected(two)


def test_detail_of_a_missing_id_is_unchanged(two):
    with pytest.raises(CardNotFoundError, match=r"^no card, issue, or document with id nope$"):
        views.detail(two, "nope")
```

Append at the end of the file:

```python
@pytest.fixture
def root(tmp_path):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    return repo


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _doc_state(conn, doc_id):
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    backup = documents.backup_path(conn, doc_id)
    return (tuple(row) if row else None, backup.read_text() if backup.is_file() else None)


def test_require_document_on_a_missing_or_non_document_id_is_unchanged(two):
    for missing in ("nope", "p1"):
        with pytest.raises(DocumentNotFoundError, match=rf"^no document with id {missing}$"):
            documents.require(two, P, missing)


def test_list_and_sync_all_cover_only_the_projects_documents(two, root):
    make_document(two, "pd", "pnotes", content="old")
    _write(root, "docs/pnotes.md", "new")
    _write(root, "docs/qnotes.md", "changed")  # Q's source path, under P's root
    q_before = _doc_state(two, "qd")
    assert [d.id for d in documents.list_all(two, P)] == ["pd"]
    assert [d.id for d in documents.list_all(two, Q)] == ["qd"]
    results = documents.sync_all(two, P, root)
    assert {k: v.source_state for k, v in results.items()} == {"pd": "updated"}
    assert _doc_state(two, "qd") == q_before


def test_document_uniqueness_is_per_project(two, root):
    make_document(two, "qn", "notes", project_id=Q)  # Q's docs/notes.md
    mine = documents.add(two, P, root, _write(root, "docs/notes.md", "p"))
    assert (mine.source_path, mine.stem) == ("docs/notes.md", "notes")
    with pytest.raises(DuplicateStemError):
        documents.add(two, P, root, _write(root, "other/Notes.md", ""))
    with pytest.raises(DuplicatePathError):
        documents.add(two, P, root, root / "docs" / "notes.md")
    second = documents.add(two, P, root, _write(root, "docs/second.md", ""))
    moved, _ = documents.update(
        two, P, root, second.id, new_path=_write(root, "elsewhere/qnotes.md", "")
    )
    assert moved.stem == "qnotes"  # Q's qd has this stem too


DOC_REFUSED = [
    pytest.param(
        lambda c, root: documents.update(c, P, root, "qd", title="x"), id="update_title"
    ),
    pytest.param(
        lambda c, root: documents.update(c, P, root, "qd", new_path=root / "docs" / "moved.md"),
        id="update_path",
    ),
    pytest.param(lambda c, root: documents.update(c, P, root, "qd"), id="update_sync_only"),
    pytest.param(
        lambda c, root: documents.restore(c, P, root, "qd", force=True), id="restore"
    ),
    pytest.param(lambda c, root: documents.delete(c, P, "qd"), id="delete"),
    pytest.param(
        lambda c, root: cli_cards.delete_entity(c, P, "qd", False), id="delete_entity"
    ),
]


@pytest.mark.parametrize("call", DOC_REFUSED)
def test_a_foreign_document_is_refused_and_untouched(two, root, call):
    _write(root, "docs/moved.md", "moved")
    _write(root, "docs/qnotes.md", "changed")
    before = _doc_state(two, "qd")
    with pytest.raises(DocumentNotFoundError, match=_foreign("qd", "document")):
        call(two, root)
    assert _doc_state(two, "qd") == before
    assert (root / "docs" / "qnotes.md").read_text() == "changed"


def test_show_syncs_only_the_owning_projects_documents(two, root):
    two.execute("UPDATE projects SET root_path = ? WHERE id = ?", (str(root), P))
    two.commit()
    make_document(two, "pd", "pnotes", content="old")
    _write(root, "docs/pnotes.md", "new")
    _write(root, "docs/qnotes.md", "changed")
    p_before, q_before = _doc_state(two, "pd"), _doc_state(two, "qd")
    assert views.detail(two, "qd")["source_state"] == "missing"  # nothing under /other
    assert _doc_state(two, "pd") == p_before
    views.detail(two, "p1")
    assert _doc_state(two, "qd") == q_before
    assert _doc_state(two, "pd") != p_before  # P's own documents are synced


def test_export_holds_only_the_projects_issues_and_documents(two, root):
    make_issue(two, "pi")
    make_document(two, "pd", "pnotes")
    _write(root, "docs/qnotes.md", "changed")
    q_before = _doc_state(two, "qd")
    data = snapshot.export(two, P, root)
    assert [i["id"] for i in data["issues"]] == ["pi"]
    assert [d["id"] for d in data["documents"]] == ["pd"]
    assert _doc_state(two, "qd") == q_before
```

- [ ] **Step 2: Write the failing CLI test**

Append to `tests/test_cli.py`:

```python
def test_document_commands_are_scoped_to_this_project(project, foreign_entities):
    doc = foreign_entities["document"]
    (project / "docs").mkdir()
    (project / "docs" / "notes.md").write_text("mine")
    mine = ok("doc", "add", "docs/notes.md")["id"]  # the other project also has `notes`
    assert [d["id"] for d in ok("doc", "list")] == [mine]
    _refused("doc", "update", doc, "--title", "x", error_type="DocumentNotFoundError")
    _refused("doc", "restore", doc, error_type="DocumentNotFoundError")
    _refused("delete", doc, error_type="DocumentNotFoundError")
    assert ok("show", doc)["title"] == "notes"
    assert (project / "docs" / "notes.md").read_text() == "mine"
    assert [d["id"] for d in ok("export")["documents"]] == [mine]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_project_scope.py tests/test_cli.py -k "document or detail or export or sync" -v`
Expected: FAIL. The unit tests fail with `TypeError` (`views.detail` / `documents.*` argument count) or `DID NOT RAISE`. The CLI test fails on `doc add` with `DuplicatePathError`.

- [ ] **Step 4: Implement `documents.py`**

In `src/brd/documents.py`, replace `require` and `list_all` with:

```python
def require(conn: sqlite3.Connection, project_id: str, doc_id: str) -> Document:
    doc = get(conn, doc_id)
    if doc is None:
        raise DocumentNotFoundError(f"no document with id {doc_id}")
    entities.require_in_project(conn, project_id, doc_id)
    return doc


def list_all(conn: sqlite3.Connection, project_id: str) -> list[Document]:
    rows = conn.execute(
        f"SELECT documents.* FROM documents {db.in_project('documents.id')} "
        "ORDER BY documents.created_at, documents.source_path",
        (project_id,),
    ).fetchall()
    return [_row(row) for row in rows]
```

Replace `_check_unique` with:

```python
def _check_unique(
    conn: sqlite3.Connection,
    project_id: str,
    rel: str,
    stem: str,
    exclude_id: str | None = None,
) -> None:
    # Per project, like the schema's UNIQUE (project_id, ...) constraints.
    scoped = f"FROM documents {db.in_project('documents.id')} WHERE documents.id IS NOT ?"
    row = conn.execute(
        f"SELECT documents.id {scoped} AND documents.source_path = ?",
        (project_id, exclude_id, rel),
    ).fetchone()
    if row:
        raise DuplicatePathError(f"{rel} is already registered as document {row['id']}")
    row = conn.execute(
        f"SELECT documents.source_path {scoped} AND documents.stem = ?",  # stem is NOCASE
        (project_id, exclude_id, stem),
    ).fetchone()
    if row:
        raise DuplicateStemError(
            f"a document named {stem!r} is already registered ({row['source_path']}); "
            f"rename one of the files so [[{stem}]] stays unambiguous"
        )
```

In `add`, change `_check_unique(conn, rel, stem)` to `_check_unique(conn, project_id, rel, stem)`.

Replace `sync_all`, `update`, `restore` and `delete` with:

```python
def sync_all(conn: sqlite3.Connection, project_id: str, root: Path) -> dict[str, SyncResult]:
    return {doc.id: sync(conn, root, doc) for doc in list_all(conn, project_id)}


def update(
    conn: sqlite3.Connection,
    project_id: str,
    root: Path,
    doc_id: str,
    new_path: Path | None = None,
    title: str | None = None,
) -> tuple[Document, SyncResult]:
    doc = require(conn, project_id, doc_id)
    old_stem = doc.stem
    if new_path is not None:
        rel, stem = _validate_path(root, new_path)
        _check_unique(conn, project_id, rel, stem, exclude_id=doc.id)
        conn.execute(
            "UPDATE documents SET source_path = ?, stem = ?, updated_at = ? WHERE id = ?",
            (rel, stem, _now(), doc.id),
        )
    if title is not None:
        conn.execute(
            "UPDATE documents SET title = ?, updated_at = ? WHERE id = ?",
            (title, _now(), doc.id),
        )
    conn.commit()
    doc = require(conn, project_id, doc_id)
    result = sync(conn, root, doc)
    if doc.stem.lower() != old_stem.lower():
        refs.reindex_mentions(conn, old_stem)
        refs.reindex_mentions(conn, doc.stem)
    return require(conn, project_id, doc_id), result


def restore(
    conn: sqlite3.Connection, project_id: str, root: Path, doc_id: str, force: bool = False
) -> Document:
    doc = require(conn, project_id, doc_id)
    backup = backup_path(conn, doc.id)
    if not backup.is_file():
        raise DocumentContentLostError(f"no backup exists for document {doc_id}")
    source = _source(root, doc)
    if source.is_file():
        if _hash(source.read_bytes()) == doc.content_hash:
            return doc
        if not force:
            raise RestoreConflictError(
                f"{doc.source_path} exists and differs from brd's backup; "
                "pass --force to overwrite it"
            )
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(backup.read_bytes())
    return doc


def delete(conn: sqlite3.Connection, project_id: str, doc_id: str) -> None:
    require(conn, project_id, doc_id)
    entities.delete(conn, doc_id)
    backup_path(conn, doc_id).unlink(missing_ok=True)
```

(`refs.reindex_mentions` gains its `project_id` in Task 4.)

- [ ] **Step 5: Implement `views.detail`**

In `src/brd/views.py`, replace `detail` with:

```python
def detail(conn: sqlite3.Connection, entity_id: str) -> dict:
    kind = entities.kind_of(conn, entity_id)
    if kind is None:
        raise CardNotFoundError(f"no card, issue, or document with id {entity_id}")
    # show is global: any project's entity, labelled with the project owning it.
    owner = db.owner_of(conn, entity_id)
    # Documents may have been edited on disk; sync the owning project's
    # documents against its own root so backlinks (referenced_by) reflect
    # their current content.
    results = documents.sync_all(conn, owner.id, Path(owner.root_path))
    if kind == "document":
        shown = document_detail(
            conn, documents.require(conn, owner.id, entity_id), results[entity_id]
        )
    elif kind == "issue":
        shown = issue_detail(conn, issues.require(conn, owner.id, entity_id))
    else:
        shown = card_detail(conn, db.get_card(conn, entity_id))
    return {**shown, "project": {"id": owner.id, "name": owner.name}}
```

- [ ] **Step 6: Update the other callers**

`src/brd/snapshot.py`, in `export`:

```python
def export(conn: sqlite3.Connection, project_id: str, root: Path) -> dict:
    results = documents.sync_all(conn, project_id, root)
```

and in the same function change `for d in documents.list_all(conn)` to `for d in documents.list_all(conn, project_id)`. In `_load_export` change the uniqueness loop to:

```python
    for doc in doc_rows:
        documents._check_unique(
            conn, project_id, doc["source_path"], PurePosixPath(doc["source_path"]).stem
        )
```

`src/brd/cli/docs.py`:

```python
# list_cmd
        results = documents.sync_all(ctx.conn, ctx.project.id, Path(ctx.project.root_path))
        items = []
        for doc in documents.list_all(ctx.conn, ctx.project.id):
# update
        doc, result = documents.update(
            ctx.conn,
            ctx.project.id,
            Path(ctx.project.root_path),
            doc_id,
            new_path=path,
            title=title,
        )
# restore
        doc = documents.restore(
            ctx.conn, ctx.project.id, Path(ctx.project.root_path), doc_id, force=force
        )
```

`src/brd/cli/cards.py`: delete the line `from pathlib import Path` (its only use was `show`). Change `show`'s action to

```python
        lambda ctx: views.detail(ctx.conn, entity_id),
```

and the document branch of `delete_entity` to

```python
    if kind == "document":
        documents.delete(conn, project_id, entity_id)
        return [entity_id]
```

- [ ] **Step 7: Update existing call sites in tests**

```bash
sed -i -E 's/documents\.(require|list_all|sync_all|update|restore|delete)\(pconn/documents.\1(pconn, PROJECT.id/g' tests/test_documents.py
```

Check with `grep -nE "documents\.(require|list_all|sync_all|update|restore|delete)\(" tests/test_documents.py`: every hit passes `PROJECT.id` second (for example `documents.update(pconn, PROJECT.id, root, doc.id, ...)`, `documents.list_all(pconn, PROJECT.id)`).

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run pytest tests/test_project_scope.py tests/test_cli.py tests/test_documents.py tests/test_snapshot.py tests/test_cli_docs.py -v`
Expected: PASS.

Run: `uv run pytest`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add src/brd/documents.py src/brd/views.py src/brd/snapshot.py src/brd/cli/docs.py src/brd/cli/cards.py tests/test_project_scope.py tests/test_cli.py tests/test_documents.py
git commit -m "Scope documents and their uniqueness to the current project"
```

---

### Task 4: `[[stem]]` links resolve within the project owning the text

**Files:**
- Modify: `src/brd/refs.py:21-28` (`resolve`), `:47-63` (`reindex`), `:66-82` (`reindex_mentions`)
- Modify: `src/brd/pretty.py` (`text`, `_comment_lines`, `render_detail`, new `_owner_id`)
- Modify: `src/brd/documents.py` (`add`'s and `update`'s `reindex_mentions` calls)
- Test: `tests/test_project_scope.py`, call sites in `tests/test_refs.py`

**Interfaces:**
- Consumes: `documents.add(conn, project_id, root, path, ...)`, `documents.update(conn, project_id, root, doc_id, ...)`, `views.detail(conn, entity_id)`, test helpers `root`, `_write` (Task 3).
- Produces: `refs.resolve(conn, project_id: str | None, target: str) -> str | None`; `refs.reindex_mentions(conn, project_id: str, stem: str) -> None`; `pretty.text(conn, project_id: str | None, value: str | None) -> str`. `refs.reindex(conn, entity_id)` is unchanged. Test helpers used later: `_comment(conn, comment_id, entity_id, body)` and `_link_targets(conn, entity_id) -> set[str]` in `tests/test_project_scope.py`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_project_scope.py`, change the brd import to:

```python
from brd import comments, core, db, documents, entities, issues, pretty, refs, snapshot, views
```

Append at the end of the file:

```python
Q_UUID = "abababab-abab-4bab-8bab-abababababab"


def _comment(conn, comment_id, entity_id, body):
    conn.execute(
        "INSERT INTO comments (id, entity_id, author, body, created_at) "
        "VALUES (?, ?, 'me', ?, ?)",
        (comment_id, entity_id, body, NOW),
    )
    conn.commit()


def _link_targets(conn, entity_id):
    return {r["id"] for r in refs.outgoing(conn, entity_id) if r["origin"] == "link"}


@pytest.fixture
def notes(two):
    """Both projects have a document with stem `notes`: pn in P, qn in Q."""
    make_document(two, "pn", "notes", title="P notes")
    make_document(two, "qn", "notes", title="Q notes", project_id=Q)
    return two


def test_resolve_stems_within_the_project_and_uuids_globally(notes):
    assert refs.resolve(notes, P, "notes") == "pn"
    assert refs.resolve(notes, P, "docs/NOTES.md") == "pn"
    assert refs.resolve(notes, Q, "notes") == "qn"
    assert refs.resolve(notes, P, "qnotes") is None  # only Q has it
    make_card(notes, Q_UUID, project_id=Q)
    assert refs.resolve(notes, P, Q_UUID) == Q_UUID


def test_reindex_resolves_stems_against_the_owning_project(notes):
    make_card(notes, "pc", description="see [[notes]]")
    make_card(notes, "qc", description="see [[notes]]", project_id=Q)
    make_card(notes, Q_UUID, project_id=Q)
    make_card(notes, "pu", description=f"see [[{Q_UUID}]]")
    for card_id in ("pc", "qc", "pu"):
        refs.reindex(notes, card_id)
    assert _link_targets(notes, "pc") == {"pn"}
    assert _link_targets(notes, "qc") == {"qn"}
    assert _link_targets(notes, "pu") == {Q_UUID}


def test_a_stem_only_another_project_has_stays_unresolved(two):
    make_card(two, "pc")
    _comment(two, "k-p", "pc", "see [[qnotes]]")
    refs.reindex(two, "pc")
    assert _link_targets(two, "pc") == set()
    assert pretty.text(two, P, "see [[qnotes]]") == "see [[qnotes]] (unresolved)"


def test_reindex_mentions_rescans_only_the_projects_texts(two):
    make_card(two, "pc", description="[[notes]]")
    make_issue(two, "pi", body="[[notes]]")
    make_document(two, "ph", "phub", content="see [[notes]]")
    _comment(two, "k-p", "p1", "[[notes]]")
    make_card(two, "qc", description="[[notes]]", project_id=Q)
    _comment(two, "k-q", "q1", "[[notes]]")
    # Seeded without reindexing: no entity has a link ref yet.
    make_document(two, "pn", "notes")
    make_document(two, "qn", "notes", project_id=Q)
    refs.reindex_mentions(two, P, "notes")
    for entity_id in ("pc", "pi", "ph", "p1"):
        assert _link_targets(two, entity_id) == {"pn"}
    assert _link_targets(two, "qc") == set()  # not rescanned, though Q has `notes`
    assert _link_targets(two, "q1") == set()


def test_adding_or_renaming_a_document_rescans_only_its_project(two, root):
    make_document(two, "qn", "notes", project_id=Q)
    make_document(two, "qr", "renamed", project_id=Q)
    make_card(two, "qc", description="[[notes]] and [[renamed]]", project_id=Q)
    make_card(two, "pc", description="[[notes]] and [[renamed]]")
    added = documents.add(two, P, root, _write(root, "docs/notes.md", ""))
    assert _link_targets(two, "pc") == {added.id}
    assert _link_targets(two, "qc") == set()
    old = documents.add(two, P, root, _write(root, "docs/old.md", ""))
    (root / "docs" / "old.md").rename(root / "docs" / "renamed.md")
    documents.update(two, P, root, old.id, new_path=root / "docs" / "renamed.md")
    assert _link_targets(two, "pc") == {added.id, old.id}
    assert _link_targets(two, "qc") == set()


def test_pretty_renders_stem_links_against_the_owning_project(notes):
    make_card(notes, "qc", description="see [[notes]]", project_id=Q)
    _comment(notes, "k-q", "qc", "also [[notes]]")
    shown = views.detail(notes, "qc")
    out = pretty.render_detail(notes, shown)
    assert "see [[Q notes]]" in out
    assert "  also [[Q notes]]" in out
    assert "  also [[Q notes]]" in pretty.render_comments(notes, shown["comments"])
    assert pretty.text(notes, P, "[[notes]]") == "[[P notes]]"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_project_scope.py -k "resolve or reindex or stem or rescans or pretty" -v`
Expected: FAIL with `TypeError` (`resolve()` / `reindex_mentions()` / `text()` take fewer positional arguments) or assertion errors (`qc` has `{"pn"}`, `qc` rescanned).

- [ ] **Step 3: Implement `refs.py`**

Replace `resolve` with:

```python
def resolve(conn: sqlite3.Connection, project_id: str | None, target: str) -> str | None:
    """A [[<uuid>]] target is any entity on the board; a [[stem]] target is
    a document of project_id only."""
    as_uuid = _as_uuid(target)
    if as_uuid is not None:
        return as_uuid if entities.kind_of(conn, as_uuid) else None
    row = conn.execute(
        f"SELECT documents.id FROM documents {db.in_project('documents.id')} "
        "WHERE documents.stem = ?",
        (project_id, normalize_stem(target)),
    ).fetchone()  # stem is COLLATE NOCASE
    return row["id"] if row else None
```

In `reindex`, insert at the top of the body (after the docstring):

```python
    owner = conn.execute(
        "SELECT project_id FROM entities WHERE id = ?", (entity_id,)
    ).fetchone()
    # Stems resolve within the project owning the text; an unknown entity
    # has none, so its stems resolve to nothing.
    project_id = owner["project_id"] if owner else None
```

and change `dst = resolve(conn, token.target)` to `dst = resolve(conn, project_id, token.target)`.

Replace `reindex_mentions` with:

```python
def reindex_mentions(conn: sqlite3.Connection, project_id: str, stem: str) -> None:
    """Reindex every entity of project_id whose text mentions stem, so links
    written before a document existed (or under its old name) resolve now.
    Other projects' texts can't link to this project's stems. Over-matching
    is harmless: reindex is idempotent."""
    pattern = "%" + stem.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    ids: set[str] = set()
    for query in (
        f"SELECT cards.id FROM cards {db.in_project('cards.id')} "
        "WHERE cards.description LIKE ? ESCAPE '\\'",
        f"SELECT issues.id FROM issues {db.in_project('issues.id')} "
        "WHERE issues.body LIKE ? ESCAPE '\\'",
        f"SELECT comments.entity_id AS id FROM comments {db.in_project('comments.entity_id')} "
        "WHERE comments.body LIKE ? ESCAPE '\\'",
    ):
        ids.update(row["id"] for row in conn.execute(query, (project_id, pattern)))
    needle = stem.lower()
    for row in conn.execute(
        f"SELECT documents.id FROM documents {db.in_project('documents.id')}", (project_id,)
    ).fetchall():
        if needle in _read_backup(conn, row["id"]).lower():
            ids.add(row["id"])
    for entity_id in sorted(ids):
        reindex(conn, entity_id)
```

- [ ] **Step 4: Pass the project from `documents.add` and `documents.update`**

In `src/brd/documents.py`, `add`: change `refs.reindex_mentions(conn, stem)` to `refs.reindex_mentions(conn, project_id, stem)`. In `update`:

```python
    if doc.stem.lower() != old_stem.lower():
        refs.reindex_mentions(conn, project_id, old_stem)
        refs.reindex_mentions(conn, project_id, doc.stem)
```

- [ ] **Step 5: Implement `pretty.py`**

Change the import to `from brd import db, entities, links, refs`. Replace `text` with:

```python
def text(conn: sqlite3.Connection, project_id: str | None, value: str | None) -> str:
    def display(token: links.LinkToken) -> str | None:
        dst = refs.resolve(conn, project_id, token.target)
        return entities.title_of(conn, dst) if dst else None

    return links.render(value, display)


def _owner_id(conn: sqlite3.Connection, entity_id: str) -> str | None:
    # Render stems against the project owning the text, as reindex resolves them.
    owner = db.owner_of(conn, entity_id)
    return owner.id if owner else None
```

Replace `_comment_lines` with:

```python
def _comment_lines(conn: sqlite3.Connection, items: list[dict]) -> list[str]:
    lines = []
    for comment in items:
        lines.append(f"{comment['author']} · {_stamp(comment['created_at'])}")
        body = text(conn, _owner_id(conn, comment["entity_id"]), comment["body"])
        lines.extend(f"  {line}" for line in body.splitlines())
    return lines
```

In `render_detail`, change `parts += ["", text(conn, body)]` to

```python
        parts += ["", text(conn, _owner_id(conn, data["id"]), body)]
```

- [ ] **Step 6: Update existing call sites in tests**

```bash
sed -i -E 's/refs\.(resolve|reindex_mentions)\(pconn, /refs.\1(pconn, PROJECT.id, /g; s/^from tests\.factories import make_card, make_document$/from tests.factories import PROJECT, make_card, make_document/' tests/test_refs.py
```

Check with `grep -nE "refs\.(resolve|reindex_mentions)\(|^from tests" tests/test_refs.py`: every call passes `PROJECT.id` second, and `PROJECT` is imported.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_project_scope.py tests/test_refs.py tests/test_documents.py tests/test_pretty.py -v`
Expected: PASS.

Run: `uv run pytest`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/brd/refs.py src/brd/pretty.py src/brd/documents.py tests/test_project_scope.py tests/test_refs.py
git commit -m "Resolve [[stem]] links within the project owning the text"
```

---

### Task 5: Explicit refs refuse a source or target from another project

**Files:**
- Modify: `src/brd/refs.py:85-103` (`add_explicit`, `remove_explicit`)
- Modify: `src/brd/issues.py` (`open_issue`'s `refs.add_explicit` call)
- Modify: `src/brd/cli/refs.py:19,34`
- Test: `tests/test_project_scope.py`, `tests/test_cli.py`, call sites in `tests/test_refs.py`, `tests/test_entities.py:60`, `tests/test_core.py:321-322,589`, `tests/test_documents.py:254`

**Interfaces:**
- Consumes: `entities.require_in_project` (Task 1); `SCOPED_REFUSED` (Task 2); `foreign_entities`, `_refused` (Task 2).
- Produces: `refs.add_explicit(conn, project_id, src_id, dst_id) -> None`; `refs.remove_explicit(conn, project_id, src_id, dst_id) -> None`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_project_scope.py`, append these entries to the `SCOPED_REFUSED` list (inside its closing `]`):

```python
    pytest.param(
        lambda c: refs.add_explicit(c, P, "q1", "p1"), CardNotFoundError, "q1", "card",
        id="ref_add_foreign_source",
    ),
    pytest.param(
        lambda c: refs.add_explicit(c, P, "p1", "qi"), IssueNotFoundError, "qi", "issue",
        id="ref_add_foreign_target",
    ),
    pytest.param(
        lambda c: refs.remove_explicit(c, P, "q1", "p1"), CardNotFoundError, "q1", "card",
        id="ref_remove_foreign_source",
    ),
```

Append at the end of the file:

```python
def test_ref_remove_checks_only_the_source(two):
    two.executemany(
        "INSERT INTO refs (src_id, dst_id, origin) VALUES (?, ?, 'explicit')",
        [("q1", "p1"), ("p1", "q1")],
    )
    two.commit()
    with pytest.raises(CardNotFoundError, match=_foreign("q1")):
        refs.remove_explicit(two, P, "q1", "p1")
    refs.remove_explicit(two, P, "p1", "q1")  # a foreign target: the edge still goes
    assert [tuple(r) for r in two.execute("SELECT src_id, dst_id FROM refs")] == [("q1", "p1")]
```

Append to `tests/test_cli.py`:

```python
def test_ref_commands_are_scoped_to_this_project(foreign_entities):
    mine = ok("add", "--title", "mine")["id"]
    _refused("ref", "add", foreign_entities["card"], mine)
    _refused("ref", "add", mine, foreign_entities["issue"], error_type="IssueNotFoundError")
    _refused("ref", "remove", foreign_entities["card"], mine)
    assert ok("show", mine)["refs"] == []
    assert ok("show", foreign_entities["card"])["refs"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_project_scope.py tests/test_cli.py -k "ref_" -v`
Expected: FAIL. The unit tests fail with `TypeError: add_explicit() takes 3 positional arguments but 4 were given`. The CLI test fails because `ref add <foreign card> <mine>` succeeds.

- [ ] **Step 3: Implement**

In `src/brd/refs.py`, replace `add_explicit` and `remove_explicit` with:

```python
def add_explicit(conn: sqlite3.Connection, project_id: str, src_id: str, dst_id: str) -> None:
    entities.require_in_project(conn, project_id, src_id)
    # Ref targets stay in the current project until S4 lifts the check.
    entities.require_in_project(conn, project_id, dst_id)
    if src_id == dst_id:
        raise SelfReferenceError(f"{src_id} can't reference itself")
    conn.execute(
        "INSERT OR IGNORE INTO refs (src_id, dst_id, origin) VALUES (?, ?, 'explicit')",
        (src_id, dst_id),
    )
    conn.commit()


def remove_explicit(conn: sqlite3.Connection, project_id: str, src_id: str, dst_id: str) -> None:
    # Only the source is checked: like `unblock --by`, an edge to another
    # project's entity can still be removed.
    entities.require_in_project(conn, project_id, src_id)
    conn.execute(
        "DELETE FROM refs WHERE src_id = ? AND dst_id = ? AND origin = 'explicit'",
        (src_id, dst_id),
    )
    conn.commit()
```

In `src/brd/issues.py`, `open_issue`: change `refs.add_explicit(conn, issue.id, ref_id)` to `refs.add_explicit(conn, project_id, issue.id, ref_id)`.

In `src/brd/cli/refs.py`: change `refs.add_explicit(ctx.conn, src_id, dst_id)` to `refs.add_explicit(ctx.conn, ctx.project.id, src_id, dst_id)` and `refs.remove_explicit(ctx.conn, src_id, dst_id)` to `refs.remove_explicit(ctx.conn, ctx.project.id, src_id, dst_id)`.

- [ ] **Step 4: Update existing call sites in tests**

```bash
sed -i -E 's/refs\.(add_explicit|remove_explicit)\((p?conn), /refs.\1(\2, PROJECT.id, /g' tests/test_refs.py tests/test_entities.py tests/test_core.py tests/test_documents.py
```

Check with `grep -nE "refs\.(add_explicit|remove_explicit)\(" tests/*.py`: every hit passes `PROJECT.id` second. `PROJECT` is already imported in each of these files (`tests/test_refs.py` since Task 4).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_project_scope.py tests/test_cli.py tests/test_refs.py tests/test_entities.py tests/test_core.py tests/test_documents.py tests/test_issues.py -v`
Expected: PASS.

Run: `uv run pytest`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/brd/refs.py src/brd/issues.py src/brd/cli/refs.py tests/test_project_scope.py tests/test_cli.py tests/test_refs.py tests/test_entities.py tests/test_core.py tests/test_documents.py
git commit -m "Refuse explicit refs from or to an entity of another project"
```

---

### Task 6: Scoped tags: add/remove/list and counts

**Files:**
- Modify: `src/brd/tags.py:1-57`
- Modify: `src/brd/documents.py` (`add`'s `tags.add` call)
- Modify: `src/brd/views.py:61` (`document_summary`)
- Modify: `src/brd/cli/tags.py:17,27,39-40`
- Test: `tests/test_project_scope.py`, `tests/test_cli.py`, call sites in `tests/test_tags.py`, `tests/test_documents.py:43`

**Interfaces:**
- Consumes: `entities.require_in_project` (Task 1); `SCOPED_REFUSED` (Task 2); `foreign_entities`, `_refused` (Task 2).
- Produces: `tags.for_entity(conn, entity_id) -> list[str]`; `tags.list_for(conn, project_id, entity_id) -> list[str]`; `tags.add(conn, project_id, entity_id, tag_list) -> list[str]`; `tags.remove(conn, project_id, entity_id, tag_list) -> list[str]`; `tags.counts(conn, project_id) -> list[dict]`. The `two` fixture now also tags `qd` with `qtag`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_project_scope.py`, change the brd import to:

```python
from brd import comments, core, db, documents, entities, issues, pretty, refs, snapshot, tags, views
```

In the `two` fixture, after `make_document(pconn, "qd", "qnotes", content="q body", project_id=Q)` add:

```python
    pconn.execute("INSERT INTO tags (entity_id, tag) VALUES ('qd', 'qtag')")
```

and change its docstring's last line to `document qd (tagged qtag)."""`.

Append these entries to the `SCOPED_REFUSED` list:

```python
    pytest.param(
        lambda c: tags.add(c, P, "qd", ["x"]), DocumentNotFoundError, "qd", "document",
        id="tag_add",
    ),
    pytest.param(
        lambda c: tags.add(c, P, "qd", ["bad tag"]), DocumentNotFoundError, "qd", "document",
        id="tag_add_invalid_tag",
    ),
    pytest.param(
        lambda c: tags.remove(c, P, "qd", ["qtag"]), DocumentNotFoundError, "qd", "document",
        id="tag_remove",
    ),
    pytest.param(
        lambda c: tags.list_for(c, P, "qd"), DocumentNotFoundError, "qd", "document",
        id="tag_list_for",
    ),
    pytest.param(
        lambda c: tags.add(c, P, "q1", ["x"]), CardNotFoundError, "q1", "card",
        id="tag_add_foreign_card",
    ),
```

Append at the end of the file:

```python
def test_tag_counts_cover_only_the_projects_entities(two):
    make_document(two, "pd", "pnotes")
    make_document(two, "qd2", "qother", project_id=Q)
    two.executemany(
        "INSERT INTO tags (entity_id, tag) VALUES (?, ?)",
        [("pd", "x"), ("qd", "x"), ("qd2", "x"), ("qd2", "y")],
    )
    two.commit()
    assert tags.counts(two, P) == [{"tag": "x", "count": 1}]


def test_show_lists_a_foreign_documents_tags(two):
    assert views.detail(two, "qd")["tags"] == ["qtag"]
    assert tags.for_entity(two, "qd") == ["qtag"]
```

Append to `tests/test_cli.py`:

```python
def test_tag_commands_are_scoped_to_this_project(foreign_entities):
    doc = foreign_entities["document"]
    assert ok("tag", "list") == []
    _refused("tag", "add", doc, "x", error_type="DocumentNotFoundError")
    _refused("tag", "remove", doc, "t", error_type="DocumentNotFoundError")
    _refused("tag", "list", doc, error_type="DocumentNotFoundError")
    assert ok("show", doc)["tags"] == ["t"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_project_scope.py tests/test_cli.py -k "tag" -v`
Expected: FAIL. The unit tests fail with `TypeError` or `AttributeError: module 'brd.tags' has no attribute 'for_entity'`. The CLI test fails on `tag list` returning `[{"tag": "t", "count": 1}]`.

- [ ] **Step 3: Implement `tags.py`**

Change the import `from brd import entities` to `from brd import db, entities`. Replace everything from `_require_taggable` to the end of the file with:

```python
def _require_taggable(conn: sqlite3.Connection, project_id: str, entity_id: str) -> None:
    # Ownership first: a foreign card is reported as foreign, not untaggable.
    entities.require_in_project(conn, project_id, entity_id)
    entities.require_capability(conn, entity_id, entities.TAGGABLE, NotTaggableError, "tagged")


def for_entity(conn: sqlite3.Connection, entity_id: str) -> list[str]:
    """Any entity's tags, unchecked: `brd show` is global."""
    rows = conn.execute(
        "SELECT tag FROM tags WHERE entity_id = ? ORDER BY tag", (entity_id,)
    ).fetchall()
    return [row["tag"] for row in rows]


def list_for(conn: sqlite3.Connection, project_id: str, entity_id: str) -> list[str]:
    entities.require_in_project(conn, project_id, entity_id)
    return for_entity(conn, entity_id)


def add(
    conn: sqlite3.Connection, project_id: str, entity_id: str, tag_list: list[str]
) -> list[str]:
    _require_taggable(conn, project_id, entity_id)
    normalized = [normalize(tag) for tag in tag_list]  # validate all before writing
    conn.executemany(
        "INSERT OR IGNORE INTO tags (entity_id, tag) VALUES (?, ?)",
        [(entity_id, tag) for tag in normalized],
    )
    conn.commit()
    return for_entity(conn, entity_id)


def remove(
    conn: sqlite3.Connection, project_id: str, entity_id: str, tag_list: list[str]
) -> list[str]:
    _require_taggable(conn, project_id, entity_id)
    normalized = [normalize(tag) for tag in tag_list]
    conn.executemany(
        "DELETE FROM tags WHERE entity_id = ? AND tag = ?",
        [(entity_id, tag) for tag in normalized],
    )
    conn.commit()
    return for_entity(conn, entity_id)


def counts(conn: sqlite3.Connection, project_id: str) -> list[dict]:
    rows = conn.execute(
        f"SELECT tags.tag, COUNT(*) AS count FROM tags {db.in_project('tags.entity_id')} "
        "GROUP BY tags.tag ORDER BY tags.tag",
        (project_id,),
    ).fetchall()
    return [{"tag": row["tag"], "count": row["count"]} for row in rows]
```

- [ ] **Step 4: Update the callers**

`src/brd/documents.py`, `add`: change `tags.add(conn, doc.id, normalized_tags)` to `tags.add(conn, project_id, doc.id, normalized_tags)`.

`src/brd/views.py`, `document_summary`: change `"tags": tags.list_for(conn, doc.id),` to `"tags": tags.for_entity(conn, doc.id),`.

`src/brd/cli/tags.py`:

```python
# add
    run(
        pretty,
        lambda ctx: {"id": entity_id, "tags": tags.add(ctx.conn, ctx.project.id, entity_id, tag_list)},
    )
# remove
    run(
        pretty,
        lambda ctx: {
            "id": entity_id,
            "tags": tags.remove(ctx.conn, ctx.project.id, entity_id, tag_list),
        },
    )
# list_cmd action
        if entity_id is None:
            return tags.counts(ctx.conn, ctx.project.id)
        return {"id": entity_id, "tags": tags.list_for(ctx.conn, ctx.project.id, entity_id)}
```

- [ ] **Step 5: Update existing call sites in tests**

```bash
sed -i -E 's/tags\.(add|remove|list_for|counts)\(pconn/tags.\1(pconn, PROJECT.id/g; s/^from tests\.factories import make_card, make_document$/from tests.factories import PROJECT, make_card, make_document/' tests/test_tags.py
sed -i 's/tags\.list_for(pconn, doc\.id)/tags.list_for(pconn, PROJECT.id, doc.id)/' tests/test_documents.py
```

Check with `grep -nE "tags\.(add|remove|list_for|counts)\(|^from tests" tests/test_tags.py tests/test_documents.py`: every call passes `PROJECT.id` second (`tags.counts(pconn, PROJECT.id)`), and `PROJECT` is imported in `tests/test_tags.py`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_project_scope.py tests/test_cli.py tests/test_tags.py tests/test_documents.py tests/test_cli_docs.py tests/test_snapshot.py -v`
Expected: PASS.

Run: `uv run pytest`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/brd/tags.py src/brd/documents.py src/brd/views.py src/brd/cli/tags.py tests/test_project_scope.py tests/test_cli.py tests/test_tags.py tests/test_documents.py
git commit -m "Scope tag commands and tag counts to the current project"
```

---

### Task 7: Scoped comments: add on issues, list, delete

**Files:**
- Modify: `src/brd/comments.py:1-73`
- Modify: `src/brd/views.py:33,49` (`card_detail`, `issue_detail`)
- Modify: `src/brd/cli/comments.py:42,53`
- Test: `tests/test_project_scope.py`, `tests/test_cli.py`, call sites in `tests/test_comments.py`

**Interfaces:**
- Consumes: `entities.require_in_project`, `entities.foreign_message` (Task 1); `SCOPED_REFUSED` (Task 2); `_comment` (Task 4); `foreign_entities`, `_refused` (Task 2).
- Produces: `comments.for_entity(conn, entity_id) -> list[Comment]`; `comments.list_for(conn, project_id, entity_id) -> list[Comment]`; `comments.delete(conn, project_id, comment_id) -> Comment`. `comments.add(conn, project_id, entity_id, body, author)` keeps its signature.

- [ ] **Step 1: Write the failing tests**

In `tests/test_project_scope.py`, add `CommentNotFoundError` to the `brd.errors` import (alphabetically after `CardNotFoundError`). Append these entries to the `SCOPED_REFUSED` list:

```python
    pytest.param(
        lambda c: comments.add(c, P, "qi", "hi", "alice"), IssueNotFoundError, "qi", "issue",
        id="comments_add_foreign_issue",
    ),
    pytest.param(
        lambda c: comments.add(c, P, "qi", "   ", "alice"), IssueNotFoundError, "qi", "issue",
        id="comments_add_foreign_issue_empty_body",
    ),
    pytest.param(
        lambda c: comments.add(c, P, "qd", "hi", "alice"), DocumentNotFoundError, "qd",
        "document", id="comments_add_foreign_document",
    ),
    pytest.param(
        lambda c: comments.list_for(c, P, "qi"), IssueNotFoundError, "qi", "issue",
        id="comments_list_foreign_issue",
    ),
    pytest.param(
        lambda c: comments.list_for(c, P, "q1"), CardNotFoundError, "q1", "card",
        id="comments_list_foreign_card",
    ),
```

Append at the end of the file:

```python
def test_comment_delete_refuses_a_comment_on_a_foreign_entity(two):
    _comment(two, "k-q", "q1", "keep")
    before = _state(two)
    with pytest.raises(CommentNotFoundError, match=_foreign("k-q", "comment")):
        comments.delete(two, P, "k-q")
    assert _state(two) == before
    with pytest.raises(CommentNotFoundError, match=r"^no comment with id nope$"):
        comments.delete(two, P, "nope")


def test_comment_delete_removes_an_own_comment(two):
    _comment(two, "k-p", "p1", "go")
    assert comments.delete(two, P, "k-p").id == "k-p"
    assert comments.for_entity(two, "p1") == []


def test_show_lists_comments_of_a_foreign_card_and_issue(two):
    _comment(two, "k-c", "q1", "on card")
    _comment(two, "k-i", "qi", "on issue")
    assert [c["id"] for c in views.detail(two, "q1")["comments"]] == ["k-c"]
    assert [c["id"] for c in views.detail(two, "qi")["comments"]] == ["k-i"]
```

Append to `tests/test_cli.py`:

```python
def test_comment_commands_are_scoped_to_this_project(project, foreign_entities):
    conn = db.connect(paths.project_db_path(project))
    try:
        conn.execute(
            "INSERT INTO comments (id, entity_id, author, body, created_at) "
            "VALUES ('k-foreign', ?, 'them', 'theirs', '2026-09-24T00:00:00+00:00')",
            (foreign_entities["card"],),
        )
        conn.commit()
    finally:
        conn.close()
    _refused("comment", "list", foreign_entities["card"])
    _refused("comment", "add", foreign_entities["issue"], "hi", error_type="IssueNotFoundError")
    _refused(
        "comment", "add", foreign_entities["document"], "hi", error_type="DocumentNotFoundError"
    )
    _refused("comment", "delete", "k-foreign", error_type="CommentNotFoundError")
    assert ok("show", foreign_entities["issue"])["comments"] == []
    assert [c["id"] for c in ok("show", foreign_entities["card"])["comments"]] == ["k-foreign"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_project_scope.py tests/test_cli.py -k "comment" -v`
Expected: FAIL. The new unit tests fail with `DID NOT RAISE`, `NotCommentableError`, `TypeError`, or `AttributeError: ... 'for_entity'`. The CLI test fails because `comment list <foreign card>` succeeds.

- [ ] **Step 3: Implement `comments.py`**

Change `from brd import core, entities, refs` to `from brd import db, entities, refs`. Replace `add`, `list_for` and `delete` with:

```python
def add(
    conn: sqlite3.Connection, project_id: str, entity_id: str, body: str, author: str
) -> Comment:
    # Ownership first: a foreign document is reported as foreign, not
    # uncommentable, and a foreign issue's empty comment as foreign.
    entities.require_in_project(conn, project_id, entity_id)
    entities.require_capability(
        conn, entity_id, entities.COMMENTABLE, NotCommentableError, "commented on"
    )
    if not body.strip():
        raise EmptyCommentError("comment body is empty")
    comment = Comment(
        id=str(uuid.uuid4()),
        entity_id=entity_id,
        author=author,
        body=body,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    conn.execute(
        "INSERT INTO comments (id, entity_id, author, body, created_at) VALUES (?, ?, ?, ?, ?)",
        (comment.id, comment.entity_id, comment.author, comment.body, comment.created_at),
    )
    conn.commit()
    refs.reindex(conn, entity_id)
    return comment


def for_entity(conn: sqlite3.Connection, entity_id: str) -> list[Comment]:
    """Any entity's comments, unchecked: `brd show` is global."""
    rows = conn.execute(
        "SELECT * FROM comments WHERE entity_id = ? ORDER BY created_at, rowid",
        (entity_id,),
    ).fetchall()
    return [_row(row) for row in rows]


def list_for(conn: sqlite3.Connection, project_id: str, entity_id: str) -> list[Comment]:
    entities.require_in_project(conn, project_id, entity_id)
    return for_entity(conn, entity_id)


def delete(conn: sqlite3.Connection, project_id: str, comment_id: str) -> Comment:
    row = conn.execute("SELECT * FROM comments WHERE id = ?", (comment_id,)).fetchone()
    if row is None:
        raise CommentNotFoundError(f"no comment with id {comment_id}")
    comment = _row(row)
    owner = db.owner_of(conn, comment.entity_id)
    if owner is not None and owner.id != project_id:
        raise CommentNotFoundError(entities.foreign_message("comment", comment_id, owner))
    conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
    conn.commit()
    refs.reindex(conn, comment.entity_id)
    return comment
```

- [ ] **Step 4: Update the callers**

`src/brd/views.py`: in `card_detail` change `comments.list_for(conn, card.id)` to `comments.for_entity(conn, card.id)`; in `issue_detail` change `comments.list_for(conn, issue.id)` to `comments.for_entity(conn, issue.id)`.

`src/brd/cli/comments.py`:

```python
# list_cmd
        lambda ctx: [
            views.comment_dict(c) for c in comments.list_for(ctx.conn, ctx.project.id, entity_id)
        ],
# delete
    run(
        pretty,
        lambda ctx: views.comment_dict(comments.delete(ctx.conn, ctx.project.id, comment_id)),
    )
```

- [ ] **Step 5: Update existing call sites in tests**

```bash
sed -i -E 's/comments\.(list_for|delete)\(pconn, /comments.\1(pconn, PROJECT.id, /g' tests/test_comments.py
```

Check with `grep -nE "comments\.(list_for|delete)\(" tests/test_comments.py`: every hit passes `PROJECT.id` second.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_project_scope.py tests/test_cli.py tests/test_comments.py tests/test_cli_social.py tests/test_pretty.py -v`
Expected: PASS.

- [ ] **Step 7: Full verification**

Run: `uv run pytest`
Expected: all pass, 0 failures (517 at the start plus the tests added in Tasks 1-7).

Run: `grep -rnE "issues\.(require|list_issues|update|close|reopen)\(|documents\.(require|list_all|sync_all|update|restore|delete|_check_unique)\(|refs\.(resolve|reindex_mentions|add_explicit|remove_explicit)\(|tags\.(add|remove|list_for|counts)\(|comments\.(list_for|delete)\(|pretty\.text\(|views\.detail\(" src`
Expected: every call passes a project id (`project_id`, `owner.id` or `ctx.project.id`) right after the connection, except `views.detail(conn, entity_id)`.

- [ ] **Step 8: Commit**

```bash
git add src/brd/comments.py src/brd/views.py src/brd/cli/comments.py tests/test_project_scope.py tests/test_cli.py tests/test_comments.py
git commit -m "Scope comments on issues, comment listing and deletion to the current project"
```
<!-- task-pipeline: validated -->
