# Cursor CLI Integration Specification

## Overview

This document specifies the integration of Cursor CLI (`agent`) into the ORX orchestrator as an executor engine.

## Cursor CLI Reference

### Installation

```bash
curl https://cursor.com/install -fsS | bash
```

Binary location: `~/.local/bin/agent`

### Authentication

Two methods supported:
1. **Browser login** (interactive): `agent login`
2. **API key** (headless): `export CURSOR_API_KEY=your_key` or `--api-key` flag

### Key Commands

| Command | Description |
|---------|-------------|
| `agent` | Start interactive session |
| `agent -p "prompt"` | Non-interactive (print) mode |
| `agent status` | Check authentication status |
| `agent ls` | List previous conversations |
| `agent resume` | Resume latest conversation |

### Non-Interactive Mode Flags

| Flag | Description |
|------|-------------|
| `-p, --print` | Non-interactive print mode (required for automation) |
| `--model "model"` | Select model (e.g., "sonnet-4.5", "gpt-5.2", "auto") |
| `--output-format` | Output format: `text`, `json`, `stream-json` |
| `--force` | Allow file modifications in print mode |
| `--api-key` | API key (alternative to env var) |

### Available Models (via Cursor Service)

| Model | Provider | Description |
|-------|----------|-------------|
| `auto` | Cursor | Auto-selects best model for task |
| `sonnet-4.5` | Anthropic | Claude Sonnet 4.5 - balanced |
| `opus-4.5` | Anthropic | Claude Opus 4.5 - most capable |
| `gpt-5.2` | OpenAI | GPT-5.2 |
| `gemini-3-pro` | Google | Gemini 3 Pro |
| `gemini-3-flash` | Google | Gemini 3 Flash - fast |
| `grok` | xAI | Grok Code |
| `composer-1` | Cursor | Cursor's own model |

### Output Formats

#### JSON Format (`--output-format json`)

Single JSON object on completion:

```json
{
  "type": "result",
  "subtype": "success",
  "is_error": false,
  "duration_ms": 1234,
  "duration_api_ms": 1234,
  "result": "<full assistant text>",
  "session_id": "<uuid>",
  "request_id": "<optional>"
}
```

#### Text Format (`--output-format text`)

Clean final answer only - ideal for simple scripts.

#### Stream JSON Format (`--output-format stream-json`)

NDJSON with events: `system`, `user`, `assistant`, `tool_call`, `result`.

## ORX Integration

### Executor Implementation

**File:** `src/orx/executors/cursor.py`

**Class:** `CursorExecutor`

### Command Building

#### Text Mode (Planning/Review)

```bash
agent -p --output-format json --model "sonnet-4.5" "prompt content"
```

- No `--force` flag (read-only)
- Used for: PLAN, SPEC, DECOMPOSE, REVIEW stages

#### Apply Mode (Implementation)

```bash
agent -p --output-format json --model "sonnet-4.5" --force "prompt content"
```

- Includes `--force` flag for file modifications
- Used for: IMPLEMENT, FIX stages

### Model Selection Priority

1. `stages.<stage>.model` (explicit stage override)
2. `executors.cursor.stage_models[stage]` (per-stage default)
3. `executors.cursor.default.model` (executor default)
4. `engine.model` (legacy global config)
5. CLI default (`auto`)

### Configuration

#### orx.yaml

```yaml
engine:
  type: cursor

executors:
  cursor:
    bin: agent  # Binary path (default: agent)
    default:
      model: sonnet-4.5  # Default model
      output_format: json
    stage_models:
      plan: auto
      implement: opus-4.5
      review: sonnet-4.5
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `CURSOR_API_KEY` | API key for headless authentication |

## Comparison with Other Executors

| Aspect | Cursor | Claude Code | Copilot | Codex |
|--------|--------|-------------|---------|-------|
| Binary | `agent` | `claude` | `copilot` | `codex` |
| Print mode | `-p` | `-p` | exec | `--prompt-file` |
| Model flag | `--model` | `--model` | `--model` | `--model` |
| JSON output | `--output-format json` | `--output-format json` | N/A | `--json` |
| Force mode | `--force` | `--dangerously-skip-permissions` | `--allow-all-tools` | `--full-auto` |
| Auth env | `CURSOR_API_KEY` | `ANTHROPIC_API_KEY` | GitHub OAuth | OpenAI API key |

## Security Considerations

1. **API Key Handling**: Use environment variable `CURSOR_API_KEY` rather than `--api-key` flag in scripts to avoid key exposure in process lists
2. **Force Mode**: Only use `--force` in sandboxed/trusted environments
3. **File Access**: In text mode (no `--force`), agent cannot modify files

## Testing

### Unit Tests

```bash
python -m pytest tests/unit/test_model_routing.py -v -k "Cursor"
```

### Integration Test

```bash
# Requires CURSOR_API_KEY set
agent -p --output-format json "Say hello in exactly 3 words"
```

Expected output:
```json
{
  "type": "result",
  "subtype": "success",
  "result": "Hello there, friend!",
  ...
}
```

## References

- [Cursor CLI Overview](https://cursor.com/docs/cli/overview)
- [Headless CLI Guide](https://cursor.com/docs/cli/headless)
- [Output Formats](https://cursor.com/docs/cli/reference/output-format)
- [Authentication](https://cursor.com/docs/cli/reference/authentication)
- [Models](https://cursor.com/docs/models)
