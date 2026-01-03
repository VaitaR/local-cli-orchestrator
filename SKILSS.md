# orx — Agent Operating Contract (Usage Only)

**Scope:** This document is only for an LLM agent to **use** `orx` inside a target git repository. It is **not** a guide for modifying `orx` itself.

**Source of truth:** `README.md`, `ARCHITECTURE.md`, and observed CLI behavior.

---

## 1) Hard Rules (MUST / MUST NOT)

### MUST
- Run `orx` from a **git repository root** (it uses git worktrees).
- Treat `runs/<run_id>/` and `.worktrees/<run_id>/` as **runtime artifacts**.
- Keep secrets out of prompts and logs; use placeholders and refer to secret names/paths.
- Ensure `runs/<run_id>/artifacts/patch.diff` is produced by **`git diff`** (this is how `orx` ships changes).
- Prefer small, explicit tasks with a clear scope.

### MUST NOT
- Do not run `orx` in a directory that is not a git repo.
- Do not hand-edit `runs/<run_id>/artifacts/patch.diff`.
- Do not ask the executor to modify sensitive files if guardrails are enabled (defaults include patterns like `*.env*`, `*secrets*`, `.git/*`, `*.pem`, `*.key`).

---

## 2) What `orx` Does (Current Contract)

### 2.1 CLI Commands

| Command | Purpose | Key flags | Notes |
|---|---|---|---|
| `orx init` | Create `orx.yaml` | `--dir`, `--engine`, `--force` | Writes config into `--dir` |
| `orx run` | Start a new run | `--dir`, `--config`, `--engine`, `--base-branch`, `--dry-run` | Task is a string or `@file.md` |
| `orx resume <run_id>` | Resume a run | `--dir`, `--config`, `--dry-run` | Cannot resume `done`/`failed` |
| `orx status [run_id]` | Show run status | `--dir`, `--json` | Without id: last 10 runs |
| `orx clean <run_id\|all>` | Remove artifacts/worktrees | `--dir`, `--force` | `all` deletes `runs/` and `.worktrees/` |

**FACT:** `orx run @task.md` resolves `task.md` relative to the current working directory, **not** relative to `--dir`. If you are not in the repo root, use an absolute path: `@/abs/path/task.md`.

### 2.2 Execution Model (FSM)

`orx` runs a sequential state machine:

1. `plan` (executor text mode)
2. `spec` (executor text mode)
3. `decompose` (executor text mode → produces `backlog.yaml`)
4. `implement_item` loop over backlog items:
   - `implement` (executor apply mode)
   - capture `patch.diff` via `git diff`
   - guardrails check
   - `verify` (quality gates)
   - on gate failure: `fix` (executor apply mode) + retry up to `run.max_fix_attempts`
5. `review` (executor text mode → produces `review.md` and `pr_body.md` artifacts)
6. `ship` (final `patch.diff`, optional commit/push/PR)

ASSUMPTION: stage naming and ordering follow `Runner` + `StateManager` implementation.

### 2.3 Executors (CLI agent adapters)

| `engine.type` | External binary | Text stages | Apply stages | Command shape |
|---|---|---|---|---|
| `codex` | `codex` | `run_text` | `run_apply` | `codex exec --full-auto --cd <worktree> @<prompt.md>` |
| `gemini` | `gemini` | `run_text` | `run_apply` | `gemini --yolo --approval-mode auto_edit --output-format json --prompt @<prompt.md>` |
| `fake` | none | deterministic | deterministic | Used for tests / dry simulations |

### 2.4 Quality Gates

Supported gate names: `ruff`, `pytest`, `docker`.

| Gate | Default | Skip behavior | Logs | Evidence in fix-loop |
|---|---|---|---|---|
| `ruff` | `ruff check .` | never | `runs/<id>/logs/ruff.log` | yes (tail) |
| `pytest` | `pytest -q` | if no tests found or exit code `5` | `runs/<id>/logs/pytest.log` | yes (tail) |
| `docker` | `docker build ...` | if no `Dockerfile` | `runs/<id>/logs/docker.log` | TODO: not included |

**WORKAROUND:** You can repurpose `ruff` gate to run any command (e.g. `command: make`, `args: ["helm-lint"]`). Caveat: logs/evidence will still be labeled as `ruff`.

---

## 3) Configuration (`orx.yaml`) — What to Set

Minimal practical fields:

