"""Ruff linting gate."""

from __future__ import annotations

from pathlib import Path

import structlog

from orx.gates.base import BaseGate, GateResult
from orx.infra.command import CommandRunner

logger = structlog.get_logger()


class RuffGate(BaseGate):
    """Gate that runs ruff linting.

    Example:
        >>> gate = RuffGate(cmd=CommandRunner())
        >>> result = gate.run(
        ...     cwd=Path("/workspace"),
        ...     log_path=Path("/logs/ruff.log"),
        ... )
        >>> result.ok
        True
    """

    def __init__(
        self,
        *,
        cmd: CommandRunner,
        command: str = "ruff",
        args: list[str] | None = None,
        required: bool = True,
        fix: bool = False,
    ) -> None:
        """Initialize the ruff gate.

        Args:
            cmd: CommandRunner instance.
            command: Path to the ruff binary.
            args: Additional arguments.
            required: Whether this gate is required to pass.
            fix: If True, run with --fix to auto-fix issues.
        """
        default_args = ["check", "."]
        if fix:
            default_args.append("--fix")
        super().__init__(
            command=command,
            args=args if args is not None else default_args,
            required=required,
        )
        self.cmd = cmd
        self.fix = fix

    @property
    def name(self) -> str:
        """Name of the gate."""
        return "ruff"

    def run(self, *, cwd: Path, log_path: Path) -> GateResult:
        """Run ruff check.

        Args:
            cwd: Working directory.
            log_path: Path to write log to.

        Returns:
            GateResult with pass/fail status.
        """
        log = logger.bind(gate=self.name, cwd=str(cwd))
        log.info("Running ruff gate")

        # Ensure log directory exists
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # Build command
        full_command = [self.command, *self.args]

        # Run ruff
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

        ok = result.returncode == 0

        if ok:
            log.info("Ruff gate passed")
            message = "All ruff checks passed"
        else:
            log.warning("Ruff gate failed", returncode=result.returncode)
            message = f"Ruff found issues (exit code {result.returncode})"

        return self._create_result(
            ok=ok,
            returncode=result.returncode,
            log_path=log_path,
            message=message,
        )
