"""Docker build gate."""

from __future__ import annotations

from pathlib import Path

import structlog

from orx.gates.base import BaseGate, GateResult
from orx.infra.command import CommandRunner

logger = structlog.get_logger()


class DockerGate(BaseGate):
    """Gate that runs docker build.

    This is an optional gate that verifies the Docker image builds
    successfully.

    Example:
        >>> gate = DockerGate(cmd=CommandRunner())
        >>> result = gate.run(
        ...     cwd=Path("/workspace"),
        ...     log_path=Path("/logs/docker_build.log"),
        ... )
        >>> result.ok
        True
    """

    def __init__(
        self,
        *,
        cmd: CommandRunner,
        command: str = "docker",
        args: list[str] | None = None,
        required: bool = False,  # Usually optional
        dockerfile: str = "Dockerfile",
        image_tag: str = "orx-test:latest",
    ) -> None:
        """Initialize the docker gate.

        Args:
            cmd: CommandRunner instance.
            command: Path to the docker binary.
            args: Additional arguments.
            required: Whether this gate is required to pass.
            dockerfile: Name of the Dockerfile.
            image_tag: Tag for the built image.
        """
        super().__init__(
            command=command,
            args=args or [],
            required=required,
        )
        self.cmd = cmd
        self.dockerfile = dockerfile
        self.image_tag = image_tag

    @property
    def name(self) -> str:
        """Name of the gate."""
        return "docker"

    def render_command(self) -> str:
        """Render the full docker build command."""
        return (
            f"{self.command} build "
            f"-f {self.dockerfile} "
            f"-t {self.image_tag} ."
        )

    def run(self, *, cwd: Path, log_path: Path) -> GateResult:
        """Run docker build.

        Args:
            cwd: Working directory.
            log_path: Path to write log to.

        Returns:
            GateResult with pass/fail status.
        """
        log = logger.bind(gate=self.name, cwd=str(cwd))
        log.info("Running docker gate")

        # Ensure log directory exists
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # Check if Dockerfile exists
        dockerfile_path = cwd / self.dockerfile
        if not dockerfile_path.exists():
            log.info("No Dockerfile found, skipping docker build")
            log_path.write_text(
                f"No {self.dockerfile} found in {cwd} - skipping docker build\n"
            )
            return self._create_result(
                ok=True,
                returncode=0,
                log_path=log_path,
                message="No Dockerfile found - skipped",
            )

        # Build command
        full_command = [
            self.command,
            "build",
            "-t",
            self.image_tag,
            "-f",
            self.dockerfile,
            ".",
            *self.args,
        ]

        # Run docker build
        result = self.cmd.run(
            full_command,
            cwd=cwd,
            stdout_path=log_path,
            stderr_path=log_path.with_suffix(".stderr.log"),
        )

        # Merge stderr into main log
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
            log.info("Docker gate passed", image=self.image_tag)
            message = f"Docker build succeeded: {self.image_tag}"
        else:
            log.warning("Docker gate failed", returncode=result.returncode)
            message = f"Docker build failed (exit code {result.returncode})"

        return self._create_result(
            ok=ok,
            returncode=result.returncode,
            log_path=log_path,
            message=message,
        )
