# Pipeline Architecture Specification v2

> **Status**: Draft
> **Date**: 2026-01-11
> **Breaking Changes**: Yes (old FSM Runner replaced, but current pipeline reproducible)

---

## 1. Overview

Переход `orx` от жёстко-зашитого последовательного FSM к **конфигурируемым node-based pipelines** с:
1.  **Гибкостью**: Пользователь определяет набор нод и их порядок.
2.  **Контекстными блоками**: Явное объявление какие артефакты/контексты нужны каждой ноде.
3.  **Сохраняемыми пресетами**: CLI и Dashboard позволяют создавать, сохранять и переиспользовать pipelines.
4.  **Параллелизмом**: `MapNode` для параллельного выполнения задач из backlog.

---

## 2. Core Concepts

### 2.1. Context Blocks (Контекстные Сущности)

Контекстный блок — единица данных, доступная нодам pipeline.

| Block Key           | Description                              | Source                          |
|---------------------|------------------------------------------|---------------------------------|
| `task`              | Описание задачи от пользователя          | Ввод пользователя               |
| `plan`              | Высокоуровневый план                     | Output PlanNode                 |
| `spec`              | Техническая спецификация                 | Output SpecNode                 |
| `backlog`           | Список WorkItem (YAML)                   | Output DecomposeNode            |
| `repo_map`          | Структура проекта (файлы, модули)        | Auto-extracted (RepoContextBuilder) |
| `tooling_snapshot`  | pyproject.toml, ruff.toml и т.д.         | Auto-extracted                  |
| `verify_commands`   | Команды проверки (gates)                 | Auto-extracted                  |
| `agents_context`    | AGENTS.md секции (Module Boundaries, DoD)| Auto-extracted                  |
| `architecture`      | ARCHITECTURE.md overview                 | Auto-extracted                  |
| `error_logs`        | Логи ошибок (ruff, pytest)               | Runtime (fix loop)              |
| `patch_diff`        | Git diff изменений                       | Runtime                         |
| `current_item`      | Текущий WorkItem (в MapNode)             | Runtime                         |
| `file_snippets`     | Содержимое hint-файлов                   | Runtime                         |

### 2.2. Node (Нода)

```python
class NodeDefinition(BaseModel):
    """Определение ноды в pipeline."""
    id: str                      # Уникальный ID ("plan", "my_custom_step")
    type: NodeType               # llm_text | llm_apply | map | gate | custom
    template: str | None = None  # Путь к prompt template (относительно templates/)
    inputs: list[str] = []       # Ключи контекстных блоков на вход
    outputs: list[str] = []      # Ключи контекстных блоков на выход
    config: NodeConfig = {}      # Специфичные настройки (model, timeout, retries)

class NodeType(str, Enum):
    LLM_TEXT = "llm_text"        # LLM генерирует текст (plan, spec, review)
    LLM_APPLY = "llm_apply"      # LLM применяет изменения к файлам (implement)
    MAP = "map"                  # Итерирует по коллекции (backlog items)
    GATE = "gate"                # Запускает проверки (ruff, pytest)
    CUSTOM = "custom"            # Пользовательский Python callable

class NodeConfig(BaseModel):
    """Конфигурация ноды."""
    model: str | None = None           # Override модели для этой ноды
    timeout_seconds: int | None = None # Override timeout
    max_retries: int = 0               # Количество повторов при ошибке
    gates: list[str] = []              # Для type=gate: список gate names
    concurrency: int = 1               # Для type=map: параллельность
    item_pipeline: list[NodeDefinition] = []  # Для type=map: вложенный pipeline
```

### 2.3. Pipeline Definition

```python
class PipelineDefinition(BaseModel):
    """Полное определение pipeline."""
    id: str                           # Уникальный ID ("standard", "fast_fix", "custom_v1")
    name: str                         # Человекочитаемое имя
    description: str = ""             # Описание
    nodes: list[NodeDefinition]       # Упорядоченный список нод
    default_context: list[str] = []   # Контексты, извлекаемые автоматически перед стартом
```

