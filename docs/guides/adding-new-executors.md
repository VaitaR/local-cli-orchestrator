# Adding New CLI Executor Integrations

This guide documents the complete process for adding a new CLI executor (agentic coding tool) to ORX orchestrator.

## Overview

ORX supports multiple CLI-based coding assistants as "executors". Each executor wraps a specific CLI tool and provides:
- **Text mode**: Read-only access for planning/review stages
- **Apply mode**: Full tool access for implementation stages
- **Model selection**: Per-stage model configuration
- **Output parsing**: Structured result extraction

## Prerequisites

Before adding a new executor, ensure you have:
1. The CLI tool installed and accessible
2. Documentation for the CLI's flags and options
3. Understanding of the CLI's output format

## Step-by-Step Guide

### Step 1: Study the CLI Interface

Document these key aspects:

| Aspect | Questions to Answer |
|--------|---------------------|
| **Non-interactive mode** | What flag enables non-interactive execution? (`-p`, `--prompt`, `exec`, etc.) |
| **Model selection** | What flag selects the model? (`--model`, `-m`) |
| **Output format** | Does it support JSON output? What's the structure? |
| **Permission control** | How to allow/deny tool access? |
| **Working directory** | How to specify allowed paths? |
| **Prompt input** | File path, stdin, or command argument? |

Create a specification document in `docs/specs/<cli>-integration.md`.

### Step 2: Create the Executor Class

Create `src/orx/executors/<cli_name>.py`:

```python
"""<CLI Name> executor implementation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from orx.exceptions import ExecutorError
from orx.executors.base import BaseExecutor, ExecResult, LogPaths, ResolvedInvocation
from orx.infra.command import CommandRunner

if TYPE_CHECKING:
    from orx.config import ModelSelector

logger = structlog.get_logger()


class MyCliExecutor(BaseExecutor):
    """Executor adapter for MyCLI.

    Document:
    - How it wraps the CLI
    - Key differences from other executors
    - Available models
    - Text vs Apply mode behavior
    """

    def __init__(
        self,
        *,
        cmd: CommandRunner,
        binary: str = "mycli",
        extra_args: list[str] | None = None,
        dry_run: bool = False,
        default_model: str | None = None,
        # Add CLI-specific options here
    ) -> None:
        super().__init__(
            binary=binary,
            extra_args=extra_args,
            dry_run=dry_run,
            default_model=default_model,
        )
        self.cmd = cmd
        # Initialize CLI-specific options

    @property
    def name(self) -> str:
        return "mycli"

    def _build_command(
        self,
        *,
        prompt_path: Path,
        cwd: Path,
        model_selector: ModelSelector | None = None,
        out_path: Path | None = None,
        text_only: bool = False,
    ) -> tuple[list[str], dict[str, Any]]:
        """Build the CLI command.

        Returns:
            Tuple of (command list, resolved model info).
        """
        resolved = self._resolve_model(model_selector)

        cmd = [self.binary]

        # Add non-interactive flag
        # cmd.append("-p")  # or whatever flag

        # Add model selection
        if resolved["model"]:
            cmd.extend(["--model", resolved["model"]])

        # Add permission controls based on mode
        if text_only:
            # Read-only mode
            pass
        else:
            # Full access mode
            pass

        # Add working directory
        cmd.extend(["--add-dir", str(cwd)])

        # Add prompt (varies by CLI)
        # Option A: File path
        # cmd.extend(["--prompt-file", str(prompt_path)])
        # Option B: @ reference
        # cmd.extend(["--prompt", f"@{prompt_path}"])
        # Option C: Read content
        # cmd.append(prompt_path.read_text())

        return cmd, resolved

    def resolve_invocation(
        self,
        *,
        prompt_path: Path,
        cwd: Path,
        logs: LogPaths,
        out_path: Path | None = None,
        model_selector: ModelSelector | None = None,
        text_only: bool = False,
    ) -> ResolvedInvocation:
        """Resolve command invocation without executing."""
        cmd, resolved = self._build_command(
            prompt_path=prompt_path,
            cwd=cwd,
            model_selector=model_selector,
            out_path=out_path,
            text_only=text_only,
        )

        return ResolvedInvocation(
            cmd=cmd,
            artifacts={
                "stdout": logs.stdout,
                "stderr": logs.stderr,
            },
            model_info={
                "executor": self.name,
                "model": resolved["model"],
                "text_only": text_only,
            },
        )

    def _parse_output(self, stdout_path: Path) -> tuple[str, dict[str, Any]]:
        """Parse CLI output.

        Returns:
            Tuple of (text content, extra metadata).
        """
        if not stdout_path.exists():
            return "", {}

        content = stdout_path.read_text().strip()

        # Parse based on CLI output format
        # JSON example:
        try:
            data = json.loads(content)
            return data.get("result", ""), data
        except json.JSONDecodeError:
            return content, {}

    def run_text(
        self,
        *,
        cwd: Path,
        prompt_path: Path,
        logs: LogPaths,
        out_path: Path,
        model_selector: ModelSelector | None = None,
    ) -> ExecResult:
        """Run in text-only mode (read-only tools)."""
        cmd, resolved = self._build_command(
            prompt_path=prompt_path,
            cwd=cwd,
            model_selector=model_selector,
            text_only=True,
        )

        if self.dry_run:
            out_path.write_text("(dry run)")
            return ExecResult(
                returncode=0,
                stdout_path=logs.stdout,
                stderr_path=logs.stderr,
                success=True,
            )

        result = self.cmd.run(
            cmd,
            cwd=cwd,
            stdout_path=logs.stdout,
            stderr_path=logs.stderr,
            timeout=600,
        )

        text, extra = self._parse_output(logs.stdout)
        out_path.write_text(text)
        result.extra = extra

        return result

    def run_apply(
        self,
        *,
        cwd: Path,
        prompt_path: Path,
        logs: LogPaths,
        model_selector: ModelSelector | None = None,
    ) -> ExecResult:
        """Run in apply mode (full tool access)."""
        cmd, resolved = self._build_command(
            prompt_path=prompt_path,
            cwd=cwd,
            model_selector=model_selector,
            text_only=False,
        )

        if self.dry_run:
            return ExecResult(
                returncode=0,
                stdout_path=logs.stdout,
                stderr_path=logs.stderr,
                success=True,
            )

        result = self.cmd.run(
            cmd,
            cwd=cwd,
            stdout_path=logs.stdout,
            stderr_path=logs.stderr,
            timeout=1800,
        )

        text, extra = self._parse_output(logs.stdout)
        result.extra = extra

        return result
```

