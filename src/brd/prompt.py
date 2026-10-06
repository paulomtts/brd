SNIPPET = """## Task tracking with brd

This repo tracks work with `brd`, a local kanban CLI. At the start of your
first session here, run `brd --help` (and `brd <command> --help` for any
command you use) and save what you learn to your memory. Re-run it if brd
reports an unknown command or option.

Blocking: a card's `status` is authoritative — `blocked` already covers
blockers in other projects, not-found blockers and containers, and
`brd next` lists only cards that can start now. `blocked_by` ids may
belong to other projects or be not-found; `blockers` gives each one's
project, title, status and `released`. Blocking a story or milestone
waits for all of its children.

**Whenever you edit a registered document, run `brd doc update <id>` right after.**
"""


def render() -> str:
    return SNIPPET
