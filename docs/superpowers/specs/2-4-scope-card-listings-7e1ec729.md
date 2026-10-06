# 2.4 Scope card listings and mutations to the current project

Card: `7e1ec729-fc07-4043-b101-faa6cfbf0dd4` (subtask of story `54de5e9d` "Project-scoped
schema", milestone `6aa7043a` "Single database and cross-project blocking"). Blocked by
2.3 (`da130e91`, done on this branch's parent: schema v4 with `entities.project_id`,
`src/brd/db.py:172-176`, and the same-project parent trigger, `src/brd/db.py:224-231`).

Parent design spec: `docs/superpowers/specs/2026-10-06-single-db-cross-project-blocking-design.md`
(in the main checkout; not in this branch's history). Cited by section and line as
**[P §n Lx]**.

## Goal

Card commands only see and change cards of the project they run in. The project is
`ctx.project` (`src/brd/cli/_app.py:53-56`):

- `brd list`, `brd next` and `brd tree` list only the current project's cards.
- `brd update`, `brd delete` (card branch), `brd block` / `brd unblock` (the card being
  changed), `brd comment add` on a card, and the `--parent` of `brd add` / `brd update`
  refuse a card from another project. The error is a `CardNotFoundError` (an
  `EntityNotFoundError`) that names the owning project.
- Blocker targets (`brd block --by`, `brd add --blocked-by`) must still be in the current
  project. This check is lifted in S4.
- `brd show <id>` stays global, and its output gains the owning project.

There is still one board file per project, holding one `projects` row. Users see no
difference until S3 puts every project in one `brd.db`. Until then, tests seed a second
project into one connection (`tests/factories.add_project`, `tests/factories.py:21-29`)
to exercise the filters.

## Inherited constraints

| Constraint | Source |
|---|---|
| Commands are scoped to the current project. Only edges, `show`, edge targets and `[[uuid]]` links cross projects. | [P D3 L33] |
| Ownership lives on `entities.project_id`. | [P D4 L34] |
| `list`, `next` and `tree` are filtered by `entities.project_id` through **one helper in `db.py`**. | [P §2 L109-111]; card text |
| Mutating commands (`update`, `delete`, the source of `block`/`unblock`, `comment`, …) require the entity to belong to the current project. Otherwise they raise `EntityNotFoundError` naming the owning project. | [P §2 L112-115] |
| `brd show <id>` is global, and its output includes the owning project. | [P §2 L117] |
| Status resolution and the cycle check follow edges globally. | [P §2 L119-120] |
| In phase 2, edge targets are still validated as same-project by code. | [P Implementation order L276-280]; card text ("Blocker targets keep the same-project check for now (lifted in S4)") |
| `blocked_by` stays a list of ids wherever it appears today. | [P §4 L173-174] |
| New functions that take the project take it as a **required** positional parameter `project_id: str`, second after `conn`, as `create_card`, `import_tree` and `insert_card` already do. They never fall back to "the board's only project". | 2.3 spec B4; `src/brd/core.py:140`, `src/brd/core.py:296` |

## Behaviour

Below, "P" is the current project (`ctx.project`) and "Q" is another project in the same
connection. "A foreign card" is a card whose `entities.project_id` is Q's id.

### B1. One scoping helper, one owner lookup (`db.py`)

- `db.in_project(id_column: str) -> str` returns the SQL fragment
  `JOIN entities AS scope ON scope.id = <id_column> AND scope.project_id = ?`. The caller
  binds the project id as the fragment's single parameter. This is the only place a
  query joins on `entities.project_id` to filter a listing. Card 2.5 reuses it for issues
  and documents.
- `db.owner_of(conn, entity_id: str) -> Project | None` returns the `projects` row that
  owns the entity, or `None` when the id is not in `entities`.

### B2. Listings show only P's cards

- `db.list_cards(conn, project_id, status=None, parent_id=_UNSET)` returns only cards
  owned by `project_id`. The status filter, the parent filter (including `parent_id=None`,
  meaning top-level) and the `created_at` order work as today.
- `brd list` (with or without `--status` / `--parent`) lists only P's cards.
  `--parent <foreign id>` returns `[]`, as an unknown parent id does today. It is not an
  error: `list` validates no ids today, and this card does not add validation.
- `brd next` without `--parent` returns only P's ready leaf cards. A P card blocked by
  anything is still excluded: status resolution is unchanged and global [P §2 L119-120].
- `brd next --parent <foreign id>` and `brd tree <foreign id>` fail with the foreign-card
  error (B4). `brd tree` with no root lists only P's top-level cards and their subtrees.
  Children are always in the same project as their parent (trigger, 2.3).
- `snapshot.export(conn, project_id, root)` passes the project to `build_tree`, so the
  export's `cards` holds only P's cards. Issues, documents, comments, tags and refs in the
  export are unchanged by this card (S5).

### B3. Signatures (callers pass `ctx.project.id`)

| Function | New signature |
|---|---|
| `db.list_cards` | `(conn, project_id, status=None, parent_id=_UNSET)` |
| `core.require_card` (new public name for `_require_card`) | `(conn, project_id, card_id) -> Card` |
| `core._require_blocker` | `(conn, project_id, blocker_id) -> None` |
| `core.update_card` | `(conn, project_id, card_id, title=None, description=None, status=None, parent_id=None)` |
| `core.block_card` | `(conn, project_id, card_id, blocker_id)` |
| `core.unblock_card` | `(conn, project_id, card_id, blocker_id)` |
| `core.delete_card` | `(conn, project_id, card_id, cascade=False)` |
| `core.next_cards` | `(conn, project_id, limit=None, parent_id=None)` |
| `core.build_tree` | `(conn, project_id, root_id=None)` |
| `snapshot.export` | `(conn, project_id, root)` |
| `cli.cards.delete_entity` | `(conn, project_id, entity_id, cascade)` |
| `comments.add` | `(conn, project_id, entity_id, body, author)` |

`core.create_card` and `issues.open_issue` keep their signatures. They pass their existing
`project_id` to the checks below. The duplicate `_require_card` in `src/brd/cli/cards.py:13-17`
goes away; the CLI uses `core.require_card`. Return values and the JSON shape of `list`,
`next`, `tree`, `add`, `update`, `block`, `unblock` and `delete` do not change.

### B4. The foreign-card error

`core.require_card(conn, project_id, card_id)`:

- No card with that id: `CardNotFoundError("no card with id <id>")`, as today.
- A foreign card: `CardNotFoundError` with the message
  `no card with id <id> in this project; it belongs to project <owner name> (<owner id>)`.
  The CLI envelope `type` is `CardNotFoundError`, the same as for a missing card
  (`src/brd/cli/_app.py:59-61`).
- A P card: returns it.

A refused command writes nothing: no row changes, no edge is added or removed, no comment
is added, and `updated_at` stays as it was.

Every path below goes through this check:

| Command / function | Id checked |
|---|---|
| `brd update` / `core.update_card` | the card, and `--parent` when given |
| `brd add --parent` / `core.create_card` | the parent |
| `brd delete` / `delete_entity` when the id is a card; `core.delete_card` | the card (with `--cascade`, every descendant is in P by the trigger) |
| `brd block` / `core.block_card` | the card being blocked |
| `brd unblock` / `core.unblock_card` | the card being unblocked |
| `brd next --parent`, `brd tree <root>` | the parent / root |
| `brd comment add <card id>` / `comments.add` | the entity, when its kind is `card` |
| `brd issue open --blocks <card>` / `issues.open_issue` | each `--blocks` card. This check runs **before** the issue row is inserted, replacing the global `db.get_card` pre-check at `src/brd/issues.py:85-87`, so a foreign `--blocks` leaves no issue behind. |

`brd update --parent <foreign card>` now fails with this error, before the same-project
trigger is reached, rather than with a raw `sqlite3.IntegrityError`.

If the id is a non-card entity (issue or document), these paths behave as today. For
example, `brd update <issue id>` still says `no card with id <id>`, whatever project owns
the issue. `brd delete` of an issue or document id is unchanged (2.5).

### B5. Blocker targets stay same-project

`core._require_blocker(conn, project_id, blocker_id)` is used by `brd block --by` and
`brd add --blocked-by`. It checks, in this order:

1. Id not in `entities`: `CardNotFoundError("no card or issue with id <id>")`, as today.
2. Owned by another project: `CardNotFoundError` with the message
   `no card or issue with id <id> in this project; it belongs to project <owner name> (<owner id>)`.
   This holds for any kind: a foreign card, issue or document.
3. A P entity whose kind is not a blocker (a document): `InvalidBlockerError`, as today.

`brd add --blocked-by <foreign id>` creates no card. All targets are checked before the
insert, as today (`src/brd/core.py:147-149`). `brd unblock --by` does not check its
target: it removes the edge if one exists, as today.

### B6. Status resolution and cycles are unchanged

`resolve_status`, `_is_released`, `would_create_block_cycle` and
`would_create_parent_cycle` keep their signatures and keep looking up by id across every
project [P §2 L119-120]. No new code path can create a foreign edge, but an edge seeded
directly in a test still affects status. Example: P card X `blocked_by` a Q card Y in
`todo` is shown as `blocked` in P's `list`, and Y is not listed.

### B7. `brd show` is global and names the owner

`views.detail(conn, root, entity_id)` (`brd show`) finds any entity by id, in any project,
as today. Its output gains one key, for every kind (card, issue, document):

```json
"project": {"id": "<owner project id>", "name": "<owner project name>"}
```

The other keys are unchanged, and a missing id is still
`CardNotFoundError("no card, issue, or document with id <id>")`. `views.card_detail`
does **not** gain the key, so `list`, `next`, `add`, `update`, `block` and `unblock`
output stays as it is. `--pretty` show output is unchanged.

## Tests

Tests stay flat in `tests/`. There are two tiers:

- **Unit:** in-process calls on a `pconn` connection (`tests/conftest.py:7-12`), with a
  second project seeded by `add_project(pconn, OTHER_PROJECT)` and cards made with
  `make_card(..., project_id=OTHER_PROJECT.id)`. This is where the filters and checks are
  pinned: two projects can share one connection only here, and only here can the
  database state after a refusal be read directly.
- **CLI:** `typer` runner through `tests/cli_helpers.py` with the `project` fixture
  (`tests/conftest.py:15-24`). The test opens the board file
  (`paths.project_db_path(repo)`), seeds OTHER_PROJECT and a foreign card into it, and
  closes it before invoking. This tier pins the wiring: `ctx.project.id` reaches each
  command, and the envelope `type` and message are what consumers parse.

New tests go in `tests/test_project_scope.py` (unit) and `tests/test_cli.py` (CLI).

| # | Test | Tier | Why this tier |
|---|---|---|---|
| T1 | `db.in_project("cards.id")` used in a raw query returns only the bound project's cards | Unit | The helper is a SQL fragment; only a direct query exercises it alone |
| T2 | `db.owner_of` returns the owning `Project` for P and Q entities, and `None` for an unknown id | Unit | Pure db function |
| T3 | `db.list_cards(conn, P)` returns only P's cards, and so do `status=` and `parent_id=None` (P and Q both have top-level `todo` cards) | Unit | Needs two projects in one connection |
| T4 | `next_cards(conn, P)` excludes Q's ready leaves. A P card blocked by a seeded Q `todo` card is excluded, and is included once Q's card is `done` (B6) | Unit | Two projects plus a directly seeded cross-project edge |
| T5 | `build_tree(conn, P)` holds only P's roots and subtrees. `build_tree(conn, P, root_id=<Q card>)` raises the foreign-card error | Unit | Same |
| T6 | `snapshot.export(conn, P, root)["cards"]` holds no Q card | Unit | Export is called in-process; no CLI path reaches a second project |
| T7 | Parametrised over `update_card` (fields), `update_card(parent_id=<Q card>)` with a P card, `create_card(parent_id=<Q card>)`, `delete_card` (with and without `cascade`), `block_card` (foreign source), `unblock_card` (foreign source with an existing edge), `next_cards(parent_id=<Q>)` and `comments.add` on a Q card: each raises `CardNotFoundError` whose message contains `OTHER_PROJECT.name` and `OTHER_PROJECT.id`, and the cards, blocked_by and comments tables are unchanged | Unit | Asserts the error and that nothing was written; only reading the database directly shows no write |
| T8 | `require_card` on a missing id still says `no card with id <id>`. `update_card` on a Q **issue** id still says `no card with id` | Unit | Unchanged error paths |
| T9 | `block_card(conn, P, <P card>, <Q card>)` and `block_card(..., <Q issue>)` raise `CardNotFoundError` naming Q, and add no edge. `create_card(conn, P, ..., blocked_by=[<Q card>])` raises the same and inserts no card. A Q document target also raises `CardNotFoundError` naming Q (ownership is checked before kind). A P document target still raises `InvalidBlockerError` | Unit | The same-project target check needs two projects |
| T10 | `issues.open_issue(conn, P, "t", blocks=[<Q card>])` raises `CardNotFoundError` naming Q, and the `issues` and `entities` tables gain no row | Unit | Pins that the check runs before the insert |
| T11 | `views.detail` on a P card, a Q card, a Q issue and a Q document returns `project == {"id", "name"}` of the owner, and the other keys match `card_detail` / `issue_detail` / `document_detail` | Unit | Show is global; only a second project shows the owner is not just "current" |
| T12 | All existing P-only behaviour still holds: the existing `test_core.py`, `test_issues.py`, `test_comments.py`, `test_db.py`, `test_migration.py`, `test_cli*.py`, `test_snapshot.py` and `test_pretty.py` pass with call sites updated to the new signatures | Unit + CLI | Regression |
| T13 | CLI: with a seeded foreign card F, `brd list`, `brd next` and `brd tree` output excludes F. `brd update F --title x`, `brd delete F`, `brd block F --by <P card>`, `brd unblock F --by <P card>` and `brd comment add F hi` each exit 1 with envelope type `CardNotFoundError` and a message naming `other` | CLI | Proves `ctx.project.id` reaches every command and pins the envelope consumers parse |
| T14 | CLI: `brd block <P card> --by F` and `brd add --title t --blocked-by F` exit 1 with `CardNotFoundError` naming `other` | CLI | Wiring of the target check |
| T15 | CLI: `brd show F` succeeds with `project.name == "other"`. `brd show <P card>` has `project.id == ` the registered project's id. `brd show nope` is still `CardNotFoundError` | CLI | The output shape is the user-visible contract |

## Out of scope

- Issues, documents, refs and tags: `issue list`, `issue update/close/reopen`, `doc
  list/sync` (including the `documents.sync_all` call inside `views.detail`), document
  uniqueness, `[[stem]]` resolution, `refs.reindex_mentions`, `ref add` sources, tag
  mutations, `comment list` / `comment delete`, comments on issues, and the issue and
  document branches of `brd delete`. These belong to **card 2.5** (`43ff4aca`).
- Export scoping beyond the `cards` section (S5), and import's `_require_import_target`
  (it still accepts any id already in the database, S5).
- Lifting the same-project check on blocker targets, the `blockers` output, and not-found
  blockers (S4) [P §4 L149-187].
- Moving to one `brd.db`, project resolution without the marker, and the
  all-commands leak guard [P Testing L255-257] (S3 / story-level).
- `--pretty` rendering of the owning project.
- Adding a `project` key to `card_detail` (list/next/add/update output).

## Notes for the planner

- About 134 existing test call sites use the old signatures of `list_cards`,
  `update_card`, `block_card`, `unblock_card`, `delete_card`, `next_cards`,
  `build_tree`, `snapshot.export`, `delete_entity` and `comments.add`. They are in
  `tests/test_core.py`, `test_issues.py`, `test_comments.py`, `test_db.py`,
  `test_migration.py` and `test_cli_issues.py`. Update each call site in the task that
  changes the signature, passing `PROJECT.id`, so the suite stays green task by task.
- `tests/test_project_scope.py:20-41` has stale lambdas (`core.create_card(conn, title="c")`
  and others). They pass only because `TypeError` is expected. Leave them alone.
- `list_cards` must select `cards.*`, since `entities` also has an `id` column. Bind the
  helper's project parameter before the status/parent parameters.
- Verification: `uv run pytest` (471 passing at the start of this card). There is no
  typecheck or lint configuration.