### Step 3: Add Model Definitions

Edit `src/orx/executors/models.py`:

```python
# Add after other model dicts (CODEX_MODELS, GEMINI_MODELS, etc.)

MYCLI_MODELS: dict[str, ModelInfo] = {
    "model-a": ModelInfo(
        id="model-a",
        name="Model A",
        engine="mycli",
        description="Description here",
        capabilities=ModelCapabilities(
            supports_reasoning=False,  # or True
            supports_thinking_budget=False,  # or True
            context_window=200000,
            tier=1,  # 1=best, 2=standard, 3=fallback
        ),
    ),
    # Add more models...
}


def discover_mycli_models(binary: str = "mycli") -> list[ModelInfo] | None:
    """Attempt to discover available models via CLI."""
    output = _run_cli_command([binary, "--version"])
    if output is None:
        return None
    logger.debug("MyCLI discovery: using static model definitions")
    return None
```

Then update these functions in `models.py`:

1. **`get_available_models()`** - Add elif branch:
```python
elif engine == "mycli":
    discovered = discover_mycli_models(binary or "mycli")
    models = discovered or list(MYCLI_MODELS.values())
```

2. **`get_model_info()`** - Add model search:
```python
# Check MyCLI models
if engine is None or engine == "mycli":
    if model_id in MYCLI_MODELS:
        return MYCLI_MODELS[model_id]
    for model in MYCLI_MODELS.values():
        if model_id in model.aliases:
            return model
```

