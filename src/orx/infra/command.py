"""Subprocess command runner with logging."""

from __future__ import annotations

import json
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
    def _heartbeat_logger(
        log: structlog.BoundLogger, stop_event: threading.Event, interval: int
    ) -> None:
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
            # Provide lightweight fake outputs for certain agent CLIs to make
            # dry-run end-to-end flows useful (e.g., CLAUDE outputs used
            # by YAML extraction). Only emit to stdout_path/stderr_path if
            # paths were provided.
            try:
                cmd0 = command[0] if command else ""
                if "claude" in cmd0 or any("claude" in str(c) for c in command):
                    # Produce a JSON result with a YAML payload in `result`.
                    # Attempt to infer run_id from cwd (worktree name), fallback to 'dry-run'.
                    run_id = str(cwd.name) if cwd else "dry-run"
                    sample_yaml = (
                        f'run_id: "{run_id}"\n'
                        "items:\n"
                        '  - id: "W001"\n'
                        '    title: "Example task"\n'
                        '    objective: "Auto-generated task"\n'
                        "    acceptance:\n"
                        '      - "Auto-generated acceptance criterion"\n'
                        "    files_hint:\n"
                        '      - "src/example.py"\n'
                        "    depends_on: []\n"
                        '    status: "todo"\n'
                        "    attempts: 0\n"
                        '    notes: ""\n'
                    )
                    payload = {
                        "type": "result",
                        "subtype": "success",
                        "result": sample_yaml,
                        "cost_usd": 0.0,
                        "duration_ms": 10,
                        "num_turns": 1,
                        "session_id": "dry-run",
                        "is_error": False,
                    }
                    if stdout_path:
                        stdout_path.parent.mkdir(parents=True, exist_ok=True)
                        stdout_path.write_text(json.dumps(payload))
                else:
                    # Touch stdout/stderr so callers can read files
                    if stdout_path:
                        stdout_path.parent.mkdir(parents=True, exist_ok=True)
                        stdout_path.write_text("(dry run output)")
                    if stderr_path:
                        stderr_path.parent.mkdir(parents=True, exist_ok=True)
                        stderr_path.write_text("")
            except Exception:
                # If writing fails, ignore in dry-run
                pass

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
            if self.heartbeat_interval > 0 and (
                timeout is None or timeout > self.heartbeat_interval
            ):
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
        """Run a command and capture stdout/stderr in memory.

        Args:
            command: Command and arguments to run.
            cwd: Working directory for the command.
            timeout: Timeout in seconds.
            check: If True, raise on non-zero exit code.
            env: Environment variables (merged with current env).

        Returns:
            Tuple of (returncode, stdout, stderr).

        Raises:
            CommandError: If command cannot be started or times out, or if check=True and command fails.
        """
        log = logger.bind(command=command, cwd=str(cwd) if cwd else None)
        log.info("Running command (capture mode)")

        if self.dry_run:
            log.info("Dry run - skipping execution")
            return 0, "", ""

        import os

        full_env = os.environ.copy()
        if env:
            full_env.update(env)

        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=full_env,
                check=False,
            )
            log.info("Command completed", returncode=result.returncode)

            if check and result.returncode != 0:
                msg = f"Command failed with exit code {result.returncode}: {' '.join(command)}"
                raise CommandError(
                    msg,
                    command=command,
                    returncode=result.returncode,
                    cwd=cwd,
                )

            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired as e:
            log.error("Command timed out", timeout=timeout)
            msg = f"Command timed out after {timeout}s: {' '.join(command)}"
            raise CommandError(msg, command=command, cwd=cwd) from e
        except FileNotFoundError as e:
            log.error("Command not found", command=command[0])
            msg = f"Command not found: {command[0]}"
            raise CommandError(msg, command=command, cwd=cwd) from e

    def start_process(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        stdout_path: Path | None = None,
        stderr_path: Path | None = None,
        env: dict[str, str] | None = None,
        start_new_session: bool = True,
    ) -> subprocess.Popen[bytes]:
        """Start a subprocess and return the process handle.

        Args:
            command: Command and arguments to run.
            cwd: Working directory for the command.
            stdout_path: Path to write stdout to.
            stderr_path: Path to write stderr to.
            env: Environment variables (merged with current env).
            start_new_session: Whether to start a new process session.

        Returns:
            subprocess.Popen handle for the started process.

        Raises:
            CommandError: If dry_run is enabled or command cannot be started.
        """
        log = logger.bind(command=command, cwd=str(cwd) if cwd else None)
        log.info("Starting process")

        if self.dry_run:
            msg = f"CommandRunner.start_process does not support dry_run: {' '.join(command)}"
            raise CommandError(msg, command=command, cwd=cwd)

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

            process = subprocess.Popen(
                command,
                cwd=cwd,
                stdout=stdout_handle,
                stderr=stderr_handle,
                env=full_env,
                start_new_session=start_new_session,
            )
            log.info("Process started", pid=process.pid)
            return process
        except Exception as e:
            msg = f"Failed to start process: {' '.join(command)}"
            log.error("Failed to start process", error=str(e))
            raise CommandError(msg, command=command, cwd=cwd) from e
        finally:
            if stdout_handle and stdout_handle != subprocess.DEVNULL:
                stdout_handle.close()  # type: ignore[union-attr]
            if stderr_handle and stderr_handle != subprocess.DEVNULL:
                stderr_handle.close()  # type: ignore[union-attr]

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
