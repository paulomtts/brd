# 3.4 Leak guard across every listing and lookup command

Card: `9da10121-5ebd-4a6b-9ed9-56fc58ae50a9`. It is the fourth and last subtask of story
`4939dac5` "One database". The milestone is `6aa7043a` "Single database and cross-project
blocking". It is blocked by 3.3 `91e68a83` (`init --relink`, `forget --project`). 3.3 is
merged into this branch, as are 3.1 (every project in one `brd.db`) and 3.2 (the project
is the deepest registered root).

Parent design spec: `docs/superpowers/specs/2026-10-06-single-db-cross-project-blocking-design.md`.
It is in the main checkout (`/home/mtts/Code/brd/docs/...`), not in this branch's history.
Citations look like **[P §n Lx]**.

## Goal

All projects now share one database, so a command that forgets to filter by project
shows another project's data. This card adds a guard against that. One parametrised CLI
test seeds two projects with near-identical content in one `brd.db`. It then runs every
listing and lookup command from each project's root and from a subdirectory of that
root. For each run it checks that nothing owned by the other project appears in the
output.

The card is mostly tests. It also fixes any leak the guard finds. One leak is already
known: `brd export` returns the `comments`, `tags` and `refs` of **every** project
(`src/brd/snapshot.py:29-46`, three unfiltered `SELECT`s). The card, cards, issues and
documents sections of the export are already scoped. This spec fixes the leak (B5).

## Inherited constraints

| Constraint | Source |
|---|---|
| Leak guard: one parametrised test seeds two projects with similar content and runs every listing and lookup command from each root, asserting nothing from the other project appears. | [P Testing L255-257] |
| Commands are scoped to the current project. Only edges, `show`, edge targets and `[[uuid]]` links cross projects. | [P D3 L33] |
| Scoped, filtered through one helper in `db.py`: `list`, `next`, `tree`, `issue list`, `doc list`/`sync`, `[[stem]]` link resolution, `refs.reindex_mentions` scans, document uniqueness checks, `export` without `--all`. | [P §2 L109-111] |
| Mutating commands require the entity to belong to the current project. Otherwise they raise a not-found error that names the owning project. | [P §2 L112-115] |
| Global: `brd show <id>` (its output includes the owning project), blocker targets, `brd ref add` targets, `[[<uuid>]]` links. | [P §2 L117-120] |
| `brd projects` lists every project (`id`, `name`, `root_path`). | [P §2 L122] |
| Comments and tags are scoped through `entity_id`. | [P §1 L67] |
| Edges are exported as stored, including cross-project targets. | [P §5 L205-206] |
| In this phase, code still checks that edge targets are in the same project. | [P Implementation order L279-280] |
| The scoping helper is `db.in_project(id_column)`, a join on `entities` bound to one `?` parameter. | `src/brd/db.py:561-564` |

### Notes on the parent spec

- **`show` is global.** `brd show <foreign id>` returns that entity and labels it with its
  owner. This is by design, and `tests/test_project_scope.py:308-337` pins it. The card
  says "show of a **local** id", so the guard runs `show` only on the current project's
  ids.
- **Foreign `[[<uuid>]]` links are by design.** If one project's text links to another
  project's uuid, that is an edge, and the target's title and summary may appear in
  `refs` / `referenced_by` [P D3 L33, §2 L119]. That is not a leak. So the seed contains
  no cross-project links or edges. What the guard catches is content showing up with no
  edge that put it there.
- **A refused foreign id echoes the id and the owner.** When a scoped command gets
  another project's id, the error message names that id and the owning project
  (`src/brd/entities.py:41-45`, [P §2 L113-115]). The user typed that id, so seeing it
  again is not a leak. The other project's **content** must still not appear.

## Terms

- **side**: one of the two seeded projects, `alpha` or `bravo`. Both are registered with
  `brd init` in sibling directories `<tmp>/alpha` and `<tmp>/bravo`, sharing one
  `XDG_DATA_HOME` and therefore one `brd.db`.
- **marker**: a token that appears in every piece of user-written text of a side, and
  nowhere else. Use `ALPHAMARK` for alpha and `BRAVOMARK` for bravo. It goes in titles,
  descriptions, bodies, comment bodies, comment authors, document content and (in
  lowercase) tags. Matching is **case-insensitive**, because tags are normalised.
- **foreign ids**: every id the other side owns. That means its project id, card ids,
  issue ids, document ids and comment ids.
- **leak**: the other side's marker, or any foreign id, appears in a command's stdout.
  One exception: an id the command was given as an argument may appear (see the notes
  above).

## Behaviour

### B1. Seed (the same shape on both sides)

Each side `S` with marker `M` is seeded through the CLI with its cwd at its root, in this
order:

1. `docs/notes.md` with content `# M notes\n\nSee [[plan]].\n`. Register it with
   `brd doc add docs/notes.md --title "M notes" --tag M-tag`, where `M-tag` is the
   lowercase marker plus `-tag`. Both sides have a document with stem `notes`, so a
   `[[notes]]` link that resolved across projects would pull in the other side's title.
2. A card `M story` (the parent).
3. A child card `M task one` under the story, with description
   `M task links [[notes]]`.
4. A child card `M task two` under the story, `--blocked-by` task one.
5. An issue `M bug` with body `M bug about [[notes]]` and `--blocks` task two.
6. A comment on task one: body `M comment on [[notes]]`, `--author M-author`.
7. An explicit ref from task one to the issue (`brd ref add`).

Both sides have the same hierarchy, edge, link, ref, comment and tag shapes, and stems
that collide. Only the marker differs. The cards are all `todo`, so `next` lists task
one on each side.

The seed runs **once per test module** (module-scoped fixture) and records each side's
root and its ids. Every test then sets `XDG_DATA_HOME` and the cwd for itself.

### B2. Commands under guard

Each row runs from both sides. For each side it runs from the root and from
`<root>/sub/deeper` (created by the fixture, not registered), in both JSON mode and
`--pretty`. Rows marked *(own id)* pass the current side's id.

| id | Command | Expected |
|---|---|---|
| `list` | `brd list` | ok |
| `list-status` | `brd list --status todo` | ok |
| `list-parent` | `brd list --parent <story>` *(own id)* | ok |
| `next` | `brd next` | ok |
| `next-parent` | `brd next --parent <story>` *(own id)* | ok |
| `tree` | `brd tree` | ok |
| `tree-root` | `brd tree <story>` *(own id)* | ok |
| `issue-list` | `brd issue list` | ok |
| `doc-list` | `brd doc list` | ok |
| `doc-list-tag` | `brd doc list --tag <own tag>` | ok |
| `tag-counts` | `brd tag list` | ok |
| `tag-list` | `brd tag list <doc>` *(own id)* | ok |
| `comment-list` | `brd comment list <task one>` *(own id)* | ok |
| `show-card` | `brd show <task one>` *(own id)* | ok |
| `show-issue` | `brd show <issue>` *(own id)* | ok |
| `show-doc` | `brd show <doc>` *(own id)* | ok |
| `export` | `brd export` | ok |

"ok" means exit code 0. The output is checked for a leak (B4) and for one sanity
condition: the **own** marker appears (case-insensitively) in stdout. Without the sanity
check, a command that printed nothing would trivially pass. Every row prints some text
of the current side, so the condition holds for all of them.

Link and ref resolution is covered inside these rows. `list`, `next` and `show-card`
include `refs`/`referenced_by` (`src/brd/views.py:14-18`). `--pretty` renders `[[notes]]`
with the resolved document's title (`src/brd/pretty.py:6-12`). `show-doc` lists
`referenced_by` for the `notes` document. `export` includes only the *explicit* refs (the task one → issue ref), not `[[...]]` mention refs.

### B3. Foreign ids passed to scoped lookups

These run from each side, at its root, in both modes, with the **other** side's ids:

| id | Command | Expected |
|---|---|---|
| `list-parent-foreign` | `brd list --parent <foreign story>` | ok, `[]` (pinned at unit level by `tests/test_project_scope.py:274`) |
| `next-parent-foreign` | `brd next --parent <foreign story>` | error `CardNotFoundError` |
| `tree-root-foreign` | `brd tree <foreign story>` | error `CardNotFoundError` |
| `comment-list-foreign` | `brd comment list <foreign task one>` | error `CardNotFoundError` |
| `tag-list-foreign` | `brd tag list <foreign doc>` | error `DocumentNotFoundError` |

Error rows exit with code 1 and print an error envelope (JSON) or the error text
(`--pretty`). The leak check (B4) applies in both modes. The id passed is exempt, and so
is the other side's project name and id, which the refusal message names by design.
The other side's marker must not appear. The own-marker sanity check does not apply to
these rows.

If any `Expected` cell turns out to differ from what the code does today, and the actual
behaviour is still leak-free, the implementer may correct the cell. The cell must not be
weakened to hide a leak.

### B4. The leak check

Given a command's stdout, the current side and the arguments it was given:

- the other side's marker does not occur (case-insensitive substring), and
- no foreign id occurs as a substring, apart from the exempt ids listed above.

On failure, the assertion message names the command id, the side, the cwd variant, the
mode and the offending token, so that one failing case says where the leak is.

### B5. Fix: `export` is scoped in full