3. **`get_default_model()`** - Add default:
```python
elif engine == "mycli":
    return "model-a"  # Your default model
```

### Step 4: Update Configuration Schema

Edit `src/orx/config.py`:

1. **Add to EngineType enum:**
```python
class EngineType(str, Enum):
    CODEX = "codex"
    GEMINI = "gemini"
    COPILOT = "copilot"
    CLAUDE_CODE = "claude_code"
    CURSOR = "cursor"
    MYCLI = "mycli"  # Add this
    FAKE = "fake"
```

2. **Add to ExecutorsConfig:**
```python
class ExecutorsConfig(BaseModel):
    codex: ExecutorConfig = Field(default_factory=ExecutorConfig)
    gemini: ExecutorConfig = Field(default_factory=ExecutorConfig)
    copilot: ExecutorConfig = Field(default_factory=ExecutorConfig)
    claude_code: ExecutorConfig = Field(default_factory=ExecutorConfig)
    mycli: ExecutorConfig = Field(default_factory=ExecutorConfig)  # Add this
```

3. **Add binary default in EngineConfig.__init__:**
```python
defaults = {
    EngineType.CODEX: "codex",
    EngineType.GEMINI: "gemini",
    EngineType.COPILOT: "copilot",
    EngineType.CLAUDE_CODE: "claude",
    EngineType.CURSOR: "agent",
    EngineType.MYCLI: "mycli",  # Add this
    EngineType.FAKE: "",
}
```

### Step 5: Update Router

Edit `src/orx/executors/router.py`:

1. **Add import:**
```python
from orx.executors.mycli import MyCliExecutor
```

2. **Add to `_create_executors()`:**
```python
# MyCLI executor
mycli_cfg = self.executors_config.mycli
self._executors[EngineType.MYCLI] = MyCliExecutor(
    cmd=self.cmd,
    binary=mycli_cfg.bin or "mycli",
    dry_run=self.dry_run,
    default_model=mycli_cfg.default.model,
)
```

3. **Update `resolve_model_selector()`:**

In Priority 2 section:
```python
elif executor_type == EngineType.MYCLI:
    exec_cfg = self.executors_config.mycli
```

In Priority 4 section:
```python
elif selector is None and executor_type == EngineType.MYCLI:
    mycli_default = self.executors_config.mycli.default
    if mycli_default.model:
        selector = ModelSelector(model=mycli_default.model)
```

### Step 6: Update Dashboard API

Edit `src/orx/dashboard/handlers/api.py`:

In `get_available_engines()`, add elif branch:
```python
elif e == EngineType.MYCLI:
    engine_data["stage_models"] = _effective_stage_models(
        orx_config.executors.mycli, default_config.executors.mycli
    )
```

### Step 7: Add Unit Tests

Edit `tests/unit/test_model_routing.py`:

```python
class TestMyCliCommandBuilder:
    """Test MyCLI command building with model selection."""

    @pytest.fixture
    def cmd(self) -> CommandRunner:
        return CommandRunner(dry_run=True)

    @pytest.fixture
    def prompt_file(self, tmp_path: Path) -> Path:
        prompt = tmp_path / "prompt.md"
        prompt.write_text("Test prompt")
        return prompt

    def test_mycli_command_with_model(
        self, cmd: CommandRunner, prompt_file: Path
    ) -> None:
        from orx.executors.mycli import MyCliExecutor

        executor = MyCliExecutor(cmd=cmd, dry_run=True)
        selector = ModelSelector(model="model-a")

        invocation = executor.resolve_invocation(
            prompt_path=prompt_file,
            cwd=Path("/tmp/workspace"),
            logs=LogPaths(
                stdout=Path("/tmp/stdout.log"),
                stderr=Path("/tmp/stderr.log"),
            ),
            model_selector=selector,
        )

        assert "--model" in invocation.cmd
        assert "model-a" in invocation.cmd

    def test_mycli_text_mode(
        self, cmd: CommandRunner, prompt_file: Path
    ) -> None:
        # Test read-only mode behavior
        pass

    def test_mycli_apply_mode(
        self, cmd: CommandRunner, prompt_file: Path
    ) -> None:
        # Test full access mode behavior
        pass
```

