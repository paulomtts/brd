SNIPPET = """## Task tracking with brd

This repo tracks work with `brd`, a local kanban CLI. At the start of your
first session here, run `brd --help` (and `brd <command> --help` for any
command you use) and save what you learn to your memory. Re-run it if brd
reports an unknown command or option.

**Whenever you edit a registered document, run `brd doc update <id>` right after.**
"""


def render() -> str:
    return SNIPPET
