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
