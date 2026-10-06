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

---

# 6.1 `--help` and `brd prompt`: the Blocking Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** State brd's blocking contract (status is authoritative, cross-project and not-found blockers, `blockers` detail, container release) in `brd --help`, `brd prompt`, and `brd block --by` help.

**Architecture:** Three static strings change: the `GUIDE` epilog in `src/brd/cli/_app.py`, `SNIPPET` in `src/brd/prompt.py`, and the `--by` option help of `block` in `src/brd/cli/cards.py`. Unit tests read the rendered text (Typer `CliRunner` for help, `prompt.render()` for the snippet). No behaviour, JSON shape or exit code changes.

**Tech Stack:** Python, Typer (rich-rendered help), pytest, `uv`.

**Spec:** `docs/superpowers/specs/6-1-help-and-prompt-the-84795ab7.md` (prepended above).

## Global Constraints

- Text-only change: no command behaviour, JSON shape or exit code changes.
- Do NOT edit `README.md` (sibling card 6.2 owns it).
- Do not change help text of any command other than the `brd --help` epilog and `brd block --by`.
- The epilog is rendered with rich markup: any literal `[` must be written `\\[` in the Python source. The new text contains no square brackets.
- Epilog style: plain paragraphs separated by blank lines, backslash line continuations inside the `"""\` string.
- The existing epilog paragraphs stay, including "An open issue can block a card … closing it, for any reason, unblocks the card."
- `prompt.SNIPPET` still opens with `## Task tracking with brd`, still points at `brd --help` / `brd <command> --help` and memory, and the line `**Whenever you edit a registered document, run `brd doc update <id>` right after.**` stays byte-identical. `brd prompt` still prints exactly `prompt.render()`.
- Help assertions run with `terminal_width=200` against whitespace-collapsed output (`" ".join(output.split())`), because rich wraps the epilog (observed: it wraps at ~80 columns regardless) and can break a phrase across lines.
- Verification: `uv run pytest` (no typecheck or lint is configured). Baseline at plan time: 928 passed.

## Review Focus

1. **A bracket or markup character in new epilog text** — rich would swallow or error on it; expected: the help renders every phrase literally. Pinned by the unchanged `test_help_carries_the_usage_guidance` (`[[doc-stem]]`, `[[<id>]]`) plus Task 1's T1, which asserts the new phrases appear in rendered output.
2. **Rich wrapping a tested phrase across a line break** — expected: tests still find it. Every help test in this plan collapses whitespace first (Task 1, Task 3).
3. **Help drifting from the code's releasing statuses** — expected: help names exactly the statuses in `core._RELEASING_STATUSES`. Pinned by Task 1's T2.
4. **Snippet edit disturbing the doc-update rule or the `brd prompt` output** — expected: rule byte-identical, command output equals `prompt.render()`. Pinned by the unchanged `test_prompt_keeps_the_doc_update_rule_inline` and Task 2's T5 extension.
5. **Help/prompt run outside any registered project** — expected: exit 0, no DB touched. Pinned by T5 (`brd prompt` with no project set up, exit 0) and existing `tests/test_single_db_migration.py::test_commands_without_data_do_not_migrate`; Task 3's T6 also asserts `brd block --help` exits 0 with no project.

## File Structure

- Modify `src/brd/cli/_app.py` (the `GUIDE` string, lines 13-35): add two blocking paragraphs after the "Issues are bugs…" paragraph.
- Modify `src/brd/prompt.py` (`SNIPPET`): add one blocking paragraph between the `brd --help` paragraph and the bold doc-update rule.
- Modify `src/brd/cli/cards.py:147`: `--by` help string of `block`.
- Modify `tests/test_prompt.py`: add T1, T2, T3, T6.
- Modify `tests/test_cli.py:43-49`: extend `test_prompt_prints_plain_markdown_not_json` (T5).

---

### Task 1: `brd --help` epilog carries the blocking contract

**Files:**
- Modify: `src/brd/cli/_app.py:13-35` (`GUIDE`)
- Test: `tests/test_prompt.py`

**Interfaces:**
- Consumes: `brd.core._RELEASING_STATUSES` (existing `frozenset({"done", "merged", "canceled", "archived"})` at `src/brd/core.py:21`); `brd.cli.app`.
- Produces: helper `_help_text(*args: str) -> str` in `tests/test_prompt.py` (whitespace-collapsed help output for `brd <args> --help`), reused by Task 3.

