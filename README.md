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
brd update <card-id> --status done        # move a card forward (todo, in_progress, done, merged, canceled)
brd delete <id>                           # delete (--cascade for cards with children)
brd projects                              # list all registered projects

brd issue open --title "Grammar is ambiguous" --blocks <card-id>
brd issue close <issue-id> --reason wontfix
brd doc add docs/parser-notes.md --tag design   # register a markdown file
brd doc update <doc-id>                   # after editing it: refresh brd's backup
brd comment add <card-or-issue-id> "Lexer done; see [[parser-notes]]"
brd tag list                              # all tags with counts
```

## Storage

`brd init` creates a gitignored `.brd` marker file in the project root
and stores the actual board in a per-project SQLite file under
`~/.local/share/brd/` (or `$XDG_DATA_HOME/brd`), keyed by the project's
absolute path. Nothing project-specific is committed to git; a board
doesn't automatically travel with a clone to another machine.

To keep a durable, diffable record in git and move a board between
machines, commit a snapshot and restore from it:

```bash
brd export > docs/board/snapshot.json   # commit this
brd import docs/board/snapshot.json     # on another machine/clone, after brd init
```

`import` preserves the original ids, content, and timestamps — including document backups (restore a missing file with `brd doc restore <id>`) — and refuses to run (touching nothing) if any id in the snapshot already exists in the target board. Older `brd tree` snapshots still import.

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
