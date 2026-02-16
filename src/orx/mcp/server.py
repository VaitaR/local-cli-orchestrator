"""orx MCP Server — tools, resources, and prompts for orchestrator control.

Run via:
    python -m orx.mcp              # stdio transport (default)
    python -m orx.mcp --transport sse --port 8422   # SSE transport
"""

from __future__ import annotations

import json
import os
from enum import Enum
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Server instance
# ---------------------------------------------------------------------------

_MCP_INSTRUCTIONS = (
    "You are connected to the orx orchestrator MCP server. "
    "First call prompt `operator_guide` to load usage rules, then use "
    "`start_run` and poll with `get_run_status` until completion."
)

mcp = FastMCP("orx", instructions=_MCP_INSTRUCTIONS)


# ---------------------------------------------------------------------------
# Helpers — resolve project root and create stores lazily
# ---------------------------------------------------------------------------

def _resolve_project_root() -> Path:
    """Resolve the project root from env or cwd."""
    env = os.environ.get("ORX_PROJECT_ROOT")
    if env:
        return Path(env).resolve()
    return Path.cwd().resolve()


def _runs_dir() -> Path:
    return _resolve_project_root() / "runs"


def _read_json(path: Path) -> dict[str, Any]:
    """Safely read a JSON file, returning {} on error."""
    try:
        return json.loads(path.read_text())  # type: ignore[no-any-return]
    except (OSError, json.JSONDecodeError):
        return {}


def _tail(path: Path, lines: int = 50) -> str:
    """Read last *lines* from a text file."""
    if not path.exists():
        return ""
    try:
        all_lines = path.read_text().splitlines()
        return "\n".join(all_lines[-lines:])
    except OSError:
        return ""


def _read_operator_guide(max_chars: int | None = None) -> str:
    """Read operator guide from SKILLS.md (or legacy SKILSS.md)."""
    root = _resolve_project_root()
    for filename in ("SKILLS.md", "SKILSS.md"):
        path = root / filename
        if not path.exists():
            continue
        try:
            content = path.read_text()
        except OSError:
            continue

        if max_chars is not None and len(content) > max_chars:
            return content[:max_chars] + "\n\n... (truncated)"
        return content

    return (
        "# orx MCP Operator Guide\n\n"
        "Guide file not found in project root. "
        "Use start_run(task=..., pipeline=...) and poll get_run_status(run_id) "
        "until status is success, failed, or paused."
    )


# ---------------------------------------------------------------------------
# Enums for typed tool arguments
# ---------------------------------------------------------------------------

class PipelineChoice(str, Enum):
    standard = "standard"
    fast_fix = "fast_fix"
    plan_only = "plan_only"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def start_run(
    task: str,
    pipeline: PipelineChoice = PipelineChoice.standard,
    base_branch: str | None = None,
) -> dict[str, str]:
    """Start a new orx run asynchronously.

    Returns immediately with run_id and queued status.
    Poll get_run_status() to track progress.
    """
    import subprocess

    root = _resolve_project_root()
    cmd = ["orx", "run", "--dir", str(root), "--pipeline", pipeline.value]
    if base_branch:
        cmd.extend(["--base-branch", base_branch])
    cmd.append(task)

    proc = subprocess.Popen(
        cmd,
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        text=True,
    )

    # Try to capture run_id from early output (orx prints it quickly)
    run_id: str | None = None
    if proc.stdout:
        import select
        import sys

        # Wait up to 5s for first output line that contains a run id
        timeout = 5.0
        if sys.platform != "win32":
            import time

            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                ready, _, _ = select.select([proc.stdout], [], [], 0.5)
                if ready:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    # orx prints "Run ID: <id>" or similar
                    if "run" in line.lower() and "_" in line:
                        # Extract something that looks like a run id (YYYYMMDD_HHMMSS_hex)
                        for token in line.split():
                            if len(token) >= 20 and "_" in token:
                                run_id = token.strip().rstrip(".")
                                break
                    if run_id:
                        break

    return {
        "run_id": run_id or "pending",
        "status": "queued",
        "pid": str(proc.pid),
    }


