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

---

# 5.1 Export Is a List of Project Entries; `brd export --all` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `brd export` prints a v2 snapshot, `{"brd_export": 2, "projects": [entry, ...]}`, holding the current project. `brd export --all` prints every registered project from any directory. `brd import` still accepts what export writes, as long as the snapshot holds a single project.

**Architecture:** `snapshot.export` becomes `snapshot.export_project(conn, project)`, which returns one entry: today's v1 body plus a `project` object. `snapshot.export_projects(conn, projects)` wraps the entries in the v2 envelope, and both CLI paths call it. That is the single code path D9 asks for. `snapshot._load` checks the version: for v2 it unwraps exactly one entry and passes it to the unchanged `_load_export`. `--all` runs through a local `_run_global` helper in `src/brd/cli/snapshot.py`. The helper opens `master.connect()` without resolving a cwd project, lists projects with `db.list_projects(conn)`, and reports `BrdError`s through `_app.fail`, so `_app.py` does not change.

**Tech Stack:** Python 3, sqlite3, Typer CLI, pytest (run with `uv run pytest`).

**Spec:** `docs/superpowers/specs/5-1-export-is-a-list-of-a8e090a7.md` (prepended above).

## Global Constraints

- `data` has exactly the keys `brd_export` and `projects`, and `brd_export` is the integer `2`.
- Each entry has exactly the keys `project`, `cards`, `issues`, `documents`, `comments`, `tags`, `refs`.
- `project` has exactly `id`, `name`, `root_path`, `created_at`, equal to that project's row in `brd projects`.
- An entry's body is byte-for-byte today's v1 body: card nodes carry `blocked_by` id lists and no `blockers` key, documents carry `content`, and `refs` holds only `explicit` refs.
- Edges are exported as stored, including cross-project and not-found targets. An edge owned by another project never appears in this project's entry.
- `--all` lists projects in `brd projects` order (`db.list_projects`, by `created_at`) on the command's own connection. It never resolves the cwd project.
- `export` without `--all` is scoped to the current project. Outside a project it fails with a `ProjectNotFoundError` envelope and exit 1.
- Import accepts a v2 snapshot with exactly one entry, and v1 and `brd tree` snapshots unchanged. Zero or several entries, a non-list `projects`, or a bad entry → `ImportFormatError`, and nothing is written.
- Owned files: `src/brd/snapshot.py`, `src/brd/cli/snapshot.py`. Do not touch `src/brd/cli/_app.py`, and leave its `GUIDE` text as is.
- `export --all` is **not** added to the leak guard's `GUARDED` list.
- Verification: `uv run pytest` (whole suite) passes. No typecheck or linter is configured.

## Review Focus

