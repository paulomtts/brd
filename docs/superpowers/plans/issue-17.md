<!-- task-pipeline: validated -->
# Spec (verbatim)

<!-- Verbatim copy of docs/superpowers/specs/issue-17-design.md -->

# Issue #17 — 1.16 Full end-to-end integration test and README

Parent story: #1 "Implement brd CLI v1". Narrows Task 16 of `docs/superpowers/plans/2026-09-17-brd-cli.md` (lines 2495–2631) to a single subtask. This is a coverage-and-documentation pass; it produces **no new interface**.

## Scope

In scope:

1. Append one test, `test_end_to_end_workflow(isolated_env)`, to `tests/test_cli.py`, composing the already-implemented commands into a single realistic workflow.
2. Replace the currently-empty `README.md` with install/usage documentation.
3. Verify the new test and the full suite pass.
4. Commit exactly `README.md` and `tests/test_cli.py` with message `Add end-to-end integration test and README`.

Out of scope (hard boundary): any change to `src/brd/` — commands `init`, `add`, `show`, `list`, `update`, `block`, `unblock`, `tree`, `next`, `projects` all already exist from siblings #13–#16. No new CLI flags, no new output fields, no new modules, no new test files, no changes to existing tests or fixtures. The plan's post-plan shell smoke test (plan lines 2617–2631) is a manual check only and must **not** be encoded as a pytest test.

## Test placement rule (authoritative: `docs/superpowers/specs/2026-09-17-brd-cli-design.md:183-192`)

This repo has exactly two tiers, both flat in `tests/test_<module>.py` — there is no unit/integration/e2e directory taxonomy:

- **Unit tier** — `tests/test_paths.py`, `tests/test_db.py`, `tests/test_master.py`, `tests/test_core.py`, `tests/test_output.py`: direct calls against a temp SQLite file, no mocking of SQLite.
- **CLI end-to-end tier** — `tests/test_cli.py`: `CliRunner`-driven invocations of the full command surface against a temp XDG data dir monkeypatched per test.

The new test drives the whole command surface through `CliRunner` against a temp XDG dir, so it belongs in the **CLI end-to-end tier**, appended to the existing `tests/test_cli.py`. It reuses the module-level `runner` and `app` (`tests/test_cli.py:1-8`) and the `isolated_env` fixture (`tests/test_cli.py:30-36`) — it must not define new fixtures or a new file.

## Observable behavior asserted by the workflow

Against a fresh `isolated_env` (temp `XDG_DATA_HOME`, cwd = temp repo directory named `myrepo`):

1. `brd init` exits 0.
2. `brd add --title "Story: ship feature"` returns an envelope whose `data` carries the new card's `id`.
3. `brd add --title "Subtask: write migration"` likewise (this card is the blocker).
4. `brd add --title "Subtask: write endpoint" --parent <story-id> --blocked-by <blocker-id>` creates a card that is both nested under the story and blocked.
5. First `brd next`: `data` is a list of ready cards whose ids include the story and the blocker, and exclude the blocked subtask.
6. `brd update <blocker-id> --status done` moves the blocker to done.
7. Second `brd next`: the previously blocked subtask now appears in the ready ids — the block is satisfied by the dependency reaching `done`.
8. `brd tree <story-id>`: `data[0]["children"][0]["id"]` equals the subtask id — parent/child nesting survives the round trip.
9. `brd projects`: `data[0]["name"]` equals `"myrepo"` — the project registered by `init` is the cwd repo directory name.

All assertions read `result.stdout` parsed with `json.loads`, matching the established style in `tests/test_cli.py` (e.g. the existing `next`/`tree` tests around lines 400–431). Default output is JSON; `--pretty` is not exercised here.

## Error paths