### 2.4. Pipeline Presets (Пресеты)

```yaml
# ~/.orx/pipelines/standard.yaml  (или в orx.yaml секция pipelines:)
pipelines:
  standard:
    name: "Standard Full Pipeline"
    description: "Plan → Spec → Decompose → Implement → Review → Ship"
    default_context: ["repo_map", "tooling_snapshot", "agents_context", "architecture"]
    nodes:
      - id: plan
        type: llm_text
        template: "plan.md"
        inputs: ["task", "repo_map", "agents_context"]
        outputs: ["plan"]
        
      - id: spec
        type: llm_text
        template: "spec.md"
        inputs: ["task", "plan", "repo_map", "agents_context"]
        outputs: ["spec"]
        
      - id: decompose
        type: llm_text
        template: "decompose.md"
        inputs: ["spec", "repo_map", "architecture"]
        outputs: ["backlog"]
        
      - id: implement_loop
        type: map
        inputs: ["backlog", "spec"]
        outputs: ["implementation_report"]
        config:
          concurrency: 1  # Параллельность (1 = последовательно)
          item_pipeline:
            - id: implement_item
              type: llm_apply
              template: "implement.md"
              inputs: ["current_item", "spec", "file_snippets", "agents_context", "verify_commands"]
              outputs: ["patch_diff"]
              
            - id: verify_item
              type: gate
              inputs: ["patch_diff"]
              config:
                gates: ["ruff", "pytest"]
                
      - id: review
        type: llm_text
        template: "review.md"
        inputs: ["plan", "patch_diff", "backlog"]
        outputs: ["review"]
        
      - id: ship
        type: custom
        inputs: ["review", "patch_diff"]
        outputs: []
        
  fast_fix:
    name: "Fast Fix (No Planning)"
    description: "Directly implement from task"
    default_context: ["repo_map", "agents_context"]
    nodes:
      - id: implement
        type: llm_apply
        template: "implement_direct.md"
        inputs: ["task", "repo_map", "agents_context"]
        outputs: ["patch_diff"]
        
      - id: verify
        type: gate
        inputs: ["patch_diff"]
        config:
          gates: ["ruff", "pytest"]
          
  plan_only:
    name: "Plan Only"
    description: "Generate plan without implementation"
    nodes:
      - id: plan
        type: llm_text
        template: "plan.md"
        inputs: ["task", "repo_map"]
        outputs: ["plan"]
```

---

## 3. Data Model & Schema

### 3.1. Artifact Store (Хранилище Артефактов)

```python
class ArtifactStore:
    """Хранилище артефактов для run."""
    
    def __init__(self, paths: RunPaths):
        self._paths = paths
        self._cache: dict[str, Any] = {}
        self._metadata: dict[str, ArtifactMeta] = {}
    
    def get(self, key: str) -> Any:
        """Получить артефакт по ключу."""
        if key in self._cache:
            return self._cache[key]
        # Lazy load from disk
        return self._load_from_disk(key)
    
    def set(self, key: str, value: Any, *, persist: bool = True) -> None:
        """Установить артефакт."""
        self._cache[key] = value
        self._metadata[key] = ArtifactMeta(
            key=key,
            created_at=datetime.now(UTC),
            size_bytes=len(str(value).encode()),
        )
        if persist:
            self._persist_to_disk(key, value)
    
    def exists(self, key: str) -> bool:
        """Проверить существование артефакта."""
        return key in self._cache or self._disk_path(key).exists()
    
    def keys(self) -> list[str]:
        """Список всех ключей."""
        ...
    
    # Маппинг ключей на файлы (совместимость с текущей структурой)
    KEY_TO_PATH = {
        "task": "context/task.md",
        "plan": "context/plan.md",
        "spec": "context/spec.md",
        "backlog": "context/backlog.yaml",
        "repo_map": "context/project_map.md",
        "tooling_snapshot": "context/tooling_snapshot.md",
        "verify_commands": "context/verify_commands.md",
        "patch_diff": "artifacts/patch.diff",
        "review": "artifacts/review.md",
    }
```

