"""Subprocess command runner with logging."""

from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import IO

import structlog

from orx.exceptions import CommandError

logger = structlog.get_logger()


@dataclass
class CommandResult:
    """Result of a command execution.

    Attributes:
        returncode: Exit code of the process.
        stdout_path: Path to captured stdout.
        stderr_path: Path to captured stderr.
        command: The command that was run.
        cwd: Working directory where command ran.
    """

    returncode: int
    stdout_path: Path | None
    stderr_path: Path | None
    command: list[str]
    cwd: Path | None


class CommandRunner:
    """Runs subprocess commands with consistent logging.

    All subprocess calls in orx should go through this class to ensure
    consistent logging and error handling.

    Example:
        >>> runner = CommandRunner()
        >>> result = runner.run(
        ...     ["echo", "hello"],
        ...     cwd=Path("/tmp"),
        ...     stdout_path=Path("/tmp/out.log"),
        ...     stderr_path=Path("/tmp/err.log"),
        ... )
        >>> result.returncode
        0
    """

    def __init__(self, dry_run: bool = False, heartbeat_interval: int = 30) -> None:
        """Initialize the command runner.

        Args:
            dry_run: If True, commands are logged but not executed.
            heartbeat_interval: Interval in seconds for heartbeat logging (0 to disable).
        """
        self.dry_run = dry_run
        self.heartbeat_interval = heartbeat_interval

    @staticmethod
    def _heartbeat_logger(log: structlog.BoundLogger, stop_event: threading.Event, interval: int) -> None:
        """Log heartbeat messages while a command is running.

        Args:
            log: Logger instance.
            stop_event: Event to signal when to stop.
            interval: Interval in seconds between heartbeats.
        """
        elapsed = 0
        while not stop_event.wait(timeout=interval):
            elapsed += interval
            log.info("Command still running", elapsed_seconds=elapsed)

    def run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        stdout_path: Path | None = None,
        stderr_path: Path | None = None,
        timeout: int | None = None,
        check: bool = False,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        """Run a command and capture output.

        Args:
            command: Command and arguments to run.
            cwd: Working directory for the command.
            stdout_path: Path to write stdout to.
            stderr_path: Path to write stderr to.
            timeout: Timeout in seconds.
            check: If True, raise on non-zero exit code.
            env: Environment variables (merged with current env).

        Returns:
            CommandResult with exit code and log paths.

        Raises:
            CommandError: If check=True and command fails.
        """
        log = logger.bind(command=command, cwd=str(cwd) if cwd else None)
        log.info("Running command")

        if self.dry_run:
            log.info("Dry run - skipping execution")
            return CommandResult(
                returncode=0,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                command=command,
                cwd=cwd,
            )

        stdout_handle: IO[bytes] | int | None = None
        stderr_handle: IO[bytes] | int | None = None

        try:
            if stdout_path:
                stdout_path.parent.mkdir(parents=True, exist_ok=True)
                stdout_handle = stdout_path.open("wb")
            else:
                stdout_handle = subprocess.DEVNULL

            if stderr_path:
                stderr_path.parent.mkdir(parents=True, exist_ok=True)
                stderr_handle = stderr_path.open("wb")
            else:
                stderr_handle = subprocess.DEVNULL

            import os

            full_env = os.environ.copy()
            if env:
                full_env.update(env)

            # Start heartbeat logging if enabled and timeout is long enough
            stop_heartbeat = threading.Event()
            heartbeat_thread = None
            if self.heartbeat_interval > 0 and (timeout is None or timeout > self.heartbeat_interval):
                heartbeat_thread = threading.Thread(
                    target=self._heartbeat_logger,
                    args=(log, stop_heartbeat, self.heartbeat_interval),
                    daemon=True,
                )
                heartbeat_thread.start()

            try:
                result = subprocess.run(
                    command,
                    cwd=cwd,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    timeout=timeout,
                    env=full_env,
                    check=False,
                )
            finally:
                # Stop heartbeat
                if heartbeat_thread:
                    stop_heartbeat.set()
                    heartbeat_thread.join(timeout=1)

            log.info("Command completed", returncode=result.returncode)

            if check and result.returncode != 0:
                msg = f"Command failed with exit code {result.returncode}: {' '.join(command)}"
                raise CommandError(
                    msg,
                    command=command,
                    returncode=result.returncode,
                    cwd=cwd,
                )

            return CommandResult(
                returncode=result.returncode,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                command=command,
                cwd=cwd,
            )

        except subprocess.TimeoutExpired as e:
            log.error("Command timed out", timeout=timeout)
            msg = f"Command timed out after {timeout}s: {' '.join(command)}"
            raise CommandError(msg, command=command, cwd=cwd) from e

        except FileNotFoundError as e:
            log.error("Command not found", command=command[0])
            msg = f"Command not found: {command[0]}"
            raise CommandError(msg, command=command, cwd=cwd) from e

        finally:
            if stdout_handle and stdout_handle != subprocess.DEVNULL:
                stdout_handle.close()  # type: ignore[union-attr]
            if stderr_handle and stderr_handle != subprocess.DEVNULL:
                stderr_handle.close()  # type: ignore[union-attr]

    def run_capture(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        timeout: int | None = None,
        check: bool = False,
        env: dict[str, str] | None = None,
    ) -> tuple[int, str, str]:
        """Run a command and capture output as strings.

        This is useful for commands where you need the output immediately
        rather than written to files.

        Args:
            command: Command and arguments to run.
            cwd: Working directory for the command.
            timeout: Timeout in seconds.
            check: If True, raise on non-zero exit code.
            env: Environment variables.

        Returns:
            Tuple of (returncode, stdout, stderr).

        Raises:
            CommandError: If check=True and command fails.
        """
        log = logger.bind(command=command, cwd=str(cwd) if cwd else None)
        log.debug("Running command (capture mode)")

        if self.dry_run:
            log.info("Dry run - skipping execution")
            return (0, "", "")

        try:
            import os

            full_env = os.environ.copy()
            if env:
                full_env.update(env)

            result = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                timeout=timeout,
                env=full_env,
                check=False,
            )

            stdout = result.stdout.decode("utf-8", errors="replace")
            stderr = result.stderr.decode("utf-8", errors="replace")

            log.debug("Command completed", returncode=result.returncode)

            if check and result.returncode != 0:
                msg = f"Command failed with exit code {result.returncode}: {' '.join(command)}"
                raise CommandError(
                    msg,
                    command=command,
                    returncode=result.returncode,
                    cwd=cwd,
                )

            return (result.returncode, stdout, stderr)

        except subprocess.TimeoutExpired as e:
            log.error("Command timed out", timeout=timeout)
            msg = f"Command timed out after {timeout}s: {' '.join(command)}"
            raise CommandError(msg, command=command, cwd=cwd) from e

        except FileNotFoundError as e:
            log.error("Command not found", command=command[0])
            msg = f"Command not found: {command[0]}"
            raise CommandError(msg, command=command, cwd=cwd) from e

    def run_git(
        self,
        args: list[str],
        *,
        cwd: Path,
        check: bool = True,
    ) -> tuple[int, str, str]:
        """Run a git command.

        Convenience method for running git commands.

        Args:
            args: Git subcommand and arguments.
            cwd: Working directory (must be in a git repo).
            check: If True, raise on non-zero exit code.

        Returns:
            Tuple of (returncode, stdout, stderr).
        """
        return self.run_capture(["git", *args], cwd=cwd, check=check)