`snapshot.export(conn, project_id, root)` returns, for its `comments`, `tags` and `refs`
sections, only the rows whose **owning entity** belongs to `project_id`:

- `comments`: rows whose `entity_id` is owned by the project.
- `tags`: rows whose `entity_id` is owned by the project.
- `refs` (explicit only, as today): rows whose `src_id` is owned by the project. The
  `dst_id` is not filtered, because edges are exported as stored [P §5 L205-206].

Each section keeps today's columns and ordering: comments by `created_at, rowid`, tags by
`entity_id, tag`, refs by `src_id, dst_id`. Filter through `db.in_project`, so there is
one scoping helper [P §2 L109]. When there is only one project, the export is unchanged.
`brd import` of a scoped export behaves as before (`tests/test_snapshot.py` keeps
passing).

### B6. Any further leak the guard finds

If B2 or B3 fails anywhere other than export, fix the leak in the same subtask. Filter
the offending query with `db.in_project`, or check the id with
`entities.require_in_project` or `core.require_card`, so the command meets the
constraint table. Each such fix also gets a domain-level test next to the existing ones
in `tests/test_project_scope.py`. The exploration found no leak apart from export, so
this section is a contingency.

## Tests

| # | Test | Tier | Why this tier / what it proves |
|---|---|---|---|
| T1 | `tests/test_cli_leak_guard.py::test_nothing_from_the_other_project_leaks`, parametrised over side × cwd variant (root, `sub/deeper`) × the B2 rows × mode (JSON, `--pretty`). Asserts exit 0, the B4 leak check and the own-marker sanity check. | CLI | The card asks for one parametrised CLI test [P L255-257]. A leak can sit in a domain query, in a view (`views.py`), or in `--pretty` rendering, and only the CLI goes through all three plus `open_project` resolution. Fails today on the `export` rows (B5). |
| T2 | Same file: `test_a_foreign_id_reveals_no_foreign_content`, parametrised over side × the B3 rows × mode. Asserts the expected exit code and envelope type (`err(...)` in JSON mode), and the B4 check with the exemptions. | CLI | Scoped lookups given an id from the other board must refuse without dumping its content. The error envelope is user-visible wiring. |
| T3 | `tests/test_project_scope.py::test_export_holds_only_the_projects_comments_tags_and_refs`, using the `two` fixture (`:118`). Give both projects a comment, a tag on a document, and an explicit ref between their own entities. `snapshot.export(two, P, root)` returns only P's comment ids, P's `(entity_id, tag)` pairs and refs with P-owned `src_id`. The other project's rows are still in the db. | Domain | Pins B5 at the function that owns it, next to the existing export scope tests (`:304`, `:580`). Fails today. |
| T4 | Same file: `test_export_keeps_a_ref_to_another_projects_entity`. Insert a raw explicit ref row (factory or `INSERT`) from a P card to a Q entity. P's export includes it, and Q's export does not. | Domain | B5's `dst_id` rule [P §5 L205-206]. Pins the filter to the source, so a later "fix" that filters both ends is rejected. |
| T5 | The seed fixture checks itself: after seeding, `brd export` from each side (after B5) has 3 cards, 1 issue, 1 document, 1 comment, 1 tag and 1 explicit ref. The `[[notes]]` mention refs are not in the export (explicit only), so the seed check also runs `brd show <task one>` and asserts its `refs` include its own side's `notes` document id. | CLI (inside T1's fixture) | Guards the guard. If seeding silently failed (for example the doc was never added, so the stems never collide), T1 would pass vacuously. |

Kept unchanged: every existing test, including `tests/test_snapshot.py` (export shape and
round trip) and the global-`show` tests at `tests/test_project_scope.py:308-337`.
Baseline: `uv run pytest` gives 668 passed. After this card it is 668 plus the new cases,
all passing. T1 runs many cases, so seeding happens once per module (B1) to keep the
file's run time small (target: a few seconds).

## Out of scope

- Cross-project edges, `blockers` output and `not-found` targets. Those are phase 3
  [P L281-283]. The seed has no cross-project edges or links, because those may cross by
  design [P D3 L33].
- `brd export --all`, export format v2 and import placement. Those are phase 4 [P §5].
- `brd show <foreign id>` (global by design), `brd projects` (lists every project by
  design) and `brd prompt` (static text).
- Mutating commands on foreign ids. Their refusals are already pinned at domain level
  (`tests/test_project_scope.py:234-240`, `:475-481`, `:555-563`).
- Nested projects (one root inside another). Resolution is covered by 3.2's tests. The
  guard uses sibling roots plus an unregistered subdirectory.
- `brd doc update`/`restore`/`sync` and `brd import`, which are not listing or lookup
  commands. (`doc list` syncs implicitly and is covered.)