### 3.2. Context Builder (Сборщик Контекста)

```python
class ContextBuilder:
    """Собирает контекст для ноды на основе её inputs."""
    
    def __init__(self, store: ArtifactStore, worktree: Path):
        self._store = store
        self._worktree = worktree
        self._extractors = self._register_extractors()
    
    def build_for_node(self, node: NodeDefinition) -> dict[str, Any]:
        """Собрать контекст для ноды."""
        context = {}
        for key in node.inputs:
            if self._store.exists(key):
                context[key] = self._store.get(key)
            elif key in self._extractors:
                # Auto-extract (repo_map, agents_context, etc.)
                value = self._extractors[key]()
                self._store.set(key, value)
                context[key] = value
            else:
                raise MissingContextError(f"Context '{key}' not available for node '{node.id}'")
        return context
    
    def _register_extractors(self) -> dict[str, Callable]:
        """Регистрация автоматических экстракторов контекста."""
        return {
            "repo_map": lambda: RepoContextBuilder(self._worktree).build().project_map,
            "tooling_snapshot": lambda: RepoContextBuilder(self._worktree).build().tooling_snapshot,
            "verify_commands": lambda: RepoContextBuilder(self._worktree).build().verify_commands,
            "agents_context": lambda: extract_agents_context(self._worktree),
            "architecture": lambda: extract_architecture_overview(self._worktree),
            "file_snippets": lambda item: build_file_snippets(
                worktree=self._worktree,
                files=item.files_hint if item else [],
            ),
        }
```

---

## 4. Execution Engine

### 4.1. PipelineRunner (Новый Runner)

```python
class PipelineRunner:
    """Исполнитель pipeline."""
    
    def __init__(
        self,
        config: OrxConfig,
        pipeline: PipelineDefinition,
        paths: RunPaths,
    ):
        self.config = config
        self.pipeline = pipeline
        self.paths = paths
        self.store = ArtifactStore(paths)
        self.context_builder = ContextBuilder(self.store, paths.worktree_path)
        self.node_executors = self._create_executors()
        self.metrics = MetricsCollector(...)
        self.events = EventLogger(paths.events_jsonl)
    
    def run(self, task: str) -> PipelineResult:
        """Запустить pipeline."""
        # 1. Инициализация
        self.store.set("task", task)
        self._extract_default_context()
        
        # 2. Выполнение нод последовательно
        for node in self.pipeline.nodes:
            result = self._execute_node(node)
            if not result.success:
                return PipelineResult(success=False, failed_node=node.id, error=result.error)
        
        return PipelineResult(success=True)
    
    def _execute_node(self, node: NodeDefinition) -> NodeResult:
        """Выполнить одну ноду."""
        self.events.log("node_start", node_id=node.id, node_type=node.type)
        
        # Собрать контекст
        context = self.context_builder.build_for_node(node)
        
        # Получить executor для типа ноды
        executor = self.node_executors[node.type]
        
        # Выполнить с метриками
        with self.metrics.stage(node.id):
            result = executor.execute(node, context, self.store)
        
        # Сохранить outputs
        for key, value in result.outputs.items():
            self.store.set(key, value)
        
        self.events.log("node_end", node_id=node.id, success=result.success)
        return result
    
    def _create_executors(self) -> dict[NodeType, NodeExecutor]:
        """Создать executors для каждого типа ноды."""
        return {
            NodeType.LLM_TEXT: LLMTextNodeExecutor(self.config),
            NodeType.LLM_APPLY: LLMApplyNodeExecutor(self.config),
            NodeType.MAP: MapNodeExecutor(self.config),
            NodeType.GATE: GateNodeExecutor(self.config),
            NodeType.CUSTOM: CustomNodeExecutor(self.config),
        }
```

### 4.2. Node Executors

