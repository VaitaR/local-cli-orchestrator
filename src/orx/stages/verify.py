"""Verify stage implementation."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from orx.gates.base import GateResult
from orx.stages.base import BaseStage, StageContext, StageResult

logger = structlog.get_logger()


@dataclass
class VerifyResult:
    """Result of verification.

    Attributes:
        passed: Whether all gates passed.
        gate_results: Results from each gate.
        ruff_failed: Whether ruff specifically failed.
        pytest_failed: Whether pytest specifically failed.
    """

    passed: bool
    gate_results: list[GateResult]
    ruff_failed: bool = False
    pytest_failed: bool = False


class VerifyStage(BaseStage):
    """Stage that runs quality gates.

    Runs configured gates (ruff, pytest, etc.) and reports results.
    """

    @property
    def name(self) -> str:
        """Name of the stage."""
        return "verify"

    def run_gates(self, ctx: StageContext) -> VerifyResult:
        """Run all configured gates.

        Args:
            ctx: Stage context.

        Returns:
            VerifyResult with gate outcomes.
        """
        log = logger.bind(stage=self.name, gate_count=len(ctx.gates))
        log.info("Running verification gates")

        results: list[GateResult] = []
        ruff_failed = False
        pytest_failed = False
        all_passed = True

        for gate in ctx.gates:
            gate_log = log.bind(gate=gate.name)
            gate_log.info("Running gate")

            log_path = ctx.paths.log_path(gate.name)
            result = gate.run(cwd=ctx.workspace.worktree_path, log_path=log_path)
            results.append(result)

            if result.failed:
                gate_log.warning("Gate failed", message=result.message)
                if gate.name == "ruff":
                    ruff_failed = True
                elif gate.name == "pytest":
                    pytest_failed = True

                # Check if gate is required
                if hasattr(gate, "required") and gate.required:
                    all_passed = False
            else:
                gate_log.info("Gate passed")

        return VerifyResult(
            passed=all_passed,
            gate_results=results,
            ruff_failed=ruff_failed,
            pytest_failed=pytest_failed,
        )

    def get_evidence(self, ctx: StageContext, verify_result: VerifyResult) -> dict:
        """Build evidence dict from verification results.

        Args:
            ctx: Stage context.
            verify_result: Results from verification.

        Returns:
            Evidence dictionary for fix prompts.
        """
        evidence: dict = {
            "ruff_failed": verify_result.ruff_failed,
            "pytest_failed": verify_result.pytest_failed,
        }

        # Get log tails
        if verify_result.ruff_failed:
            evidence["ruff_log"] = ctx.pack.get_log_tail("ruff", 50)

        if verify_result.pytest_failed:
            evidence["pytest_log"] = ctx.pack.get_log_tail("pytest", 50)

        # Get current diff
        diff = ctx.pack.read_patch_diff()
        if diff:
            # Truncate if too long
            if len(diff) > 5000:
                evidence["patch_diff"] = diff[:5000] + "\n... (truncated)"
            else:
                evidence["patch_diff"] = diff

        return evidence

    def execute(self, ctx: StageContext) -> StageResult:
        """Execute the verify stage.

        Args:
            ctx: Stage context.

        Returns:
            StageResult indicating success/failure.
        """
        log = logger.bind(stage=self.name)
        log.info("Executing verify stage")

        verify_result = self.run_gates(ctx)

        if verify_result.passed:
            log.info("All gates passed")
            return self._success(
                "All gates passed",
                data={"gate_results": [r.message for r in verify_result.gate_results]},
            )
        else:
            failed_gates = [r.message for r in verify_result.gate_results if r.failed]
            log.warning("Some gates failed", failed=failed_gates)

            evidence = self.get_evidence(ctx, verify_result)

            return self._failure(
                f"Gates failed: {', '.join(failed_gates)}",
                data={
                    "gate_results": [r.message for r in verify_result.gate_results],
                    "evidence": evidence,
                },
            )
