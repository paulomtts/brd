# 5.1 Export is a list of project entries; `brd export --all`

Card: `a8e090a7-01a6-4b53-952b-94879740afc9`. First subtask of story `3d5969ce`
"Export/import v2" (spec section 5, D9-D11), in milestone `6aa7043a` "Single database and
cross-project blocking". Story 4 (cross-project edges, not-found targets, `blockers`
output) is merged into this branch.

Parent design spec: `docs/superpowers/specs/2026-10-06-single-db-cross-project-blocking-design.md`.
It is in the main checkout (`/home/mtts/Code/brd/docs/...`), not in this branch's history.
Citations look like **[P §n Lx]** or **[P Dn Lx]**. Sibling spec cited:
`docs/superpowers/specs/4-3-blockers-detail-in-f6674b60.md` (**[4.3]**).

## Goal

Today `brd export` prints one flat v1 object (`{"brd_export": 1, cards, issues, documents,
comments, tags, refs}`) for the current project, and nothing exports the other projects
in the shared `brd.db`. This card changes the export format to v2: always a list of
project entries, each one today's v1 body plus a `project` object. `brd export` writes the
current project as a one-entry list; `brd export --all` writes every registered project.

## Inherited constraints

| Constraint | Source |
|---|---|
| Export format v2 is always a list of project entries; one-project and all-project exports share one code path. | [P D9 L39] |
| Envelope is `{"brd_export": 2, "projects": [{"project": {"id", "name", "root_path", "created_at"}, "cards", "issues", "documents", "comments", "tags", "refs"}]}`. | [P §5 L191-L203] |
| Each entry has exactly today's v1 body plus `project`. | [P §5 L205] |
| Edges are exported as stored, including cross-project and not-found targets. | [P §5 L205-L206] |
| `brd export` → `[current project]`; `brd export --all` → every project. Both call `export_project(conn, project)` per entry. | [P §5 L208-L209] |
| `export` without `--all` is scoped to the current project. | [P §2 L111] |
| `blocked_by` stays a list of ids in export; card nodes in export carry no `blockers`. | [P §4 L173-L174], [4.3] (export kept v1) |
| Import of v2, D11 placement and D10 replacement are later subtasks (5.2, 5.3). | story card `3d5969ce`, cards `2dbf2631`, `7188185d` |
| Owned files: `src/brd/snapshot.py`, `src/brd/cli/snapshot.py`. | story card `3d5969ce` |

## Behavior

### B1. Format

Every successful `brd export` prints the usual success envelope (`{"ok": true, "data": …}`)
whose `data` is:

```json
{
  "brd_export": 2,
  "projects": [
    {
      "project": {"id": "…", "name": "…", "root_path": "…", "created_at": "…"},
      "cards": [], "issues": [], "documents": [],
      "comments": [], "tags": [], "refs": []
    }
  ]
}
```

- `data` has exactly the keys `brd_export` and `projects`; `brd_export` is the integer `2`.
- Each entry has exactly the keys `project`, `cards`, `issues`, `documents`, `comments`,
  `tags`, `refs`.
- `project` has exactly `id`, `name`, `root_path`, `created_at`, equal to that project's
  row as `brd projects` / `brd init` report it.
- `cards`, `issues`, `documents`, `comments`, `tags`, `refs` are byte-for-byte what the v1
  export carried for that project today: same fields, same ordering, card tree nodes with
  `blocked_by` id lists and no `blockers` key, documents with `content`, only `explicit`
  refs.
- A project with no entities exports an entry with six empty lists.

### B2. `brd export` (no flag)

- Writes the current project (resolved from the cwd as every command does) as the single
  entry of `projects`.
- Contains nothing owned by another project (the leak guard's `export` case keeps passing).
- Outside any registered project: `ProjectNotFoundError` envelope, exit 1 (unchanged).

### B3. `brd export --all`

- New flag `--all` on `brd export`; help text says it exports every registered project.
- `projects` holds one entry per registered project, in `brd projects` order (by project
  `created_at`). Each entry holds only that project's own entities, exactly as
  `brd export` run from that project's root would produce it.
- Works from any directory, including one that is not inside a registered project (scope
  is global per [P §2 L111]). With no projects registered, `projects` is `[]`.
- A project whose `root_path` no longer exists still exports: its documents carry the
  backed-up content, as `brd export` already does for a missing source file. The command
  does not fail because one project's directory is gone.
- As today, exporting syncs each exported project's registered documents first (a changed
  source file is backed up); `--all` does this for every project.
