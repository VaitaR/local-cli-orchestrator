# AGENTS.md — Instructions for the coding LLM agent

## Rules

* Follow module boundaries; do not introduce cross-import cycles.
* Never write to `runs/` outside `RunPaths` / `ContextPack` helpers.
* All subprocess calls must go through `CommandRunner` so logs are consistent.
* Ensure `patch.diff` is always produced by `git diff`.
* Treat `pipeline/*` as production execution path (`standard` by default for `orx run`); use legacy FSM only when explicitly requested.
* Python support is limited to 3.11/3.12.
* Add tests for every stage and resume behavior.
* Prefer small commits; keep functions pure when possible.
* Keep prompts in `src/orx/prompts/` and render with a single renderer module.

## Definition of Done (MVP)

* `orx run` (default `standard` pipeline) completes successfully in toy repo with FakeExecutor.
* Artifacts and logs are present as specified.
* Fix-loop works on failing pytest.
* Resume works.
* Base branch override works.

## Module Boundaries

```
src/orx/
├── cli.py           # Entry point, uses Runner
├── runner.py        # Orchestrates stages (legacy FSM + pipeline dispatch)
├── state.py         # State persistence, uses paths (supports PAUSED state)
├── config.py        # Configuration schema (Pydantic)
├── paths.py         # Directory layout (incl. observability paths)
├── exceptions.py    # Custom exceptions
│
├── context/         # Artifact management
│   ├── pack.py      # Read/write context files
│   ├── backlog.py   # Backlog schema
│   ├── repo_context/ # Auto-extracted project context (Python/TS tooling)
│   └── intelligence/ # Tree-sitter code intelligence (NEW)
│       ├── parser.py    # RepoParser: extract definitions, imports (Python/JS/TS)
│       ├── skeleton.py  # SkeletonGenerator: strip bodies, keep signatures
│       ├── graph.py     # RepoGraph: file-level dependency graph + repo map
│       └── bundle.py    # SmartBundler: tiered context assembly (full/skeleton/map)
│
├── workspace/       # Git operations
│   ├── git_worktree.py  # Worktree management
│   └── guardrails.py    # File modification checks
│
├── executors/       # CLI agent adapters
│   ├── base.py      # Protocol + BaseExecutor base class
│   ├── models.py    # Centralized model definitions + capabilities
│   ├── router.py    # Model routing + fallback policy
│   ├── codex.py     # Codex CLI wrapper
│   ├── gemini.py    # Gemini CLI wrapper
│   ├── claude_code.py # Claude Code CLI wrapper (NEW)
│   ├── copilot.py   # GitHub Copilot CLI wrapper (NEW)
│   ├── cursor.py    # Cursor CLI wrapper (NEW)
│   └── fake.py      # Testing executor
│
├── gates/           # Quality checks
│   ├── base.py      # Protocol definition
│   ├── ruff.py      # Ruff linting
│   ├── pytest.py    # Pytest runner
│   ├── docker.py    # Docker build gate
│   └── generic.py   # Custom command gates
│
├── stages/          # FSM stages (used by legacy FSM + stage protocol)
│   ├── base.py      # Stage protocol (BaseStage/TextOutputStage/ApplyStage)
│   ├── plan.py      # PLAN: text output
│   ├── spec.py      # SPEC: text output
│   ├── decompose.py # DECOMPOSE: backlog.yaml
│   ├── implement.py # IMPLEMENT: filesystem changes
│   ├── reproduce.py # REPRODUCE: create failing test (Fail-to-Pass) (NEW)
│   ├── verify.py    # VERIFY: run gates
│   ├── review.py    # REVIEW: text output
│   ├── ship.py      # SHIP: commit/push/PR
│   └── knowledge.py # KNOWLEDGE_UPDATE: self-improvement
│
├── pipeline/        # Pipeline execution engine (production path) (NEW)
│   ├── definition.py    # NodeType, NodeDefinition, PipelineDefinition
│   ├── runner.py        # PipelineRunner: pause/resume, verify-fix loop, review loop
│   ├── registry.py      # PipelineRegistry: built-in + user-defined pipelines
│   ├── artifacts.py     # ArtifactStore for pipeline data flow
│   ├── context_builder.py # ContextBuilder: assemble node inputs + intelligence context
│   ├── constants.py     # Pipeline IDs and limits
│   └── executors/       # Node-type executors
│       ├── base.py      # Node executor protocol
│       ├── llm_text.py  # LLM text generation nodes
│       ├── llm_apply.py # LLM filesystem modification nodes
│       ├── map.py       # MAP nodes (iterate over backlog items)
│       ├── gate.py      # Gate verification nodes
│       └── custom.py    # Custom callable nodes
│
├── observability/   # Observability v2 — event-first tracing (NEW)
│   ├── schema.py    # ObsEvent, Correlation, SCHEMA_VERSION="2.0"
│   ├── correlation.py # StepCounter, CorrelationIds
│   ├── writer.py    # EventWriter (JSONL) + MetadataWriter (JSON)
│   ├── runtime.py   # RunObservability: session lifecycle, LLM/proc/fs/gate events
│   ├── tty.py       # TTYRecorder: asciinema v2 cast files
│   ├── projector.py # ProjectedRun: derive summaries from raw events
│   ├── redaction.py # Recursive sensitive field redaction
│   └── validate.py  # Event file validation (schema, monotonic step_ids)
│
├── knowledge/       # Self-improvement module
│   ├── evidence.py  # Collect run artifacts
│   ├── problems.py  # Extract problems from observability events
│   ├── guardrails.py # Marker-scoped updates
│   └── updater.py   # AGENTS.md + ARCHITECTURE.md updates
│
├── metrics/         # Legacy metrics (v1, kept for compatibility)
│   ├── schema.py    # Pydantic models
│   ├── collector.py # Stage timing + LLM metrics
│   ├── tokens.py    # Token estimation (tiktoken + fallback)
│   ├── aggregator.py # Metrics aggregation
│   └── writer.py    # Persistence (stages.jsonl, run.json)
│
├── dashboard/       # Web UI (FastAPI + HTMX)
│   ├── server.py    # App factory
│   ├── config.py    # DashboardConfig with env var support
│   ├── store/       # Data access (filesystem-based)
│   ├── handlers/    # Routes (pages, partials, api)
│   ├── worker/      # Background subprocess management (LocalWorker)
│   └── templates/   # Jinja2 templates (pages + partials incl. observability tabs)
│
├── prompts/         # Prompt templates
│   ├── renderer.py  # Jinja2 renderer (+ context caching split)
│   └── templates/   # .md template files
│
└── infra/           # Infrastructure
    └── command.py   # Subprocess wrapper + CommandObserver + power tools
```