```python
class NodeExecutor(Protocol):
    """Протокол исполнителя ноды."""
    
    def execute(
        self,
        node: NodeDefinition,
        context: dict[str, Any],
        store: ArtifactStore,
    ) -> NodeResult:
        ...

class LLMTextNodeExecutor:
    """Executor для LLM-нод, генерирующих текст."""
    
    def execute(self, node: NodeDefinition, context: dict, store: ArtifactStore) -> NodeResult:
        # 1. Render prompt template
        prompt = self.renderer.render(node.template, **context)
        
        # 2. Call LLM executor
        result = self.llm_executor.run_text(
            prompt=prompt,
            model=node.config.model,
            timeout=node.config.timeout_seconds,
        )
        
        # 3. Return outputs
        if result.success:
            output_key = node.outputs[0] if node.outputs else node.id
            return NodeResult(success=True, outputs={output_key: result.content})
        return NodeResult(success=False, error=result.error)

class MapNodeExecutor:
    """Executor для параллельной итерации по коллекции."""
    
    def execute(self, node: NodeDefinition, context: dict, store: ArtifactStore) -> NodeResult:
        # 1. Get collection to iterate
        backlog = context.get("backlog")
        if not backlog:
            return NodeResult(success=False, error="No backlog provided")
        
        # 2. Create thread pool
        concurrency = node.config.concurrency
        results = []
        
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = []
            for item in backlog.items:
                # Build item-specific context
                item_context = {**context, "current_item": item}
                future = pool.submit(self._run_item_pipeline, node.config.item_pipeline, item_context, store)
                futures.append(future)
            
            for future in as_completed(futures):
                results.append(future.result())
        
        # 3. Aggregate results
        all_success = all(r.success for r in results)
        return NodeResult(
            success=all_success,
            outputs={"implementation_report": self._build_report(results)},
        )
```

---

## 5. CLI & Dashboard Integration

### 5.1. CLI Commands

```bash
# Запуск с дефолтным pipeline
orx run "Implement feature X"

# Запуск с конкретным pipeline
orx run --pipeline fast_fix "Fix the bug"
orx run --pipeline plan_only "Design the architecture"

# Список доступных pipelines
orx pipelines list

# Показать детали pipeline
orx pipelines show standard

# Создать новый pipeline (интерактивно или из YAML)
orx pipelines create my_pipeline --from-yaml my_pipeline.yaml

# Редактировать pipeline
orx pipelines edit my_pipeline

# Удалить pipeline
orx pipelines delete my_pipeline
```

### 5.2. CLI Implementation

```python
# src/orx/cli.py additions

pipelines_app = typer.Typer(name="pipelines", help="Manage pipeline presets")

@pipelines_app.command("list")
def pipelines_list():
    """List available pipelines."""
    registry = PipelineRegistry.load()
    for p in registry.pipelines:
        typer.echo(f"  {p.id:20} {p.name}")

@pipelines_app.command("show")
def pipelines_show(pipeline_id: str):
    """Show pipeline details."""
    registry = PipelineRegistry.load()
    pipeline = registry.get(pipeline_id)
    typer.echo(f"Pipeline: {pipeline.name}")
    typer.echo(f"Description: {pipeline.description}")
    typer.echo("\nNodes:")
    for node in pipeline.nodes:
        typer.echo(f"  [{node.type.value}] {node.id}")
        typer.echo(f"      inputs:  {', '.join(node.inputs)}")
        typer.echo(f"      outputs: {', '.join(node.outputs)}")

@app.command()
def run(
    task: str,
    pipeline: Annotated[str | None, typer.Option("--pipeline", "-p")] = None,
    ...
):
    """Run with optional pipeline selection."""
    pipeline_def = load_pipeline(pipeline or "standard")
    runner = PipelineRunner(config, pipeline_def, paths)
    runner.run(task)

app.add_typer(pipelines_app, name="pipelines")
```

### 5.3. Dashboard Pages

