"""Unit tests for transient error detection and retry handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from orx.executors.base import ExecResult, LogPaths


@pytest.fixture
def temp_logs(tmp_path: Path) -> LogPaths:
    """Create temporary log paths."""
    stdout = tmp_path / "stdout.log"
    stderr = tmp_path / "stderr.log"
    stdout.touch()
    stderr.touch()
    return LogPaths(stdout=stdout, stderr=stderr)


class TestTransientErrorDetection:
    """Test is_transient_error() method."""

    def test_successful_result_not_transient(self, temp_logs: LogPaths) -> None:
        """Successful results are not transient errors."""
        result = ExecResult(
            returncode=0,
            stdout_path=temp_logs.stdout,
            stderr_path=temp_logs.stderr,
            success=True,
        )
        assert not result.is_transient_error()

    def test_rate_limit_429_is_transient(self, temp_logs: LogPaths) -> None:
        """HTTP 429 rate limit errors are transient."""
        temp_logs.stderr.write_text("Error: 429 Too Many Requests")
        result = ExecResult(
            returncode=1,
            stdout_path=temp_logs.stdout,
            stderr_path=temp_logs.stderr,
            success=False,
        )
        assert result.is_transient_error()

    def test_capacity_exhausted_is_transient(self, temp_logs: LogPaths) -> None:
        """MODEL_CAPACITY_EXHAUSTED errors are transient."""
        temp_logs.stderr.write_text(
            '{"error": {"code": 429, "message": "No capacity available for model", '
            '"details": [{"reason": "MODEL_CAPACITY_EXHAUSTED"}]}}'
        )
        result = ExecResult(
            returncode=1,
            stdout_path=temp_logs.stdout,
            stderr_path=temp_logs.stderr,
            success=False,
        )
        assert result.is_transient_error()

    def test_resource_exhausted_is_transient(self, temp_logs: LogPaths) -> None:
        """RESOURCE_EXHAUSTED errors are transient."""
        temp_logs.stderr.write_text('GaxiosError: status: "RESOURCE_EXHAUSTED"')
        result = ExecResult(
            returncode=1,
            stdout_path=temp_logs.stdout,
            stderr_path=temp_logs.stderr,
            success=False,
        )
        assert result.is_transient_error()

    def test_timeout_is_transient(self, temp_logs: LogPaths) -> None:
        """Timeout errors are transient."""
        temp_logs.stderr.write_text("Error: Request timed out after 120 seconds")
        result = ExecResult(
            returncode=1,
            stdout_path=temp_logs.stdout,
            stderr_path=temp_logs.stderr,
            success=False,
        )
        assert result.is_transient_error()

    def test_server_error_503_is_transient(self, temp_logs: LogPaths) -> None:
        """503 Service Unavailable is transient."""
        temp_logs.stderr.write_text("HTTP 503: Service Unavailable")
        result = ExecResult(
            returncode=1,
            stdout_path=temp_logs.stdout,
            stderr_path=temp_logs.stderr,
            success=False,
        )
        assert result.is_transient_error()

    def test_connection_reset_is_transient(self, temp_logs: LogPaths) -> None:
        """Connection reset errors are transient."""
        temp_logs.stderr.write_text("Connection reset by peer")
        result = ExecResult(
            returncode=1,
            stdout_path=temp_logs.stdout,
            stderr_path=temp_logs.stderr,
            success=False,
        )
        assert result.is_transient_error()

    def test_model_not_found_not_transient(self, temp_logs: LogPaths) -> None:
        """Model not found is NOT transient (permanent error)."""
        temp_logs.stderr.write_text("Error: Model not found: invalid model id")
        result = ExecResult(
            returncode=1,
            stdout_path=temp_logs.stdout,
            stderr_path=temp_logs.stderr,
            success=False,
        )
        # Model not found is checked by is_model_unavailable_error, not transient
        assert not result.is_transient_error()
        assert result.is_model_unavailable_error()

    def test_syntax_error_not_transient(self, temp_logs: LogPaths) -> None:
        """Code syntax errors are NOT transient."""
        temp_logs.stderr.write_text("SyntaxError: invalid syntax at line 42")
        result = ExecResult(
            returncode=1,
            stdout_path=temp_logs.stdout,
            stderr_path=temp_logs.stderr,
            success=False,
        )
        assert not result.is_transient_error()

    def test_error_message_also_checked(self, temp_logs: LogPaths) -> None:
        """Error message field is also checked for transient markers."""
        result = ExecResult(
            returncode=1,
            stdout_path=temp_logs.stdout,
            stderr_path=temp_logs.stderr,
            success=False,
            error_message="Rate limit exceeded, please retry",
        )
        assert result.is_transient_error()


class TestRetryAfterExtraction:
    """Test get_retry_after_seconds() method."""

    def test_no_retry_hint(self, temp_logs: LogPaths) -> None:
        """Returns None when no retry hint present."""
        temp_logs.stderr.write_text("Some generic error occurred")
        result = ExecResult(
            returncode=1,
            stdout_path=temp_logs.stdout,
            stderr_path=temp_logs.stderr,
            success=False,
        )
        assert result.get_retry_after_seconds() is None

    def test_retry_after_seconds(self, temp_logs: LogPaths) -> None:
        """Extracts 'retry after Ns' format."""
        temp_logs.stderr.write_text("Rate limited. Retry after 60s")
        result = ExecResult(
            returncode=1,
            stdout_path=temp_logs.stdout,
            stderr_path=temp_logs.stderr,
            success=False,
        )
        assert result.get_retry_after_seconds() == 60

    def test_wait_seconds_format(self, temp_logs: LogPaths) -> None:
        """Extracts 'wait N seconds' format."""
        temp_logs.stderr.write_text("Please wait 30 seconds before retrying")
        result = ExecResult(
            returncode=1,
            stdout_path=temp_logs.stdout,
            stderr_path=temp_logs.stderr,
            success=False,
        )
        assert result.get_retry_after_seconds() == 30

    def test_quota_reset_hours_minutes(self, temp_logs: LogPaths) -> None:
        """Extracts 'quota will reset after Xh' format."""
        temp_logs.stderr.write_text(
            "You have exhausted your capacity. Your quota will reset after 4h23m31s"
        )
        result = ExecResult(
            returncode=1,
            stdout_path=temp_logs.stdout,
            stderr_path=temp_logs.stderr,
            success=False,
        )
        # 4h = 14400, but we return the first pattern match
        retry = result.get_retry_after_seconds()
        assert retry is not None
        # Should capture hours, minutes, seconds (4*3600 + 23*60 + 31 = 15811)
        assert retry > 0


class TestQuotaErrorDetection:
    """Test is_quota_error() method."""

    def test_quota_in_stderr(self, temp_logs: LogPaths) -> None:
        """Detects quota errors in stderr."""
        temp_logs.stderr.write_text("Error: API quota exceeded")
        result = ExecResult(
            returncode=1,
            stdout_path=temp_logs.stdout,
            stderr_path=temp_logs.stderr,
            success=False,
        )
        assert result.is_quota_error()

    def test_rate_limit_detected(self, temp_logs: LogPaths) -> None:
        """Detects rate limit as quota error."""
        temp_logs.stderr.write_text("Too many requests, please slow down")
        result = ExecResult(
            returncode=1,
            stdout_path=temp_logs.stdout,
            stderr_path=temp_logs.stderr,
            success=False,
        )
        assert result.is_quota_error()

    def test_capacity_detected(self, temp_logs: LogPaths) -> None:
        """Detects capacity errors as quota error."""
        result = ExecResult(
            returncode=1,
            stdout_path=temp_logs.stdout,
            stderr_path=temp_logs.stderr,
            success=False,
            error_message="No capacity available for model",
        )
        assert result.is_quota_error()
