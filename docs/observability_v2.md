# Observability v2 Contract (Hard Cutover)

## Status
- Effective date: 2026-02-06
- Backward compatibility: **none**
- Legacy files not supported: `runs/<id>/events.jsonl(event=...)`, `metrics/run.json`, `metrics/stages.jsonl`

## Canonical Bundle Layout

```text
runs/<run_id>/observability/
  events.jsonl
  metadata.json
  tty/
    session.cast
  llm/
    request_<call_id>.txt
    response_<call_id>.txt
  patches/
    <stage>_<item>_a<attempt>.diff
  exports/
    redacted/
      events.redacted.jsonl
```

`runs/<run_id>/artifacts/patch.diff` remains mandatory and must be produced by `git diff`.

## Event Envelope (Required)

Each line in `events.jsonl` is a JSON object:

```json
{
  "schema_version": "2.0",
  "event_id": "hex-id",
  "ts": "2026-02-06T12:34:56.123456+00:00",
  "run_id": "20260206_123456_abcd1234",
  "source": "gateway|native|tty|os|fs|supervisor",
  "event_type": "llm.request",
  "step_id": 42,
  "correlation": {
    "call_id": "optional",
    "parent_id": "optional",
    "span_id": "optional"
  },
  "payload": {}
}
```

`step_id` must be strictly monotonic across run + resume.

## Canonical Event Types

- `run.start`
- `run.end`
- `stage.start`
- `stage.end`
- `llm.request`
- `llm.response`
- `proc.exec.start`
- `proc.exec.end`
- `fs.patch`
- `tty.segment.start`
- `tty.segment.end`
- `gate.approval`
- `observability.warning`

## Payload Minimums

- `llm.request`: `stage`, `prompt_path`, `full_context_path`, `chars`, optional `model`, `item_id`, `attempt`
- `llm.response`: `stage`, `returncode`, `success`, `tokens`, `response_path`, optional `duration_ms`, `item_id`, `attempt`
- `proc.exec.start`: `command_id`, `cmd`, `cwd`, `env_allowlist`
- `proc.exec.end`: `command_id`, `returncode`, `duration_ms`, `stdout_path`, `stderr_path`
- `fs.patch`: `stage`, `patch_path`, `before_checksum`, `after_checksum`, optional `item_id`, `attempt`

## Sensitivity Classification

- High: `llm.request.full_context_path`, `llm.response.response_path`, command env, logs
- Medium: file paths, command lines, patch payloads
- Low: stage names, event_type, durations, status

Local storage is `private_full`. External sharing must go through redacted export.

## Redaction Policy (Export)

- Redact common secret keys and values (`token`, `api_key`, `password`, bearer tokens, cloud keys)
- Preserve event envelope and correlation fields
- Output path: `observability/exports/redacted/events.redacted.jsonl`

## Capability Matrix (Current ORX Managed Executors)

- Codex/Gemini/Cursor/Copilot/Claude Code/Fake via ORX executor adapters:
  - LLM request/response events: yes (prompt/response materialized)
  - Process events: yes (through `CommandRunner` observer hooks)
  - Network payload capture: not yet implemented (`observability.warning`)

