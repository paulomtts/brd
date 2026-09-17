# brd — local kanban CLI for agents

Date: 2026-09-17

> **Amendment (2026-09-17, later):** The "Storage layout" and "Project
> resolution" sections below describe the original central-store design
> (per-project DBs under the XDG data dir, keyed by a master DB with UUIDs).
> This was superseded: the per-project DB now lives at
> `<repo-root>/.brd/board.db`, is committed to git (not gitignored) so it
> travels with clones, and is resolved by walking up the filesystem — no
> master DB lookup involved. The master DB survives only as a local,
> best-effort cache for `brd projects`, keyed by `root_path`. See
> `src/brd/master.py` for the current behavior.

## Purpose

`brd` is a CLI tool for storing and managing cards on a board, representing
the status of work through card properties and structure. It's a kanban
manager with no visual UI, designed primarily for AI agents to track
long-running tasks locally, without relying on Jira, GitHub Projects, or any
other external system.

Success criteria:
- An agent working in a repo can register the repo as a project, create
  cards, link dependencies between them, query the dependency/hierarchy
  tree, and fetch the next ready-to-work card(s) — all via `brd` commands
  invoked from anywhere inside the repo.
- Output is machine-parseable by default (JSON), since the primary
  consumer is an agent, not a human at a terminal.
- The tool is designed to compose with future multi-agent orchestration
  (e.g. `leave-me-alone:orchestrator`), which needs to fetch a *set* of
  ready tasks at once, not just one.

## Non-goals (v1)

- No visual/TUI board rendering.
- No multi-user concurrency/locking beyond what SQLite WAL gives for free.
- No remote/networked storage — everything is local SQLite.
- No custom per-project status sets (fixed status enum for v1).
- No card fields beyond the minimal core (no priority, tags, assignee, or
  notes log in v1).

## Architecture

Layered structure under `src/brd/`:

- `cli.py` — typer app; one function per command. Thin: parses args, calls
  into `core.py`, renders via `output.py`. Never touches SQL directly.
- `core.py` — business logic: card creation/update, status derivation
  (`blocked`), `next`-task selection, tree building, cycle validation on
  `parent_id` and `blocked_by` writes. No typer or SQL here — testable in
  isolation against `db.py`.
- `db.py` — SQLite connection management, schema creation, and raw
  parameterized queries. No ORM — plain stdlib `sqlite3` with a light
  wrapper. WAL mode enabled; connections are opened, used, and closed
  within a single command invocation (no long-lived daemon).
- `models.py` — dataclasses: `Card`, `Project`.
- `master.py` — master DB specifics: the project registry, and resolving
  "the current project" by walking up from cwd for a `.brd` marker file
  (same discovery pattern as `.git`).
- `output.py` — renders results as JSON (default) or pretty text
  (`--pretty`/`--human`), including the success/error envelope.

### Storage layout

Both the master DB and all per-project DBs live under the XDG data
directory, not inside project repos:

```
~/.local/share/brd/
  master.db
  projects/
    <project-id>.db
```

`master.db` holds a `projects` table mapping project id → name → repo root
path → db file path. This means `brd` works regardless of which
subdirectory of a repo the agent is in, survives the repo being moved
(as long as `brd init` is re-run or the path is updated), and needs no
per-repo database file to manage or gitignore.

### Project resolution

`brd init` creates a `.brd` marker file at the repo root containing the
project's UUID, and appends `.brd` to the repo's `.gitignore` (creating
`.gitignore` if it doesn't exist; skipping the append if `.brd` is already
listed). Every command except `init` and `projects` resolves "the current
project" by walking up from `cwd` looking for `.brd`, reading the project
id from it, and looking that id up in `master.db`.

Project name defaults to the repo root folder name (the folder containing
`.brd`); `brd init --name <override>` can set a different name if the
default collides with an existing registered project.

## Data model

### `projects` table (master DB)

| column | type |
|---|---|
| id | TEXT UUID4, PK |
| name | TEXT UNIQUE |
| root_path | TEXT |
| db_path | TEXT |
| created_at | TEXT (ISO8601) |

### `cards` table (per-project DB)