1. **A project whose root directory was deleted** must not break `--all`. Its documents are served from the backup (Task 2: `test_export_all_with_a_missing_project_root`).
2. **A fresh install with no projects**, and `--all` run from a directory that is in no project, must succeed with `projects: []` and with every project respectively, not fail with `ProjectNotFoundError` (Task 2: `test_export_all_with_no_projects_is_empty`, `test_export_all_works_outside_any_project`).
3. **Feeding `export --all` output (two entries) back to `brd import`** must refuse cleanly with a message naming the count and write nothing. It must not partially import the first entry (Task 1: `test_import_refuses_a_multi_entry_export`, plus the import line in Task 2's `test_export_all_lists_every_project_in_creation_order`).
4. **A v2 entry missing one body key** (e.g. a hand-trimmed file without `refs`) must be `ImportFormatError` "malformed snapshot", not a silent partial import (Task 1: extra case in `test_malformed_snapshot_is_an_envelope`).
5. **`--pretty` export** must print parseable indented JSON for both paths. Today it prints a Python `repr` (`{'brd_export': 1, ...}`), which is not JSON. The spec asks for "the same JSON indented", so this plan adds a JSON renderer (Task 2: `test_export_pretty_is_indented_json`).

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/brd/snapshot.py` | Modify | `FORMAT_VERSION = 2`, `V1_FORMAT_VERSION = 1`, `export_project`, `export_projects`, `_single_entry`; `_load` dispatches on version. `export` is removed. |
| `src/brd/cli/snapshot.py` | Modify | `export` calls `export_projects`; `--all` flag; `_run_global`; `_indented` JSON renderer for `--pretty`. |
| `tests/test_snapshot.py` | Modify | New v2/`--all` tests; existing tests read the body through `_entry(...)`. |
| `tests/test_cli.py` | Modify | Two foreign-exclusion asserts read `["projects"][0]`. |
| `tests/test_cli_leak_guard.py` | Modify | `_check_seed` reads the single entry. |
| `README.md` | Modify | Snapshot section describes v2, `--all`, and what import accepts. |

**On `--pretty`:** `output._render_pretty` falls through to `str(data)` for a dict, so `brd export --pretty` prints a Python repr today. B3 and spec test 7 ask for indented JSON that parses. Task 2 therefore passes a render function to `run()` and prints `json.dumps(data, indent=2)` in `_run_global`. Both of those live in the owned CLI module. `_app.py` and `output.py` do not change.

---

### Task 1: Export format v2 and the one-entry import bridge

**Files:**
- Modify: `src/brd/snapshot.py:1-58` (constants and `export`), `src/brd/snapshot.py:69-80` (`_load`)
- Modify: `src/brd/cli/snapshot.py:11-17` (`export_cmd`)
- Test: `tests/test_snapshot.py`, `tests/test_cli.py:1189`, `tests/test_cli.py:1234`, `tests/test_cli_leak_guard.py:96-110`

**Interfaces:**
- Consumes: `brd.models.Project` (dataclass with `id`, `name`, `root_path`, `created_at`); `documents.sync_all(conn, project_id, root: Path)`; `core.build_tree(conn, project_id, with_blockers=False)`.
- Produces:
  - `snapshot.FORMAT_VERSION: int = 2`, `snapshot.V1_FORMAT_VERSION: int = 1`
  - `snapshot.ENTRY_BODY_KEYS: tuple[str, ...] = ("cards", "issues", "documents", "comments", "tags", "refs")`
  - `snapshot.export_project(conn: sqlite3.Connection, project: Project) -> dict`: one entry
  - `snapshot.export_projects(conn: sqlite3.Connection, projects: list[Project]) -> dict`: `{"brd_export": 2, "projects": [...]}`
  - Test helpers in `tests/test_snapshot.py`: `_entry(data) -> dict` (the only entry of a one-project export) and `_another_project(tmp_path, monkeypatch, name) -> tuple[Path, dict]` (inits a project in the **same** install and chdirs into it; returns its root and the `init` data).

- [ ] **Step 1: Write the failing tests and move existing tests to the v2 shape**

In `tests/test_snapshot.py`, add these helpers right after `_fresh_project` (after line 39):

```python
ENTRY_KEYS = {"project", "cards", "issues", "documents", "comments", "tags", "refs"}


def _entry(data):
    """The single project entry of a one-project export."""
    (entry,) = data["projects"]
    return entry


def _another_project(tmp_path, monkeypatch, name):
    """Init project `name` in the same install as `project` (same data dir,
    unlike _fresh_project) and chdir into it."""
    root = tmp_path / name
    root.mkdir()
    monkeypatch.chdir(root)
    return root, ok("init")
```

Replace `test_export_shape` (lines 42-48) with:

```python
def test_export_is_a_one_entry_project_list(populated):
    data = ok("export")
    assert set(data) == {"brd_export", "projects"}
    assert data["brd_export"] == 2
    entry = _entry(data)
    assert set(entry) == ENTRY_KEYS
    (registered,) = ok("projects")
    assert entry["project"] == registered
    assert set(entry["project"]) == {"id", "name", "root_path", "created_at"}
    assert [c["id"] for c in entry["cards"]] == [populated["card"]["id"]]
    assert entry["documents"][0]["content"].startswith("# Notes")
    assert entry["tags"] == [{"entity_id": populated["doc"]["id"], "tag": "design"}]
    assert entry["refs"] and all(r["origin"] == "explicit" for r in entry["refs"])


def test_export_of_an_empty_project_has_empty_lists(project):
    entry = _entry(ok("export"))
    assert {k: v for k, v in entry.items() if k != "project"} == {
        "cards": [], "issues": [], "documents": [], "comments": [], "tags": [], "refs": []
    }
```

In `test_import_rolls_back_document_backup_on_integrity_error`, change `data["comments"].append(` to:

```python
    _entry(data)["comments"].append(
```

In `test_import_rejects_unsafe_document_source_path`, change `data["documents"][0]["source_path"] = source_path` to:

```python
    _entry(data)["documents"][0]["source_path"] = source_path
```

Add four cases to the `test_malformed_snapshot_is_an_envelope` parametrize list (after `["not a node"],`):

```python
        {"brd_export": 2, "projects": "x"},
        {"brd_export": 2, "projects": [5]},
        {"brd_export": 2},
        {"brd_export": 2, "projects": [{"project": {}, "cards": []}]},
```

In `test_import_rejects_unknown_blocker`, change `data["cards"][0]["blocked_by"].append(GHOST)` to:

```python
    _entry(data)["cards"][0]["blocked_by"].append(GHOST)
```

In `test_import_rejects_unknown_ref_target`, change `data["refs"].append(...)` to:

```python
    _entry(data)["refs"].append(
        {"src_id": populated["card"]["id"], "dst_id": GHOST, "origin": "explicit"}
    )
```

Replace the body of `test_round_trip_keeps_refs_between_snapshot_entities` with:

```python
def test_round_trip_keeps_refs_between_snapshot_entities(populated, tmp_path, monkeypatch):
    data = ok("export")
    assert _entry(data)["refs"], "populated has an explicit issue -> document ref"
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(data))
    other = _fresh_project(tmp_path, monkeypatch)
    ok("import", snapshot)
    assert _entry(ok("export"))["refs"] == _entry(data)["refs"]
```

In `test_export_card_nodes_have_no_blockers`, change the first line of the body to:

```python
    nodes = list(_card_nodes(_entry(ok("export"))["cards"]))
```

Append at the end of `tests/test_snapshot.py`:

```python
@pytest.mark.parametrize("count", [0, 2])
def test_import_refuses_a_multi_entry_export(project, tmp_path, monkeypatch, count):
    ok("add", "--title", "A")
    entries = [_entry(ok("export"))]
    _another_project(tmp_path, monkeypatch, "second")
    ok("add", "--title", "B")
    entries.append(_entry(ok("export")))
    data = {"brd_export": 2, "projects": entries[:count]}
    other, error = _import_error_into_fresh(tmp_path, monkeypatch, data)
    assert error["type"] == "ImportFormatError"
    assert f"{count} project entries" in error["message"]
    assert "not supported yet" in error["message"]
    _assert_nothing_imported(other)
```

These stay as they are, because they import `ok("export")` output unchanged and so now exercise the one-entry v2 bridge: `test_round_trip_into_fresh_project`, `test_import_collision_touches_nothing`, `test_import_accepts_wrapped_export_envelope` (wraps a v2 export), and `test_import_stem_collision_touches_nothing`. Hand-built `{"brd_export": 1, ...}` inputs also stay, as proof that v1 still imports.

In `tests/test_cli.py`, line 1189, change to:

```python
    assert [node["id"] for node in ok("export")["projects"][0]["cards"]] == [mine]
```

In `tests/test_cli.py`, line 1234, change to:

```python
    assert [d["id"] for d in ok("export")["projects"][0]["documents"]] == [mine]
```

In `tests/test_cli_leak_guard.py` `_check_seed`, change `exported = _ok("export")` to:

```python
    (exported,) = _ok("export")["projects"]
    assert exported["project"]["id"] == side.project
```

(The rest of `_check_seed` reads `exported["cards"]` etc. and stays the same. The `("export", ...)` GUARDED case stays.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_snapshot.py tests/test_cli.py tests/test_cli_leak_guard.py -q`
Expected: FAIL. The new and edited export tests fail with `KeyError: 'projects'`, `test_import_refuses_a_multi_entry_export` fails because the message says "unsupported brd_export version 2", and the leak-guard module errors in the `board` fixture (`KeyError: 'projects'`). The four new malformed cases already pass, because v2 is rejected as unsupported today. They guard the new path.

- [ ] **Step 3: Implement v2 export and the import bridge**

In `src/brd/snapshot.py`, change the imports and constants (lines 1-8) to:

```python
import dataclasses
import sqlite3
from pathlib import Path, PurePosixPath

from brd import core, db, documents, entities, issues, refs
from brd.errors import EntityAlreadyExistsError, ImportFormatError
from brd.models import Project

FORMAT_VERSION = 2
V1_FORMAT_VERSION = 1
ENTRY_BODY_KEYS = ("cards", "issues", "documents", "comments", "tags", "refs")
```

Replace `def export(conn, project_id, root)` and its first lines with the following. The body from `"cards":` down to the closing `}` of the `"refs"` list stays exactly as it is:

```python
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
```

(This removes the `"brd_export": FORMAT_VERSION,` line from the old body. Everything from `"issues": ...` to the end of the function is unchanged and still uses `project_id` and `results`.)

Replace `_load` (lines 69-80) with:

```python
def _load(conn: sqlite3.Connection, project_id: str, raw) -> dict:
    # `brd export > file` writes the whole envelope; accept it unwrapped too.
    if isinstance(raw, dict) and isinstance(raw.get("data"), dict):
        raw = raw["data"]
    if isinstance(raw, dict) and "brd_export" in raw:
        if raw["brd_export"] == FORMAT_VERSION:
            return _load_export(conn, project_id, _single_entry(raw))
        if raw["brd_export"] != V1_FORMAT_VERSION:
            raise ImportFormatError(f"unsupported brd_export version {raw['brd_export']!r}")
        return _load_export(conn, project_id, raw)
    nodes = raw["data"] if isinstance(raw, dict) and "data" in raw else raw
    if not isinstance(nodes, list):
        raise ImportFormatError("expected a `brd export` object or a `brd tree` snapshot list")
    return {"imported": core.import_tree(conn, project_id, nodes)}


def _single_entry(snap: dict) -> dict:
    """Until multi-project import lands, a v2 snapshot imports only when it
    holds exactly one project; that entry's body goes into the cwd project."""
    entries = snap.get("projects")
    if not isinstance(entries, list):
        raise ImportFormatError(
            f"malformed snapshot: `projects` must be a list, got {type(entries).__name__}"
        )
    if len(entries) != 1:
        raise ImportFormatError(
            f"snapshot has {len(entries)} project entries; importing anything but "
            "exactly one project is not supported yet"
        )
    (entry,) = entries
    if not isinstance(entry, dict) or not all(key in entry for key in ENTRY_BODY_KEYS):
        raise ImportFormatError(
            "malformed snapshot: a project entry must be an object with "
            + ", ".join(ENTRY_BODY_KEYS)
        )
    return entry
```

In `src/brd/cli/snapshot.py`, replace `export_cmd` (lines 11-17) with:

```python
@app.command(name="export")
def export_cmd(pretty: bool = pretty_option()) -> None:
    """Print a JSON snapshot: a list of project entries, each with its cards, issues,
    documents, comments, tags and refs."""
    run(pretty, lambda ctx: snapshot.export_projects(ctx.conn, [ctx.project]))
```

(`Path` is still imported, because `import_cmd` uses it.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_snapshot.py tests/test_cli.py tests/test_cli_leak_guard.py -q`
Expected: PASS.

Then the whole suite: `uv run pytest -q`
Expected: PASS. If some other test indexes `ok("export")[...]`, it shows up here. Find them with `grep -rn 'ok("export")\|_ok("export")' tests` and fix each one by reading through `["projects"][0]`.

- [ ] **Step 5: Commit**

```bash
git add src/brd/snapshot.py src/brd/cli/snapshot.py tests/test_snapshot.py tests/test_cli.py tests/test_cli_leak_guard.py
git commit -m "Export a list of project entries (format v2); import a one-entry v2 snapshot"
```

---

### Task 2: `brd export --all`, indented JSON for `--pretty`, docs

**Files:**
- Modify: `src/brd/cli/snapshot.py` (imports, new `_indented`, `_run_global`, `export_cmd`)
- Modify: `README.md:60-68` (snapshot section)
- Test: `tests/test_snapshot.py`

**Interfaces:**
- Consumes: `snapshot.export_projects(conn, projects: list[Project]) -> dict` (Task 1); `db.list_projects(conn) -> list[Project]`; `master.connect() -> sqlite3.Connection`; `_app.fail(exc: BrdError, pretty: bool) -> NoReturn`; `_app.run(pretty, fn, render)`, where `render: Callable[[Ctx, Any], str]`; test helpers `_entry`, `_another_project`, `_card_nodes`, `write` (Task 1 or existing).
- Produces: CLI flag `brd export --all`; `cli.snapshot._indented(data: dict) -> str`; `cli.snapshot._run_global(pretty: bool, fn: Callable[[sqlite3.Connection], dict]) -> None`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_snapshot.py`, change the imports at the top to:

```python
import json
import shutil

import pytest

from brd import paths
from tests.cli_helpers import err, human, invoke, ok
```

Append at the end of `tests/test_snapshot.py`:

```python
def test_export_all_lists_every_project_in_creation_order(project, tmp_path, monkeypatch):
    a_card = ok("add", "--title", "A card")["id"]
    a_issue = ok("issue", "open", "--title", "A issue")["id"]
    a_entry = _entry(ok("export"))
    _another_project(tmp_path, monkeypatch, "second")
    b_card = ok("add", "--title", "B card")["id"]
    b_entry = _entry(ok("export"))

    from_b = ok("export", "--all")
    monkeypatch.chdir(project)
    from_a = ok("export", "--all")
    assert from_a == from_b
    assert set(from_a) == {"brd_export", "projects"} and from_a["brd_export"] == 2
    assert [e["project"] for e in from_a["projects"]] == ok("projects")
    assert from_a["projects"] == [a_entry, b_entry]
    assert [c["id"] for c in a_entry["cards"]] == [a_card]
    assert [i["id"] for i in a_entry["issues"]] == [a_issue]
    assert [c["id"] for c in b_entry["cards"]] == [b_card]
    assert b_entry["issues"] == []
    # Without --all, still only the current project.
    assert ok("export")["projects"] == [a_entry]

    # A two-project snapshot does not import yet (5.2), and writes nothing.
    snapshot = tmp_path / "all.json"
    snapshot.write_text(json.dumps(from_a))
    assert err("import", snapshot) == "ImportFormatError"
    assert [c["id"] for c in ok("list")] == [a_card]


def test_export_all_works_outside_any_project(project, tmp_path, monkeypatch):
    ok("add", "--title", "A")
    _another_project(tmp_path, monkeypatch, "second")
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)
    data = ok("export", "--all")
    assert [e["project"] for e in data["projects"]] == ok("projects")
    assert len(data["projects"]) == 2
    assert err("export") == "ProjectNotFoundError"


def test_export_all_with_no_projects_is_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    assert ok("export", "--all") == {"brd_export": 2, "projects": []}


def test_export_all_with_a_missing_project_root(project, tmp_path, monkeypatch):
    second, registered = _another_project(tmp_path, monkeypatch, "second")
    write(second, "docs/plan.md", "# Plan\nkept in the backup")
    doc = ok("doc", "add", "docs/plan.md")
    monkeypatch.chdir(project)
    shutil.rmtree(second)

    data = ok("export", "--all")
    (entry,) = [e for e in data["projects"] if e["project"]["id"] == registered["id"]]
    assert [d["id"] for d in entry["documents"]] == [doc["id"]]
    assert entry["documents"][0]["content"] == "# Plan\nkept in the backup"


def test_export_keeps_cross_project_and_not_found_edges(project, tmp_path, monkeypatch):
    _, b = _another_project(tmp_path, monkeypatch, "b")
    b_card = ok("add", "--title", "B card")["id"]
    b_issue = ok("issue", "open", "--title", "B issue")["id"]
    _, g = _another_project(tmp_path, monkeypatch, "g")
    ghost = ok("add", "--title", "ghost")["id"]
    monkeypatch.chdir(project)
    a1 = ok("add", "--title", "a1")["id"]
    a2 = ok("add", "--title", "a2")["id"]
    ok("block", a1, "--by", b_card)
    ok("block", a1, "--by", ghost)
    ok("block", a2, "--by", b_issue)
    ok("ref", "add", a1, b_card)
    ok("ref", "add", a1, ghost)
    ok("forget", "--project", g["id"])  # ghost is now not-found

    entry = _entry(ok("export"))
    nodes = {n["id"]: n for n in _card_nodes(entry["cards"])}
    assert set(nodes[a1]["blocked_by"]) == {b_card, ghost}
    assert nodes[a2]["blocked_by"] == [b_issue]
    assert {"src_id": a1, "dst_id": b_card, "origin": "explicit"} in entry["refs"]
    assert {"src_id": a1, "dst_id": ghost, "origin": "explicit"} in entry["refs"]

    everything = ok("export", "--all")
    assert [e["project"]["id"] for e in everything["projects"]] == [
        entry["project"]["id"], b["id"]
    ]
    assert everything["projects"][0] == entry
    b_entry = everything["projects"][1]
    assert b_entry["refs"] == []
    assert all(n["blocked_by"] == [] for n in _card_nodes(b_entry["cards"]))
    assert a1 not in json.dumps(b_entry) and a2 not in json.dumps(b_entry)


def test_export_pretty_is_indented_json(project, tmp_path, monkeypatch):
    ok("add", "--title", "A")
    _another_project(tmp_path, monkeypatch, "second")
    for args in (["export"], ["export", "--all"]):
        text = human(*args)
        assert text.startswith("{\n  ")
        assert json.loads(text) == ok(*args)


def test_export_help_mentions_all():
    result = invoke("export", "--help")
    assert result.exit_code == 0, result.output
    # Rich wraps help inside a bordered panel; compare with borders and
    # line breaks folded away.
    text = " ".join(result.stdout.replace("│", " ").split())
    assert "--all" in text
    assert "every registered project" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_snapshot.py -q -k "export_all or cross_project_and_not_found or pretty_is_indented or help_mentions_all"`
Expected: FAIL. Every `--all` call exits 2 with "No such option: --all", so `ok` fails its `exit_code == 0` assertion. `test_export_pretty_is_indented_json` fails on its `startswith("{\n  ")` assertion, because `--pretty` prints a Python repr today.

- [ ] **Step 3: Implement `--all` and the JSON renderer**

Replace the top of `src/brd/cli/snapshot.py`, through the end of `export_cmd`, with:

```python
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path

import typer

from brd import db, master, output, snapshot
from brd.cli._app import app, fail, pretty_option, run
from brd.errors import BrdError, ImportReadError


def _indented(data: dict) -> str:
    return json.dumps(data, indent=2)


def _run_global(pretty: bool, fn: Callable[[sqlite3.Connection], dict]) -> None:
    """Like run(), but never resolves the cwd project: for a command whose
    scope is every project, so it works from any directory."""
    try:
        conn = master.connect()
    except BrdError as exc:
        fail(exc, pretty)
    try:
        data = fn(conn)
    except BrdError as exc:
        fail(exc, pretty)
    finally:
        conn.close()
    if pretty:
        print(_indented(data))
    else:
        output.print_result(output.ok_envelope(data), pretty)


@app.command(name="export")
def export_cmd(
    all_projects: bool = typer.Option(
        False,
        "--all",
        help="Export every registered project, not just the current one; "
        "works from any directory.",
    ),
    pretty: bool = pretty_option(),
) -> None:
    """Print a JSON snapshot: a list of project entries, each with its cards, issues,
    documents, comments, tags and refs. Only the current project unless --all."""
    if all_projects:
        _run_global(pretty, lambda conn: snapshot.export_projects(conn, db.list_projects(conn)))
    else:
        run(
            pretty,
            lambda ctx: snapshot.export_projects(ctx.conn, [ctx.project]),
            lambda ctx, data: _indented(data),
        )
```

(`import_cmd` below is unchanged.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_snapshot.py -q`
Expected: PASS.

- [ ] **Step 5: Update the README snapshot section**

In `README.md`, replace the block from `To keep a durable, diffable record in git` through the paragraph that ends `Older \`brd tree\` snapshots still import.` with:

````markdown
To keep a durable, diffable record in git and move a board between
machines, commit a snapshot and restore from it:

```bash
brd export > docs/board/snapshot.json   # commit this
brd import docs/board/snapshot.json     # on another machine/clone, after brd init
```

A snapshot is a list of project entries: each one is a project (id, name,
root path) with its cards, issues, documents, comments, tags and refs.
`brd export` writes the current project; `brd export --all` writes every
registered project and works from any directory.

`import` restores a one-project snapshot into the current project. It preserves the original ids, content, and timestamps — including document backups (restore a missing file with `brd doc restore <id>`) — and refuses to run (touching nothing) if any id in the snapshot already exists in the target board. Older one-object `brd export` snapshots and `brd tree` snapshots still import.
````

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS. The leak guard's `export` case in `pretty` mode now prints indented JSON of the current side only, so it still finds no foreign marker.

- [ ] **Step 7: Commit**

```bash
git add src/brd/cli/snapshot.py tests/test_snapshot.py README.md
git commit -m "Add brd export --all for every project; print export --pretty as indented JSON"
```

---

## Spec coverage check

| Spec item | Task |
|---|---|
| B1 format: keys, `brd_export: 2`, entry keys, `project` equals `brd projects`, v1 body, empty project | Task 1 (`test_export_is_a_one_entry_project_list`, `test_export_of_an_empty_project_has_empty_lists`, `test_export_card_nodes_have_no_blockers`) |
| B2 plain export is current project only; leak guard; `ProjectNotFoundError` outside | Task 1 (leak guard `_check_seed`, `tests/test_cli.py` foreign tests); Task 2 (`test_export_all_works_outside_any_project`) |
| B3 `--all`: help, order, per-project equality, any cwd, no projects → `[]`, missing root, sync, `--pretty` | Task 2 (tests 3, 4, no-projects, 5, 7, help test). Sync: `export_project` calls `documents.sync_all` per project, and test 5 exercises the backup path |
| B4 cross-project and not-found edges kept; other projects' edges absent | Task 2 (`test_export_keeps_cross_project_and_not_found_edges`) |
| B5 import bridge: one entry, wrapped, 0/many refused, malformed, v1 and tree unchanged, other versions | Task 1 (round-trip tests, wrapped envelope, `test_import_refuses_a_multi_entry_export`, malformed parametrisation, existing v1/tree/`brd_export: 99` tests) |
| B6 docs: `--help`, README; GUIDE unchanged | Task 2 (help test, README step); `_app.py` untouched |
| Interface: `FORMAT_VERSION = 2`, v1 constant, `export_project`, `export_projects`, `db.list_projects` on own connection, no `_app.py` change | Tasks 1-2 |
<!-- task-pipeline: validated -->
