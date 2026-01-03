"""Generic command gate for arbitrary commands."""

from __future__ import annotations

from pathlib import Path

import structlog

from orx.gates.base import BaseGate, GateResult
from orx.infra.command import CommandRunner

logger = structlog.get_logger()


class GenericGate(BaseGate):
    """Gate that runs an arbitrary command.

    This gate can be used for custom checks like helm-lint, e2e tests,
    or any other command-based validation.

    Example:
        >>> gate = GenericGate(
        ...     name="helm-lint",
        ...     cmd=CommandRunner(),
        ...     command="make",
        ...     args=["helm-lint"],
        ... )
        >>> result = gate.run(
        ...     cwd=Path("/workspace"),
        ...     log_path=Path("/logs/helm-lint.log"),
        ... )
        >>> result.ok
        True
    """

    def __init__(
        self,
        *,
        name: str,
        cmd: CommandRunner,
        command: str,
        args: list[str] | None = None,
        required: bool = True,
    ) -> None:
        """Initialize the generic gate.

        Args:
            name: Name of the gate (used in logs and evidence).
            cmd: CommandRunner instance.
            command: Command to execute.
            args: Arguments to pass to the command.
            required: Whether this gate is required to pass.
        """
        super().__init__(
            command=command,
            args=args if args is not None else [],
            required=required,
        )
        self._name = name
        self.cmd = cmd

    @property
    def name(self) -> str:
        """Name of the gate."""
        return self._name

    def run(self, *, cwd: Path, log_path: Path) -> GateResult:
        """Run the command.

        Args:
            cwd: Working directory.
            log_path: Path to write log to.

        Returns:
            GateResult with pass/fail status.
        """
        log = logger.bind(gate=self.name, cwd=str(cwd))
        log.info("Running generic gate", command=self.command, args=self.args)

        # Ensure log directory exists
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # Build command
        full_command = [self.command, *self.args]

        # Run command
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
            log.info("Generic gate passed")
            message = f"{self.name} check passed"
        else:
            log.warning("Generic gate failed", returncode=result.returncode)
            message = f"{self.name} check failed (exit code {result.returncode})"

        return self._create_result(
            ok=ok,
            returncode=result.returncode,
            log_path=log_path,
            message=message,
        )
