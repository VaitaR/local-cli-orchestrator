"""Tests for dashboard server utilities."""

from datetime import UTC, datetime

from orx.dashboard.server import format_short_time


class TestFormatShortTime:
    """Tests for format_short_time Jinja2 filter."""

    def test_format_short_time_with_valid_datetime(self) -> None:
        """Test that format_short_time returns HH:MM format for valid datetime."""
        dt = datetime(2025, 1, 15, 14, 32, 0, tzinfo=UTC)
        assert format_short_time(dt) == "14:32"

    def test_format_short_time_with_morning_time(self) -> None:
        """Test that format_short_time works for morning times."""
        dt = datetime(2025, 1, 15, 9, 5, 0, tzinfo=UTC)
        assert format_short_time(dt) == "09:05"

    def test_format_short_time_with_midnight(self) -> None:
        """Test that format_short_time works for midnight."""
        dt = datetime(2025, 1, 15, 0, 0, 0, tzinfo=UTC)
        assert format_short_time(dt) == "00:00"

    def test_format_short_time_with_none_returns_empty_string(self) -> None:
        """Test that format_short_time returns empty string for None."""
        assert format_short_time(None) == ""

    def test_format_short_time_with_different_minutes(self) -> None:
        """Test that format_short_time handles various minute values."""
        # Single digit minutes should be zero-padded
        dt1 = datetime(2025, 1, 15, 10, 5, tzinfo=UTC)
        assert format_short_time(dt1) == "10:05"

        # Double digit minutes
        dt2 = datetime(2025, 1, 15, 10, 45, tzinfo=UTC)
        assert format_short_time(dt2) == "10:45"
