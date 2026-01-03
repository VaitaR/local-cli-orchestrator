# AGENTS.md — Instructions for the coding LLM agent

## Rules

* Follow module boundaries; do not introduce cross-import cycles.
* Never write to `runs/` outside `RunPaths` / `ContextPack` helpers.
* All subprocess calls must go through `CommandRunner` so logs are consistent.
* Ensure `patch.diff` is always produced by `git diff`.
* Add tests for every stage and resume behavior.
* Prefer small commits; keep functions pure when possible.
* Keep prompts in `src/orx/prompts/` and render with a single renderer module.

## Definition of Done (MVP)

* `orx run` completes successfully in toy repo with FakeExecutor.
* Artifacts and logs are present as specified.
* Fix-loop works on failing pytest.
* Resume works.
* Base branch override works.

## Module Boundaries

```
src/orx/
├── cli.py           # Entry point, uses Runner
├── runner.py        # Orchestrates stages, uses all below
├── state.py         # State persistence, uses paths
├── config.py        # Configuration schema
├── paths.py         # Directory layout
├── exceptions.py    # Custom exceptions
│
├── context/         # Artifact management
│   ├── pack.py      # Read/write context files
│   └── backlog.py   # Backlog schema
│
├── workspace/       # Git operations
│   ├── git_worktree.py  # Worktree management
│   └── guardrails.py    # File modification checks
│
├── executors/       # CLI agent adapters
│   ├── base.py      # Protocol definition
│   ├── router.py    # Model routing + fallback policy
│   ├── codex.py     # Codex CLI wrapper
│   ├── gemini.py    # Gemini CLI wrapper
│   └── fake.py      # Testing executor
│
├── gates/           # Quality checks
│   ├── base.py      # Protocol definition
│   ├── ruff.py      # Ruff linting
│   ├── pytest.py    # Pytest runner
│   └── docker.py    # Docker build (optional)
│
├── stages/          # FSM stages
│   ├── base.py      # Stage protocol
│   ├── plan.py      # Planning stage
│   ├── spec.py      # Specification stage
│   ├── decompose.py # Backlog decomposition
│   ├── implement.py # Implementation + fix
│   ├── verify.py    # Gate verification
│   ├── review.py    # Code review
│   └── ship.py      # Commit/push/PR
│
├── prompts/         # Prompt templates
│   ├── renderer.py  # Jinja2 renderer
│   └── templates/   # .md template files
│
└── infra/           # Infrastructure
    └── command.py   # Subprocess wrapper
```

## Dependency Direction (enforced)

* `runner` depends on interfaces (`Executor`, `Gate`, `Workspace`) and `context`.
* `executors/*` depends on `subprocess` only via `CommandRunner`.
* `workspace/*` depends on `git` only via `CommandRunner`.
* `gates/*` depends on command runner only.
* `context/*` depends on filesystem only.

No cyclic dependencies.

## Testing

Run unit tests:
```bash
make test
```

Run integration tests:
```bash
make test-integration
```

Run with real LLM (requires codex/gemini installed):
```bash
RUN_LLM_TESTS=1 make smoke-llm
```

## Common Tasks

### Adding a new executor

1. Create `src/orx/executors/myengine.py`
2. Implement `Executor` protocol from `base.py` (including `resolve_invocation`)
3. Add engine type to `config.py` `EngineType` enum
4. Register in `runner.py:_create_executor()` and `src/orx/executors/router.py:ModelRouter._create_executors()`
5. Add tests

### Adding a new gate

1. Create `src/orx/gates/mygate.py`
2. Implement `Gate` protocol from `base.py`
3. Add gate config to `config.py`
4. Add creation logic to `runner.py` `_create_gates`
5. Add tests

### Adding a new stage

1. Create `src/orx/stages/mystage.py`
2. Extend `BaseStage` or `TextOutputStage` or `ApplyStage`
3. Create template in `src/orx/prompts/templates/mystage.md`
4. Add to `runner.py` stages dict and stage order
5. If it needs model routing, add to `StagesConfig` in `config.py`
6. Add tests

<!-- ORX:START AGENTS -->
## Auto-Updated Learnings

### Key File Locations
- **Knowledge Module**: `src/orx/knowledge/` - Self-improvement stage
  - `evidence.py` - Collects evidence pack from run artifacts
  - `guardrails.py` - Marker-based scoped updates, change limits
  - `updater.py` - Coordinates AGENTS.md + ARCHITECTURE.md updates
- **Model Router**: `src/orx/executors/router.py` - Per-stage executor/model selection
- **Knowledge Stage**: `src/orx/stages/knowledge.py` - KnowledgeUpdateStage
- **Knowledge Prompts**: `src/orx/prompts/templates/knowledge_*.md`

### Coding Patterns
- Use ORX markers (`<!-- ORX:START/END -->`) for scoped updates
- Validate changes with `KnowledgeGuardrails` before applying
- Architecture updates use gatekeeping (check if changes affect structure)

### ⚠️ Gotchas
- Knowledge update is NON-FATAL: failures don't break the run
- Markers MUST be present in files for scoped updates
- Max 300 lines total, 200 per file, 50 deletions by default
<!-- ORX:END AGENTS -->
