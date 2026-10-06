# 3.2 Find the project by deepest registered root; drop the `.brd` marker

Card: `222a1279-5c8e-4432-b3c6-1348e809e3d8`. It is the second subtask of story `4939dac5`
"One database". The milestone is `6aa7043a` "Single database and cross-project blocking".
It is blocked by 3.1 `08eb80d6` (everything in `brd.db`), which is merged into this branch.
Siblings that run after it: 3.3 `91e68a83` (`init --relink`, `forget --project`) and 3.4
`9da10121` (leak guard).

Parent design spec: `docs/superpowers/specs/2026-10-06-single-db-cross-project-blocking-design.md`.
It is in the main checkout (`/home/mtts/Code/brd/docs/...`), not in this branch's history.
Citations look like **[P §n Lx]**.

## Goal

Today a command finds its project in two steps. It walks up from the cwd looking for a
`.brd` file (`master.find_marker`, `src/brd/master.py:152-160`), then looks up that
directory's exact `root_path` in `brd.db` (`master.registered_project`,
`src/brd/master.py:170-177`). `brd init` writes the marker and adds `.brd` to the repo's
`.gitignore`.

After this card, the registry in `brd.db` is the only source of truth. A command belongs to
the registered project whose `root_path` is the cwd or the cwd's deepest ancestor. `brd
init` writes nothing into the repo. `.brd` files and `.gitignore` lines that already exist
are left alone and have no effect.

## Inherited constraints

| Constraint | Source |
|---|---|
| The `.brd` marker is dropped. The current project is the deepest registered `root_path` that is the cwd or one of its ancestors. | [P D5 L35] |
| `master.resolve_project` picks that project in one query. If there is none, it raises `ProjectNotFoundError`. `Ctx` is `(conn, project)`. | [P §2 L100-102] |
| `brd init` registers the cwd with a new UUID and writes nothing into the repo: no marker and no `.gitignore` edit. Running it again in a registered root only updates the name. Nested projects are allowed and the deepest root wins. | [P §2 L104-107] |
| `init`'s in-repo `.brd/` directory migration, its UUID-marker migration and the `.gitignore` edit are removed. Existing `.brd` files and `.gitignore` lines are left alone and ignored. | [P §3 L144-146] |
| Required resolution tests: subdirectory, nested projects, unregistered dir. (`--relink` belongs to 3.3.) | [P Testing L258]; card text |
| Edge targets are still checked as same-project in code. This card does not relax that. | [P Implementation order L279-280] |

### Notes on the parent spec

- [P §2 L100] writes `master.resolve_project(cwd)`. Every data command already shares one
  `brd.db` connection (`src/brd/cli/_app.py:64-74`), and the connection is opened before
  resolution so that an unmigrated install migrates even outside a project. The function
  therefore takes the connection: `resolve_project(conn, start)`. Nothing else changes.
- [P §3 L146-147] asks for release notes about very old formats. This repo has no
  changelog, so the README's Storage section (B6) carries that note.

## Terms

- **cwd**: `Path.cwd()` with symlinks resolved (`Path.resolve()`), as `find_marker` did
  (`src/brd/master.py:153`).
- **ancestor-or-self of C**: C itself and every directory above it, up to and including
  `/`. The match is by whole path components. `/a/b` is an ancestor of `/a/b/c` but not of
  `/a/bc`.
- **registered root**: the `root_path` column of a `projects` row in `brd.db`. `init`
  stores it as `str(Path.cwd())` (`src/brd/cli/project.py:26`), and that does not change.

## Behaviour

### B1. Resolving the current project

`master.resolve_project(conn: sqlite3.Connection, start: Path) -> Project`:

1. Resolve `start` (follow symlinks).
2. Return the registered project whose `root_path` equals an ancestor-or-self of the
   resolved start and is the longest such path, which is the deepest one.
3. If no registered root is an ancestor-or-self, raise `ProjectNotFoundError`. The message
   contains the resolved start path and the text `brd init`. For example:
   `no registered project at or above /home/u/repo; run \`brd init\` there`.
4. Use one SQL statement. It must not treat `%` or `_` in a path as wildcards. For
   example, compute the candidate paths in Python (`[p, *p.parents]` as strings) and run
   `SELECT ... WHERE root_path IN (...) ORDER BY length(root_path) DESC LIMIT 1`. This
   also handles a project registered at `/`. Put the SQL in `src/brd/db.py`, next to
   `get_project` (`src/brd/db.py:505-509`), and build the row with `_row_to_project`. That
   follows the rule that SQL lives in `db.py` and `master.py` orchestrates.
5. The lookup is read-only and does not write to `brd.db`.

Results:

| Registered roots | cwd | Result |
|---|---|---|
| `/r` | `/r` | `/r` |
| `/r` | `/r/a/b` | `/r` |
| `/r`, `/r/sub` | `/r/sub/x` | `/r/sub` (deepest wins) |
| `/r`, `/r/sub` | `/r/other` | `/r` |
| `/r` | `/r2` | `ProjectNotFoundError` (`/r` is a string prefix but not a component prefix) |
| none | anywhere | `ProjectNotFoundError` |
| `/r` (cwd reached through symlink `/link` → `/r`) | `/link/a` | `/r` |

A `.brd` file or directory anywhere on the path makes no difference. An unregistered
directory that contains `.brd` gives the same `ProjectNotFoundError` as one that does not.

### B2. Command wiring

