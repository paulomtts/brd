# 6.1 `--help` and `brd prompt`: the blocking contract

Card: 84795ab7 (subtask of story 6bfad168 "Document the new surface").
Parent design: `docs/superpowers/specs/2026-10-06-single-db-cross-project-blocking-design.md`
in the main checkout (commit 98c42de; not present in this worktree's `docs/`), cited
below as **[P]** with line numbers.

## Goal

Agents and people read `brd --help` and `brd prompt` to learn how to use brd. Neither
says anything yet about how blocking works now that edges cross projects, can point at
nothing, and containers release their dependents. This card adds that consumer
contract to both, worded from the code as built, so a reader can trust `status` and
`brd next` without re-deriving anything from `blocked_by`.

This is a text-only change. No command behaviour, JSON shape or exit code changes.

## Inherited constraints

- [P] §6 lines 241-248: `brd --help` **and** `brd prompt` gain a short section stating
  (a) `status` is authoritative: `blocked` already accounts for cross-project
  blockers, not-found blockers and container release, and `brd next` lists only cards
  that can start now; (b) `blocked_by` is a list of ids that may belong to other
  projects or be not-found, and `blockers` carries project, title, status and
  `released` for each; (c) blocking a story or milestone means waiting for all of its
  children.
- [P] §6 lines 250-251: orchestrator / agent-manager changes are out of scope; they
  read this contract.
- [P] D1 (line 31) and §4 lines 161-169: a container releases dependents when its
  stored status is releasing or every child is released, recursively; its own
  displayed status is unchanged. `RELEASING` = `{done, merged, canceled, archived}`.
- [P] D6/D7 (lines 36-37): an edge whose target is not in the database is kept,
  reported as `not-found`, and blocks.
- [P] D8 (line 38): `brd forget` and import's project replacement leave incoming edges
  in place as not-found; they reconnect if the ids return.
- [P] §4 lines 173-184: `blocked_by` stays a list of ids; `blockers` entries carry
  `id`, `kind`, `project` (`{id, name}`), `title`, `status`, `released`.
- [P] "Implementation order" item 3 (lines 281-283) assigns "consumer contract text"
  to the cross-project phase; story 6bfad168 owns `src/brd/cli/_app.py` help text,
  `src/brd/prompt.py` and `README.md`.

## Behaviour as built (the facts the text must state)

Read from the code at this branch's HEAD; the text must not promise more than this.

| Fact | Source |
|------|--------|
| Only a stored `todo` is re-derived; every other stored status is returned as-is. `blocked` is derived and cannot be set. | `src/brd/core.py:23-24`, `core.py` `InvalidStatusError` on `--status blocked` |
| A `todo` card resolves to `blocked` if any blocker is not found, is an open issue, or is an unreleased card; documents never block. | `core.py:34-50` |
| A card whose parent resolves to `blocked` is itself `blocked`. | `core.py:52-55` |
| A card blocker is released when it resolves to done, merged, canceled or archived, **or** it has children and all of them are released (recursive). The container's own status may still read `todo`. Loops fail closed. | `core.py:18-20`, `core.py:60-71` |
| An issue blocker is released once it is closed, for any reason. | `core.py:40-46`, `core.py:98-102` |
| Blocker lookup is global: a blocker may belong to any project; only the blocked card must be in the current project. `brd block --by` refuses an id that does not exist now (`CardNotFoundError`); not-found blockers arise later (the blocker's project forgotten, replaced by import, or not imported yet). | `core.py:174-180`, `core.py:275-288`, [P] D8 |
| `blocked_by` (ids) and `blockers` (detail) appear together, same order, on card detail (so `show`, `list`, `next`, `block`, `unblock` outputs) and on `brd tree` nodes. A `blockers` entry is `{id, kind, project:{id,name}, title, status, released}`; a not-found one has `kind`/`project`/`title` null, `status` `"not-found"`, `released` false. | `src/brd/views.py:21-37`, `core.py:74-115` |
| `blockers` is derived: export omits it and import ignores it. | `src/brd/snapshot.py:40`, `snapshot.py:193` |
| `brd next` lists stored-`todo` cards that resolve to `todo`; without `--parent` it skips containers; with `--parent` it lists ready direct children, containers included. | `core.py:318-337` |

## Required behaviour

### R1. `brd --help` carries the blocking contract

The epilog of `brd --help` (the `GUIDE` string in `src/brd/cli/_app.py`) gains a
blocking section — one or two paragraphs in the existing style (plain paragraphs
separated by blank lines, backslash line continuations) — that states all of:

1. `status` is authoritative. `blocked` already accounts for blockers in other
   projects, not-found blockers, container release, and a blocked parent. `brd next`
   lists only cards that can start now. (Readers need not inspect `blocked_by`
   themselves.)
2. `blocked_by` is a list of ids, which may belong to other projects or be not-found.
   A not-found blocker blocks; it appears when the blocker's project was forgotten or
   not imported here, and reconnects when that id returns.
3. `blockers` lists each blocker in the same order with its id, kind, project, title,
   status and `released`.
4. A card blocker releases its dependents once it is done, merged, canceled or
   archived. Blocking a story or milestone (any container) waits for all of its
   children: it releases once every child has, even while its own status still reads
   todo.

The existing paragraphs stay, including "An open issue can block a card … closing it,
for any reason, unblocks the card" (asserted indirectly by nothing today, but it is
still true and the new text relies on it rather than repeating it).

Suggested wording (the planner may tighten it, but every tested phrase in T1 must
survive verbatim):

> Blocking: `status` is authoritative. `blocked` already accounts for blockers in other
> projects, not-found blockers, container release and a blocked parent, and `brd next`
> lists only cards that can start now.
>
> `blocked_by` is a list of ids that may belong to other projects or be not-found (the
> blocker's project was forgotten or not imported here); a not-found blocker blocks
> until its id returns. `blockers` gives each one's id, kind, project, title, status
> and `released`, in the same order. A card blocker releases its dependents once it is
> done, merged, canceled or archived; blocking a story or milestone waits for all of
> its children, even while its own status still reads todo.

Markup rule: the epilog is rendered with rich markup, so any literal `[` must be
escaped as `\\[` in the Python source (see the existing `\\[\\[doc-stem]]`). The
suggested wording contains no square brackets.

### R2. `brd prompt` carries the same contract, briefly

`prompt.SNIPPET` gains a short paragraph (a few lines, markdown) between the
"run `brd --help`" paragraph and the bold doc-update rule, stating R1.1-R1.4 in
compressed form. Suggested wording:

> Blocking: a card's `status` is authoritative — `blocked` already covers blockers in
> other projects, not-found blockers and containers, and `brd next` lists only cards
> that can start now. `blocked_by` ids may belong to other projects or be not-found;
> `blockers` gives each one's project, title, status and `released`. Blocking a story
> or milestone waits for all of its children.

Unchanged: the snippet still opens with `## Task tracking with brd`, still points at
`brd --help` / `brd <command> --help` and memory, and the line
`**Whenever you edit a registered document, run `brd doc update <id>` right after.**`
stays byte-identical. `brd prompt` still prints exactly `prompt.render()`.

### R3. `brd block --help` says the blocker may be in another project

The `--by` option help of `brd block` (`src/brd/cli/cards.py`, `block`) changes from
"Id of the card or issue blocking it." to say the blocker may belong to another
project, e.g. "Id of the card or issue blocking it; it may belong to another
project." The command docstring stays. This is the one per-command help string that is
now incomplete; other command help is out of scope.

### Error paths

None new. All three surfaces are static text; `brd --help`, `brd block --help` and
`brd prompt` keep exiting 0 and need no project (`brd prompt` and `--help` already run
outside a registered project; this must not regress).

## Tests

All tests are **unit tier** (`tests/test_prompt.py`, plain pytest, Typer `CliRunner`
or a direct `prompt.render()` call): the deliverable is fixed text, so the cheapest
test that reads the rendered output is the right one; nothing here touches the
database. The behaviour the text describes is already pinned by existing tests
(blocking/release in `tests/test_core.py`, `blockers` output and cross-project
edges in `tests/test_cli.py` and friends, leak guard in `tests/test_cli_leak_guard.py`);
this card does not re-test it.

Rich wraps the epilog to the terminal width and may break a phrase across lines, so
help assertions run against the output with whitespace collapsed
(`" ".join(output.split())`) and `terminal_width=200`, as the existing help test does.

- **T1 (unit) `test_help_states_the_blocking_contract`** — `brd --help` output,
  whitespace-collapsed, contains each of: `is authoritative`, `other projects`,
  `not-found`, `brd next`, `can start now`, `blocked_by`, `blockers`, `released`,
  `waits for all of its children`. Why unit: static epilog text.
- **T2 (unit) `test_help_names_every_releasing_status`** — for each status in
  `core._RELEASING_STATUSES`, the whitespace-collapsed `brd --help` output contains it.
  Guards against the help drifting from the code if a releasing status is added or
  removed. Why unit: compares two in-process values.
- **T3 (unit) `test_prompt_states_the_blocking_contract`** — `prompt.render()`
  contains each of: `authoritative`, `other projects`, `not-found`, `brd next`,
  `blocked_by`, `blockers`, `released`, `all of its children`.
- **T4 (unit) existing tests still pass unchanged** —
  `test_prompt_points_agents_at_help_and_memory`,
  `test_prompt_keeps_the_doc_update_rule_inline` and
  `test_help_carries_the_usage_guidance` (its phrase list, including `[[doc-stem]]`
  and `[[<id>]]`, proves the new text did not break rich markup escaping).
- **T5 (unit) extend `tests/test_cli.py::test_prompt_prints_plain_markdown_not_json`**
  — add `assert result.output == prompt.render()`. It already invokes `brd prompt`
  with no project set up and asserts exit 0 and non-JSON output; the extra line pins
  that the command prints the whole snippet, new paragraph included, so the contract
  reaches an agent that has not set up a board yet. (`brd prompt`/`--help` running
  without touching data is already pinned by
  `tests/test_single_db_migration.py::test_commands_without_data_do_not_migrate`.)
- **T6 (unit) `test_block_help_says_the_blocker_may_be_in_another_project`** —
  `brd block --help` (`terminal_width=200`, whitespace-collapsed) contains
  `another project`.

Verification: `uv run pytest` (no typecheck or lint is configured).

## Out of scope

- `README.md` — sibling card 6.2 (aae281df) owns the README sections on one database,
  migration, relink, forget and export/import; this card must not edit `README.md`.
- Any behaviour change to status resolution, `brd next`, `blockers` output, `--pretty`
  rendering, export/import or the cycle check.
- Help text for commands other than `brd --help`'s epilog and `brd block --by` (e.g.
  `next`, `add --blocked-by`, `issue open --blocks`, `tree`).
- Orchestrator / agent-manager changes ([P] lines 250-251).
- Re-testing blocking semantics already covered by the core and CLI suites.
