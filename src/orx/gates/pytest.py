"""Pytest testing gate."""

from __future__ import annotations

from pathlib import Path

import structlog

from orx.gates.base import BaseGate, GateResult
from orx.infra.command import CommandRunner

logger = structlog.get_logger()


class PytestGate(BaseGate):
    """Gate that runs pytest.

    Example:
        >>> gate = PytestGate(cmd=CommandRunner())
        >>> result = gate.run(
        ...     cwd=Path("/workspace"),
        ...     log_path=Path("/logs/pytest.log"),
        ... )
        >>> result.ok
        True
    """

    def __init__(
        self,
        *,
        cmd: CommandRunner,
        command: str = "pytest",
        args: list[str] | None = None,
        required: bool = True,
        verbose: bool = False,
    ) -> None:
        """Initialize the pytest gate.

        Args:
            cmd: CommandRunner instance.
            command: Path to the pytest binary.
            args: Additional arguments.
            required: Whether this gate is required to pass.
            verbose: If True, run with verbose output.
        """
        default_args = ["-q"]
        if verbose:
            default_args = ["-v"]
        super().__init__(
            command=command,
            args=args if args is not None else default_args,
            required=required,
        )
        self.cmd = cmd

    @property
    def name(self) -> str:
        """Name of the gate."""
        return "pytest"

    def run(self, *, cwd: Path, log_path: Path) -> GateResult:
        """Run pytest.

        Args:
            cwd: Working directory.
            log_path: Path to write log to.

        Returns:
            GateResult with pass/fail status.
        """
        log = logger.bind(gate=self.name, cwd=str(cwd))
        log.info("Running pytest gate")

        # Ensure log directory exists
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # Check if there are any tests to run
        # Look for test files
        test_files = list(cwd.glob("**/test_*.py")) + list(cwd.glob("**/*_test.py"))
        tests_dir = cwd / "tests"

        if not test_files and not tests_dir.exists():
            log.info("No tests found, skipping pytest")
            log_path.write_text("No tests found - skipping pytest\n")
            return self._create_result(
                ok=True,
                returncode=0,
                log_path=log_path,
                message="No tests found - skipped",
            )

        # Build command
        full_command = [self.command, *self.args]

        # Run pytest
        result = self.cmd.run(
            full_command,
            cwd=cwd,
            stdout_path=log_path,
            stderr_path=log_path.with_suffix(".stderr.log"),
        )

        # Merge stderr into main log if it exists
        stderr_path = log_path.with_suffix(".stderr.log")
        if stderr_path.exists():
            stderr_content = stderr_path.read_text()
            if stderr_content:
                with log_path.open("a") as f:
                    f.write("\n--- stderr ---\n")
                    f.write(stderr_content)
            stderr_path.unlink()

        # pytest exit codes:
        # 0: All tests passed
        # 1: Tests were collected and run but some failed
        # 2: Test execution was interrupted
        # 3: Internal error
        # 4: pytest command line usage error
        # 5: No tests were collected

        if result.returncode == 5:
            # No tests collected - treat as pass
            log.info("No tests collected by pytest")
            return self._create_result(
                ok=True,
                returncode=0,
                log_path=log_path,
                message="No tests collected - skipped",
            )

        ok = result.returncode == 0

        if ok:
            log.info("Pytest gate passed")
            message = "All tests passed"
        else:
            log.warning("Pytest gate failed", returncode=result.returncode)
            message = f"Tests failed (exit code {result.returncode})"

        return self._create_result(
            ok=ok,
            returncode=result.returncode,
            log_path=log_path,
            message=message,
        )
