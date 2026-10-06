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


---

# 3.4 Leak Guard Across Every Listing and Lookup Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scope `brd export`'s `comments`, `tags` and `refs` sections to the current project, then add one parametrised CLI test that seeds two near-identical projects in one `brd.db` and proves no listing or lookup command shows the other project's data.

**Architecture:** The fix is in the three unscoped `SELECT`s in `src/brd/snapshot.py::export`. Each gets the existing scoping join `db.in_project(...)`: on `comments.entity_id`, on `tags.entity_id`, and on `refs.src_id` only (an edge's target may sit in another project). The guard is a new test module, `tests/test_cli_leak_guard.py`. A module-scoped fixture seeds both projects once through the CLI and checks that the seed worked. Two parametrised tests then run every command row from each side, cwd and output mode, and search stdout for the other side's marker or ids.

**Tech Stack:** Python ≥3.12, stdlib `sqlite3`, Typer (`tests/cli_helpers.invoke` wraps `typer.testing.CliRunner`), pytest, run with `uv run pytest`.

**Spec:** `docs/superpowers/specs/3-4-leak-guard-across-9da10121.md` (reproduced in full above).

## Global Constraints

- One scoping helper: filter through `db.in_project(id_column)` (`src/brd/db.py:561-564`). It returns `JOIN entities AS scope ON scope.id = <id_column> AND scope.project_id = ?`, which binds exactly one `?` parameter. Do not write a second scoping query.
- `export` keeps today's columns and order: comments `id, entity_id, author, body, created_at` ordered by `created_at, rowid`; tags `entity_id, tag` ordered by `entity_id, tag`; refs `src_id, dst_id, origin` (explicit only) ordered by `src_id, dst_id`.
- Refs are filtered on `src_id` only. `dst_id` is never filtered: edges are exported as stored, including cross-project targets [P §5 L205-206].
- With one project, the export is unchanged. `tests/test_snapshot.py` keeps passing untouched.
- Markers are `ALPHAMARK` / `BRAVOMARK`. Tags are the lowercase marker plus `-tag`. Comment authors are the marker plus `-author`. Marker matching is case-insensitive.
- `show` is global by design. The guard runs `show` only on the current side's ids.
- A refused foreign id may echo the id it was given plus the other project's id and name. The other side's marker and any other foreign id must not appear.
- Baseline is `uv run pytest` → 668 passed. After Task 1: 671 passed. After Task 2: 827 passed (671 + 136 T1 cases + 20 T2 cases).
- The repo's commit messages are a plain imperative sentence with no `feat:` prefix.

## Review Focus

1. **A project with no comments, tags or refs of its own, while the other project has all three.** A person expects `brd export` to give `[]` for all three sections, not the other project's rows. Pinned in Task 1 (`test_export_of_a_project_without_comments_tags_or_refs_is_empty`).
2. **Comments on issues, not only on cards.** The join is on `entity_id`, so issue comments must be scoped exactly like card comments. Pinned in Task 1 (`test_export_holds_only_the_projects_comments_tags_and_refs`, which comments on `pi` and `qi`).
3. **Ordering after the join.** Adding a join must not change the documented order: comments by `created_at, rowid` even when their ids sort the other way, and tags by `entity_id, tag`. Pinned in Task 1 (same test: `k-p2` is inserted before `k-p1` and must come first; `atag` comes before `ptag`).
4. **An incoming ref from the other project (Q source → P target).** It is Q's edge, so a person expects it in Q's export and not in P's. A "fix" that filters on either end would put it in both. Pinned in Task 1 (`test_export_keeps_a_ref_to_another_projects_entity` asserts both directions).
5. **The guard passing vacuously.** If the seed silently broke (no document, so no colliding stems) or the guard cannot see a leak, every case would pass. The module fixture's `_check_seed` pins the seed (T5). Task 2 Step 3 reverts the export fix and watches the guard fail.

## File Structure

- `src/brd/snapshot.py`: `export()`. Its `comments`, `tags` and `refs` queries get `db.in_project(...)` and a `(project_id,)` parameter. No other change.
- `tests/test_project_scope.py`: three domain tests (T3, T4 and the Review Focus 1 test) plus an `_explicit_ref` helper, appended at the end of the file. They reuse the existing `two` fixture (`:117-130`), `root` fixture (`:483-487`) and `_comment` helper (`:610-616`).
- `tests/test_cli_leak_guard.py` (new): the seed fixture with its self-check (B1, T5), T1 (B2) and T2 (B3).

No other source file changes. A prototype of exactly the code below was run against this branch. Before the fix, the guard failed only on the 8 `export` rows: all other B2 rows and every B3 expected cell held. So B6 (fix any further leak) needs no work. If a non-export row ever fails while you run this plan, stop and report it rather than weakening the test.

---

### Task 1: Scope `export`'s comments, tags and refs to the project (B5)

**Files:**
- Modify: `src/brd/snapshot.py:29-46` (the `"comments"`, `"tags"` and `"refs"` entries of the dict that `export()` returns)
- Test: `tests/test_project_scope.py` (append at the end, after `test_show_lists_comments_of_a_foreign_card_and_issue`)

**Interfaces:**
- Consumes: `db.in_project(id_column: str) -> str` (existing). From `tests/test_project_scope.py`: the `two` fixture (P owns cards `p1`, `p2`; Q owns cards `q1`, `q-child`, issue `qi` and document `qd` tagged `qtag`), the `root` fixture (`tmp_path / "repo"` with `docs/`), `_comment(conn, comment_id, entity_id, body)` (inserts author `'me'` and `created_at` `NOW`, then commits), and the module constants `P`, `Q`, `NOW`. Factories `make_issue` and `make_document` are already imported there.
- Produces: `snapshot.export(conn, project_id, root) -> dict` with the same signature and keys as today, scoped to `project_id` in every section. Test helper `_explicit_ref(conn, src_id, dst_id)` in `tests/test_project_scope.py`.

- [ ] **Step 1: Write the failing tests**

Append to the end of `tests/test_project_scope.py`:

```python


def _explicit_ref(conn, src_id, dst_id):
    conn.execute(
        "INSERT INTO refs (src_id, dst_id, origin) VALUES (?, ?, 'explicit')", (src_id, dst_id)
    )
    conn.commit()


def test_export_holds_only_the_projects_comments_tags_and_refs(two, root):
    make_issue(two, "pi")
    make_document(two, "pd", "pnotes")
    two.executemany(
        "INSERT INTO tags (entity_id, tag) VALUES (?, ?)", [("pd", "ptag"), ("pd", "atag")]
    )
    _comment(two, "k-p2", "p1", "on p card")  # inserted first: rowid, not id, orders
    _comment(two, "k-p1", "pi", "on p issue")
    _comment(two, "k-qc", "q1", "on q card")
    _comment(two, "k-qi", "qi", "on q issue")
    _explicit_ref(two, "p1", "pi")
    _explicit_ref(two, "p1", "p2")
    _explicit_ref(two, "q1", "q-child")
    data = snapshot.export(two, P, root)
    assert [c["id"] for c in data["comments"]] == ["k-p2", "k-p1"]
    assert data["comments"][0] == {
        "id": "k-p2", "entity_id": "p1", "author": "me", "body": "on p card", "created_at": NOW
    }
    assert data["tags"] == [{"entity_id": "pd", "tag": "atag"}, {"entity_id": "pd", "tag": "ptag"}]
    assert data["refs"] == [
        {"src_id": "p1", "dst_id": "p2", "origin": "explicit"},
        {"src_id": "p1", "dst_id": "pi", "origin": "explicit"},
    ]
    still = two.execute(
        "SELECT (SELECT COUNT(*) FROM comments WHERE entity_id IN ('q1', 'qi')), "
        "(SELECT COUNT(*) FROM tags WHERE entity_id = 'qd'), "
        "(SELECT COUNT(*) FROM refs WHERE src_id = 'q1')"
    ).fetchone()
    assert tuple(still) == (2, 1, 1)


def test_export_of_a_project_without_comments_tags_or_refs_is_empty(two, root):
    _comment(two, "k-qc", "q1", "on q card")
    _explicit_ref(two, "q1", "q-child")  # Q's qd is already tagged qtag
    data = snapshot.export(two, P, root)
    assert (data["comments"], data["tags"], data["refs"]) == ([], [], [])


def test_export_keeps_a_ref_to_another_projects_entity(two, root):
    _explicit_ref(two, "p1", "qi")
    _explicit_ref(two, "q1", "p1")
    assert snapshot.export(two, P, root)["refs"] == [
        {"src_id": "p1", "dst_id": "qi", "origin": "explicit"}
    ]
    assert snapshot.export(two, Q, root)["refs"] == [
        {"src_id": "q1", "dst_id": "p1", "origin": "explicit"}
    ]
```

Notes for the implementer:
- `_comment` is defined further up the same module (`:610`), so calling it here is fine.
- The `two` fixture uses a single-board connection (`pconn`), so `snapshot.export(two, Q, root)` syncs Q's documents against `root`. `qd`'s source is not under `root`, so the sync records it as `missing` and does not raise. `test_show_syncs_only_the_owning_projects_documents` relies on the same behaviour.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_project_scope.py -q -k "export_holds_only_the_projects_comments or export_of_a_project_without or export_keeps_a_ref"`

Expected: `3 failed`. Each failure is an `AssertionError` showing the other project's rows in the export, for example `Left contains 2 more items` for the comment ids in the first test, `{'src_id': 'q1', 'dst_id': 'p1', 'origin': 'explicit'}` as an extra item in P's refs in the third, and non-empty lists in the second.

- [ ] **Step 3: Write the minimal implementation**

In `src/brd/snapshot.py`, replace the three entries of the dict that `export()` returns (currently lines 29-46):

```python
        "comments": [
            dict(row)
            for row in conn.execute(
                "SELECT id, entity_id, author, body, created_at FROM comments "
                "ORDER BY created_at, rowid"
            )
        ],
        "tags": [
            dict(row)
            for row in conn.execute("SELECT entity_id, tag FROM tags ORDER BY entity_id, tag")
        ],
        "refs": [
            dict(row)
            for row in conn.execute(
                "SELECT src_id, dst_id, origin FROM refs WHERE origin = 'explicit' "
                "ORDER BY src_id, dst_id"
            )
        ],
```

with:

```python
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
```

Why qualified column names: the join adds an `entities AS scope` table that has its own `id` column, so a bare `id` would be ambiguous. sqlite3 still names a result column `comments.id` as `id`, so `dict(row)` keys stay `id`, `entity_id`, and so on. `db` is already imported in `snapshot.py` (`from brd import core, db, documents, entities, issues, refs`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_project_scope.py tests/test_snapshot.py -q`
Expected: `129 passed` (`tests/test_project_scope.py`: 101 existing + 3 new; `tests/test_snapshot.py`: 25, unchanged).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: `671 passed`.

- [ ] **Step 6: Commit**

```bash
git add src/brd/snapshot.py tests/test_project_scope.py
git commit -m "Scope brd export's comments, tags and refs to the current project"
```

---

### Task 2: CLI leak guard across every listing and lookup command (B1-B4, T1, T2, T5)

**Files:**
- Create: `tests/test_cli_leak_guard.py`

**Interfaces:**
- Consumes: `tests.cli_helpers.invoke(*args, input=None)`. It runs the Typer app in-process with `CliRunner` and returns a `click.testing.Result` with `.exit_code`, `.stdout` and `.output`. Also the CLI's JSON envelope (`{"ok": true, "data": ...}` / `{"ok": false, "error": {"type": ..., "message": ...}}`), its `--pretty` error line `Error (<Type>): <message>`, and Task 1's scoped `brd export`. The seed check (T5) asserts exact counts in the export, so it needs Task 1.
- Produces: nothing other tasks consume.

Facts the test relies on, all checked against the code on this branch:
- `brd init` (cwd = root) prints `{"ok": true, "data": {"id", "name", "root_path", "created_at"}}`. The project name defaults to the directory name (`alpha` / `bravo`), which contains no marker.
- `brd add`, `brd issue open`, `brd doc add` and `brd comment add` each print the created entity, with its `id`, as `data`.
- `brd tag list` with no argument prints the project's `[{"tag", "count"}]`. With a document id, it prints `{"id", "tags"}`.
- Projects resolve by the deepest registered root above the cwd, so `<root>/sub/deeper` (never registered) resolves to that side.
- `XDG_DATA_HOME` is read on every call (`src/brd/paths.py:data_dir`), so setting it per test is enough to point at the shared `brd.db`.
- `brd export --pretty` and `brd tag list --pretty` print `str(data)` (a Python repr). That still contains the titles and tags, so the own-marker sanity check holds.

- [ ] **Step 1: Write the guard**

Create `tests/test_cli_leak_guard.py`:

```python
"""Leak guard: every listing and lookup command, run from one project, shows
nothing owned by another project in the same brd.db."""

import json
import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.cli_helpers import invoke

SIDES = ("alpha", "bravo")
MARKERS = {"alpha": "ALPHAMARK", "bravo": "BRAVOMARK"}


@dataclass
class Side:
    name: str
    marker: str
    root: Path
    project: str
    story: str
    task_one: str
    task_two: str
    issue: str
    doc: str
    comment: str

    @property
    def tag(self) -> str:
        return f"{self.marker.lower()}-tag"

    @property
    def ids(self) -> set[str]:
        return {
            self.project, self.story, self.task_one, self.task_two,
            self.issue, self.doc, self.comment,
        }


@dataclass
class Board:
    data: Path
    sides: dict[str, Side]

    def other(self, name: str) -> Side:
        return self.sides["bravo" if name == "alpha" else "alpha"]


def _ok(*args) -> dict:
    result = invoke(*args)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True, payload
    return payload["data"]


def _cards(nodes) -> list[dict]:
    return [n for node in nodes for n in [node, *_cards(node["children"])]]


def _seed(name: str, root: Path) -> Side:
    """B1: the same shape on both sides; only the marker differs."""
    m = MARKERS[name]
    root.mkdir()
    os.chdir(root)
    project = _ok("init")["id"]
    (root / "docs").mkdir()
    (root / "docs" / "notes.md").write_text(f"# {m} notes\n\nSee [[plan]].\n")
    doc = _ok("doc", "add", "docs/notes.md", "--title", f"{m} notes", "--tag", f"{m.lower()}-tag")
    story = _ok("add", "--title", f"{m} story")
    one = _ok(
        "add", "--title", f"{m} task one", "--parent", story["id"],
        "--description", f"{m} task links [[notes]]",
    )
    two = _ok(
        "add", "--title", f"{m} task two", "--parent", story["id"], "--blocked-by", one["id"]
    )
    issue = _ok(
        "issue", "open", "--title", f"{m} bug", "--body", f"{m} bug about [[notes]]",
        "--blocks", two["id"],
    )
    comment = _ok(
        "comment", "add", one["id"], f"{m} comment on [[notes]]", "--author", f"{m}-author"
    )
    _ok("ref", "add", one["id"], issue["id"])
    (root / "sub" / "deeper").mkdir(parents=True)
    return Side(
        name=name, marker=m, root=root, project=project, story=story["id"],
        task_one=one["id"], task_two=two["id"], issue=issue["id"], doc=doc["id"],
        comment=comment["id"],
    )


def _check_seed(side: Side) -> None:
    """T5, guarding the guard: a seed that silently failed would let every case pass."""
    os.chdir(side.root)
    exported = _ok("export")
    assert len(_cards(exported["cards"])) == 3
    assert [i["id"] for i in exported["issues"]] == [side.issue]
    assert [d["id"] for d in exported["documents"]] == [side.doc]
    assert [c["id"] for c in exported["comments"]] == [side.comment]
    assert exported["tags"] == [{"entity_id": side.doc, "tag": side.tag}]
    assert exported["refs"] == [
        {"src_id": side.task_one, "dst_id": side.issue, "origin": "explicit"}
    ]
    # [[notes]] mention refs are not exported; show proves the stem resolved.
    shown = _ok("show", side.task_one)
    assert side.doc in {r["id"] for r in shown["refs"]}


@pytest.fixture(scope="module")
def board(tmp_path_factory) -> Board:
    base = tmp_path_factory.mktemp("leak")
    data = base / "data"
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("XDG_DATA_HOME", str(data))
        mp.delenv("BRD_AUTHOR", raising=False)
        mp.chdir(base)
        sides = {name: _seed(name, base / name) for name in SIDES}
        for side in sides.values():
            _check_seed(side)
    return Board(data=data, sides=sides)


def _leaks(out: str, other: Side, exempt: frozenset[str] = frozenset()) -> list[str]:
    """B4: the other side's marker (any case) and every foreign id not exempt."""
    found = [other.marker] if other.marker.lower() in out.lower() else []
    return found + sorted(i for i in other.ids - exempt if i in out)


# B2: (id, argv builder). The builder gets the current side.
GUARDED = [
    ("list", lambda s: ["list"]),
    ("list-status", lambda s: ["list", "--status", "todo"]),
    ("list-parent", lambda s: ["list", "--parent", s.story]),
    ("next", lambda s: ["next"]),
    ("next-parent", lambda s: ["next", "--parent", s.story]),
    ("tree", lambda s: ["tree"]),
    ("tree-root", lambda s: ["tree", s.story]),
    ("issue-list", lambda s: ["issue", "list"]),
    ("doc-list", lambda s: ["doc", "list"]),
    ("doc-list-tag", lambda s: ["doc", "list", "--tag", s.tag]),
    ("tag-counts", lambda s: ["tag", "list"]),
    ("tag-list", lambda s: ["tag", "list", s.doc]),
    ("comment-list", lambda s: ["comment", "list", s.task_one]),
    ("show-card", lambda s: ["show", s.task_one]),
    ("show-issue", lambda s: ["show", s.issue]),
    ("show-doc", lambda s: ["show", s.doc]),
    ("export", lambda s: ["export"]),
]
CWDS = {"root": Path("."), "sub/deeper": Path("sub/deeper")}
MODES = {"json": [], "pretty": ["--pretty"]}


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(("command", "build"), GUARDED, ids=[g[0] for g in GUARDED])
@pytest.mark.parametrize("cwd", CWDS)
@pytest.mark.parametrize("side", SIDES)
def test_nothing_from_the_other_project_leaks(
    board, monkeypatch, side, cwd, command, build, mode
):
    me, other = board.sides[side], board.other(side)
    monkeypatch.setenv("XDG_DATA_HOME", str(board.data))
    monkeypatch.chdir(me.root / CWDS[cwd])
    result = invoke(*build(me), *MODES[mode])
    where = f"{command} from {side} at {cwd} ({mode})"
    assert result.exit_code == 0, f"{where}: {result.output}"
    assert me.marker.lower() in result.stdout.lower(), f"{where}: own data missing"
    assert _leaks(result.stdout, other) == [], f"{where} leaks"


# B3: (id, argv builder, expected error type or None for ok + []).
# The builder gets the other side.
FOREIGN = [
    ("list-parent-foreign", lambda o: ["list", "--parent", o.story], None),
    ("next-parent-foreign", lambda o: ["next", "--parent", o.story], "CardNotFoundError"),
    ("tree-root-foreign", lambda o: ["tree", o.story], "CardNotFoundError"),
    ("comment-list-foreign", lambda o: ["comment", "list", o.task_one], "CardNotFoundError"),
    ("tag-list-foreign", lambda o: ["tag", "list", o.doc], "DocumentNotFoundError"),
]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(("command", "build", "error"), FOREIGN, ids=[f[0] for f in FOREIGN])
@pytest.mark.parametrize("side", SIDES)
def test_a_foreign_id_reveals_no_foreign_content(
    board, monkeypatch, side, command, build, error, mode
):
    me, other = board.sides[side], board.other(side)
    monkeypatch.setenv("XDG_DATA_HOME", str(board.data))
    monkeypatch.chdir(me.root)
    args = build(other)
    result = invoke(*args, *MODES[mode])
    where = f"{command} from {side} ({mode})"
    if error is None:
        assert result.exit_code == 0, f"{where}: {result.output}"
        if mode == "json":
            assert json.loads(result.stdout) == {"ok": True, "data": []}, where
    else:
        assert result.exit_code == 1, f"{where}: {result.output}"
        if mode == "json":
            assert json.loads(result.stdout)["error"]["type"] == error, where
        else:
            assert result.stdout.startswith(f"Error ({error}): "), where
    # The refusal names the id it was given and the owning project by design.
    exempt = frozenset({other.project, *args})
    assert _leaks(result.stdout, other, exempt) == [], f"{where} leaks"
```

Design notes for the implementer (no action needed):
- The seed uses `os.chdir` inside `pytest.MonkeyPatch.context()`. `mp.chdir(base)` records the original cwd first, so leaving the `with` block restores both the cwd and the environment. Each test then sets `XDG_DATA_HOME` and its cwd through the function-scoped `monkeypatch`.
- The test ids look like `alpha-root-export-json` or `bravo-sub/deeper-list-pretty`, and every assertion message names the command, side, cwd and mode. A failing case therefore says where the leak is (B4).
- A `[[plan]]` link in the document matches no stem, so it stays unresolved. It is part of the spec's seed content and is harmless.

- [ ] **Step 2: Run the guard to verify it passes against the fixed export**

Run: `uv run pytest tests/test_cli_leak_guard.py -q`
Expected: `156 passed` (T1: 2 sides × 2 cwds × 17 rows × 2 modes = 136; T2: 2 sides × 5 rows × 2 modes = 20), in about a second.

- [ ] **Step 3: Prove the guard bites by reverting the Task 1 fix (RED)**

The leak this card found is already fixed by Task 1, so prove the guard catches it by putting the leak back temporarily. HEAD is Task 1's commit at this point.

Run:
```bash
git show HEAD -- src/brd/snapshot.py | git apply -R
uv run pytest tests/test_cli_leak_guard.py -q 2>&1 | tail -5
```
Expected: `156 errors`. Every case errors in the `board` fixture: `_check_seed` fails at `assert [c["id"] for c in exported["comments"]] == [side.comment]` with `Left contains one more item`, because the other side's comment is in the export.

Then restore the fix and confirm the file matches the commit again:
```bash
git checkout -- src/brd/snapshot.py
git status --short src/brd/snapshot.py
```
Expected: `git status` prints nothing for `src/brd/snapshot.py`.

(The prototype also confirmed what happens if `_check_seed` filters export rows to the own side's ids rather than counting them exactly. With the fix reverted, exactly the 8 `export` cases of `test_nothing_from_the_other_project_leaks` fail and the other 148 pass. Do not ship that weaker check: T5 requires the exact counts.)

- [ ] **Step 4: Run the guard again, then the full suite**

Run: `uv run pytest tests/test_cli_leak_guard.py -q`
Expected: `156 passed`.

Run: `uv run pytest -q`
Expected: `827 passed`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_cli_leak_guard.py
git commit -m "Guard every listing and lookup command against showing another project's data"
```

---

## Spec coverage check

| Spec item | Where |
|---|---|
| B1 seed: doc `notes` with tag, story, task one with `[[notes]]`, task two blocked by task one, issue with `[[notes]]` blocking task two, comment with author, explicit ref task one → issue; module-scoped; records roots and ids; `sub/deeper` created | Task 2 `_seed`, `board` fixture |
| B2: all 17 rows, both sides, root and `sub/deeper`, JSON and `--pretty`, exit 0, own-marker sanity, leak check | Task 2 `GUARDED`, `test_nothing_from_the_other_project_leaks` |
| B3: 5 foreign rows from root, both modes, expected exit and error type, leak check with id/project exemptions | Task 2 `FOREIGN`, `test_a_foreign_id_reveals_no_foreign_content` (all expected cells confirmed against current code by a prototype run) |
| B4: other marker case-insensitive, foreign ids as substrings, exemptions, message names command/side/cwd/mode | Task 2 `_leaks` and the `where` string |
| B5: comments/tags by owning entity, refs by `src_id` only, same columns and order, through `db.in_project`, single-project export unchanged | Task 1 Step 3; `tests/test_snapshot.py` stays green (Task 1 Step 4) |
| B6: further leaks | Prototype found none; Task 2 says to stop and report if one appears |
| T1 | Task 2 `test_nothing_from_the_other_project_leaks` |
| T2 | Task 2 `test_a_foreign_id_reveals_no_foreign_content` |
| T3 | Task 1 `test_export_holds_only_the_projects_comments_tags_and_refs` |
| T4 | Task 1 `test_export_keeps_a_ref_to_another_projects_entity` |
| T5 | Task 2 `_check_seed` inside the `board` fixture |
| Baseline 668 → 668 + new, all passing | Task 1 Step 5 (671), Task 2 Step 4 (827) |
<!-- task-pipeline: validated -->
