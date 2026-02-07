"""Runtime manager for observability v2 capture."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from orx.executors.base import ExecResult
from orx.observability.correlation import (
    CorrelationIds,
    StepCounter,
    new_correlation,
    new_id,
)
from orx.observability.schema import Correlation, ObsEvent
from orx.observability.tty import TTYRecorder
from orx.observability.writer import EventWriter, MetadataWriter

if TYPE_CHECKING:
    from orx.infra.command import (
        CommandExecutionEnd,
        CommandExecutionStart,
        CommandObserver,
    )
    from orx.paths import RunPaths

logger = structlog.get_logger()


@dataclass(slots=True)
class _PendingCommand:
    call_id: str
    span_id: str
    ts: str


class _RuntimeCommandObserver:
    """Command observer adapter that emits proc.exec events."""

    def __init__(self, runtime: RunObservability) -> None:
        self._runtime = runtime
        self._pending: dict[str, _PendingCommand] = {}

    def on_command_start(self, event: CommandExecutionStart) -> None:
        corr = new_correlation()
        self._pending[event.command_id] = _PendingCommand(
            call_id=corr.call_id,
            span_id=corr.span_id,
            ts=event.ts,
        )
        self._runtime.tty_note(
            f"$ {' '.join(event.command)}"
            + (f"  # cwd={event.cwd}" if event.cwd else "")
        )
        self._runtime.emit(
            source="os",
            event_type="proc.exec.start",
            payload={
                "command_id": event.command_id,
                "cmd": event.command,
                "cwd": str(event.cwd) if event.cwd else None,
                "env_allowlist": event.env_allowlist,
                "context": event.context,
            },
            correlation=Correlation(
                call_id=corr.call_id,
                span_id=corr.span_id,
            ),
        )

    def on_command_end(self, event: CommandExecutionEnd) -> None:
        pending = self._pending.pop(event.command_id, None)
        correlation = Correlation()
        if pending:
            correlation = Correlation(call_id=pending.call_id, span_id=pending.span_id)
        self._runtime.tty_note(
            f"rc={event.returncode} ({event.duration_ms}ms) $ {' '.join(event.command)}"
        )

        self._runtime.emit(
            source="os",
            event_type="proc.exec.end",
            payload={
                "command_id": event.command_id,
                "returncode": event.returncode,
                "duration_ms": event.duration_ms,
                "stdout_path": str(event.stdout_path) if event.stdout_path else None,
                "stderr_path": str(event.stderr_path) if event.stderr_path else None,
                "error": event.error,
            },
            correlation=correlation,
        )


class RunObservability:
    """Observability runtime for a single run."""

    def __init__(
        self,
        *,
        paths: RunPaths,
        step_counter: StepCounter,
        max_payload_kb: int = 512,
        tty_enabled: bool = True,
        network_mode: str = "full_payload",
    ) -> None:
        self.paths = paths
        self.run_id = paths.run_id
        self.step_counter = step_counter
        self.max_payload_bytes = max_payload_kb * 1024
        self._events = EventWriter(paths.observability_events_jsonl)
        self._metadata = MetadataWriter(paths.observability_metadata_json)
        self._tty_enabled = tty_enabled
        self._tty = TTYRecorder(paths.observability_tty_dir / "session.cast")
        self._network_mode = network_mode
        self._session_id: str | None = None
        self._run_started = False
        self._patch_checksums: dict[str, str] = {}

    @property
    def session_id(self) -> str | None:
        """Current runtime session id."""
        return self._session_id

    def make_command_observer(self) -> CommandObserver:
        """Return command observer for CommandRunner hooks."""
        return _RuntimeCommandObserver(self)

    def start(self, *, engine: str | None = None, base_branch: str | None = None) -> str:
        """Start observability session and initialize bundle metadata."""
        self._session_id = new_id()
        metadata = {
            "schema_version": "2.0",
            "run_id": self.run_id,
            "session_id": self._session_id,
            "started_at": datetime.now(tz=UTC).isoformat(),
            "engine": engine,
            "base_branch": base_branch,
            "storage_mode": "local_only",
            "privacy_mode": "private_full",
        }
        self._metadata.write(metadata)

        if self._tty_enabled:
            _, reason = self._tty.start()
            self.emit(
                source="tty",
                event_type="tty.segment.start",
                payload={
                    "segment": 1,
                    "path": str(self._tty.output_path),
                    "mode": self._tty.capture_mode,
                },
            )
            if reason:
                self.warning("tty_unavailable", detail=reason)
        self.emit(
            source="network",
            event_type="network.capture.config",
            payload={"mode": self._network_mode, "strategy": "llm-correlated-metadata"},
        )
        return self._session_id

    def finish(self, *, status: str, error: str | None = None) -> None:
        """Finalize session metadata and close tty segment."""
        if self._tty_enabled:
            self.emit(
                source="tty",
                event_type="tty.segment.end",
                payload={"segment": 1, "path": str(self._tty.output_path)},
            )
        existing = self._metadata.read()
        existing.update(
            {
                "schema_version": "2.0",
                "run_id": self.run_id,
                "session_id": self._session_id,
                "finished_at": datetime.now(tz=UTC).isoformat(),
                "status": status,
                "error": error,
            }
        )
        self._metadata.write(existing)

    def emit(
        self,
        *,
        source: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        correlation: Correlation | None = None,
    ) -> None:
        """Emit one canonical observability event."""
        raw_payload = payload or {}
        bounded_payload = self._bound_payload(raw_payload)
        event = ObsEvent(
            event_id=new_id(),
            run_id=self.run_id,
            source=source,
            event_type=event_type,
            step_id=self.step_counter.next(),
            payload=bounded_payload,
            correlation=correlation or Correlation(),
        )
        self._events.write(event)

    def run_start(self) -> None:
        """Emit run.start event once."""
        if self._run_started:
            return
        self._run_started = True
        self.tty_note(f"run.start run_id={self.run_id}")
        self.emit(source="supervisor", event_type="run.start", payload={"run_id": self.run_id})

    def run_end(self, *, status: str, error: str | None = None) -> None:
        """Emit run.end event."""
        self.tty_note(f"run.end status={status}")
        self.emit(
            source="supervisor",
            event_type="run.end",
            payload={"status": status, "error": error},
        )

    def stage_start(
        self,
        *,
        stage: str,
        item_id: str | None = None,
        attempt: int = 1,
        executor: str | None = None,
        model: str | None = None,
    ) -> None:
        """Emit stage.start event."""
        self.tty_note(
            f"stage.start {stage} attempt={attempt}"
            + (f" item={item_id}" if item_id else "")
        )
        self.emit(
            source="supervisor",
            event_type="stage.start",
            payload={
                "stage": stage,
                "item_id": item_id,
                "attempt": attempt,
                "executor": executor,
                "model": model,
            },
        )

    def stage_end(
        self,
        *,
        stage: str,
        status: str,
        message: str | None = None,
        item_id: str | None = None,
        attempt: int = 1,
        duration_ms: int | None = None,
    ) -> None:
        """Emit stage.end event."""
        self.tty_note(
            f"stage.end {stage} status={status} attempt={attempt}"
            + (f" item={item_id}" if item_id else "")
        )
        self.emit(
            source="supervisor",
            event_type="stage.end",
            payload={
                "stage": stage,
                "item_id": item_id,
                "attempt": attempt,
                "status": status,
                "message": message,
                "duration_ms": duration_ms,
            },
        )

    def llm_request(
        self,
        *,
        stage: str,
        prompt_path: Path,
        item_id: str | None = None,
        attempt: int = 1,
        model: str | None = None,
        executor: str | None = None,
    ) -> CorrelationIds:
        """Capture and emit llm.request event."""
        started = time.perf_counter()
        corr = new_correlation()
        content = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
        request_file = self._write_llm_blob(prefix="request", call_id=corr.call_id, content=content)
        self.emit(
            source="gateway",
            event_type="llm.request",
            correlation=Correlation(call_id=corr.call_id, span_id=corr.span_id),
            payload={
                "stage": stage,
                "item_id": item_id,
                "attempt": attempt,
                "model": model,
                "prompt_path": str(prompt_path),
                "full_context_path": str(request_file),
                "chars": len(content),
                "duration_ms": int((time.perf_counter() - started) * 1000),
            },
        )
        self.emit(
            source="network",
            event_type="network.request",
            correlation=Correlation(call_id=corr.call_id, span_id=corr.span_id),
            payload=self._network_request_payload(
                stage=stage,
                item_id=item_id,
                attempt=attempt,
                model=model,
                executor=executor,
                request_file=request_file,
            ),
        )
        self.tty_note(
            f"llm.request stage={stage} model={model or '-'} executor={executor or '-'}"
        )
        return corr

    def llm_response(
        self,
        *,
        stage: str,
        result: ExecResult,
        out_path: Path | None,
        item_id: str | None = None,
        attempt: int = 1,
        correlation_ids: CorrelationIds | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """Capture and emit llm.response event."""
        content = ""
        if out_path and out_path.exists():
            content = out_path.read_text(encoding="utf-8")
        elif result.stdout_path.exists():
            content = result.read_stdout()

        corr = correlation_ids or new_correlation()
        response_file = self._write_llm_blob(prefix="response", call_id=corr.call_id, content=content)
        tokens = result.get_token_usage() or {"input": 0, "output": 0, "total": 0}
        tokens["tool_calls"] = result.get_tool_calls()
        extra = result.extra if isinstance(result.extra, dict) else {}
        resolved_executor = self._resolve_executor_name(result=result)
        cost_usd = extra.get("cost_usd")
        if cost_usd is None:
            cost_usd = extra.get("total_cost_usd")

        payload = {
            "stage": stage,
            "item_id": item_id,
            "attempt": attempt,
            "returncode": result.returncode,
            "success": not result.failed,
            "error_message": result.error_message,
            "duration_ms": duration_ms,
            "tokens": tokens,
            "model": result.get_model_used(),
            "response_path": str(response_file),
            "chars": len(content),
            "executor": resolved_executor,
            "cost_usd": cost_usd,
            "total_cost_usd": extra.get("total_cost_usd"),
            "duration_api_ms": extra.get("duration_api_ms"),
            "num_turns": extra.get("num_turns"),
            "session_id": extra.get("session_id"),
            "result_type": extra.get("type"),
            "result_subtype": extra.get("subtype"),
        }

        self.emit(
            source="gateway",
            event_type="llm.response",
            payload=payload,
            correlation=Correlation(call_id=corr.call_id, span_id=corr.span_id, parent_id=corr.parent_id),
        )
        self.emit(
            source="network",
            event_type="network.response",
            correlation=Correlation(
                call_id=corr.call_id,
                span_id=corr.span_id,
                parent_id=corr.parent_id,
            ),
            payload=self._network_response_payload(
                stage=stage,
                item_id=item_id,
                attempt=attempt,
                model=result.get_model_used(),
                executor=resolved_executor,
                response_file=response_file,
                result=result,
                duration_ms=duration_ms,
            ),
        )
        self.tty_note(
            f"llm.response stage={stage} rc={result.returncode} "
            f"dur_ms={duration_ms if duration_ms is not None else '-'} "
            f"model={result.get_model_used() or '-'}"
        )

    def fs_patch(
        self,
        *,
        stage: str,
        patch_path: Path,
        item_id: str | None = None,
        attempt: int = 1,
    ) -> None:
        """Emit fs.patch event with checksum references."""
        scope_key = f"{stage}:{item_id or 'run'}"
        before_checksum = self._patch_checksums.get(scope_key)
        after_checksum = None
        patch_copy_path = self.paths.observability_patches_dir / f"{stage}_{item_id or 'run'}_a{attempt}.diff"
        patch_copy_path.parent.mkdir(parents=True, exist_ok=True)

        if patch_path.exists():
            content = patch_path.read_bytes()
            after_checksum = hashlib.sha256(content).hexdigest()
            patch_copy_path.write_bytes(content)
            self._patch_checksums[scope_key] = after_checksum

        self.emit(
            source="fs",
            event_type="fs.patch",
            payload={
                "stage": stage,
                "item_id": item_id,
                "attempt": attempt,
                "patch_path": str(patch_copy_path),
                "before_checksum": before_checksum,
                "after_checksum": after_checksum,
            },
        )

    def gate_approval(
        self,
        *,
        gate: str,
        status: str,
        item_id: str | None = None,
        attempt: int = 1,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Emit gate.approval event."""
        self.emit(
            source="supervisor",
            event_type="gate.approval",
            payload={
                "gate": gate,
                "status": status,
                "item_id": item_id,
                "attempt": attempt,
                "details": details or {},
            },
        )

    def warning(self, code: str, *, detail: str | None = None) -> None:
        """Emit non-fatal observability warning event."""
        self.emit(
            source="supervisor",
            event_type="observability.warning",
            payload={"code": code, "detail": detail},
        )

    def tty_note(self, message: str) -> None:
        """Append one synthetic TTY note frame (best effort)."""
        if not self._tty_enabled:
            return
        self._tty.note(message)

    def _write_llm_blob(self, *, prefix: str, call_id: str, content: str) -> Path:
        """Materialize llm request/response payload content to file."""
        path = self.paths.observability_llm_dir / f"{prefix}_{call_id}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def _bound_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Ensure payload stays within configured size bounds."""
        raw = json.dumps(payload, ensure_ascii=True)
        if len(raw.encode("utf-8")) <= self.max_payload_bytes:
            return payload

        truncated = {
            "truncated": True,
            "original_size": len(raw.encode("utf-8")),
            "payload_preview": raw[: self.max_payload_bytes],
        }
        logger.warning(
            "Observability payload truncated",
            run_id=self.run_id,
            original_size=len(raw.encode("utf-8")),
            max_payload_bytes=self.max_payload_bytes,
        )
        return truncated

    def _resolve_executor_name(self, *, result: ExecResult) -> str | None:
        invocation = result.invocation
        if invocation and invocation.model_info:
            executor = invocation.model_info.get("executor")
            if isinstance(executor, str) and executor:
                return executor
        return None

    def _infer_network_destination(
        self, *, executor: str | None, model: str | None
    ) -> tuple[str | None, str | None]:
        if executor:
            mapping = {
                "codex": ("openai", "api.openai.com"),
                "gemini": ("google", "generativelanguage.googleapis.com"),
                "claude_code": ("anthropic", "api.anthropic.com"),
                "copilot": ("github", "api.githubcopilot.com"),
                "cursor": ("cursor", "api.cursor.com"),
            }
            if executor in mapping:
                return mapping[executor]

        model_lower = (model or "").lower()
        if "gpt" in model_lower or "o1" in model_lower or "o3" in model_lower:
            return ("openai", "api.openai.com")
        if "gemini" in model_lower:
            return ("google", "generativelanguage.googleapis.com")
        if "claude" in model_lower or "haiku" in model_lower or "sonnet" in model_lower:
            return ("anthropic", "api.anthropic.com")
        return (None, None)

    def _network_request_payload(
        self,
        *,
        stage: str,
        item_id: str | None,
        attempt: int,
        model: str | None,
        executor: str | None,
        request_file: Path,
    ) -> dict[str, Any]:
        provider, host = self._infer_network_destination(executor=executor, model=model)
        payload: dict[str, Any] = {
            "stage": stage,
            "item_id": item_id,
            "attempt": attempt,
            "executor": executor,
            "model": model,
            "provider": provider,
            "destination_host": host,
            "mode": self._network_mode,
        }
        if self._network_mode == "full_payload":
            payload["request_path"] = str(request_file)
        return payload

    def _network_response_payload(
        self,
        *,
        stage: str,
        item_id: str | None,
        attempt: int,
        model: str | None,
        executor: str | None,
        response_file: Path,
        result: ExecResult,
        duration_ms: int | None,
    ) -> dict[str, Any]:
        provider, host = self._infer_network_destination(executor=executor, model=model)
        extra = result.extra if isinstance(result.extra, dict) else {}
        payload: dict[str, Any] = {
            "stage": stage,
            "item_id": item_id,
            "attempt": attempt,
            "executor": executor,
            "model": model,
            "provider": provider,
            "destination_host": host,
            "mode": self._network_mode,
            "returncode": result.returncode,
            "duration_ms": duration_ms,
            "duration_api_ms": extra.get("duration_api_ms"),
            "cost_usd": extra.get("cost_usd")
            if extra.get("cost_usd") is not None
            else extra.get("total_cost_usd"),
            "total_cost_usd": extra.get("total_cost_usd"),
            "num_turns": extra.get("num_turns"),
            "session_id": extra.get("session_id"),
        }
        if self._network_mode == "full_payload":
            payload["response_path"] = str(response_file)
        return payload
