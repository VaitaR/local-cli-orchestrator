# SKILLS.md — orx Operator (MCP Edition)

**Role:** You are the operator of the **orx** orchestration engine via the Model Context Protocol (MCP).
**Goal:** Complete coding tasks by delegating execution to orx pipelines and monitoring their progress through MCP tools and resources — never touch the filesystem directly.

---

## 1. Operating Rules

| Rule | Why |
|------|-----|
| **NO FILESYSTEM TOUCHING** | Never manually read/write files in `runs/` or `.worktrees/`. Use MCP tools and resources only. |
| **ASYNC EXECUTION** | `start_run` returns immediately. You MUST poll `get_run_status` to track progress. |
| **CONTEXT ECONOMY** | Do not read full logs unless `get_run_status` reports a failure. |
| **SECRETS** | Keep secrets out of task descriptions. Use placeholder names only. |
| **GIT REQUIRED** | `orx` operates on git repos. The MCP server must point at a repo root (`ORX_PROJECT_ROOT`). |

---

## 2. Workflow

### Start → Poll → Act

```
start_run(task, pipeline)
        │
        ▼
   ┌─── poll get_run_status(run_id) ◄──┐
   │              │                     │
   │    success ──┤── failed ──┐        │
   │              │            │        │
   │    paused ───┤       read logs     │
   │       │      │       debug_run     │
   │   review     │       prompt        │
   │   artifacts  │            │        │
   │       │      │    start new run    │
   │  resume_run  │                     │
   │       └──────┴─────────────────────┘
   │
   ▼
  done → read diff, review artifacts
```

### Starting Work

1. **Call** `start_run(task="…", pipeline="standard")`.
   - Use `pipeline="fast_fix"` for small bugs; `"standard"` for features.
2. **Record** the returned `run_id`.

### Monitoring

- **Poll** `get_run_status(run_id)` until `status` is one of: `success`, `failed`, `paused`.
- The response contains `stage`, `stages` map, `metrics`, and `last_error` — no logs.

### Handling Paused Runs

Some pipeline nodes are interactive (human-in-the-loop). When `status == "paused"`:
1. Read artifacts to understand what was produced: resource `orx://runs/{id}/artifacts/plan.md`, etc.
2. If satisfied, call `resume_run(run_id)`.
3. Continue polling.

### Debugging Failures

1. Check `get_run_status` → look at `last_error` and `stages` map.
2. Use the **`debug_run`** prompt — it assembles status, error evidence, and log tails into a single context block.
3. If you need raw data: resource `orx://runs/{id}/logs/pytest.log` (last 50 lines).
4. Start a new run with an improved task description.

### Cancellation

- Call `cancel_run(run_id)` to SIGTERM the running process.

---

## 3. MCP Tools Reference

| Tool | Purpose | Key Args |
|------|---------|----------|
| `start_run` | Launch a new orx run | `task` (str), `pipeline` (enum), `base_branch` (opt) |
| `get_run_status` | Status + metadata (no logs) | `run_id` |
| `resume_run` | Continue paused/interrupted run | `run_id` |
| `cancel_run` | SIGTERM running process | `run_id` |
| `list_runs` | Recent runs summary | `limit` (default 5) |
| `list_pipelines` | Available pipeline definitions | — |

> **Note:** All arguments are strictly typed via JSON Schema — the MCP server enforces valid values.

---

## 4. MCP Resources Reference

| URI Pattern | Content | MIME |
|-------------|---------|------|
| `orx://runs/{run_id}/state` | Full `state.json` | application/json |
| `orx://runs/{run_id}/diff` | Current `patch.diff` | text/x-diff |
| `orx://runs/{run_id}/logs/{name}` | Last 50 lines of log | text/plain |
| `orx://runs/{run_id}/artifacts/{name}` | Artifact content (plan.md, spec.md, etc.) | text/markdown |

---

## 5. MCP Prompts Reference

| Prompt | Purpose |
|--------|---------|
| `new_task` | Loads project context + available pipelines; prepares you to formulate a task |
| `debug_run` | Assembles failed run's status, logs, diff into one context block for analysis |