- [ ] **Step 1: Write the failing tests**

In `tests/test_prompt.py`, change the imports at the top from:

```python
from typer.testing import CliRunner

from brd import prompt
from brd.cli import app
```

to:

```python
from typer.testing import CliRunner

from brd import core, prompt
from brd.cli import app
```

Then append at the end of the file:

```python
def _help_text(*args: str) -> str:
    result = CliRunner().invoke(app, [*args, "--help"], terminal_width=200)
    assert result.exit_code == 0, result.output
    # Rich wraps the help, so a phrase may straddle a line break.
    return " ".join(result.output.split())


def test_help_states_the_blocking_contract():
    text = _help_text()
    for phrase in (
        "is authoritative",
        "other projects",
        "not-found",
        "brd next",
        "can start now",
        "blocked_by",
        "blockers",
        "released",
        "waits for all of its children",
    ):
        assert phrase in text, phrase


def test_help_names_every_releasing_status():
    text = _help_text()
    for status in sorted(core._RELEASING_STATUSES):
        assert status in text, status
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_prompt.py -v`
Expected: `test_help_states_the_blocking_contract` FAILS with `AssertionError: is authoritative`; `test_help_names_every_releasing_status` FAILS (e.g. `AssertionError: archived`). The three existing tests PASS.

- [ ] **Step 3: Add the blocking paragraphs to `GUIDE`**

In `src/brd/cli/_app.py`, replace:

```python
Issues are bugs, questions, and findings that aren't work yet. An open issue can block a card \
(`brd block <card> --by <issue>`); closing it, for any reason, unblocks the card.

Documents are registered
```

with:

```python
Issues are bugs, questions, and findings that aren't work yet. An open issue can block a card \
(`brd block <card> --by <issue>`); closing it, for any reason, unblocks the card.

Blocking: `status` is authoritative. `blocked` already accounts for blockers in other projects, \
not-found blockers, container release and a blocked parent, and `brd next` lists only cards \
that can start now.

`blocked_by` is a list of ids that may belong to other projects or be not-found (the blocker's \
project was forgotten or not imported here); a not-found blocker blocks until its id returns. \
`blockers` gives each one's id, kind, project, title, status and `released`, in the same order. \
A card blocker releases its dependents once it is done, merged, canceled or archived; blocking \
a story or milestone waits for all of its children, even while its own status still reads todo.

Documents are registered
```