@mcp.tool()
def get_run_status(run_id: str) -> dict[str, Any]:
    """Get current status of a run. Context-light: returns metadata only, not logs."""
    run_dir = _runs_dir() / run_id
    if not run_dir.is_dir():
        return {"error": f"Run {run_id} not found"}

    state = _read_json(run_dir / "state.json")
    meta = _read_json(run_dir / "meta.json")

    current_stage = state.get("current_stage", "unknown")
    stage_statuses = state.get("stage_statuses", {})

    # Determine overall status
    status = "running"
    if current_stage == "done":
        status = "success"
    elif current_stage == "failed":
        status = "failed"
    elif current_stage == "paused":
        status = "paused"

    # Check if process is alive
    pid = state.get("pid")
    if isinstance(pid, int) and pid > 0:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            if status == "running":
                status = "failed"

    # Extract last error
    last_error = None
    evidence = state.get("last_failure_evidence", {})
    if evidence:
        last_error = str(evidence.get("message", ""))[:500]

    # Metrics summary from observability
    metrics: dict[str, Any] = {}
    obs_meta = _read_json(run_dir / "observability" / "metadata.json")
    if obs_meta:
        metrics["tokens"] = obs_meta.get("tokens", {})
        metrics["duration_ms"] = obs_meta.get("duration_ms")

    return {
        "run_id": run_id,
        "status": status,
        "stage": current_stage,
        "engine": meta.get("engine"),
        "base_branch": meta.get("base_branch"),
        "stages": {k: v.get("status", "unknown") for k, v in stage_statuses.items()},
        "last_error": last_error,
        "metrics": metrics,
        "paused_after_node": state.get("paused_after_node"),
    }