---

## 6. Pipelines Quick Reference

| Pipeline | When to Use | Stages |
|----------|-------------|--------|
| `standard` | Features, refactors | Plan → Spec → Decompose → Implement (MAP) → Review → Ship |
| `fast_fix` | Bug fixes, small changes | Implement → Verify → Review → Ship |
| `plan_only` | Exploration, planning | Plan |

---

## 7. Task Authoring Tips

A good task description includes:
- **Goal** (1–3 sentences)
- **Constraints** (what must NOT change)
- **Verification** (which gates/commands must pass)

```
Fix the flaky test in test_runner.py::test_resume_from_paused.
Constraint: do not change the public API of StateManager.
Must pass: pytest, ruff.
```

---

## 8. Setup

### MCP Server Registration

**Claude Desktop / Cursor / any MCP client:**

```json
{
  "mcpServers": {
    "orx": {
      "command": "orx-mcp",
      "env": {
        "ORX_PROJECT_ROOT": "/path/to/your/repo"
      }
    }
  }
}
```

Or via `python -m`:

```json
{
  "mcpServers": {
    "orx": {
      "command": "python",
      "args": ["-m", "orx.mcp"],
      "env": {
        "ORX_PROJECT_ROOT": "/path/to/your/repo"
      }
    }
  }
}
```

### Prerequisites

- `orx` CLI installed and on PATH
- Git repository with `orx.yaml` (run `orx init` once)
- MCP SDK: `pip install orx[mcp]`

---

## 6) Run Artifacts (What Must Exist)

Directory layout:

- `runs/<run_id>/context/` (task/plan/spec/backlog + intelligence context)
- `runs/<run_id>/prompts/` (materialized prompts + system context companions)
- `runs/<run_id>/artifacts/` (patch diff, review, pr body)
- `runs/<run_id>/logs/` (agent + gate logs)
- `runs/<run_id>/metrics/` (`stages.jsonl`, `run.json`) — legacy v1
- `runs/<run_id>/observability/` — **canonical v2** (`events.jsonl`, `metadata.json`, `tty/`, `llm/`, `patches/`)
- `runs/<run_id>/events.jsonl` (append-only timeline — legacy)
- `runs/index.jsonl` (append-only run summaries)
- `.worktrees/<run_id>/` (git worktree)

Key files to inspect:
- `runs/<run_id>/state.json` (current stage, resumability, paused state)
- `runs/<run_id>/meta.json` (summary + tool versions)
- `runs/<run_id>/artifacts/patch.diff` (the authoritative diff)
- `runs/<run_id>/logs/agent_*.stderr.log` (agent failures)
- `runs/<run_id>/logs/<gate>.log` (gate output)
- `runs/<run_id>/observability/events.jsonl` (**primary** event log — v2)
- `runs/<run_id>/metrics/run.json` (time-to-green, stage breakdown — legacy)

---

## 7) Common Failure Modes (Fast Triage)

- **Not a git repo / base branch missing**: `git rev-parse --is-inside-work-tree` / `git rev-parse <branch>`.
- **Executor binary missing**: `codex`/`gemini`/`claude`/`copilot` not in PATH.
- **No output produced**: executor returned success but did not write expected stdout; inspect `runs/<id>/logs/agent_<stage>.stdout.log`.
- **No changes produced**: `patch.diff` empty; fix-loop may retry; inspect prompts + executor logs.
- **Guardrail violation**: too many files changed or forbidden files touched; reduce scope, tighten task constraints, adjust guardrails (carefully).
- **Stage is `failed`**: cannot resume; start a new run and tighten constraints.
- **Run is `paused`**: this is expected for interactive pipeline nodes; use `orx resume <run_id>` to continue.
- **Observability validation fails**: `orx observability validate --run-id <id>` to check for schema/ordering issues.

---

## 8) Notes for Repo Hygiene

`orx` creates `runs/` and `.worktrees/` in the target repo root. Ensure the target repo ignores them:

```gitignore
runs/
.worktrees/
```