## Dependency Direction (enforced)

* `runner` depends on interfaces (`Executor`, `Gate`, `Workspace`), `context`, `pipeline`, and `observability`.
* `pipeline/runner` depends on `pipeline/executors`, `pipeline/artifacts`, `pipeline/context_builder`, `observability`.
* `executors/*` depends on `subprocess` only via `CommandRunner`.
* `workspace/*` depends on `git` only via `CommandRunner`.
* `gates/*` depends on command runner only.
* `context/*` depends on filesystem only (intelligence subpackage uses `tree_sitter`).
* `observability/*` depends on filesystem only (no imports from runner/stages).
* `knowledge/*` reads from `observability/` events (read-only dependency).

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

---

## 🛠️ How to Work Efficiently (Tool Usage)

### Context Gathering Strategy

**BEFORE writing any code:**
1. **Identify the module** from the Module Boundaries map above
2. **Batch-read related files** — use grep or read multiple files in ONE call
3. **Check for existing patterns** — search for similar implementations first

**Tool usage priority:**
| Need | Best Tool | Why |
|------|-----------|-----|
| Find where X is used | `grep_search` with pattern | Fast, shows all occurrences |
| Understand module structure | `list_dir` + `read_file` (batch) | Get overview first |
| Find similar implementation | `grep_search` for class/function name | Reuse patterns |
| Check imports | `grep_search` for `from orx.X import` | Avoid cycles |

### Batch Operations (CRITICAL)

```python
# ❌ BAD: Sequential reads (slow, many tool calls)
read_file("src/orx/stages/base.py")
read_file("src/orx/stages/plan.py")
read_file("src/orx/stages/spec.py")

# ✅ GOOD: Read related files together
# Use grep_search to find all relevant code at once
grep_search("class.*Stage", include="src/orx/stages/*.py")

# Or read the whole module directory
list_dir("src/orx/stages/")
# Then read 2-3 key files in parallel
```

### Finding the Right Code

1. **Protocol/Interface** → always in `*/base.py`
2. **Configuration** → `config.py` (Pydantic models)
3. **Similar feature** → `grep_search` for keywords
4. **Test examples** → `tests/unit/test_<module>.py`

---

## ❌ NOT TO DO (Common LLM Mistakes)

### Code Quality

| ❌ Don't | ✅ Do Instead |
|----------|---------------|
| Create new utility when one exists | `grep_search` for existing helpers first |
| Copy-paste code between modules | Extract to shared location or import |
| Add import without checking cycles | Verify with `grep_search "from orx.X"` |
| Write 200+ line functions | Split into focused functions <50 lines |
| Hardcode paths/values | Use `config.py` or `paths.py` |
| Print debug output | Use `structlog` logger |
| Catch bare `except:` | Catch specific exceptions |
| Use `# type: ignore` freely | Fix the type issue properly |