- `engine.type`: `codex | gemini | fake`
- `engine.binary`: path/name of the CLI binary
- `engine.timeout`: seconds (applies to executor calls)
- `git.base_branch`: base branch used for the worktree
- `gates`: list of gate configs
- `guardrails`: forbidden patterns/paths + file count limit
- `run.max_fix_attempts`: fix-loop attempts per work item

Example (safe-ish defaults for running locally):

```yaml
version: "1.0"
engine:
  type: codex
  enabled: true
  binary: codex
  extra_args: []
  timeout: 600

git:
  base_branch: main
  remote: origin
  auto_commit: false
  auto_push: false
  create_pr: false
  pr_draft: true

gates:
  - name: ruff
    enabled: true
    command: ruff
    args: ["check", "."]
    required: true
  - name: pytest
    enabled: true
    command: pytest
    args: ["-q"]
    required: true

guardrails:
  enabled: true
  forbidden_patterns: ["*.env", "*.env.*", "*secrets*", "*.pem", "*.key", ".git/*"]
  forbidden_paths: [".env", ".env.local", ".env.production", "secrets.yaml", "secrets.json"]
  max_files_changed: 50

run:
  max_fix_attempts: 3
  parallel_items: false
  stop_on_first_failure: false
```

**Known limitations:**
- `fallback_engine` exists in config, but TODO: not used by the runner.
- `run.parallel_items` exists in config, but TODO: not implemented (loop is sequential).

---

## 4) How to Run (Agent Playbooks)

### 4.1 Start a run

Preflight (recommended):
- `git rev-parse --is-inside-work-tree`
- `git rev-parse <base_branch>`
- Verify required binaries exist (`codex`/`gemini`, plus gate commands).

Run:
- `orx init` (once per repo)
- `orx run -b <base_branch> "<task text>"`
- or `orx run -b <base_branch> @/abs/path/task.md`

After starting:
- Record the `Run ID` printed by `orx`.
- Inspect `runs/<run_id>/artifacts/patch.diff` and `runs/<run_id>/logs/`.

### 4.2 Resume a run

- `orx status <run_id>`
- If stage is not `done` or `failed`: `orx resume <run_id>`

**If stage is `failed`:** start a new run (TODO: no supported “resume failed”).

### 4.3 Clean up

- `orx clean <run_id>`
- `orx clean all --force` (dangerous: deletes all runs and worktrees)

---

## 5) Task Authoring (What to Put in `task.md`)

A good `task.md` should include:
- Goal (1–3 sentences)
- Constraints (what MUST NOT change)
- Expected outputs (files, commands, artifacts)
- Verification steps (which gates/commands must pass)
- Environment assumptions (base branch, deployment target, secret names, etc.)

Template:

```md
## Goal
...

## Constraints
- Do not touch: ...
- Scope is limited to: ...

## Verification
- Must pass: ...

## Notes
- Secrets are provided as: <secret name / env var names> (no values)
```

---

## 6) Run Artifacts (What Must Exist)

Directory layout:

- `runs/<run_id>/context/` (task/plan/spec/backlog)
- `runs/<run_id>/prompts/` (materialized prompts)
- `runs/<run_id>/artifacts/` (patch diff, review, pr body)
- `runs/<run_id>/logs/` (agent + gate logs)
- `.worktrees/<run_id>/` (git worktree)

Key files to inspect:
- `runs/<run_id>/state.json` (current stage, resumability)
- `runs/<run_id>/meta.json` (summary + tool versions)
- `runs/<run_id>/artifacts/patch.diff` (the authoritative diff)
- `runs/<run_id>/logs/agent_*.stderr.log` (agent failures)
- `runs/<run_id>/logs/<gate>.log` (gate output)

---

## 7) Common Failure Modes (Fast Triage)

- **Not a git repo / base branch missing**: `git rev-parse --is-inside-work-tree` / `git rev-parse <branch>`.
- **Executor binary missing**: `codex`/`gemini` not in PATH.
- **No output produced**: executor returned success but did not write expected stdout; inspect `runs/<id>/logs/agent_<stage>.stdout.log`.
- **No changes produced**: `patch.diff` empty; fix-loop may retry; inspect prompts + executor logs.
- **Guardrail violation**: too many files changed or forbidden files touched; reduce scope, tighten task constraints, adjust guardrails (carefully).
- **Stage is `failed`**: cannot resume; start a new run and tighten constraints.

---

## 8) Notes for Repo Hygiene

`orx` creates `runs/` and `.worktrees/` in the target repo root. Ensure the target repo ignores them:

```gitignore
runs/
.worktrees/
```