@mcp.tool()
def resume_run(run_id: str) -> dict[str, str]:
    """Resume a paused or interrupted run."""
    import subprocess

    root = _resolve_project_root()
    run_dir = _runs_dir() / run_id
    if not run_dir.is_dir():
        return {"error": f"Run {run_id} not found"}

    state = _read_json(run_dir / "state.json")
    current_stage = state.get("current_stage", "")
    if current_stage in ("done", "failed"):
        return {"error": f"Cannot resume: run is {current_stage}"}

    cmd = ["orx", "resume", run_id, "--dir", str(root)]
    subprocess.Popen(
        cmd,
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    return {"run_id": run_id, "status": "resumed"}


@mcp.tool()
def cancel_run(run_id: str) -> dict[str, Any]:
    """Cancel a running orx run by sending SIGTERM to its process."""
    import signal

    run_dir = _runs_dir() / run_id
    if not run_dir.is_dir():
        return {"success": False, "error": f"Run {run_id} not found"}

    state = _read_json(run_dir / "state.json")
    pid = state.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return {"success": False, "error": "No active PID for this run"}

    try:
        os.killpg(pid, signal.SIGTERM)
        return {"success": True, "run_id": run_id, "signal": "SIGTERM"}
    except ProcessLookupError:
        return {"success": False, "error": "Process already exited"}
    except OSError as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def list_runs(limit: int = 5) -> list[dict[str, Any]]:
    """List recent runs with compact summaries."""
    runs_root = _runs_dir()
    if not runs_root.exists():
        return []

    entries: list[tuple[str, Path]] = []
    for entry in runs_root.iterdir():
        if entry.is_dir() and not entry.name.startswith("."):
            entries.append((entry.name, entry))

    # Sort by name descending (names are timestamp-prefixed)
    entries.sort(key=lambda x: x[0], reverse=True)
    entries = entries[:limit]

    results: list[dict[str, Any]] = []
    for run_id, run_dir in entries:
        state = _read_json(run_dir / "state.json")
        current_stage = state.get("current_stage", "unknown")

        status = "running"
        if current_stage == "done":
            status = "success"
        elif current_stage == "failed":
            status = "failed"
        elif current_stage == "paused":
            status = "paused"

        # Task preview
        task_preview = ""
        task_path = run_dir / "context" / "task.md"
        if task_path.exists():
            try:
                content = task_path.read_text()
                task_preview = content[:120].replace("\n", " ")
            except OSError:
                pass

        results.append({
            "run_id": run_id,
            "status": status,
            "stage": current_stage,
            "task_preview": task_preview,
        })

    return results


@mcp.tool()
def list_pipelines() -> list[dict[str, Any]]:
    """List available pipeline definitions."""
    from orx.pipeline.registry import PipelineRegistry

    registry = PipelineRegistry.load()
    result: list[dict[str, Any]] = []
    for p in registry.pipelines:
        result.append({
            "id": p.id,
            "name": p.name,
            "description": p.description or "",
            "builtin": p.builtin,
            "nodes": [
                {"id": n.id, "type": n.type.value}
                for n in p.nodes
            ],
        })
    return result


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

@mcp.resource("orx://guide/skills")
def get_operator_guide() -> str:
    """Operator guide used by MCP agents to understand workflow."""
    return _read_operator_guide()


@mcp.resource("orx://runs/{run_id}/state")
def get_run_state(run_id: str) -> str:
    """Full state.json for a run."""
    run_dir = _runs_dir() / run_id
    state_path = run_dir / "state.json"
    if not state_path.exists():
        return json.dumps({"error": f"State not found for {run_id}"})
    return state_path.read_text()


@mcp.resource("orx://runs/{run_id}/diff")
def get_run_diff(run_id: str) -> str:
    """Current patch.diff for a run."""
    diff_path = _runs_dir() / run_id / "artifacts" / "patch.diff"
    if not diff_path.exists():
        return "# No diff available"
    return diff_path.read_text()


@mcp.resource("orx://runs/{run_id}/logs/{log_name}")
def get_run_log(run_id: str, log_name: str) -> str:
    """Last 50 lines of a specific log file (e.g., pytest.log, ruff.log)."""
    # Sanitize log_name to prevent path traversal
    safe_name = Path(log_name).name
    log_path = _runs_dir() / run_id / "logs" / safe_name
    return _tail(log_path, lines=50)


@mcp.resource("orx://runs/{run_id}/artifacts/{filename}")
def get_artifact(run_id: str, filename: str) -> str:
    """Read an artifact file (plan.md, spec.md, review.md, etc.)."""
    safe_name = Path(filename).name
    # Check in artifacts/ first, then context/
    for subdir in ("artifacts", "context"):
        path = _runs_dir() / run_id / subdir / safe_name
        if path.exists():
            return path.read_text()
    return f"# Artifact '{filename}' not found"


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

@mcp.prompt()
def operator_guide() -> str:
    """Load full operator guide for this MCP server."""
    return _read_operator_guide()


@mcp.prompt()
def new_task() -> str:
    """Prepare context for starting a new orx task.

    Loads available pipelines and a summary of the project structure
    to help formulate the task description.
    """
    root = _resolve_project_root()

    sections: list[str] = []
    sections.append("# orx — New Task Context\n")

    # Available pipelines
    sections.append("## Available Pipelines\n")
    try:
        from orx.pipeline.registry import PipelineRegistry
        registry = PipelineRegistry.load()
        for p in registry.pipelines:
            nodes_str = " → ".join(n.id for n in p.nodes)
            sections.append(f"- **{p.id}**: {p.description or p.name} ({nodes_str})")
    except Exception:
        sections.append("- standard, fast_fix, plan_only")

    sections.append("")

    # AGENTS.md summary (if exists)
    agents_path = root / "AGENTS.md"
    if agents_path.exists():
        content = agents_path.read_text()
        # Include first 2000 chars as summary
        if len(content) > 2000:
            content = content[:2000] + "\n\n... (truncated)"
        sections.append("## Project Rules (from AGENTS.md)\n")
        sections.append(content)
        sections.append("")

    # SKILLS.md summary (operator workflow for MCP clients)
    guide = _read_operator_guide(max_chars=1500)
    if guide.strip():
        sections.append("## Operator Workflow (from SKILLS.md)\n")
        sections.append(guide)
        sections.append("")

    # Git info
    import subprocess
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if branch.returncode == 0:
            sections.append(f"## Current Branch: `{branch.stdout.strip()}`\n")
    except Exception:
        pass

    sections.append(
        "## Next Step\n"
        "Describe the task and call `start_run(task=..., pipeline=...)` to begin."
    )

    return "\n".join(sections)


@mcp.prompt()
def debug_run(run_id: str) -> str:
    """Prepare context for debugging a failed run.

    Loads status, last error, and log tails.
    """
    run_dir = _runs_dir() / run_id

    sections: list[str] = []
    sections.append(f"# Debugging Run: {run_id}\n")

    if not run_dir.is_dir():
        sections.append(f"Run directory not found: {run_dir}")
        return "\n".join(sections)

    # Status
    state = _read_json(run_dir / "state.json")
    sections.append(f"**Stage:** {state.get('current_stage', 'unknown')}")
    sections.append(f"**Iteration:** {state.get('current_iteration', 0)}")

    evidence = state.get("last_failure_evidence", {})
    if evidence:
        sections.append("\n## Failure Evidence\n")
        for key, val in evidence.items():
            sections.append(f"**{key}:** {str(val)[:500]}")

    # Log tails
    logs_dir = run_dir / "logs"
    if logs_dir.exists():
        sections.append("\n## Log Tails\n")
        for log_file in sorted(logs_dir.iterdir()):
            if log_file.suffix == ".log":
                tail_content = _tail(log_file, lines=30)
                if tail_content.strip():
                    sections.append(f"### {log_file.name}\n```\n{tail_content}\n```\n")

    # Diff preview
    diff_path = run_dir / "artifacts" / "patch.diff"
    if diff_path.exists():
        diff_content = diff_path.read_text()
        if len(diff_content) > 3000:
            diff_content = diff_content[:3000] + "\n... (truncated)"
        sections.append(f"\n## Diff Preview\n```diff\n{diff_content}\n```\n")

    sections.append(
        "\n## Next Steps\n"
        "- If fixable: `start_run(task='fix: ...', pipeline='fast_fix')`\n"
        "- If needs re-plan: `start_run(task='...', pipeline='standard')`"
    )

    return "\n".join(sections)