### Import Anti-Patterns

```python
# ❌ NEVER: Creates cycle
# In src/orx/context/pack.py
from orx.runner import Runner  # runner imports context!

# ❌ NEVER: Wrong order (ruff I001)
from orx.config import Config
import structlog
from pathlib import Path

# ✅ CORRECT: stdlib → third-party → local
from __future__ import annotations

from pathlib import Path

import structlog

from orx.config import Config
```

### File Operations

```python
# ❌ NEVER: Direct file write to runs/
with open("runs/xxx/context/plan.md", "w") as f:
    f.write(content)

# ✅ ALWAYS: Use ContextPack
pack.write_plan(content)

# ❌ NEVER: Direct subprocess
import subprocess
subprocess.run(["ruff", "check"])

# ✅ ALWAYS: Use CommandRunner
cmd.run(["ruff", "check"], cwd=worktree)
```

### Testing Mistakes

```python
# ❌ BAD: Test without assertions
def test_something():
    result = do_thing()
    # No assert!

# ❌ BAD: Test too much at once
def test_entire_pipeline():
    # 100 lines of setup and checks

# ✅ GOOD: Focused test with clear assertion
def test_plan_stage_produces_output():
    result = plan_stage.run(ctx)
    assert result.success
    assert ctx.pack.plan_exists()
```

### Common Ruff Errors to Avoid

| Code | Issue | Fix |
|------|-------|-----|
| I001 | Import not sorted | stdlib → third-party → local |
| F401 | Unused import | Remove it |
| F841 | Unused variable | Use it or prefix with `_` |
| ARG002 | Unused argument | Add `# noqa: ARG002` if API requires it |
| W293 | Whitespace on blank line | Delete trailing spaces |

### Strict Typing (Mypy)

- Keep `mypy` strict for `src/orx` and tests; avoid broad `ignore_errors` overrides.
- Do not “fix” typing by loosening config globally; fix annotations/casts at call sites.
- Prefer `Sequence[Gate]` for read-only gate inputs to avoid list invariance problems.
- FastAPI handlers and startup/shutdown callbacks must have explicit return types.
- For `dict`/`list` annotations, always provide type parameters (`dict[str, Any]`, etc.).
- In tests, prefer `patch.object(...)` over direct method reassignment to avoid `method-assign`.
- When mocking `Popen`, set `MagicMock` fields first, then `cast(...)` only on return value.
- Avoid variable names that shadow imported helpers (e.g. don’t shadow `patch` from `unittest.mock`).
- Use `DashboardConfig(runs_root=...)` in typed code; `runs_dir` is runtime alias, not mypy-safe keyword.

---

## Common Tasks

### Adding a new executor

1. Create `src/orx/executors/myengine.py`
2. Extend `BaseExecutor` base class from `base.py` (implement `run_text`, `run_apply`, `resolve_invocation`)
3. Add engine type to `config.py` `EngineType` enum
4. Register in `runner.py:_create_executor()` and `src/orx/executors/router.py:ModelRouter._create_executors()`
5. If the executor supports context caching (system prompt), handle companion `<stage>_system.md` in `_build_command()`
6. Add tests

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

### Adding a new pipeline

1. Define pipeline in `src/orx/pipeline/registry.py` using `PipelineDefinition` + `NodeDefinition`
2. Choose node types: `LLM_TEXT`, `LLM_APPLY`, `MAP`, `GATE`, `CUSTOM`
3. For interactive (human-in-the-loop) nodes, set `interactive: true` in `NodeDefinition`
4. Register in `PipelineRegistry._build_builtins()` or load from YAML via `orx pipelines create`
5. Add tests

<!-- ORX:START AGENTS -->
## Auto-Updated Learnings

### Key File Locations
- **Pipeline Engine**: `src/orx/pipeline/` — production execution path
  - `runner.py` — `PipelineRunner` with pause/resume, verify-fix loop, review loop
  - `registry.py` — Built-in pipelines: `standard`, `fast_fix`, `plan_only`
  - `definition.py` — `NodeType`, `NodeDefinition`, `PipelineDefinition`
  - `context_builder.py` — Assembles node inputs with intelligence context
- **Observability v2**: `src/orx/observability/` — event-first tracing
  - `runtime.py` — `RunObservability` (core session + all event emission)
  - `schema.py` — `ObsEvent` dataclass, `SCHEMA_VERSION="2.0"`
  - `writer.py` — `EventWriter` (append-only JSONL) + `MetadataWriter`
  - `projector.py` — `ProjectedRun` (derive summaries from events)
