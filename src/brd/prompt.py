SNIPPET = """## Task tracking with brd

This repo tracks work with `brd`, a local kanban CLI.

- `brd next` — see what's ready to work on (unblocked todo cards)
- `brd show <id>` — see a card's full detail
- `brd add --title "..." [--parent <id>] [--blocked-by <id>]` — create a card
- `brd update <id> --status in_progress|done` — update status as you go
- `brd tree` — see the whole board's hierarchy/dependencies

No fixed Epic/Story/Task types — any card becomes an "epic" just by
giving other cards `--parent <its-id>`. A card with children is a
container, not work: `brd next` skips it and only surfaces its leaves.

Board data lives outside this repo (in `~/.local/share/brd/`), keyed to
this project's path — the `.brd` marker file is gitignored and doesn't
carry any board data itself. `brd tree > docs/board/snapshot.json` gives
you a committable, human-readable record; `brd import <file>` restores
it (same ids, descriptions, timestamps) on another machine or clone.

Output is JSON by default; add `--pretty` for human-readable text.
Use `brd --help` to see all commands.
"""


def render() -> str:
    return SNIPPET
