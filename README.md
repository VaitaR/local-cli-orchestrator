# orx - Local CLI Agent Orchestrator

> A local, transparent orchestrator that coordinates AI coding agents (Codex, Gemini, Cursor) through a sequential FSM with git isolation, quality gates, and self-improvement.

## Features

- **Multi-engine support**: Codex CLI, Gemini CLI, Cursor Agent (CLI mode)
- **Per-stage routing**: Configure different executors/models per stage (plan, implement, fix, etc.)
- **Sequential FSM**: Plan → Spec → Decompose → Implement → Verify → Review → Ship → Knowledge Update
- **Git isolation**: Each run uses a separate git worktree
- **Quality gates**: Ruff, pytest, generic command gates (helm-lint, e2e tests, etc.)
- **Fix loops**: Automatic retry with failure evidence and token tracking
- **Resume support**: Continue interrupted runs from checkpoint
- **Web Dashboard**: Local FastAPI + HTMX UI with real-time monitoring
- **Metrics & Observability**: Token usage tracking, stage timings, quality analysis
- **Self-improvement**: Automatic updates to AGENTS.md and ARCHITECTURE.md after successful runs
- **Full auditability**: All artifacts, logs, prompts, and metrics persisted under `runs/<id>/`

## Installation

```bash
pip install -e ".[dev]"
```

## Quick Start

```bash
# Run `orx` from the root of a git repository (it uses git worktrees).
# It will create `runs/` and `.worktrees/` under that directory.
#
# Initialize configuration
orx init

# Run a task
orx run "Add a function add(a,b) that returns the sum"

# Or from a file
orx run @task.md

# Check status
orx status

# Resume an interrupted run
orx resume <run_id>

# Clean up
orx clean <run_id>
orx clean all
```

## Configuration

Create `orx.yaml` in your project root:

```yaml
version: "1.0"
engine:
  type: codex  # or gemini, cursor, fake
  enabled: true
  binary: codex
  timeout: 600
  model: gpt-4.1  # fallback default

# Per-executor configuration
executors:
  codex:
    bin: codex
    default:
      model: gpt-4.1
      reasoning_effort: high
  cursor:
    bin: cursor  # or 'agent' if using standalone CLI
    api_key: ${CURSOR_API_KEY}  # or set in environment
  gemini:
    bin: gemini
    default:
      model: gemini-2.0-flash
      output_format: json

# Per-stage executor/model overrides
stages:
  plan:
    executor: gemini
    model: gemini-2.0-flash
  implement:
    executor: cursor
    model: grok
  fix:
    executor: codex
    model: gpt-4.1

git:
  base_branch: main
  remote: origin
  auto_commit: true
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
  forbidden_patterns:
    - "*.env"
    - "*secrets*"
  max_files_changed: 50

run:
  max_fix_attempts: 3
  stop_on_first_failure: false
```

Stage overrides apply to these stage names: `plan`, `spec`, `decompose`, `implement`, `fix`, `review`, `knowledge_update`.

## Run Directory Structure

```
runs/<run_id>/
  meta.json           # Versions, timestamps, summary
  state.json          # FSM state for resume
  context/
    task.md           # Input task
    plan.md           # Generated plan
    spec.md           # Technical specification
    backlog.yaml      # Work items
    project_map.md    # Project structure
    decisions.md      # Design decisions
    lessons.md        # Lessons learned
  prompts/
    plan.md           # Materialized prompts
    spec.md
    decompose.md
    implement.md
    fix.md
    review.md
  artifacts/
    patch.diff        # Final diff (produced by git)
    review.md         # Code review
    pr_body.md        # PR description
  logs/
    agent_*.log       # Agent stdout/stderr
    ruff.log          # Gate logs
    pytest.log
```

## Dashboard

Run the local web UI for monitoring and controlling orchestrator runs:

```bash
# Install dashboard dependencies
pip install -e ".[dashboard]"

# Start dashboard
python -m orx.dashboard
# or
make run

# Open browser to http://127.0.0.1:8421
```

**Features:**
- Real-time run monitoring with auto-refresh
- IDE-style artifacts explorer with syntax highlighting
- Token usage and tool call metrics
- Stage timeline with success/failure indicators
- Log tailing with search and filtering
- Start/cancel runs from UI

## Development

```bash
# Format code
make fmt

# Lint
make lint

# Run unit tests
make test

# Run integration tests
make test-integration

# Run with real LLM (requires codex/gemini/cursor)
RUN_LLM_TESTS=1 make smoke-llm
```

## Architecture

```
Dashboard (FastAPI + HTMX)  ←→  CLI (Typer)
                                     │
                                     ▼
                                Runner (FSM)
                                     │
    ┌────────────────────────────────┼────────────────────────────────┐
    │                                │                                │
    ▼                                ▼                                ▼
StateManager                    ContextPack                    MetricsCollector
(state.json)                    (artifacts)                    (stages.jsonl)
                                     │
                                     ▼
                            WorkspaceGitWorktree
                                     │
                                     ▼
                                  Stages
        ├── PlanStage           → Executor (text mode) → Metrics
        ├── SpecStage           → Executor (text mode) → Metrics
        ├── DecomposeStage      → Executor (text mode) → Metrics
        ├── ImplementStage      → Executor (apply mode) → Metrics
        ├── VerifyStage         → Gates (ruff, pytest) → Metrics
        ├── ReviewStage         → Executor (text mode) → Metrics
        ├── ShipStage           → Git (commit, push, PR)
        └── KnowledgeUpdateStage → Self-improvement (AGENTS.md)
                                                             │
                                                             ▼
                                                    ModelRouter
                                                    ├── CodexExecutor
                                                    ├── GeminiExecutor
                                                    ├── CursorExecutor
                                                    └── FakeExecutor (tests)
```

## License

MIT
