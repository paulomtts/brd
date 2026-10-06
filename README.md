# brd

A local-first CLI for tracking cards on a project board — a kanban
manager with no visual UI, designed for AI agents to track long-running
tasks without relying on Jira or GitHub Projects.

## Install

```bash
uv tool install brd     # or: pipx install brd
```

To work on brd itself, clone the repository and run `uv sync`.

## Usage

```bash
cd your-project
brd init                                  # register this repo as a project
brd add --title "Write the parser"        # create a card
brd add --title "Write tests" \
  --blocked-by <parser-card-id>           # create a card blocked on another
brd next                                  # fetch ready-to-work card(s)
brd tree                                  # view the whole board as a tree
brd show <id>                             # full detail of a card, issue, or document
brd update <card-id> --status done        # move a card forward (todo, in_progress, done, merged, canceled, archived)
brd delete <id>                           # delete (--cascade for cards with children)
brd projects                              # list all registered projects
brd init --relink <old-path-or-id>        # after a repo moved
brd forget --project <id>                 # forget a project whose directory is gone
brd export --all > board.json             # snapshot every project
brd import --yes board.json               # restore it on another machine

brd issue open --title "Grammar is ambiguous" --blocks <card-id>
brd issue close <issue-id> --reason wontfix
brd doc add docs/parser-notes.md --tag design   # register a markdown file
brd doc update <doc-id>                   # after editing it: refresh brd's backup
brd comment add <card-or-issue-id> "Lexer done; see [[parser-notes]]"
brd tag list                              # all tags with counts
```

## Storage

### One database

Every project's board lives in one file, `~/.local/share/brd/brd.db`
(or `$XDG_DATA_HOME/brd/brd.db` when that is set). Document backups sit
next to it, in `docs/`. `brd init` registers the current directory in
that file and writes nothing into the repo. Nothing project-specific is
committed to git, so a board doesn't travel with a clone to another
machine; see "Moving boards between machines" below.

### Upgrading from per-project databases

Older versions of brd kept a registry, `master.db`, and one board file
per project under `projects/`. The first brd command that reads data
moves every registered project into `brd.db` at once: its cards,
issues, documents, comments and document backups, with their ids and
timestamps. Any data command does this, even one run outside a
project; `brd --help` and `brd prompt` do not.

The old files are renamed with a `.migrated` suffix and never deleted.
Once your boards look right, you can delete them by hand. The command
reports the move on stderr:

`brd: migrated N projects into brd.db (old files kept as *.migrated)`

Board files under `projects/` that `master.db` did not register are
left alone and listed in a second line:

`brd: skipped K unregistered board files: projects/<hash>.db, ...`

If the move cannot finish, for example because two boards share an id,
the command fails and names what clashed. Nothing is renamed, and the
next brd command tries again once you fix the cause. `brd purge` still
works in that state.

Upgrade every installed copy of brd together. An older brd (in another
virtualenv, or under `pipx` or `uv tool`) still reads `master.db` and
`projects/`. After the move it no longer finds those boards, and
anything it records never reaches `brd.db`.

Older versions also wrote a `.brd` marker file and added `.brd` to
`.gitignore`. brd now ignores both; delete them by hand if you like.

Boards in the very old formats that `master.db` never registered, an
in-repo `.brd/` directory or a UUID `.brd` marker, are not moved. Open
each of them once with the last release that still used per-project
databases, so that it gets registered, before you upgrade. Without
that step the upgrade cannot find them.

### Finding the project, moving a repo

A command uses the registered project whose root is the current
directory or its deepest ancestor, so it works from any subdirectory,
and nested projects are allowed: inside a nested project, its own root
wins. Outside any registered project, a data command fails with:

``no registered project at or above <dir>; run `brd init` there``

Run `brd init` there to register a new project, or `brd init --relink`
if the project already exists elsewhere. Re-running `brd init` in a
registered root keeps its id and board and only renames it (`--name`).

If you move a repo, run `brd init --relink <old-path-or-id>` in its new
location: the existing project, with its id and board, now lives at the
current directory. It takes either the project id (from `brd projects`)
or the old root path; `--name` renames it at the same time.

`brd forget` removes a project and its stored board and document
backups; it never touches files in the repo. With no argument it
removes the current project; with a path, the project registered at
exactly that path. `brd forget --project <id>` works from anywhere,
for a project whose directory is gone; `brd projects` lists the ids.
Cards in other projects that were blocked on its cards stay blocked,
showing those blockers as not-found, until the ids come back (for
example, when you import the project again).

### Moving boards between machines

To keep a durable, diffable record in git and move a board between
machines, commit a snapshot and restore from it:

```bash
brd export > docs/board/snapshot.json   # commit this
brd import docs/board/snapshot.json     # on another machine/clone
```

A snapshot is a list of project entries: each one is a project (id,
name, root path) with its cards, issues, documents, comments, tags and
refs. `brd export` writes the current project; `brd export --all`
writes every registered project and works from any directory.

`brd import` restores a snapshot, preserving the original ids, content
and timestamps, including document backups. It never writes or deletes
documents' source files in the repo; restore a missing file with
`brd doc restore <id>`.

A one-project snapshot lands in the current project. Outside any
project, the current directory is registered first (keeping the
snapshot's project id when no project has it), so no `brd init` is
needed.

A multi-project snapshot (from `brd export --all`) places each entry
in the registered project with the same id, else registers it at its
recorded root path if that directory exists; it works from any
directory. Import refuses, touching nothing, when an entry cannot be
placed.

A target project that already has entities is replaced: import prints
what it will remove and add, asks y/N (default no), then deletes that
project's cards, issues, documents and comments and loads the
snapshot's in their place. `--yes` skips the question; without a
terminal and without `--yes`, import refuses and writes nothing.

Edges from other projects into a replaced project are kept: they show
as not-found until their ids return, and reconnect when they do. Edges
to ids that are not in the database are kept and counted as not-found;
importing the missing project later reconnects them. Import refuses,
touching nothing, when an id in the snapshot belongs to a project it
is not replacing.

So `brd export --all > board.json` on one machine and
`brd import --yes board.json` on another restores every project whose
root exists, with ids, hierarchy and edges intact. Re-importing a
project's own export changes nothing. Older one-object `brd export`
snapshots and `brd tree` snapshots still import.

## Documents

`brd doc add <path>` registers a markdown file inside the project. brd
stores a backup copy next to the board database and compares hashes on
every read: if the file changed, the backup is refreshed; if the file is
gone, brd serves the backup and reports it as `missing`. brd never writes
your files except when you run `brd doc restore`.

Link anything from any text with Obsidian-style `[[doc-stem]]` or
`[[<id>]]`; `brd show` lists outgoing refs and backlinks, and `--pretty`
renders links as titles.

## For agents

Add a short usage primer to a project's `CLAUDE.md`:

```bash
brd prompt >> CLAUDE.md
```

See `docs/superpowers/specs/2026-09-17-brd-cli-design.md` for the full
design.