- **Code Intelligence**: `src/orx/context/intelligence/` — tree-sitter based
  - `parser.py` — `RepoParser` (Python/JS/TS definition extraction)
  - `skeleton.py` — `SkeletonGenerator` (strip bodies, keep signatures)
  - `graph.py` — `RepoGraph` (file dependency graph + repo map)
  - `bundle.py` — `SmartBundler` (tiered context: full → skeleton → map)
- **Knowledge Module**: `src/orx/knowledge/` — self-improvement stage
  - `problems.py` — Extracts problems from observability events (not legacy metrics)
- **Model Router**: `src/orx/executors/router.py` — per-stage executor/model selection
- **Model Definitions**: `src/orx/executors/models.py` — centralized model registry + capabilities
- **Context Caching**: `src/orx/prompts/renderer.py` + `templates/system_context.md`

### Coding Patterns
- Use ORX markers (`<!-- ORX:START/END -->`) for scoped updates
- Validate changes with `KnowledgeGuardrails` before applying
- Architecture updates use gatekeeping (check if changes affect structure)
- Pipeline is the default execution path; legacy FSM via `--legacy-fsm` flag
- All observability events flow through `RunObservability.emit()`
- `CommandRunner` uses observer pattern: register `CommandObserver` via `add_observer()` for proc event capture
- Context caching splits prompts into `<stage>.md` + `<stage>_system.md`; Claude Code uses `--system-prompt`, others prepend

### Observability Patterns
- **Event schema v2**: `ObsEvent` with `event` type, `step_id` (monotonic), `correlation`, `payload`, `ts`
- **Event types**: `run.start/end`, `stage.start/end`, `llm.request/response`, `proc.exec.start/end`, `fs.patch`, `gate.approval`, `tty.segment.start/end`, `network.*`
- **Storage**: `runs/<id>/observability/` → `events.jsonl`, `metadata.json`, `tty/`, `llm/`, `patches/`, `exports/redacted/`
- **Token tracking**: Use `estimate_tokens()` from `metrics/tokens.py` (tiktoken with fallback)
- **ExecResult parsing**: Executors populate `extra` dict; runner extracts via `get_token_usage()` and `get_tool_calls()`
- **Dashboard integration**: Observability tabs (timeline, LLM, proc, fs, TTY) + legacy metrics tab

### Dashboard UI Patterns
- **HTMX lifecycle**: Initialize JS handlers on both `DOMContentLoaded` AND `htmx:afterSwap`
- **Prism highlighting**: Trigger on `htmx:afterSwap` for dynamically loaded code previews
- **File icons**: Map extensions to emoji (`.py` → 🐍, `.yaml` → ⚙️, `.json` → 📋)
- **Keyboard shortcuts**: ⌘K for search focus, arrow keys for navigation
- **New observability tabs**: timeline, llm, proc, fs, tty — driven by `observability/events.jsonl`

### Pipeline Patterns
- **Built-in pipelines**: `standard` (plan→spec→decompose→implement→review→ship), `fast_fix` (implement→verify→review→ship), `plan_only`
- **Node types**: `LLM_TEXT`, `LLM_APPLY`, `MAP`, `GATE`, `CUSTOM`
- **Pause/Resume**: Nodes with `interactive: true` trigger pause after completion; `orx resume <id>` continues
- **Reproduce stage**: Fail-to-Pass pattern — creates failing test, verifies it fails, then implement fixes
- **Review loop**: Up to 3 iterations with executor-generated feedback

### ⚠️ Gotchas
- Knowledge update is NON-FATAL: failures don't break the run
- Markers MUST be present in files for scoped updates
- Max 300 lines total, 200 per file, 50 deletions by default
- **HTMX handlers**: Never rely solely on `DOMContentLoaded` for HTMX-injected content
- **Token estimation**: Always provide fallback when tiktoken unavailable (char-based ~4 chars/token)
- **Gate mocks in tests**: Must implement `run(...)->GateResult` to satisfy `Gate` protocol under strict mypy
- **Stage model selectors**: `ctx.model_selector` is optional; assert non-`None` before reading `.model`
- **StageContext in unit tests**: It expects concrete workspace/executor types; use typed stubs + focused `cast` in tests
- **Observability v2 cutover**: Legacy `events.jsonl` (root) and `metrics/` are not used by dashboard/knowledge; canonical source is `observability/events.jsonl`
- **Pipeline vs FSM**: `orx run` defaults to pipeline engine; use `--legacy-fsm` only if needed
- **Context caching**: companion `<stage>_system.md` is auto-created by renderer; executors must handle it or ignore
- **Tree-sitter intelligence**: Optional dependency; gracefully degrades if `tree_sitter` not installed
<!-- ORX:END AGENTS -->