- `--pretty` / `--human` prints the same JSON indented, as `brd export --pretty` does
  today (no text renderer).

### B4. Edges are exported as stored

In the entry of the project that owns the edge's source:

- a card blocked by a card or an issue in another project lists that id in its node's
  `blocked_by`;
- a card blocked by an id that no longer exists anywhere (not-found, e.g. after
  `brd forget` of the owning project) lists that id in `blocked_by`;
- an explicit ref from one of its entities to another project's entity, or to a not-found
  id, appears in `refs` as `{"src_id", "dst_id", "origin": "explicit"}`.

No edge is dropped or rewritten because its target is foreign or missing. An edge owned by
another project never appears in this project's entry, even when it points into this
project.

### B5. Import keeps accepting what export writes (bridge until 5.2)

Changing the export format must not break `brd export > f; brd import f`. Until 5.2
replaces import, `brd import` accepts:

- a v2 export (bare, or wrapped in the `{"ok": true, "data": …}` envelope) whose
  `projects` has **exactly one** entry: that entry's body is imported into the cwd
  project exactly as a v1 export is today (same validation, same refusal when any id
  already exists, same counts in the result). The entry's `project` object is ignored.
- a v2 export whose `projects` has zero or more than one entry: refused with
  `ImportFormatError`, message naming the entry count and saying a multi-project import
  is not supported yet; nothing is written.
- a v2 export whose `projects` is not a list, or whose single entry is not an object or
  lacks a body key: `ImportFormatError` envelope ("malformed snapshot: …"), nothing
  written — the same path malformed v1 input takes today.
- v1 exports and legacy `brd tree` snapshots, unchanged.
- any other `brd_export` value: `ImportFormatError` "unsupported brd_export version …",
  unchanged.

This bridge is the D11 one-entry rule's simplest case [P §5 L215-L216] without the
registration part; 5.2 owns the rest.

### B6. Docs

- `brd export --help` describes the v2 list and `--all`.
- README "commit a snapshot" section: `brd export` writes the current project;
  `brd export --all` writes every project; the snapshot is a list of project entries.
  The import sentence states one-project snapshots import into the current project and
  that older v1 and `brd tree` snapshots still import.
- `GUIDE` in `src/brd/cli/_app.py` stays as is (its `brd export > …` example still holds).

## Interface for the planner

- `snapshot.FORMAT_VERSION = 2`; keep the v1 value as a named constant for import.
- `snapshot.export_project(conn, project: Project) -> dict` returns one entry (B1);
  documents are synced from `Path(project.root_path)`. It replaces `snapshot.export`.
- One envelope helper (e.g. `snapshot.export_projects(conn, projects: list[Project]) ->
  dict`) wraps entries as `{"brd_export": 2, "projects": [...]}`; both CLI paths call it,
  so there is one code path [P D9].
- `--all` lists projects with `db.list_projects(conn)` on the command's own connection
  (not `master.list_all_projects()`, which opens another).
- `--all` must not resolve the cwd project, so it cannot go through `run()`'s
  `open_project()` as is; the CLI module opens the connection (`master.connect()`, which
  also migrates) and reports `BrdError`s with the same envelope/exit code as `run()`.
  `src/brd/cli/_app.py` is outside the story's owned files: prefer a local helper in
  `src/brd/cli/snapshot.py` reusing `_app.fail`; touching `_app.py` needs a reason in the
  plan.

## Tests

All tests run the real CLI through `tests/cli_helpers.py` (`ok`, `err`, `invoke`) with the
`project` fixture (tmp `XDG_DATA_HOME`, cwd = repo, `brd init` done). Tier: **CLI
integration**, because every behavior here is the observable JSON of a command and the
existing snapshot tests live at this tier; no unit tier is needed for a function that is
only a dict assembly over already-tested queries. New tests go in `tests/test_snapshot.py`.

