# orx - Local CLI Agent Orchestrator

A local, transparent, CLI-first orchestrator that enables long, sequential, self-checking, self-improving coding work using subscription CLI agents with filesystem access.

## Features

- **Multi-engine support**: Codex CLI (`codex exec --full-auto`) and Gemini CLI (headless + auto-approve)
- **Sequential FSM**: Plan → Spec → Decompose → Implement → Verify → Review → Ship
- **Git isolation**: Each run uses a separate git worktree
- **Quality gates**: Ruff linting, pytest, optional Docker build
- **Fix loops**: Automatic retry with failure evidence
- **Resume support**: Continue interrupted runs from checkpoint
- **Full auditability**: All artifacts, logs, and state persisted under `runs/<id>/`

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
  type: codex  # or gemini, fake
  enabled: true
  binary: codex
  extra_args: []
  timeout: 600

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

# Run with real LLM (requires codex/gemini)
RUN_LLM_TESTS=1 make smoke-llm
```

## Architecture

```
CLI (Typer)
    │
    ▼
Runner (FSM)
    │
    ├── StateManager (state.json)
    ├── ContextPack (artifacts)
    ├── WorkspaceGitWorktree
    │
    └── Stages
        ├── PlanStage      → Executor (text mode)
        ├── SpecStage      → Executor (text mode)
        ├── DecomposeStage → Executor (text mode)
        ├── ImplementStage → Executor (apply mode)
        ├── VerifyStage    → Gates (ruff, pytest)
        ├── ReviewStage    → Executor (text mode)
        └── ShipStage      → Git (commit, push, PR)
```

## License

MIT