```
/pipelines                    # Список pipelines с возможностью выбора
/pipelines/new                # Создание нового pipeline (визуальный редактор)
/pipelines/{id}/edit          # Редактирование pipeline
/runs/new?pipeline={id}       # Запуск run с выбранным pipeline
```

### 5.4. Dashboard API

```python
# src/orx/dashboard/handlers/api.py additions

@router.get("/api/pipelines")
async def list_pipelines(request: Request):
    """List available pipelines."""
    registry = PipelineRegistry.load()
    return {"pipelines": [p.to_dict() for p in registry.pipelines]}

@router.get("/api/pipelines/{pipeline_id}")
async def get_pipeline(request: Request, pipeline_id: str):
    """Get pipeline details."""
    registry = PipelineRegistry.load()
    return registry.get(pipeline_id).to_dict()

@router.post("/api/pipelines")
async def create_pipeline(request: Request, payload: PipelineCreateRequest):
    """Create a new pipeline."""
    registry = PipelineRegistry.load()
    pipeline = PipelineDefinition(**payload.dict())
    registry.add(pipeline)
    registry.save()
    return {"id": pipeline.id}

@router.put("/api/pipelines/{pipeline_id}")
async def update_pipeline(request: Request, pipeline_id: str, payload: PipelineUpdateRequest):
    """Update an existing pipeline."""
    ...

@router.delete("/api/pipelines/{pipeline_id}")
async def delete_pipeline(request: Request, pipeline_id: str):
    """Delete a pipeline."""
    ...

@router.get("/api/context-blocks")
async def list_context_blocks(request: Request):
    """List available context blocks for pipeline builder."""
    return {
        "blocks": [
            {"key": "task", "label": "Task Description", "auto": False},
            {"key": "plan", "label": "Plan", "auto": False, "produced_by": "plan"},
            {"key": "spec", "label": "Specification", "auto": False, "produced_by": "spec"},
            {"key": "backlog", "label": "Backlog", "auto": False, "produced_by": "decompose"},
            {"key": "repo_map", "label": "Repository Map", "auto": True},
            {"key": "tooling_snapshot", "label": "Tooling Config", "auto": True},
            {"key": "agents_context", "label": "AGENTS.md Context", "auto": True},
            {"key": "architecture", "label": "Architecture Overview", "auto": True},
            {"key": "error_logs", "label": "Error Logs", "auto": True, "runtime": True},
            {"key": "patch_diff", "label": "Git Diff", "auto": True, "runtime": True},
            {"key": "current_item", "label": "Current Work Item", "auto": True, "runtime": True},
            {"key": "file_snippets", "label": "File Snippets", "auto": True, "runtime": True},
        ]
    }
```

---

## 6. File Structure

```
src/orx/
├── pipeline/                    # NEW: Pipeline engine
│   ├── __init__.py
│   ├── definition.py            # PipelineDefinition, NodeDefinition models
│   ├── registry.py              # PipelineRegistry (load/save pipelines)
│   ├── runner.py                # PipelineRunner (main executor)
│   ├── artifacts.py             # ArtifactStore
│   ├── context_builder.py       # ContextBuilder
│   └── executors/
│       ├── __init__.py
│       ├── base.py              # NodeExecutor protocol
│       ├── llm_text.py          # LLMTextNodeExecutor
│       ├── llm_apply.py         # LLMApplyNodeExecutor
│       ├── map.py               # MapNodeExecutor
│       ├── gate.py              # GateNodeExecutor
│       └── custom.py            # CustomNodeExecutor
│
├── config.py                    # Extended with PipelineConfig
├── cli.py                       # Extended with pipelines subcommand
│
├── dashboard/
│   ├── handlers/
│   │   └── api.py               # Extended with /api/pipelines/*
│   └── templates/
│       └── pages/
│           ├── pipelines.html   # NEW: Pipeline list page
│           └── pipeline_edit.html  # NEW: Pipeline editor

~/.orx/                          # User config directory
└── pipelines/                   # User-defined pipelines
    ├── my_custom.yaml
    └── fast_debug.yaml
```