Two projects in one install: a new helper creates a second dir under `tmp_path`, `chdir`s
into it and runs `ok("init")` **without** changing `XDG_DATA_HOME` (the existing
`_fresh_project` deliberately uses a separate data dir and stays for import tests).

### New

1. `test_export_is_a_one_entry_project_list` — `populated` fixture: `data` keys ==
   `{"brd_export", "projects"}`, `brd_export == 2`, one entry with exactly the seven keys,
   `entry["project"]` equals the project from `brd projects`, entry body matches today's
   assertions (card ids, document content, tags, explicit refs only).
2. `test_export_of_an_empty_project_has_empty_lists` — fresh `project`: one entry, six
   empty lists.
3. `test_export_all_lists_every_project_in_creation_order` — two projects each with a card
   (and an issue in one): `--all` from either root gives the same two entries in
   `brd projects` order, each entry equal to plain `brd export`'s single entry from that
   project's root; plain `export` from A still has one entry.
4. `test_export_all_works_outside_any_project` — `chdir` to an unregistered dir: `export
   --all` succeeds with every project; plain `export` there is `ProjectNotFoundError`.
5. `test_export_all_with_a_missing_project_root` — second project with a registered doc,
   delete its root dir: `export --all` succeeds and that entry's document carries the
   backed-up content.
6. `test_export_keeps_cross_project_and_not_found_edges` — three projects A, B, G in one
   install. B owns card `b_card` and open issue `b_issue`; G owns card `ghost`. From A:
   card `a1` blocked by `b_card` and by `ghost`, card `a2` blocked by `b_issue`,
   `ref add a1 b_card`, `ref add a1 ghost`. Then `forget --project <G>` (so `ghost` is
   not-found, as in 4.2's `test_forget_leaves_a_foreign_card_blocked_until_unblocked`).
   A's `export`: `set(a1 node blocked_by) == {b_card, ghost}`, `a2`'s == `[b_issue]`, `refs` contains both explicit refs. B's entry in
   `--all` contains none of A's edges; G has no entry.
7. `test_export_all_pretty_is_indented_json` — `export --all --pretty` parses as JSON
   equal to `export --all`'s `data` envelope output.
8. One-entry v2 import is covered by the updated round-trip tests below (they feed
   `ok("export")`, now v2, to `brd import`) and by the existing
   `test_import_accepts_wrapped_export_envelope`, which now wraps a v2 export.
9. `test_import_refuses_a_multi_entry_export` — two-project `export --all` file imported
   into a fresh install: `ImportFormatError`, fresh project still empty. Same for
   `{"brd_export": 2, "projects": []}`.
10. Malformed v2 cases added to the existing `test_malformed_snapshot_is_an_envelope`
    parametrisation: `{"brd_export": 2, "projects": "x"}`, `{"brd_export": 2,
    "projects": [5]}`, `{"brd_export": 2}` → `ImportFormatError`, nothing imported.

### Updated (shape moved under `data["projects"][0]`)

- `tests/test_snapshot.py`: `test_export_shape` (becomes test 1), and every test that
  reads or mutates `ok("export")[...]` before importing (round trip, collision, wrapped
  envelope, document-backup rollback, stem collision, unsafe source path, unknown blocker,
  unknown ref target, refs round trip, `test_export_card_nodes_have_no_blockers`). The
  hand-built `{"brd_export": 1, …}` inputs stay v1: they prove v1 still imports.
- `tests/test_cli.py` foreign-exclusion tests (`ok("export")["cards"]`,
  `ok("export")["documents"]`).
- `tests/test_cli_leak_guard.py` `_check_seed`. The `("export", …)` GUARDED case stays;
  `export --all` is **not** added to GUARDED, since it legitimately includes other
  projects.

### Verification

`uv run pytest` — full suite green.

## Out of scope

- v2 import placement (D11), registering the cwd or the recorded `root_path`, multi-entry
  import, per-project counts and not-found edge counts in the import report — card 5.2.
- Replacing a project with local state, confirmation, `--yes`, no-TTY refusal, round trip
  across two installs — card 5.3.
- Any change to what an entry's body contains (e.g. adding `blockers` to exported nodes),
  to `brd projects` ordering, or to `brd tree` snapshots.
- Changing `run()` / project resolution for other commands.