### Step 8: Run Tests

```bash
# Run all tests
make test

# Run specific executor tests
python -m pytest tests/unit/test_model_routing.py -v -k "MyCli"

# Verify integration
python -c "
from orx.config import EngineType, OrxConfig
from orx.executors.models import get_available_models

print('Engine types:', [e.value for e in EngineType])
print('Models:', [m.id for m in get_available_models('mycli')])
"
```

### Step 9: Test with Real CLI

```bash
# Quick CLI test
mycli --version
mycli -p "Say hello" --output-format json

# Integration test
python -c "
from pathlib import Path
from orx.executors.mycli import MyCliExecutor
from orx.executors.base import LogPaths
from orx.config import ModelSelector
from orx.infra.command import CommandRunner

cmd = CommandRunner(dry_run=True)
executor = MyCliExecutor(cmd=cmd, dry_run=True)

invocation = executor.resolve_invocation(
    prompt_path=Path('test.md'),
    cwd=Path('.'),
    logs=LogPaths(stdout=Path('out.log'), stderr=Path('err.log')),
    model_selector=ModelSelector(model='model-a'),
)
print('Command:', ' '.join(invocation.cmd[:8]))
"
```

---

## Checklist

### Files to Create
- [ ] `src/orx/executors/<cli_name>.py` - Executor class
- [ ] `docs/specs/<cli>-integration.md` - Integration spec

### Files to Modify
- [ ] `src/orx/executors/models.py`
  - [ ] Add `<CLI>_MODELS` dict
  - [ ] Add `discover_<cli>_models()` function
  - [ ] Update `get_available_models()`
  - [ ] Update `get_model_info()`
  - [ ] Update `get_default_model()`
- [ ] `src/orx/config.py`
  - [ ] Add to `EngineType` enum
  - [ ] Add to `ExecutorsConfig`
  - [ ] Add binary default
- [ ] `src/orx/executors/router.py`
  - [ ] Add import
  - [ ] Add to `_create_executors()`
  - [ ] Update `resolve_model_selector()` (2 places)
- [ ] `src/orx/dashboard/handlers/api.py`
  - [ ] Add to engines list
- [ ] `tests/unit/test_model_routing.py`
  - [ ] Add test class

### Tests to Run
- [ ] `make test` - All tests pass
- [ ] CLI integration test works
- [ ] Dashboard shows new engine

---

## Common Patterns

### Prompt Input Methods

| CLI | Method |
|-----|--------|
| Codex | `--prompt-file <path>` |
| Copilot | `--prompt @<path>` |
| Claude Code | Positional argument with content |
| Cursor | Positional argument with content |
| Gemini | `@<path>` in prompt |

### Permission Control

| CLI | Full Access | Read-Only |
|-----|-------------|-----------|
| Codex | `--full-auto` | `--sandbox read-only` |
| Copilot | `--allow-all-tools` | `--deny-tool write` |
| Claude Code | `--dangerously-skip-permissions` | `--tools "Read,Grep,..."` |
| Cursor | `--force` | (no flag - default) |
| Gemini | `--yolo` | N/A (default) |

### Output Formats

| CLI | JSON Output | Parsing |
|-----|-------------|---------|
| Codex | `--json` | Event stream |
| Copilot | N/A | Text output |
| Claude Code | `--output-format json` | `{"result": "...", ...}` |
| Cursor | `--output-format json` | `{"result": "...", ...}` |
| Gemini | `--output-format json` | `{"markdown": "...", ...}` |

---

## Troubleshooting

### "Model not found" errors
- Check `MYCLI_MODELS` keys match what CLI expects
- Verify `get_model_info()` searches your models dict

### Tests fail with import errors
- Ensure executor class is exported from module
- Check circular import issues

### CLI returns non-zero exit code
- Add debug logging to see actual command
- Check CLI version compatibility
- Verify permissions flags are correct

### Dashboard doesn't show engine
- Clear browser cache (sessionStorage)
- Check API handler has elif branch
- Restart dashboard server
