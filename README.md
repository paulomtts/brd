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

`brd init` creates `.brd/board.db` in the project root. This file is
meant to be committed to git (not gitignored) so the board travels
with clones instead of living in a separate per-machine store.

## For agents

Add a short usage primer to a project's `CLAUDE.md`:

```bash
brd prompt >> CLAUDE.md
```

See `docs/superpowers/specs/2026-09-17-brd-cli-design.md` for the full
design.
