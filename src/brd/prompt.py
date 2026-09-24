SNIPPET = """## Task tracking with brd

This repo tracks work with `brd`, a local kanban CLI.

- `brd next` — see what's ready to work on (unblocked todo cards)
- `brd show <id>` — full detail of any card, issue, or document
- `brd add --title "..." [--parent <id>] [--blocked-by <id>]` — create a card
- `brd update <id> --status in_progress|done` — update status as you go
- `brd tree` — see the whole board's hierarchy/dependencies

No fixed Epic/Story/Task types — any card becomes an "epic" just by
giving other cards `--parent <its-id>`. A card with children is a
container, not work: `brd next` skips it and only surfaces its leaves.

**Issues:** for bugs, questions, and findings that aren't work yet
(`brd issue open --title "..." [--body "..."]`, `brd issue close <id>
[--reason resolved|wontfix|duplicate]`). Block a card on an open issue
with `brd block <card> --by <issue>`; closing the issue unblocks it.

**Documents:** registered `.md` files (`brd doc list`) are tracked by brd,
which keeps a backup.
**Whenever you edit a registered document, run `brd doc update <id>` right after.**
If you move or rename one, run `brd doc update <id> --path <new>`.
Register new ones with `brd doc add <path> [--tag t]`.

**Links:** write `[[doc-stem]]` or `[[<id>]]` in card descriptions, issue
bodies, and comments to link things; `brd show` lists refs and backlinks.

**Comments:** `brd comment add <id> "..."` records progress or decisions
on a card or issue. Set `BRD_AUTHOR` to your agent name once per session.

Board data lives outside this repo (in `~/.local/share/brd/`), keyed to
this project's path — the `.brd` marker file is gitignored and doesn't
carry any board data itself. `brd export > docs/board/snapshot.json`
gives you a committable record of everything; `brd import <file>`
restores it (same ids and timestamps) on another machine or clone.

Output is JSON by default; add `--pretty` for human-readable text.
Use `brd --help` to see all commands.
"""


def render() -> str:
    return SNIPPET
