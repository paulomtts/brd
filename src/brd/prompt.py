SNIPPET = """## Task tracking with brd

This repo tracks work with `brd`, a local kanban CLI — not GitHub Issues/Jira.

- `brd next` — see what's ready to work on (unblocked todo cards)
- `brd show <id>` — see a card's full detail
- `brd add --title "..." [--parent <id>] [--blocked-by <id>]` — create a card
- `brd update <id> --status in_progress|done` — update status as you go
- `brd tree` — see the whole board's hierarchy/dependencies

Output is JSON by default; add `--pretty` for human-readable text.
"""


def render() -> str:
    return SNIPPET
