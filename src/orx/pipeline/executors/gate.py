"""Gate node executor for running quality gates."""

from __future__ import annotations

import time
from typing import Any

import structlog

from orx.gates.base import Gate
from orx.pipeline.definition import NodeDefinition
from orx.pipeline.executors.base import ExecutionContext, NodeResult

logger = structlog.get_logger()


class GateNodeExecutor:
    """Executor for gate nodes that run quality checks.

    Runs configured gates (ruff, pytest, etc.) and reports results.
    """

    def execute(
        self,
        node: NodeDefinition,
        context: dict[str, Any],  # noqa: ARG002
        exec_ctx: ExecutionContext,
    ) -> NodeResult:
        """Execute gate node.

        Args:
            node: Node definition.
            context: Input context (unused for gates).
            exec_ctx: Execution context.

        Returns:
            NodeResult indicating pass/fail.
        """
        log = logger.bind(node_id=node.id, node_type=node.type.value)
        log.info("Executing gate node")

        # Get gates to run
        gate_names = node.config.gates
        if not gate_names:
            log.info("No gates configured, skipping")
            return NodeResult(success=True)

        # Filter available gates
        gates_to_run = [g for g in exec_ctx.gates if g.name in gate_names]

        if not gates_to_run:
            log.warning("No matching gates found", requested=gate_names)
            return NodeResult(success=True)

        # Run each gate
        metrics: dict[str, Any] = {"gates": []}

        for gate in gates_to_run:
            log.info("Running gate", gate=gate.name)

            start_time = time.perf_counter()
            log_path = exec_ctx.paths.log_path(f"gate_{gate.name}_{node.id}")

            result = gate.run(cwd=exec_ctx.workspace.worktree_path, log_path=log_path)

            duration_ms = int((time.perf_counter() - start_time) * 1000)

            gate_metric = {
                "name": gate.name,
                "passed": result.ok,
                "duration_ms": duration_ms,
                "returncode": result.returncode,
            }
            metrics["gates"].append(gate_metric)

            if result.failed:
                # Try auto-fix for ruff
                if gate.name == "ruff" and exec_ctx.config.run.auto_fix_ruff:
                    log.info("Attempting auto-fix for ruff", gate=gate.name)
                    fix_result = self._try_ruff_fix(gate, exec_ctx, node.id)
                    if fix_result:
                        log.info("Auto-fix applied, retrying gate", gate=gate.name)
                        # Retry gate after fix
                        retry_result = gate.run(
                            cwd=exec_ctx.workspace.worktree_path,
                            log_path=exec_ctx.paths.log_path(
                                f"gate_{gate.name}_{node.id}_retry"
                            ),
                        )
                        if retry_result.ok:
                            log.info("Gate passed after auto-fix", gate=gate.name)
                            gate_metric["passed"] = True
                            gate_metric["auto_fixed"] = True
                            continue
                        else:
                            log.warning(
                                "Gate still failed after auto-fix",
                                gate=gate.name,
                                returncode=retry_result.returncode,
                            )

                log.error(
                    "Gate failed",
                    gate=gate.name,
                    returncode=result.returncode,
                    message=result.message,
                )

                return NodeResult(
                    success=False,
                    error=f"Gate {gate.name} failed: {result.message}",
                    metrics=metrics,
                )

            log.info("Gate passed", gate=gate.name, duration_ms=duration_ms)

        log.info("All gates passed")
        return NodeResult(success=True, metrics=metrics)

    def _try_ruff_fix(
        self,
        gate: Gate,
        exec_ctx: ExecutionContext,
        node_id: str,
    ) -> bool:
        """Try to auto-fix ruff issues.

        Args:
            gate: Ruff gate.
            exec_ctx: Execution context.
            node_id: Node ID for log naming.

        Returns:
            True if fix was attempted.
        """
        from orx.gates.ruff import RuffGate

        if not isinstance(gate, RuffGate):
            return False

        try:
            # Create fix gate with --fix flag
            fix_args = list(getattr(gate, "args", []) or ["check", "."])
            if "--fix" not in fix_args:
                fix_args.append("--fix")
            if "--unsafe-fixes" not in fix_args:
                fix_args.append("--unsafe-fixes")

            # Get CommandRunner from gate
            cmd = getattr(gate, "cmd", None)
            if not cmd:
                logger.warning("RuffGate missing CommandRunner, cannot auto-fix")
                return False

            fix_gate = RuffGate(
                cmd=cmd,
                command=getattr(gate, "command", "ruff"),
                args=fix_args,
                required=getattr(gate, "required", True),
            )

            log_path = exec_ctx.paths.log_path(f"gate_ruff_fix_{node_id}")
            fix_gate.run(cwd=exec_ctx.workspace.worktree_path, log_path=log_path)

            return True
        except Exception as e:
            logger.warning("Ruff auto-fix failed", error=str(e))
            return False