This subtask adds no new error handling. The test asserts only the happy path; a non-zero exit or unparseable stdout at any step surfaces as a test failure. If the composed workflow fails, the defect is in `src/brd/cli.py` (or a layer beneath it) and belongs to the relevant sibling subtask (#13–#16) — **do not adjust the test to match broken behavior, and do not silently expand this subtask into command logic**. Flag the failure and its owning sibling instead.

## README content

`README.md` is replaced in full with the block at plan lines 2564–2596: title and one-paragraph description (local-first kanban CLI with no visual UI, designed for AI agents), `## Install` with `uv sync`, `## Usage` with a shell block covering `init`, `add`, `add --blocked-by`, `next`, `tree`, `show`, `update --status done`, `projects`, the note that all commands output JSON by default for agent consumption with `--pretty` for human-readable output, and a pointer to `docs/superpowers/specs/2026-09-17-brd-cli-design.md`.

## Test list

| Test | Tier | Location |
| --- | --- | --- |
| `test_end_to_end_workflow` — init → add story → add blocker → add blocked subtask → next (story+blocker ready, subtask absent) → update blocker to done → next (subtask ready) → tree (story→subtask nesting) → projects (name `myrepo`) | CLI end-to-end | `tests/test_cli.py` (appended) |

No unit-tier tests are added: nothing in `core.py`, `db.py`, `master.py`, `paths.py`, or `output.py` changes.

## Verification

- `uv run pytest tests/test_cli.py::test_end_to_end_workflow -v` — expected PASS.
- `uv run pytest` — expected PASS across all `tests/test_*.py`.
- No typecheck or lint step configured for this repo.
- Manual, outside the test suite: the shell smoke test at plan lines 2621–2628, confirming the `brd` console-script entry point works and `init` appends `.brd` to `.gitignore` in a real directory.

## Done when

New test passes, full suite passes, `README.md` is non-empty and matches the plan content, and a single commit containing only `README.md` and `tests/test_cli.py` exists with the message `Add end-to-end integration test and README`.

---

# brd End-to-End Integration Test and README Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one `CliRunner`-driven end-to-end workflow test that composes the already-shipped `brd` commands, and replace the empty `README.md` with install/usage documentation.

**Architecture:** Pure coverage-and-documentation pass. All ten commands (`init`, `add`, `show`, `list`, `update`, `block`, `unblock`, `tree`, `next`, `projects`) already exist in `src/brd/cli.py` on this branch; this task only proves they compose correctly and documents them. The new test is appended to `tests/test_cli.py` — the repo's CLI end-to-end tier — reusing the module-level `runner`/`app` and the existing `isolated_env` fixture. Everything ships in a single commit containing exactly two files.

**Tech Stack:** Python 3, `typer` + `typer.testing.CliRunner`, `pytest`, `uv`, SQLite (via `src/brd/db.py`, untouched here).

**Spec:** `docs/superpowers/specs/issue-17-design.md` (reproduced verbatim at the top of this file).

## Global Constraints

- **Hard boundary: do not modify anything under `src/brd/`.** No new CLI flags, no new output fields, no new modules.
- **No new test files and no new fixtures.** The test is appended to the existing `tests/test_cli.py` and reuses the module-level `runner` (`tests/test_cli.py:8`), `app` (`tests/test_cli.py:6`), `json` import (`tests/test_cli.py:1`), and the `isolated_env` fixture (`tests/test_cli.py:30-36`).
- **Do not modify existing tests or fixtures** in `tests/test_cli.py` — only append.
- **Do not encode the shell smoke test as pytest.** It is a manual check only (see "Manual check after the commit" at the end of this plan).
- **If the new test fails, do not "fix" the test and do not touch `src/brd/`.** A failure is a defect owned by sibling subtask #13–#16. Stop and escalate, naming the failing step and the owning sibling.
- **Exactly one commit**, containing exactly `README.md` and `tests/test_cli.py`, with message verbatim: `Add end-to-end integration test and README`.
- Verification command for this repo: `uv run pytest`. No typecheck or lint step is configured.

---

### Task 1: End-to-end workflow test and README

**Files:**
- Modify: `tests/test_cli.py` (append after the final test, `test_next_pretty_flag_switches_off_json`, which ends at line 431)
- Modify: `README.md` (currently empty — replaced in full)

**Interfaces:**
- Consumes: the CLI commands already implemented in `src/brd/cli.py` — `init` (line 23), `projects` (line 44), `add` with `--title`/`--parent`/`--blocked-by` (lines 76-87), `update` with `--status` (line 188), `tree` with an optional positional `card_id` (lines 305-308), `next` (line 339). All emit a JSON envelope `{"ok": bool, "data": ..., "error": ...}` on stdout unless `--pretty`/`--human` is passed. `add` and `next` return card detail dicts with an `id` key; `tree` returns a list of nodes each with `id`, `title`, `status`, `blocked_by`, `children` (`src/brd/core.py:169-187`); `projects` returns a list of project dicts with a `name` key.
- Produces: nothing new — this is a coverage/documentation pass, not a new interface.

**Note on the TDD cycle for this task:** there is no production code to write, so the usual RED→GREEN order is inverted deliberately. Step 2 still proves the test is not vacuous by temporarily removing the `--blocked-by` wiring and watching the blocking assertion fail (a real RED), before restoring it and confirming GREEN in Step 4.

- [ ] **Step 1: Append the end-to-end workflow test**

Append to the end of `tests/test_cli.py` (after line 431, separated by two blank lines):

```python
def test_end_to_end_workflow(isolated_env):
    assert runner.invoke(app, ["init"]).exit_code == 0

    story = json.loads(
        runner.invoke(app, ["add", "--title", "Story: ship feature"]).stdout
    )["data"]
    blocker = json.loads(
        runner.invoke(app, ["add", "--title", "Subtask: write migration"]).stdout
    )["data"]
    subtask = json.loads(
        runner.invoke(
            app,
            [
                "add",
                "--title",
                "Subtask: write endpoint",
                "--parent",
                story["id"],
                "--blocked-by",
                blocker["id"],
            ],
        ).stdout
    )["data"]

    next_payload = json.loads(runner.invoke(app, ["next"]).stdout)
    ready_ids = {c["id"] for c in next_payload["data"]}
    assert story["id"] in ready_ids
    assert blocker["id"] in ready_ids
    assert subtask["id"] not in ready_ids  # blocked

    runner.invoke(app, ["update", blocker["id"], "--status", "done"])

    next_payload = json.loads(runner.invoke(app, ["next"]).stdout)
    ready_ids = {c["id"] for c in next_payload["data"]}
    assert subtask["id"] in ready_ids  # unblocked now

    tree_payload = json.loads(runner.invoke(app, ["tree", story["id"]]).stdout)
    assert tree_payload["data"][0]["children"][0]["id"] == subtask["id"]

    projects_payload = json.loads(runner.invoke(app, ["projects"]).stdout)
    assert projects_payload["data"][0]["name"] == "myrepo"
```

Do not add imports (`json`, `pytest`, `runner`, `app` are already at the top of the file) and do not define a fixture (`isolated_env` already exists at `tests/test_cli.py:30-36`).

- [ ] **Step 2: Prove the test is not vacuous (RED)**

Temporarily delete the two `--blocked-by` argument lines from the third `add` invocation, so it reads:

```python
    subtask = json.loads(
        runner.invoke(
            app,
            [
                "add",
                "--title",
                "Subtask: write endpoint",
                "--parent",
                story["id"],
            ],
        ).stdout
    )["data"]
```

Run: `uv run pytest tests/test_cli.py::test_end_to_end_workflow -v`
Expected: FAIL on `assert subtask["id"] not in ready_ids  # blocked` — with no dependency edge the subtask is already ready, which confirms the assertion is really exercising the blocking behavior rather than passing trivially.

- [ ] **Step 3: Restore the `--blocked-by` wiring**

Put the two deleted lines back so the third `add` invocation matches Step 1 exactly:

```python
    subtask = json.loads(
        runner.invoke(
            app,
            [
                "add",
                "--title",
                "Subtask: write endpoint",
                "--parent",
                story["id"],
                "--blocked-by",
                blocker["id"],
            ],
        ).stdout
    )["data"]
```

- [ ] **Step 4: Run the test to verify it passes (GREEN)**

Run: `uv run pytest tests/test_cli.py::test_end_to_end_workflow -v`
Expected: PASS — every command already exists on this branch, so the composed workflow should succeed as written.

If it FAILS: do not edit the test and do not edit `src/brd/`. Stop and report which step failed (`init` / `add` / `next` / `update` / `tree` / `projects`) together with the actual stdout, and name the owning sibling subtask (#13 for `init`/`projects`, #14 for `add`/`show`/`list`, #15 for `update`/`block`/`unblock`, #16 for `tree`/`next`).

- [ ] **Step 5: Write the README**

Replace the entire contents of `README.md` (the file is currently empty) with:

````markdown
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

See `docs/superpowers/specs/2026-09-17-brd-cli-design.md` for the full
design.
````

Write the markdown between the four-backtick fences above (starting at `# brd`, ending at `design.`) — the four-backtick fence is only this plan's quoting device; the README's own fences are the three-backtick `bash` blocks.

- [ ] **Step 6: Run the full test suite**

Run: `uv run pytest`
Expected: PASS across `tests/test_paths.py`, `tests/test_db.py`, `tests/test_master.py`, `tests/test_core.py`, `tests/test_output.py`, and `tests/test_cli.py`.

- [ ] **Step 7: Confirm only the two intended files changed**

Run: `git status --porcelain`
Expected: exactly two lines, ` M README.md` and ` M tests/test_cli.py`. If anything under `src/brd/` appears, revert it — it is outside this subtask's boundary.

- [ ] **Step 8: Commit**

```bash
git add README.md tests/test_cli.py
git commit -m "Add end-to-end integration test and README

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011rpKbM8YZgV45PCeiFqncT"
```

---

## Manual check after the commit (not part of the test suite)

Run once from a real shell to confirm the console-script entry point and `.gitignore` behavior outside `CliRunner`. Do **not** encode this as a pytest test.

```bash
cd /tmp && rm -rf brd-smoke-test && mkdir brd-smoke-test && cd brd-smoke-test
git init -q
uv run --project /home/paulomtts/Code/brd brd init
uv run --project /home/paulomtts/Code/brd brd add --title "Try it for real"
uv run --project /home/paulomtts/Code/brd brd next --pretty
cat .gitignore
```

Expected: `init` succeeds, `.gitignore` contains `.brd`, and `next --pretty` prints the card just added.
