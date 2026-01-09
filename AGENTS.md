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
│   ├── backlog.py   # Backlog schema
│   └── repo_context/ # Auto-extracted project context (Python/TS tooling)
│
├── workspace/       # Git operations
│   ├── git_worktree.py  # Worktree management
│   └── guardrails.py    # File modification checks
│
├── executors/       # CLI agent adapters
│   ├── base.py      # Protocol definition
│   ├── router.py    # Model routing + fallback policy
│   ├── codex.py     # Codex CLI wrapper
│   ├── gemini.py    # Gemini CLI wrapper (use @file, not --prompt)
│   └── fake.py      # Testing executor
│
├── gates/           # Quality checks
│   ├── base.py      # Protocol definition
│   ├── ruff.py      # Ruff linting
│   ├── pytest.py    # Pytest runner
│   └── generic.py   # Custom command gates
│
├── stages/          # FSM stages
│   ├── base.py      # Stage protocol
│   ├── plan.py      # PLAN: text output
│   ├── spec.py      # SPEC: text output
│   ├── decompose.py # DECOMPOSE: backlog.yaml
│   ├── implement.py # IMPLEMENT: filesystem changes
│   ├── verify.py    # VERIFY: run gates
│   ├── review.py    # REVIEW: text output
│   ├── ship.py      # SHIP: commit/push/PR
│   └── knowledge.py # KNOWLEDGE_UPDATE: self-improvement
│
├── knowledge/       # Self-improvement module
│   ├── evidence.py  # Collect run artifacts
│   ├── problems.py  # Extract problems from stages.jsonl
│   ├── guardrails.py # Marker-scoped updates
│   └── updater.py   # AGENTS.md + ARCHITECTURE.md updates
│
├── metrics/         # Observability
│   ├── schema.py    # Pydantic models
│   ├── collector.py # Stage timing + LLM metrics
│   ├── tokens.py    # Token estimation (tiktoken + fallback)
│   └── writer.py    # Persistence (stages.jsonl, run.json)
│
├── dashboard/       # Web UI (FastAPI + HTMX)
│   ├── server.py    # App factory
│   ├── store/       # Data access (filesystem-based)
│   ├── handlers/    # Routes (pages, partials, api)
│   └── templates/   # Jinja2 templates
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

---

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

### Observability Patterns
- **Token tracking**: Use `estimate_tokens()` from `metrics/tokens.py` (tiktoken with fallback)
- **Metrics schema**: `TokenUsage` includes `input`, `output`, `total`, and `tool_calls` counts
- **ExecResult parsing**: Executors populate `extra` dict; runner extracts via `get_token_usage()` and `get_tool_calls()`
- **Dashboard integration**: Metrics displayed via HTMX partials; Prism.js for syntax highlighting

### Dashboard UI Patterns
- **HTMX lifecycle**: Initialize JS handlers on both `DOMContentLoaded` AND `htmx:afterSwap`
- **Prism highlighting**: Trigger on `htmx:afterSwap` for dynamically loaded code previews
- **File icons**: Map extensions to emoji (`.py` → 🐍, `.yaml` → ⚙️, `.json` → 📋)
- **Keyboard shortcuts**: ⌘K for search focus, arrow keys for navigation

### ⚠️ Gotchas
- Knowledge update is NON-FATAL: failures don't break the run
- Markers MUST be present in files for scoped updates
- Max 300 lines total, 200 per file, 50 deletions by default
- **HTMX handlers**: Never rely solely on `DOMContentLoaded` for HTMX-injected content
- **Token estimation**: Always provide fallback when tiktoken unavailable (char-based ~4 chars/token)
<!-- ORX:END AGENTS -->