(Only the two new paragraphs are added; the "Documents are registered" line and everything after it are unchanged. Each continued line ends with a space then `\`, matching the existing style. No square brackets, so no rich escaping is needed.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_prompt.py -v`
Expected: all 5 tests PASS (including the unchanged `test_help_carries_the_usage_guidance`, which proves the `\\[\\[doc-stem]]` escaping still renders).

Also eyeball it: `uv run brd --help` — the two new paragraphs appear after the "Issues are bugs…" paragraph, rendered literally.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass (930 passed).

- [ ] **Step 6: Commit**

```bash
git add src/brd/cli/_app.py tests/test_prompt.py
git commit -m "State the blocking contract in brd --help: status is authoritative, cross-project and not-found blockers, container release"
```

---

### Task 2: `brd prompt` carries the blocking contract

**Files:**
- Modify: `src/brd/prompt.py` (`SNIPPET`)
- Test: `tests/test_prompt.py`, `tests/test_cli.py:43-49`

**Interfaces:**
- Consumes: `brd.prompt.render() -> str` (unchanged signature).
- Produces: nothing new.

- [ ] **Step 1: Write the failing test and extend the CLI test**

Append to `tests/test_prompt.py`:

```python
def test_prompt_states_the_blocking_contract():
    snippet = prompt.render()
    for phrase in (
        "authoritative",
        "other projects",
        "not-found",
        "brd next",
        "blocked_by",
        "blockers",
        "released",
        "all of its children",
    ):
        assert phrase in snippet, phrase
```

In `tests/test_cli.py`, add `prompt` to the `brd` import — change:

```python
from brd import db, paths
```

to:

```python
from brd import db, paths, prompt
```

and replace `test_prompt_prints_plain_markdown_not_json` (lines 43-49) with:

```python
def test_prompt_prints_plain_markdown_not_json():
    result = runner.invoke(app, ["prompt"])
    assert result.exit_code == 0
    assert "## Task tracking with brd" in result.output
    assert "brd --help" in result.output
    assert result.output == prompt.render()
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.output)
```

(Before editing, run `grep -n "prompt" tests/test_cli.py` and confirm no local variable or fixture named `prompt` exists that the new import would shadow; at plan time there is none.)

- [ ] **Step 2: Run the tests to verify the new one fails**

Run: `uv run pytest tests/test_prompt.py::test_prompt_states_the_blocking_contract tests/test_cli.py::test_prompt_prints_plain_markdown_not_json -v`
Expected: `test_prompt_states_the_blocking_contract` FAILS with `AssertionError: authoritative`. `test_prompt_prints_plain_markdown_not_json` PASSES already (it pins existing behaviour: `brd prompt` prints `render()` with `end=""`); it is there so the new paragraph is proven to reach a project-less agent.

- [ ] **Step 3: Add the blocking paragraph to `SNIPPET`**

Replace the whole `SNIPPET` in `src/brd/prompt.py` with:

```python
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
```

(The heading, the first paragraph and the bold rule line are byte-identical to before; only the middle paragraph and its blank line are new. The line breaks are placed so no tested phrase — `other projects`, `brd next`, `all of its children` — straddles a newline. The dash is U+2014 EM DASH.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_prompt.py tests/test_cli.py::test_prompt_prints_plain_markdown_not_json -v`
Expected: all PASS, including `test_prompt_points_agents_at_help_and_memory` and `test_prompt_keeps_the_doc_update_rule_inline`.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass (931 passed).

- [ ] **Step 6: Commit**

```bash
git add src/brd/prompt.py tests/test_prompt.py tests/test_cli.py
git commit -m "State the blocking contract in brd prompt; pin that brd prompt prints the whole snippet"
```

---

### Task 3: `brd block --by` help says the blocker may be in another project

**Files:**
- Modify: `src/brd/cli/cards.py:147`
- Test: `tests/test_prompt.py`

**Interfaces:**
- Consumes: `_help_text(*args: str) -> str` from Task 1 (in `tests/test_prompt.py`).
- Produces: nothing new.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_prompt.py`:

```python
def test_block_help_says_the_blocker_may_be_in_another_project():
    assert "another project" in _help_text("block")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_prompt.py::test_block_help_says_the_blocker_may_be_in_another_project -v`
Expected: FAIL with `AssertionError` (`'another project' in '...Id of the card or issue blocking it...'`).

- [ ] **Step 3: Change the `--by` help**

In `src/brd/cli/cards.py`, replace:

```python
    by: str = typer.Option(..., "--by", help="Id of the card or issue blocking it."),
```

inside `def block(` (line 147 — the `unblock` command's `--by` at line 162 reads "Id of the blocker to remove." and is NOT changed) with:

```python
    by: str = typer.Option(
        ..., "--by", help="Id of the card or issue blocking it; it may belong to another project."
    ),
```

The docstring `"""Mark a card as blocked by another card or an open issue."""` stays.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_prompt.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass (932 passed).

- [ ] **Step 6: Commit**

```bash
git add src/brd/cli/cards.py tests/test_prompt.py
git commit -m "Say in brd block --help that the blocker may belong to another project"
```

---

## Spec coverage check

| Spec item | Task |
|---|---|
| R1.1 status authoritative, blocked covers other projects / not-found / container release / blocked parent; `brd next` = can start now | Task 1 (text + T1) |
| R1.2 `blocked_by` ids, other projects or not-found; not-found blocks; arises from forgotten / not imported; reconnects when id returns | Task 1 (text + T1 `not-found`, `other projects`) |
| R1.3 `blockers` id, kind, project, title, status, `released`, same order | Task 1 (text + T1 `blockers`, `released`) |
| R1.4 releasing statuses; container waits for all children even while it reads todo | Task 1 (text + T1 `waits for all of its children`, T2) |
| R1 existing paragraphs stay; markup escaping intact | Task 1 (only inserts; T4 `test_help_carries_the_usage_guidance`) |
| R2 snippet paragraph between help paragraph and bold rule; rule byte-identical; `brd prompt` prints `render()` | Task 2 (T3, T4, T5) |
| R3 `brd block --by` mentions another project; docstring unchanged | Task 3 (T6) |
| Error paths: help/prompt exit 0 without a project | T5 (prompt, no project), T6 / `_help_text` (exit 0 asserted), existing `test_commands_without_data_do_not_migrate` |
| Out of scope: README, other commands' help | Global Constraints |
<!-- task-pipeline: validated -->
