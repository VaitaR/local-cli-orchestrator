# Claude Code CLI Integration Specification

## Overview

Integration of Claude Code CLI (`claude`) as a new executor engine in ORX orchestrator.
Claude Code is Anthropic's official agentic coding assistant with native tool use.

**CLI Version**: 2.0.76+  
**Documentation**: https://code.claude.com/docs/en/cli-reference

---

## CLI Interface Summary

### Non-Interactive Mode (Print Mode)

```bash
claude -p "prompt text" [options]
claude -p --output-format json "prompt"
cat prompt.md | claude -p "process this"
```

### Key Flags for ORX Integration

| Flag | Purpose | ORX Usage |
|------|---------|-----------|
| `-p, --print` | Non-interactive mode, required for automation | Always used |
| `--output-format <format>` | Output: text, json, stream-json | Use `json` for structured parsing |
| `--model <model>` | Model selection (sonnet, opus, haiku, or full name) | Per-stage model selection |
| `--dangerously-skip-permissions` | Bypass all permission checks | Apply mode (sandbox only) |
| `--allowedTools <tools>` | Allow specific tools without prompting | Fine-grained tool control |
| `--disallowedTools <tools>` | Deny specific tools | Text-only mode |
| `--tools <tools>` | Restrict available tools | "Read,Grep,Glob" for text mode |
| `--add-dir <dirs>` | Additional directories for tool access | Working directory access |
| `--max-turns <n>` | Limit agentic turns | Safety limit |
| `--append-system-prompt <text>` | Add to system prompt | Stage-specific instructions |
| `--verbose` | Verbose logging | Debug mode |
| `--fallback-model <model>` | Auto-fallback on overload | Resilience |

### Available Models

| Alias | Full Name | Description |
|-------|-----------|-------------|
| `sonnet` | claude-sonnet-4-5-20250929 | Latest Sonnet (default) |
| `opus` | claude-opus-4-20250514 | Most capable, expensive |
| `haiku` | claude-haiku-4-5-20250929 | Fast, cost-effective |

**Note**: Claude Code also supports external providers via MCP. The user has GLM configured.

### Output Formats

**JSON output** (`--output-format json`):
```json
{
  "type": "result",
  "subtype": "success",
  "cost_usd": 0.0123,
  "duration_ms": 1234,
  "duration_api_ms": 1000,
  "is_error": false,
  "num_turns": 3,
  "result": "The actual response text...",
  "session_id": "uuid-here",
  "total_cost_usd": 0.05
}
```

**Error output**:
```json
{
  "type": "result", 
  "subtype": "error_max_turns",
  "is_error": true,
  "result": "Error message..."
}
```

---

## Implementation Plan

### 1. Files to Create

| File | Purpose |
|------|---------|
| `src/orx/executors/claude_code.py` | ClaudeCodeExecutor class |

### 2. Files to Modify

| File | Changes |
|------|---------|
| `src/orx/executors/models.py` | Add `CLAUDE_CODE_MODELS` dict + discovery function |
| `src/orx/config.py` | Add `CLAUDE_CODE` to `EngineType` enum, add to `ExecutorsConfig` |
| `src/orx/executors/router.py` | Import + create ClaudeCodeExecutor in `_create_executors()`, update `resolve_model_selector()` |
| `src/orx/dashboard/handlers/api.py` | Add CLAUDE_CODE to engines list with stage_models |
| `tests/unit/test_model_routing.py` | Add `TestClaudeCodeCommandBuilder` test class |

### 3. ClaudeCodeExecutor Design

```python
class ClaudeCodeExecutor(BaseExecutor):
    """Executor for Claude Code CLI.
    
    Modes:
    - Apply mode: --dangerously-skip-permissions (full tool access)
    - Text mode: --tools "Read,Grep,Glob,LS" (read-only tools)
    
    Output: Always use --output-format json for structured parsing.
    """
    
    def __init__(
        self,
        *,
        cmd: CommandRunner,
        binary: str = "claude",
        extra_args: list[str] | None = None,
        dry_run: bool = False,
        default_model: str | None = None,
        output_format: str = "json",
        max_turns: int | None = None,
        fallback_model: str | None = None,
    ) -> None: ...
    
    def _build_command(
        self,
        *,
        prompt_path: Path,
        cwd: Path,
        model_selector: ModelSelector | None = None,
        out_path: Path | None = None,
        text_only: bool = False,
    ) -> tuple[list[str], dict[str, Any]]: ...
```

### 4. Model Configuration