| column | type |
|---|---|
| id | TEXT UUID4, PK |
| title | TEXT NOT NULL |
| description | TEXT |
| status | TEXT, CHECK IN ('todo', 'in_progress', 'done') |
| parent_id | TEXT, FK → cards.id, nullable |
| created_at | TEXT (ISO8601) |
| updated_at | TEXT (ISO8601) |

Note: `status` never stores `'blocked'`. `blocked` is a fourth value
exposed only in *reads* — computed as: `status == 'todo'` AND the card has
at least one unresolved `blocked_by` edge (a linked card whose own
resolved status isn't `done`). Writing `status=blocked` directly is
rejected.

### `blocked_by` table (per-project DB)

| column | type |
|---|---|
| card_id | TEXT, FK → cards.id |
| blocks_on_id | TEXT, FK → cards.id |

Primary key: `(card_id, blocks_on_id)`. Means "`card_id` is blocked by
`blocks_on_id`" — `blocks_on_id` must reach `done` before `card_id` is
unblocked.

### Hierarchy vs. blocking

`parent_id` (on `cards`) and `blocked_by` (separate table) are two
distinct relationships:
- `parent_id` expresses grouping/hierarchy (e.g. story → subtasks).
- `blocked_by` expresses ordering/dependency, independent of hierarchy.

Both are validated for cycles in `core.py` before a write is committed:
`parent_id` cycles (a card can't be its own ancestor) and `blocked_by`
cycles (a card can't transitively block itself).

## CLI surface

All commands auto-resolve the current project via the `.brd` marker
walk-up, except `init` and `projects`.

| command | description |
|---|---|
| `brd init [--name <override>]` | Register current repo as a project; create `.brd` marker, add it to `.gitignore`, create the per-project DB. |
| `brd add --title <t> [--description <d>] [--parent <id>] [--blocked-by <id> ...]` | Create a card, status defaults to `todo`. |
| `brd show <id>` | Full card detail: resolved status, parent, children, blockers (with their current resolved status). |
| `brd list [--status <s>] [--parent <id>]` | List cards, each with resolved status. |
| `brd update <id> [--title] [--description] [--status] [--parent]` | Edit fields. Rejects `--status blocked` (computed-only) and `parent_id` cycles. |
| `brd block <id> --by <blocker-id>` | Add a `blocked_by` edge. Rejects cycles. |
| `brd unblock <id> --by <blocker-id>` | Remove a `blocked_by` edge. |
| `brd tree [<id>]` | Print dependency + hierarchy tree; rooted at `<id>` if given, else the whole board. |
| `brd next [--limit N]` | Return all unblocked `todo` cards, oldest-created first (or top N with `--limit`). No special-casing for parent vs. leaf cards. |
| `brd projects` | List registered projects from master DB (name, root_path, card counts). |

### Output format

JSON by default (agents are the primary consumer); `--pretty`/`--human`
renders formatted text/tables/tree views for interactive use.

Every command's output uses a consistent envelope:

```json
{"ok": true, "data": {...}}
{"ok": false, "error": {"type": "CardNotFoundError", "message": "..."}}
```

Non-zero exit code on `ok: false`.

## Error handling

Typed exceptions raised in `core.py`/`db.py`/`master.py`
(`ProjectNotFoundError`, `CardNotFoundError`, `CycleError`, etc.), caught
once at the `cli.py` boundary and converted into the error envelope above.
No stack traces in default output; `--verbose` opts into showing them.

## Concurrency

SQLite WAL mode; each command invocation opens a connection, does its
work, and closes it. No daemon, no cross-process locking beyond what
SQLite provides — sufficient for a local, mostly-single-agent-at-a-time
CLI tool.

## Testing

pytest.

- `core.py` and `db.py`: unit tests against a temp SQLite file, exercising
  status derivation, cycle detection, and `next` selection directly — no
  mocking of SQLite itself.
- `cli.py`: end-to-end tests driving the full command surface (init → add
  → block → next → tree → update → unblock) against a temp XDG data dir
  (env var monkeypatched per test).

## Dependencies

- `typer` — CLI framework.
- stdlib `sqlite3`, `uuid`, `pathlib`, `json` — no ORM, no extra JSON lib.
- Dev: `pytest`.
