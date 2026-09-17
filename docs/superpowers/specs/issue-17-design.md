# Issue #17 — 1.16 Full end-to-end integration test and README

Subtask of story #1 ("Implement brd CLI v1"), last in the linear stack. Narrows Task 16 of `docs/superpowers/plans/2026-09-17-brd-cli.md` (lines 2495–2611) to its implementable form.

## Scope

A coverage-and-documentation pass. No new interfaces, no new modules, no new core logic.

In scope:
- Append one end-to-end test, `test_end_to_end_workflow(isolated_env)`, to `tests/test_cli.py`.
- Replace the contents of `README.md` (currently 0 bytes) with the project's user-facing documentation.

Out of scope (owned by siblings #2–#16, already complete and in review):
- Any change to `src/brd/cli.py`, `src/brd/core.py`, `src/brd/db.py`, `src/brd/master.py`, `src/brd/models.py`, `src/brd/output.py`, `src/brd/paths.py`.
- Any new test file or new fixture. The existing module-level `runner` (`tests/test_cli.py:8`) and `isolated_env` fixture (`tests/test_cli.py:29-36`) are reused as-is.
- The `initialized_project` fixture (`tests/test_cli.py:100-103`) is deliberately *not* used: the workflow test invokes `brd init` itself so that the init step is part of the asserted flow.

The one exception to "do not touch `src/`": if the new test fails, the fix goes into the underlying command implementation, never into the test. Prior subtasks tested each command individually and the suite is green at 154/154, so a failure here means a genuine composition bug, not a test-expectation mismatch.

## Observable behavior

### Test

`test_end_to_end_workflow` drives the full documented lifecycle through `CliRunner` against a temp XDG data dir and a fresh `myrepo` working directory, asserting on parsed JSON (the default output mode) at each step:

1. `brd init` exits 0.
2. `brd add --title "Story: ship feature"` returns a card; `brd add --title "Subtask: write migration"` returns a second card (the blocker).
3. `brd add --title "Subtask: write endpoint" --parent <story-id> --blocked-by <blocker-id>` returns a third card.
4. `brd next` returns the story and the blocker as ready; the blocked subtask is absent — confirming `status` is derived as blocked at read time and never persisted.
5. `brd update <blocker-id> --status done` moves the blocker forward.
6. `brd next` now includes the subtask — confirming the dependency clears on completion.
7. `brd tree <story-id>` returns the story with the subtask as its first child.
8. `brd projects` returns a single project named `myrepo`.

The test body is given verbatim in the plan (lines 2509–2551) and is followed exactly.

### README

`README.md` contains, per the plan (lines 2564–2597): the `# brd` title; a one-line pitch (local-first kanban CLI, no visual UI, built for AI agents tracking long-running tasks without Jira or GitHub Projects); an **Install** section (`uv sync`); a **Usage** section with a shell block covering `init`, `add`, `add --blocked-by`, `next`, `tree`, `show`, `update --status done`, `projects`; a note that all commands emit JSON by default for agent consumption with `--pretty` for human-readable output; and a pointer to `docs/superpowers/specs/2026-09-17-brd-cli-design.md`.

Every command and flag named in the README must exist on the real CLI surface in `src/brd/cli.py` (verified: `init`, `projects`, `add`, `show`, `list`, `update`, `block`, `unblock`, `tree`, `next`). The README documents the subset above; it does not need to document `list`, `block`, or `unblock`.

## Constraints carried down from the milestone

- JSON is the default output; `--pretty`/`--human` toggles text. The test parses `result.stdout` as JSON without passing any flag, which is itself an assertion of that default.
- Every command responds with the `{"ok": true, "data": ...}` / `{"ok": false, "error": {"type", "message"}}` envelope; the test reads `["data"]` off each payload.
- `status` is never persisted as `blocked` — blockedness is derived, which is exactly what steps 4 and 6 exercise.
- Card and project IDs are UUID4 strings, passed opaquely between invocations.
- Both DB tiers live under the XDG data dir, never in the project repo; `isolated_env` enforces this by pointing `XDG_DATA_HOME` at `tmp_path`.

## Error paths

None new. This subtask adds no code that can raise and introduces no new failure mode. The happy path is the entire deliverable; error paths (unknown card id, cycle rejection, uninitialized project, invalid status) are already covered by the per-command tests written in subtasks #12–#16 and are not re-tested here.

## Test list

The repo has a **two-tier** taxonomy, per `docs/superpowers/specs/2026-09-17-brd-cli-design.md:183-192` — `core.py`/`db.py` unit tests against a temp SQLite file, and `cli.py` end-to-end tests driving the full command surface via `CliRunner` against a temp XDG data dir. There is no separate integration or conformance tier. `docs/superpowers/plans/issue-16.md:52` reinforces the rule: nothing belongs in `tests/test_core.py` when the logic already has core unit coverage from prior subtasks.

| Test | Tier | File |
| --- | --- | --- |
| `test_end_to_end_workflow` | cli end-to-end (`cli.py` tier) | `tests/test_cli.py` |

That is the complete list — one test. It composes existing commands only, so by the placement rule it is a `cli.py`-tier end-to-end test and nothing lands in `tests/test_core.py`, `tests/test_db.py`, `tests/test_master.py`, `tests/test_paths.py`, or `tests/test_output.py`. The README change is documentation and is not itself under test.

## Done when

`uv run pytest -q` passes with 155 tests (154 existing plus the new one), `README.md` is non-empty and matches the plan's content, and `README.md` + `tests/test_cli.py` are committed together.