```python
CLAUDE_CODE_MODELS = {
    "sonnet": ModelInfo(
        id="sonnet",
        name="Claude Sonnet 4.5",
        engine="claude_code",
        description="Latest Sonnet - balanced performance",
        capabilities=ModelCapabilities(
            supports_thinking_budget=True,
            max_thinking_budget=32768,
            context_window=200000,
            tier=1,
        ),
    ),
    "opus": ModelInfo(
        id="opus",
        name="Claude Opus 4",
        engine="claude_code",
        description="Most capable Claude model",
        capabilities=ModelCapabilities(
            supports_thinking_budget=True,
            max_thinking_budget=65536,
            context_window=200000,
            tier=1,
        ),
    ),
    "haiku": ModelInfo(
        id="haiku",
        name="Claude Haiku 4.5",
        engine="claude_code",
        description="Fast and cost-effective",
        capabilities=ModelCapabilities(
            context_window=200000,
            tier=2,
        ),
    ),
}
```

### 5. Command Building Logic

**Apply mode** (IMPLEMENT, FIX stages):
```bash
claude -p \
  --output-format json \
  --model sonnet \
  --dangerously-skip-permissions \
  --add-dir /workspace \
  --max-turns 50 \
  "$(cat prompt.md)"
```

**Text mode** (PLAN, SPEC, REVIEW stages):
```bash
claude -p \
  --output-format json \
  --model sonnet \
  --tools "Read,Grep,Glob,LS,Bash(cat:*),Bash(head:*),Bash(tail:*)" \
  --add-dir /workspace \
  "$(cat prompt.md)"
```

### 6. Output Parsing

```python
def _parse_output(self, stdout_path: Path) -> tuple[str, dict[str, Any]]:
    """Parse JSON output from Claude Code CLI."""
    content = stdout_path.read_text().strip()
    
    try:
        data = json.loads(content)
        text = data.get("result", "")
        extra = {
            "cost_usd": data.get("cost_usd"),
            "duration_ms": data.get("duration_ms"),
            "num_turns": data.get("num_turns"),
            "session_id": data.get("session_id"),
            "is_error": data.get("is_error", False),
            "subtype": data.get("subtype"),
        }
        return text, extra
    except json.JSONDecodeError:
        # Fallback: treat as plain text
        return content, {}
```

### 7. Error Detection

```python
def _check_errors(self, result: ExecResult, extra: dict) -> None:
    """Check for Claude Code specific errors."""
    if extra.get("is_error"):
        subtype = extra.get("subtype", "unknown")
        if subtype == "error_max_turns":
            raise ExecutorError("Max turns exceeded")
        elif subtype == "error_rate_limit":
            # Transient error - can retry
            result.is_transient = True
        # ... other error types
```

---

## Verification Checklist

### Code Changes

- [ ] `src/orx/executors/claude_code.py` created with ClaudeCodeExecutor
- [ ] `CLAUDE_CODE_MODELS` added to `models.py`
- [ ] `discover_claude_code_models()` function added
- [ ] `get_available_models()` handles "claude_code" engine
- [ ] `get_model_info()` searches CLAUDE_CODE_MODELS
- [ ] `get_default_model()` returns "sonnet" for claude_code
- [ ] `EngineType.CLAUDE_CODE` added to enum
- [ ] `ExecutorsConfig.claude_code` field added
- [ ] Binary default "claude" added
- [ ] Router imports ClaudeCodeExecutor
- [ ] Router creates ClaudeCodeExecutor in `_create_executors()`
- [ ] `resolve_model_selector()` handles CLAUDE_CODE
- [ ] API handler adds CLAUDE_CODE to engines list

### Tests

- [ ] `TestClaudeCodeCommandBuilder` class added
- [ ] Test: command includes --model flag
- [ ] Test: apply mode uses --dangerously-skip-permissions
- [ ] Test: text mode restricts tools
- [ ] Test: output format is json
- [ ] Test: --add-dir includes working directory
- [ ] All existing tests still pass

### Integration

- [ ] `claude --version` returns valid version
- [ ] Quick test with `claude -p --output-format json "Say hello"`
- [ ] Full test with sample prompt file

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| `--dangerously-skip-permissions` is dangerous | Only use in sandboxed/trusted environments |
| Rate limiting | Use `--fallback-model` for resilience |
| Cost overruns | Use `--max-turns` to limit agent iterations |
| JSON parsing failures | Fallback to text mode parsing |

---

## External Provider Support (GLM)

User has GLM configured as external provider via MCP. This works transparently:
- MCP servers are configured in `~/.claude/mcp-config.json`
- Claude Code automatically routes to external providers when configured
- No special handling needed in executor - just pass model name

To use GLM models, user would configure in orx.yaml:
```yaml
engine:
  type: claude_code
  model: glm-xxx  # GLM model via MCP
```