---

## 7. Implementation Plan

### Phase 1: Core Models & Storage (3-4 дня)
- [ ] `src/orx/pipeline/definition.py` — Pydantic models
- [ ] `src/orx/pipeline/artifacts.py` — ArtifactStore
- [ ] `src/orx/pipeline/registry.py` — Load/save pipelines
- [ ] Unit tests for models and storage

### Phase 2: Node Executors (4-5 дней)
- [ ] `src/orx/pipeline/executors/base.py` — Protocol
- [ ] `src/orx/pipeline/executors/llm_text.py` — Port from TextOutputStage
- [ ] `src/orx/pipeline/executors/llm_apply.py` — Port from ApplyStage
- [ ] `src/orx/pipeline/executors/map.py` — Port from _run_implement_loop
- [ ] `src/orx/pipeline/executors/gate.py` — Port from VerifyStage
- [ ] `src/orx/pipeline/context_builder.py` — Context assembly
- [ ] Unit tests for executors

### Phase 3: PipelineRunner (3-4 дня)
- [ ] `src/orx/pipeline/runner.py` — Main executor
- [ ] Integration with existing metrics, events, state
- [ ] Resume/checkpoint support
- [ ] Integration tests

### Phase 4: CLI Integration (2-3 дня)
- [ ] `orx pipelines` subcommand group
- [ ] `orx run --pipeline` option
- [ ] Default pipelines YAML (standard, fast_fix, plan_only)
- [ ] CLI tests

### Phase 5: Dashboard Integration (3-4 дня)
- [ ] `/api/pipelines/*` endpoints
- [ ] `/pipelines` list page
- [ ] `/pipelines/{id}/edit` editor page (basic)
- [ ] Context block selector UI
- [ ] Dashboard E2E tests

### Phase 6: Polish & Migration (2-3 дня)
- [ ] Remove old Runner FSM code
- [ ] Update documentation
- [ ] Migration guide
- [ ] Performance testing

**Total Estimate**: 17-23 дня

---

## 8. Acceptance Criteria

1. **Текущий pipeline воспроизводится**: `orx run --pipeline standard` даёт тот же результат, что и старый FSM.
2. **Новые pipelines работают**: `orx run --pipeline fast_fix` корректно пропускает plan/spec.
3. **CLI управление**: `orx pipelines list/show/create/delete` работают.
4. **Dashboard UI**: Можно выбрать pipeline при создании run, есть страница pipelines.
5. **Context blocks**: Каждая нода получает только заявленные inputs.
6. **Параллелизм**: `concurrency > 1` в MapNode корректно работает (если worktree isolation готова).
7. **Resume**: Pipeline можно возобновить с последней успешной ноды.
8. **Метрики**: Per-node метрики записываются в stages.jsonl.

---

## 9. Configuration Constants

```python
# src/orx/pipeline/constants.py

# Maximum number of pipelines per user
MAX_USER_PIPELINES = 50

# Maximum nodes per pipeline
MAX_NODES_PER_PIPELINE = 20

# Maximum concurrency for MapNode
MAX_MAP_CONCURRENCY = 8

# Default timeout per node (seconds)
DEFAULT_NODE_TIMEOUT = 600

# Maximum retries per node
MAX_NODE_RETRIES = 3

# Context block size limits (bytes)
MAX_CONTEXT_BLOCK_SIZE = 500_000  # 500KB

# Auto-extracted contexts
AUTO_EXTRACT_CONTEXTS = ["repo_map", "tooling_snapshot", "agents_context", "architecture", "verify_commands"]
```

---

## 10. Open Questions

1. **Worktree isolation for parallel**: Нужны ли отдельные worktrees для каждого параллельного item?
2. **Pipeline versioning**: Нужно ли версионировать pipelines для воспроизводимости?
3. **Context caching**: Кэшировать ли auto-extracted contexts между runs?
4. **Custom nodes**: Как определять Python callable для custom nodes?