`open_project()` in `src/brd/cli/_app.py:64-74` keeps its order: it calls `master.connect()`
first, so the migration of 3.1 still runs from any command. It then calls
`master.resolve_project(conn, Path.cwd())`. If that raises, the connection is closed
before the exception propagates (same `BaseException` guard as today). Every command
that goes through `open_project` gets a `ProjectNotFoundError` error envelope with exit
code 1 when the cwd is not inside a registered project, as it does today.

### B3. `brd init`

`master.init_project(root_path, name)`:

- Upserts the project exactly as today (`db.upsert_project`, `src/brd/db.py:488-497`). A
  new root gets a new UUID, `name` (or the directory's basename) and `created_at`. A root
  that is already registered keeps its `id` and `created_at`, and only `name` changes.
- Writes no file and no directory under `root_path`. Leaves any existing `.gitignore`
  byte-for-byte unchanged, and creates none.
- Leaves an existing `.brd` file or `.brd/` directory in place, untouched, and never reads
  it. A `.brd/board.db` or a UUID in a `.brd` file is no longer imported.
- Works inside an already registered project. Running `init` in `/r/sub` while `/r` is
  registered adds a second project at `/r/sub`, and commands run below `/r/sub` then
  resolve to it (B1).
- Returns the stored `Project`. The CLI output of `brd init` does not change.

### B4. `brd forget`

`master.forget_project(root_path)` is unchanged except that it no longer deletes a `.brd`
file at the root (`src/brd/master.py:209-211`). A `.brd` file that exists there stays.
Removing the registry row, the cascaded rows and the doc backups works as before. The
exact-match lookup on `root_path` stays (`brd forget` is still positional-path or cwd; 3.3
changes it).

### B5. Removed code

The following are deleted from `src/brd/master.py`. No caller remains in `src/` or
`tests/`:

- `MARKER_FILENAME`, `find_marker`, `resolve_project_root`, `registered_project`
  (`:12`, `:152-177`).
- `_migrate_in_repo_format`, `_migrate_legacy_uuid_marker`, `_copy_cards` (`:71-114`).
  `_copy_cards` has no other caller. `consolidate.py` has its own copy logic.

`shutil` stays imported because `purge_all` uses it.

### B6. README

`README.md:40-45` ("Storage") describes the gitignored `.brd` marker and per-project
SQLite files. Replace it with text that says:

- `brd init` registers the current directory in `~/.local/share/brd/brd.db` (or
  `$XDG_DATA_HOME/brd/brd.db`) and writes nothing into the repo.
- A command uses the registered project whose root is the cwd or its deepest ancestor.
  Nested projects are allowed.
- An old `.brd` file or `.gitignore` line can be deleted by hand. brd ignores it.
- Boards stored in the very old in-repo `.brd/` or UUID-marker formats must first be
  opened once with the last release that still used per-project databases.

The snapshot/export paragraph that follows stays.

## Error paths

| Condition | Result |
|---|---|
| cwd not at or below any registered root (with or without a `.brd` file) | `ProjectNotFoundError`. The message contains the resolved cwd and `brd init`. Exit 1, error envelope, connection closed, `projects` table unchanged. |
| Unmigrated install with a failing migration | Unchanged from 3.1: `MigrationError` envelope, raised by `connect()` before resolution runs. |
| `brd forget` on an unregistered path | Unchanged: `ProjectNotFoundError("no registered project at …")`. |

## Tests

The suite runs with `uv run pytest`. There are two tiers:

- **Unit**: calls `master` / `db` functions directly against a real `brd.db` under
  `tmp_path` (`XDG_DATA_HOME` monkeypatched). This is the right tier for resolution
  rules and `init`'s file-system effects, because those are properties of the
  functions, and failures point straight at them.
- **CLI**: Typer `CliRunner` through `tests/cli_helpers` (`ok`/`err`/`invoke`) and the
  `project` fixture (`tests/conftest.py:14-25`). This is the right tier for things a user
  sees: envelopes, exit codes, and `open_project` wiring, including connection cleanup.

### New or rewritten

| # | Test | Tier | Why this tier |
|---|---|---|---|
| T1 | `resolve_project` at the registered root returns that project. | Unit | Base case of B1 |
| T2 | From a nested subdirectory (`root/a/b`), it returns the ancestor project. | Unit | B1 subdirectory rule [P L258] |
| T3 | With `/r` and `/r/sub` registered: from `/r/sub/x` it returns `/r/sub`, and from `/r/other` it returns `/r`. Registration order does not matter (register the deeper root first in one of the cases). | Unit | B1 deepest-wins rule [P L258] |
| T4 | With `tmp/repo` registered, `tmp/repo2` raises `ProjectNotFoundError`. | Unit | Component match, not string prefix |
| T5 | An unregistered dir raises `ProjectNotFoundError` whose message has the path and `brd init`. A `.brd` file in that dir changes nothing. | Unit | B1 step 3 [P L258] |
| T6 | A root path containing `%` and `_` (for example `tmp/a_%b`) resolves itself and does not match its sibling `tmp/aXYb`. | Unit | Guards the no-wildcards rule in B1 step 4 |
| T7 | `init_project` leaves the repo directory empty (`list(repo.iterdir()) == []`) and registers the project in `brd.db`. | Unit | B3 "writes nothing" (card) |
| T8 | `init_project` with an existing `.gitignore` leaves its bytes unchanged. With an existing `.brd` file holding a UUID, and a `.brd/` dir in another repo, both are untouched afterwards and no cards are imported. | Unit | B3 ignore rule [P L145] |
| T9 | Re-running `init_project` with a new name keeps `id` and `created_at` and changes `name`. One `projects` row. | Unit | B3 re-init (card). Already covered by `test_init_project_upserts_name_on_rerun` (`tests/test_master.py:86`) and `test_init_project_rerun_keeps_id_and_created_at` (`:287`). Keep them; add nothing new. |
| T10 | `init_project` in `/r/sub` while `/r` is registered gives two projects. | Unit | B3 nested allowed |
| T11 | `forget_project` removes the registry row and leaves a `.brd` file at the root in place. | Unit | B4. Rewrites `tests/test_master.py:177-186`. |
| T12 | CLI: `brd init`, then `brd add` at the root, then `brd list` from `repo/sub/deeper` shows the card. | CLI | User-visible subdirectory resolution through `open_project` |
| T13 | CLI: nested `brd init` in `repo/sub`. A card added from `repo/sub/x` is listed from `repo/sub` and not from `repo`. | CLI | User-visible deepest-wins rule |
| T14 | CLI: `brd list` in an unregistered dir (no marker) gives a `ProjectNotFoundError` envelope with exit 1, message containing `brd init` and the path, and no `projects` rows. Renamed from `test_unregistered_marker_is_a_project_not_found_envelope` (`tests/test_cli_app.py:109`). | CLI | B2 error envelope |
| T15 | CLI: `brd init` output is unchanged, and the cwd contains no `.brd` and no `.gitignore` afterwards. Inverts `tests/test_cli.py:58`. | CLI | B3 as the user sees it |

The existing tests `test_open_project_from_a_subdirectory_resolves_the_same_project` and
`..._through_a_symlinked_cwd_...` (`tests/test_cli_app.py:84-107`) must keep passing
unchanged.

### Removed or edited

- `tests/test_master.py`: delete `test_init_project_creates_brd_db_and_gitignored_marker`
  and `test_init_project_appends_to_existing_gitignore_once` (`:29-65`, replaced by T7
  and T8). Delete the legacy UUID-marker test (`:99-120`), the in-repo `.brd/` migration
  test (`:123-145`), both `test_find_marker_*` (`:147-161`) and
  `test_copy_cards_drops_dangling_legacy_edges` (`:398-420`), because their code is gone.
  Replace `test_registered_project_*` (`:372-393`) with T1 and T5.
- `tests/test_cli.py:131`: the assertion that `.brd` is absent after `forget` may stay,
  stays as is: init no longer creates a `.brd`, so it is trivially true and needs no edit.
- `tests/test_cli_app.py:23,154,169` and `tests/test_single_db_migration.py:564,580,627,644`:
  remove the lines that write `.brd`. Those tests chdir into a registered root, or into an
  unregistered one where they expect `ProjectNotFoundError`. They must still pass without
  the marker.

## Out of scope

- `brd init --relink` and `brd forget --project <id>`: sibling 3.3 `91e68a83`
  [P §2 L106, L122-123].
- The cross-project leak-guard test: sibling 3.4 `9da10121` [P Testing L255-257].
- Changing `forget` or `get_project` to anything other than an exact `root_path` match.
- Normalizing or re-resolving `root_path` values that are already stored, or how `init`
  stores the path.
- Deleting existing `.brd` files or `.gitignore` lines from users' repos.
- Cross-project edges, `blockers` output, export/import v2 (phases 3 and 4 of [P L271-284]).
- `brd prompt` text, which says nothing about the marker.

---

# 3.2 Find the project by deepest registered root; drop the `.brd` marker — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every command finds its project as the registered `root_path` that is the cwd or its deepest ancestor, and `brd init` writes nothing into the repo.

**Architecture:** One new read-only query, `db.deepest_project(conn, root_paths)`, picks the longest of a list of exact candidate paths. `master.resolve_project(conn, start)` builds those candidates (`start.resolve()` and every parent) and raises `ProjectNotFoundError` when nothing matches. `cli/_app.open_project` calls it in place of the marker walk. `master.init_project` shrinks to an upsert, `master.forget_project` stops deleting `.brd`, and every marker and legacy-import helper is deleted.

**Tech Stack:** Python 3.12, sqlite3 (stdlib), Typer, pytest. Run tests with `uv run pytest`.

**Spec:** `docs/superpowers/specs/3-2-find-the-project-by-222a1279.md` (reproduced in full above this line).

## Global Constraints

- SQL lives in `src/brd/db.py`; `src/brd/master.py` orchestrates (B1 step 4).
- Resolution is one SQL statement, uses no `LIKE`/`GLOB`, and does not write to `brd.db` (B1 steps 4-5).
- The not-found message is exactly `no registered project at or above {resolved start}; run \`brd init\` there` (B1 step 3).
- `open_project()` calls `master.connect()` before resolution and closes the connection on any `BaseException` from resolution (B2).
- `brd init` writes no file or directory under the root, never reads `.brd`, and never edits or creates `.gitignore` (B3).
- `brd forget` keeps its exact `root_path` match and no longer deletes `.brd` (B4).
- `root_path` is stored as `str(Path.cwd())` by `init`; do not change how it is stored (Out of scope).
- `shutil` stays imported in `master.py` (`purge_all` uses it) (B5).
- Edge targets stay checked as same-project; do not touch `blocked_by` code (Inherited constraints).
- Baseline: `uv run pytest -q` → `617 passed` before Task 1.

## Review Focus

1. **A stale `.brd` marker in an unregistered subdirectory of a registered project** (old checkouts leave these). Expected: the marker is ignored and the enclosing project is used. Pinned in Task 1 (unit) and Task 2 (CLI).
2. **A project registered at `/` (or any very short root) next to a deeper one.** Expected: `/` matches every path, and the deeper root still wins inside its tree. Pinned in Task 1.
3. **Resolution must not write.** A command run in an unregistered directory must leave `brd.db` unchanged, and a successful lookup must not open a write transaction. Pinned in Task 1 (`total_changes`) and Task 2 (T14 checks `projects` is empty).
4. **Forgetting a nested project.** Expected: commands below the forgotten root fall back to the enclosing registered project instead of failing. Pinned in Task 3.
5. **An existing `.gitignore` without a trailing newline.** The old code appended `\n.brd\n`. Expected: the bytes are untouched. Pinned in Task 3 (T8 compares bytes).

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/brd/db.py` | Modify (after `get_project`, `:505-509`) | Add `deepest_project`, the one resolution query |
| `src/brd/master.py` | Modify | Add `resolve_project`. Delete `MARKER_FILENAME`, `find_marker`, `resolve_project_root`, `registered_project`, `_copy_cards`, `_migrate_in_repo_format`, `_migrate_legacy_uuid_marker`. Shrink `init_project`. Drop the marker unlink from `forget_project` |
| `src/brd/cli/_app.py` | Modify `open_project` (`:64-74`) | Call `master.resolve_project` |
| `README.md` | Modify "Storage" (`:38-45`) | Describe the registry-only model |
| `tests/test_master.py` | Modify | Unit tests T1-T11 plus the Review Focus tests; delete the marker and legacy-import tests |
| `tests/test_cli_app.py` | Modify | CLI tests T12-T14, the stale-marker CLI test, and removal of `.brd` writes |
| `tests/test_cli.py` | Modify `test_init_registers_project` (`:52-64`) | T15 |
| `tests/test_single_db_migration.py` | Modify `:564`, `:580`, `:627`, `:644` | Remove `.brd` writes |

---

### Task 1: `resolve_project` — deepest registered root in one query

**Files:**
- Modify: `src/brd/db.py` (insert after `get_project`, which ends at line 509)
- Modify: `src/brd/master.py` (insert after `registered_project`, which ends at line 177)
- Test: `tests/test_master.py` (replace lines 372-395, the two `test_registered_project_*` tests)

**Interfaces:**
- Consumes: `db._row_to_project(row) -> Project`, `master.connect() -> sqlite3.Connection`, `master.init_project(root_path: Path, name: str | None = None) -> Project`, `db.upsert_project(conn, project) -> Project`.
- Produces:
  - `db.deepest_project(conn: sqlite3.Connection, root_paths: list[str]) -> Project | None`: the project whose `root_path` is the longest string in `root_paths`, or `None`.
  - `master.resolve_project(conn: sqlite3.Connection, start: Path) -> Project`: raises `ProjectNotFoundError("no registered project at or above {start.resolve()}; run `brd init` there")`.
  - Test helper `_resolve(start)` in `tests/test_master.py`: opens `master.connect()`, calls `resolve_project`, and closes the connection. Task 3 uses it.

- [ ] **Step 1: Write the failing tests**

In `tests/test_master.py`, delete `test_registered_project_returns_the_registered_row` and `test_registered_project_raises_when_root_is_not_registered` (lines 372-395). In their place, add the following. The imports at the top of the file (`shutil`, `uuid`, `pytest`, `db`, `master`, `paths`, `Project`, `PROJECT`, `make_card`, `make_document`) already cover everything used here.

```python
def _resolve(start):
    conn = master.connect()
    try:
        return master.resolve_project(conn, start)
    finally:
        conn.close()


def _not_found(start):
    return f"no registered project at or above {start.resolve()}; run `brd init` there"


def test_resolve_project_at_the_registered_root(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    project = master.init_project(repo)

    assert _resolve(repo) == project


def test_resolve_project_from_a_nested_subdirectory(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    nested = repo / "a" / "b"
    nested.mkdir(parents=True)
    project = master.init_project(repo)

    assert _resolve(nested) == project


@pytest.mark.parametrize("deeper_first", [False, True])
def test_resolve_project_picks_the_deepest_registered_root(tmp_path, monkeypatch, deeper_first):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    outer = tmp_path / "r"
    inner = outer / "sub"
    (inner / "x").mkdir(parents=True)
    (outer / "other").mkdir()
    if deeper_first:
        inner_project = master.init_project(inner)
        outer_project = master.init_project(outer)
    else:
        outer_project = master.init_project(outer)
        inner_project = master.init_project(inner)

    assert _resolve(inner / "x") == inner_project
    assert _resolve(inner) == inner_project
    assert _resolve(outer / "other") == outer_project
    assert _resolve(outer) == outer_project


def test_resolve_project_matches_whole_path_components(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    sibling = tmp_path / "repo2"
    repo.mkdir()
    sibling.mkdir()
    master.init_project(repo)

    with pytest.raises(master.ProjectNotFoundError):
        _resolve(sibling)


def test_resolve_project_with_nothing_registered_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    with pytest.raises(master.ProjectNotFoundError) as excinfo:
        _resolve(tmp_path)

    assert str(excinfo.value) == _not_found(tmp_path)


def test_resolve_project_outside_any_root_names_the_path_and_brd_init(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    registered = tmp_path / "registered"
    plain = tmp_path / "plain"
    marked = tmp_path / "marked"
    for directory in (registered, plain, marked):
        directory.mkdir()
    (marked / ".brd").write_text("")
    master.init_project(registered)

    with pytest.raises(master.ProjectNotFoundError) as plain_error:
        _resolve(plain)
    with pytest.raises(master.ProjectNotFoundError) as marked_error:
        _resolve(marked)

    assert str(plain_error.value) == _not_found(plain)
    assert str(marked_error.value) == _not_found(marked)
    assert "brd init" in str(plain_error.value)


def test_resolve_project_treats_percent_and_underscore_literally(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    wild = tmp_path / "a_%b"
    lookalike = tmp_path / "aXYb"
    (wild / "x").mkdir(parents=True)
    lookalike.mkdir()
    project = master.init_project(wild)

    assert _resolve(wild) == project
    assert _resolve(wild / "x") == project
    with pytest.raises(master.ProjectNotFoundError):
        _resolve(lookalike)


def test_resolve_project_follows_a_symlinked_start(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    (repo / "a").mkdir(parents=True)
    project = master.init_project(repo)
    link = tmp_path / "link"
    link.symlink_to(repo, target_is_directory=True)

    assert _resolve(link / "a") == project


def test_resolve_project_reaches_a_project_registered_at_the_filesystem_root(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    repo.mkdir()
    conn = master.connect()
    try:
        top = db.upsert_project(
            conn, Project(db.new_project_id(), "top", "/", "2026-01-01T00:00:00+00:00")
        )
        deeper = db.upsert_project(
            conn, Project(db.new_project_id(), "repo", str(repo), "2026-01-01T00:00:00+00:00")
        )

        assert master.resolve_project(conn, tmp_path) == top
        assert master.resolve_project(conn, repo) == deeper
    finally:
        conn.close()


def test_resolve_project_ignores_a_brd_marker_in_an_unregistered_subdirectory(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    sub = repo / "sub"
    sub.mkdir(parents=True)
    project = master.init_project(repo)
    (sub / ".brd").write_text("")

    assert _resolve(sub) == project


def test_resolve_project_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    repo.mkdir()
    project = master.init_project(repo)
    conn = master.connect()
    try:
        before = conn.total_changes

        assert master.resolve_project(conn, repo) == project
        with pytest.raises(master.ProjectNotFoundError):
            master.resolve_project(conn, tmp_path / "elsewhere")

        assert conn.total_changes == before
        assert not conn.in_transaction
    finally:
        conn.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_master.py -q -k resolve_project`
Expected: every selected test FAILS with `AttributeError: module 'brd.master' has no attribute 'resolve_project'`.

- [ ] **Step 3: Add the query to `src/brd/db.py`**

Insert directly after `get_project` (which ends at line 509), before `delete_project`:

```python
def deepest_project(conn: sqlite3.Connection, root_paths: list[str]) -> Project | None:
    """The project registered at the longest of root_paths, or None. An exact
    IN match, so `%` and `_` in a path are plain characters."""
    marks = ", ".join("?" for _ in root_paths)
    row = conn.execute(
        f"SELECT * FROM projects WHERE root_path IN ({marks}) "
        "ORDER BY length(root_path) DESC LIMIT 1",
        root_paths,
    ).fetchone()
    return _row_to_project(row) if row else None
```

- [ ] **Step 4: Add `resolve_project` to `src/brd/master.py`**

Insert directly after `registered_project` (which ends at line 177), before `list_all_projects`:

```python
def resolve_project(conn: sqlite3.Connection, start: Path) -> Project:
    """The registered project whose root is start or its deepest ancestor."""
    resolved = start.resolve()
    project = db.deepest_project(conn, [str(p) for p in (resolved, *resolved.parents)])
    if project is None:
        raise ProjectNotFoundError(
            f"no registered project at or above {resolved}; run `brd init` there"
        )
    return project
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_master.py -q -k resolve_project`
Expected: all PASS (12 tests: 11 functions, one parametrized twice).

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: all PASS. The count is 617 − 2 deleted + 12 new = 627.

- [ ] **Step 7: Commit**

```bash
git add src/brd/db.py src/brd/master.py tests/test_master.py
git commit -m "$(cat <<'EOF'
Resolve the project by the deepest registered root in one query

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Commands resolve through the registry, not the marker

**Files:**
- Modify: `src/brd/cli/_app.py:64-74` (`open_project`)
- Modify: `src/brd/master.py` (delete `find_marker`, `resolve_project_root` and `registered_project`, lines 152-177)
- Test: `tests/test_cli_app.py` (new tests; rename `:109`; drop `.brd` writes at `:23`, `:113`, `:154`, `:169`)
- Test: `tests/test_single_db_migration.py` (drop `.brd` writes at `:564`, `:580`, `:627`, `:644`)
- Test: `tests/test_master.py` (delete `test_find_marker_walks_up_from_nested_dir` and `test_find_marker_returns_none_when_absent`, lines 147-161)

**Interfaces:**
- Consumes: `master.resolve_project(conn: sqlite3.Connection, start: Path) -> Project` (Task 1).
- Produces: `_app.open_project() -> Ctx`, with an unchanged signature, now resolved by registry. After this task, `master.MARKER_FILENAME` is still defined; Task 3 removes it.

- [ ] **Step 1: Write the failing CLI tests**

In `tests/test_cli_app.py`, insert these three tests directly after `test_open_project_through_a_symlinked_cwd_resolves_the_same_project` (which ends at line 106):

```python
def test_commands_from_a_deep_subdirectory_use_the_enclosing_project(project, monkeypatch):
    card = ok("add", "--title", "Root card")
    deeper = project / "sub" / "deeper"
    deeper.mkdir(parents=True)
    monkeypatch.chdir(deeper)

    assert [c["id"] for c in ok("list")] == [card["id"]]


def test_nested_init_makes_the_deepest_root_win(project, monkeypatch):
    sub = project / "sub"
    (sub / "x").mkdir(parents=True)
    root_card = ok("add", "--title", "Root card")
    monkeypatch.chdir(sub)
    ok("init")
    monkeypatch.chdir(sub / "x")
    sub_card = ok("add", "--title", "Sub card")

    monkeypatch.chdir(sub)
    assert [c["id"] for c in ok("list")] == [sub_card["id"]]
    monkeypatch.chdir(project)
    assert [c["id"] for c in ok("list")] == [root_card["id"]]


def test_a_stale_marker_in_a_subdirectory_does_not_hide_the_enclosing_project(
    project, monkeypatch
):
    card = ok("add", "--title", "Root card")
    sub = project / "sub"
    sub.mkdir()
    (sub / ".brd").write_text("")
    monkeypatch.chdir(sub)

    assert [c["id"] for c in ok("list")] == [card["id"]]
```

Replace `test_unregistered_marker_is_a_project_not_found_envelope` (lines 109-127) with this version. It is renamed, and the `.brd` write is gone:

```python
def test_unregistered_dir_is_a_project_not_found_envelope(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)

    result = invoke("list")

    assert result.exit_code == 1
    error = json.loads(result.stdout)["error"]
    assert error["type"] == "ProjectNotFoundError"
    assert "brd init" in error["message"]
    assert str(repo) in error["message"]
    conn = db.connect(paths.brd_db_path())
    try:
        assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0
    finally:
        conn.close()
```

In the same file, delete the line `    (repo / ".brd").write_text("")` from these three tests:
- `test_commands_migrate_a_v0_board` (line 23)
- `test_open_project_closes_connection_when_the_root_is_not_registered` (line 154)
- `test_open_project_closes_connection_when_migration_fails` (line 169)

In `tests/test_single_db_migration.py`, delete these four lines:
- line 564, in `test_unreadable_board_is_a_migration_error_envelope`: `    (root / ".brd").write_text("")`
- line 580, in `test_shared_ids_fail_the_command_and_a_retry_succeeds`: `    (Path(first.root_path) / ".brd").write_text("")`
- line 627, in `test_commands_read_backups_from_the_shared_docs_dir`: `    (root / ".brd").write_text("")`
- line 644, in `test_notice_goes_to_stderr_and_stdout_stays_one_envelope`: `    (root / ".brd").write_text("")`

Check that the marker writes are gone:

Run: `grep -n '"\.brd"' tests/test_cli_app.py tests/test_single_db_migration.py`
Expected: exactly one hit, in `test_a_stale_marker_in_a_subdirectory_does_not_hide_the_enclosing_project`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli_app.py tests/test_single_db_migration.py -q`
Expected: these FAIL:
- `test_a_stale_marker_in_a_subdirectory_does_not_hide_the_enclosing_project`: `ProjectNotFoundError`, because the marker walk stops at `sub/.brd`.
- `test_unregistered_dir_is_a_project_not_found_envelope`: `"brd init" in error["message"]` is false, because the old message is `no .brd marker found above …`.
- `test_commands_migrate_a_v0_board`, `test_shared_ids_fail_the_command_and_a_retry_succeeds`, `test_commands_read_backups_from_the_shared_docs_dir` and `test_notice_goes_to_stderr_and_stdout_stays_one_envelope`: `ProjectNotFoundError`, because their roots no longer have a marker.

`test_commands_from_a_deep_subdirectory_use_the_enclosing_project` and `test_nested_init_makes_the_deepest_root_win` already PASS, because `init` still writes a marker until Task 3. They pin user-visible behaviour that Task 3 must not break.

- [ ] **Step 3: Rewire `open_project`**

In `src/brd/cli/_app.py`, replace `open_project` (lines 64-74) with:

```python
def open_project() -> Ctx:
    # Connect (and so migrate) first: any data command on an unmigrated
    # install migrates, even one run outside a project.
    conn = master.connect()
    try:
        project = master.resolve_project(conn, Path.cwd())
    except BaseException:
        conn.close()
        raise
    return Ctx(conn=conn, project=project)
```

- [ ] **Step 4: Delete the marker-walk functions and their tests**

In `src/brd/master.py`, delete `find_marker`, `resolve_project_root` and `registered_project` (lines 152-177 as of the start of this task, which sit between `init_project` and the `resolve_project` added in Task 1). Leave `MARKER_FILENAME`, because `init_project` and `forget_project` still use it until Task 3.

In `tests/test_master.py`, delete `test_find_marker_walks_up_from_nested_dir` and `test_find_marker_returns_none_when_absent` (lines 147-161).

Run: `grep -rnE "find_marker|resolve_project_root|master\.registered_project" src tests`
Expected: no output.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cli_app.py tests/test_single_db_migration.py tests/test_master.py -q`
Expected: all PASS.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: all PASS. The count is 627 − 2 deleted + 3 new = 628.

- [ ] **Step 7: Commit**

```bash
git add src/brd/cli/_app.py src/brd/master.py tests/test_cli_app.py tests/test_single_db_migration.py tests/test_master.py
git commit -m "$(cat <<'EOF'
Find the current project by registered root instead of the .brd marker

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `brd init` writes nothing into the repo; legacy marker imports are gone

**Files:**
- Modify: `src/brd/master.py` (delete `MARKER_FILENAME` at line 12 and `_copy_cards`, `_migrate_in_repo_format`, `_migrate_legacy_uuid_marker` at lines 71-114; rewrite `init_project` at lines 117-149; drop the marker unlink at lines 209-211 in `forget_project`)
- Modify: `README.md:38-45` ("Storage" heading and its first paragraph)
- Test: `tests/test_master.py`
- Test: `tests/test_cli.py:52-64` (`test_init_registers_project`)

**Interfaces:**
- Consumes: `_resolve(start)` and `_not_found(start)` test helpers (Task 1), `_brd()` and `_card_owner(card_id)` (existing at the top of `tests/test_master.py`).
- Produces: `master.init_project(root_path: Path, name: str | None = None) -> Project` (same signature; now only upserts). `master.forget_project(root_path: Path) -> Project` (same signature; no longer touches `.brd`).

- [ ] **Step 1: Write the failing tests**

In `tests/test_master.py`:

1. Replace `test_init_project_creates_brd_db_and_gitignored_marker` and `test_init_project_appends_to_existing_gitignore_once` (lines 29-66) with these two tests (T7 and T8):

```python
def test_init_project_writes_nothing_into_the_repo(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    project = master.init_project(repo)

    assert list(repo.iterdir()) == []
    assert project.name == "myrepo"
    assert project.root_path == str(repo)
    db_path = paths.brd_db_path()
    assert db_path.is_file()
    assert str(db_path).startswith(str(tmp_path / "data"))
    conn = _brd()
    try:
        assert db.list_projects(conn) == [project]
    finally:
        conn.close()


LEGACY_ID = "07a7d240-444a-4b71-b585-b5bc7b50fdf3"


def test_init_project_leaves_gitignore_and_old_markers_alone(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    # The original design: a .brd file holding a UUID that keys a central board.
    uuid_repo = tmp_path / "uuid-repo"
    uuid_repo.mkdir()
    gitignore_bytes = b"__pycache__/"  # no trailing newline: the old append added one
    (uuid_repo / ".gitignore").write_bytes(gitignore_bytes)
    (uuid_repo / ".brd").write_text(f"{LEGACY_ID}\n")
    old_projects_dir = tmp_path / "data" / "brd" / "projects"
    old_projects_dir.mkdir(parents=True)
    legacy = db.connect(old_projects_dir / f"{LEGACY_ID}.db")
    db.init_project_schema(legacy, PROJECT)
    make_card(legacy, "c1", title="Old card")
    legacy.close()
    # The in-repo design: a .brd/ directory holding board.db.
    dir_repo = tmp_path / "dir-repo"
    brd_dir = dir_repo / ".brd"
    brd_dir.mkdir(parents=True)
    in_repo = db.connect(brd_dir / "board.db")
    db.init_project_schema(in_repo, PROJECT)
    make_card(in_repo, "c2", title="In-repo card")
    in_repo.close()
    board_bytes = (brd_dir / "board.db").read_bytes()

    master.init_project(uuid_repo)
    master.init_project(dir_repo)

    assert sorted(p.name for p in uuid_repo.iterdir()) == [".brd", ".gitignore"]
    assert (uuid_repo / ".gitignore").read_bytes() == gitignore_bytes
    assert (uuid_repo / ".brd").read_text() == f"{LEGACY_ID}\n"
    assert [p.name for p in dir_repo.iterdir()] == [".brd"]
    assert brd_dir.is_dir()
    assert (brd_dir / "board.db").read_bytes() == board_bytes
    assert _card_owner("c1") is None
    assert _card_owner("c2") is None
```

2. Delete `test_init_project_migrates_legacy_uuid_marker_preserving_cards` and `test_init_project_migrates_in_repo_format_preserving_cards` (lines 99-145 of the original file).

3. Replace `test_forget_project_removes_marker_and_registry_row` (lines 177-187 of the original file) with T11:

```python
def test_forget_project_removes_the_registry_row_and_leaves_a_marker_alone(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    master.init_project(repo)
    (repo / ".brd").write_text("")

    forgotten = master.forget_project(repo)

    assert forgotten.name == "myrepo"
    assert (repo / ".brd").read_text() == ""
    assert master.list_all_projects() == []
```

4. Delete `test_copy_cards_drops_dangling_legacy_edges` (lines 398-420 of the original file; it is the last test in the file).

5. Append at the end of the file T10 and the nested-forget test (Review Focus 4):

```python
def test_init_project_inside_a_registered_project_adds_a_nested_one(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    outer = tmp_path / "r"
    inner = outer / "sub"
    (inner / "x").mkdir(parents=True)

    outer_project = master.init_project(outer)
    inner_project = master.init_project(inner)

    assert inner_project.id != outer_project.id
    assert {p.root_path for p in master.list_all_projects()} == {str(outer), str(inner)}
    assert _resolve(inner / "x") == inner_project
    assert list(inner.iterdir()) == [inner / "x"]


def test_forgetting_a_nested_project_hands_its_tree_back_to_the_outer_one(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    outer = tmp_path / "r"
    inner = outer / "sub"
    (inner / "x").mkdir(parents=True)
    outer_project = master.init_project(outer)
    master.init_project(inner)

    master.forget_project(inner)

    assert _resolve(inner / "x") == outer_project
    assert master.list_all_projects() == [outer_project]
```

T9 is already covered by `test_init_project_upserts_name_on_rerun` and `test_init_project_rerun_keeps_id_and_created_at`. Keep them unchanged.

In `tests/test_cli.py`, `test_init_registers_project` (lines 52-64): replace the line `    assert (isolated_env / ".brd").is_file()` (line 58) with these three lines (T15):

```python
    assert set(payload["data"]) == {"id", "name", "root_path", "created_at"}
    assert payload["data"]["root_path"] == str(isolated_env)
    assert list(isolated_env.iterdir()) == []
```

`tests/test_cli.py:131` (`assert not (isolated_env / ".brd").exists()` after `forget`) stays as is.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_master.py tests/test_cli.py -q`
Expected: these FAIL:
- `test_init_project_writes_nothing_into_the_repo`: `repo.iterdir()` lists `.brd` and `.gitignore`.
- `test_init_project_leaves_gitignore_and_old_markers_alone`: `.gitignore` bytes are `b"__pycache__/\n.brd\n"`, and `c1` and `c2` are imported.
- `test_forget_project_removes_the_registry_row_and_leaves_a_marker_alone`: `FileNotFoundError`, because forget deleted `.brd`.
- `test_init_project_inside_a_registered_project_adds_a_nested_one`: `inner.iterdir()` also lists `.brd` and `.gitignore`.
- `test_init_registers_project`: the cwd contains `.brd` and `.gitignore`.

`test_forgetting_a_nested_project_hands_its_tree_back_to_the_outer_one` already PASSES (resolution landed in Task 1 and Task 2). It pins the fallback.

- [ ] **Step 3: Strip the marker and legacy-import code from `src/brd/master.py`**

Delete line 12, `MARKER_FILENAME = ".brd"`, and the blank line that follows it.

Delete `_copy_cards`, `_migrate_in_repo_format` and `_migrate_legacy_uuid_marker` (lines 71-114 at the start of this task: from `def _copy_cards(` through the end of `_migrate_legacy_uuid_marker`, plus the blank lines that separate them).

Replace the whole of `init_project` with:

```python
def init_project(root_path: Path, name: str | None = None) -> Project:
    """Register root_path in brd.db. Writes nothing under root_path."""
    conn = connect()
    try:
        # A root that is already registered keeps its id and created_at;
        # only the name changes.
        return db.upsert_project(
            conn,
            Project(
                id=db.new_project_id(),
                name=name or root_path.name,
                root_path=str(root_path),
                created_at=_now(),
            ),
        )
    finally:
        conn.close()
```

In `forget_project`, delete these three lines and the blank line before them, so that the function ends with the doc-backup loop and then `return project`:

```python
    marker = root_path / MARKER_FILENAME
    if marker.is_file():
        marker.unlink()
```

Keep `import shutil`, because `purge_all` uses it.

Run: `grep -rnE "MARKER_FILENAME|_copy_cards|_migrate_in_repo_format|_migrate_legacy_uuid_marker" src tests`
Expected: no output.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_master.py tests/test_cli.py -q`
Expected: all PASS.

- [ ] **Step 5: Rewrite the README "Storage" paragraph**

In `README.md`, replace the paragraph directly under `## Storage` (lines 40-44, which start with ``` `brd init` creates a gitignored `.brd` marker file``` and end with `doesn't automatically travel with a clone to another machine.`) with:

```markdown
`brd init` registers the current directory in `~/.local/share/brd/brd.db`
(or `$XDG_DATA_HOME/brd/brd.db`) and writes nothing into the repo. Every
project's board lives in that one file. A command uses the registered
project whose root is the current directory or its deepest ancestor, so
it works from any subdirectory, and nested projects are allowed: inside
a nested project, its own root wins. Nothing project-specific is
committed to git; a board doesn't automatically travel with a clone to
another machine.

Older versions of brd wrote a `.brd` marker file and added `.brd` to
`.gitignore`. brd now ignores both; delete them by hand if you like.
Boards stored in the very old in-repo `.brd/` directory or UUID-marker
formats are no longer imported: open them once with the last release
that still used per-project databases before upgrading.
```

Leave the snapshot/export paragraph that follows ("To keep a durable, diffable record in git …") and everything after it unchanged.

Run: `grep -n "\.brd" README.md`
Expected: only the lines in the new second paragraph.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: `627 passed`. The count is 628 − 6 deleted + 5 new = 627. Deleted: the two gitignore/marker init tests, the two legacy-migration tests, the old forget test and `test_copy_cards_drops_dangling_legacy_edges`. New: T7, T8, T11, T10 and the nested-forget test.

- [ ] **Step 7: Commit**

```bash
git add src/brd/master.py tests/test_master.py tests/test_cli.py README.md
git commit -m "$(cat <<'EOF'
Stop writing the .brd marker and .gitignore line on init

brd init only registers the root in brd.db. Existing .brd files and
.gitignore lines are left alone, and the legacy in-repo and UUID-marker
imports are removed.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

## Spec coverage check

| Spec item | Task |
|---|---|
| B1 resolution rules, one query, no wildcards, read-only, message | Task 1 (`db.deepest_project`, `master.resolve_project`, T1-T6 + symlink, `/`, read-only tests) |
| B1 "a `.brd` anywhere changes nothing" | Task 1 (T5 marked dir; stale-marker unit test), Task 2 (stale-marker CLI test) |
| B2 `open_project` wiring, connection closed on error | Task 2 (rewire; existing `test_open_project_closes_connection_*` without markers; T14) |
| B3 init writes nothing, ignores `.brd` and `.gitignore`, re-init, nested | Task 3 (T7, T8, T10; T9 existing) |
| B4 forget leaves `.brd` | Task 3 (T11) |
| B5 removed code | Task 2 (`find_marker`, `resolve_project_root`, `registered_project`), Task 3 (`MARKER_FILENAME`, `_copy_cards`, `_migrate_*`) |
| B6 README | Task 3 Step 5 |
| T12, T13, T14 | Task 2 |
| T15 | Task 3 |
| Removed/edited tests list | Task 1 (`test_registered_project_*`), Task 2 (`test_find_marker_*`, `.brd` writes in `test_cli_app.py` and `test_single_db_migration.py`), Task 3 (init/legacy/copy_cards/forget tests) |
| Existing subdir and symlink CLI tests unchanged | Task 2 leaves them untouched; the full suite runs in every task |
<!-- task-pipeline: validated -->
