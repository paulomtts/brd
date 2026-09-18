# brd

A local-first CLI for tracking cards on a project board — a kanban
manager with no visual UI, designed for AI agents to track long-running
tasks without relying on Jira or GitHub Projects.

## Install

```bash
uv sync
```

## Usage

```bash
cd your-project
brd init                                  # register this repo as a project
brd add --title "Write the parser"        # create a card
brd add --title "Write tests" \
  --blocked-by <parser-card-id>           # create a card blocked on another
brd next                                  # fetch ready-to-work card(s)
brd tree                                  # view the whole board as a tree
brd show <card-id>                        # view one card's full detail
brd update <card-id> --status done        # move a card forward
brd projects                              # list all registered projects
```

All commands output JSON by default (for agent consumption); pass
`--pretty` for human-readable output.

## Storage

`brd init` creates a gitignored `.brd` marker file in the project root
and stores the actual board in a per-project SQLite file under
`~/.local/share/brd/` (or `$XDG_DATA_HOME/brd`), keyed by the project's
absolute path. Nothing project-specific is committed to git; a board
doesn't automatically travel with a clone to another machine.

To keep a durable, diffable record in git and move a board between
machines, commit a snapshot and restore from it:

```bash
brd tree > docs/board/snapshot.json   # commit this
brd import docs/board/snapshot.json   # on another machine/clone, after brd init
```

`import` preserves the original ids, descriptions, and timestamps, and
refuses to run (touching nothing) if any id in the snapshot already
exists in the target board.

## For agents

Add a short usage primer to a project's `CLAUDE.md`:

```bash
brd prompt >> CLAUDE.md
```

See `docs/superpowers/specs/2026-09-17-brd-cli-design.md` for the full
design.
