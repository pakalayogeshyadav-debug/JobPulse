"""
tests/test_utils/test_date_utils.py — Unit tests for date utility functions.

Tests:
    - parse_date_string() handles multiple date formats
    - parse_date_string() returns None for invalid/None inputs
    - utcnow() returns UTC-aware datetime
    - format_for_filename() produces correct timestamp strings
"""

from __future__ import annotations

from datetime import UTC, datetime

from jobpulse.utils.date_utils import format_for_filename, parse_date_string, utcnow


class TestParseDateString:
    """Tests for parse_date_string()."""

    def test_parses_iso_date_format(self) -> None:
        """Simple ISO date strings (YYYY-MM-DD) should parse correctly."""
        result = parse_date_string("2024-01-15")
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_parses_iso_datetime_with_z(self) -> None:
        """ISO 8601 UTC timestamps ending in Z should parse correctly."""
        result = parse_date_string("2024-01-15T10:30:00Z")
        assert result is not None
        assert result.tzinfo == UTC

    def test_returns_utc_aware_datetime(self) -> None:
        """All returned datetimes should be UTC-aware."""
        result = parse_date_string("2024-01-15")
        assert result is not None
        assert result.tzinfo == UTC

    def test_returns_none_for_none_input(self) -> None:
        """parse_date_string(None) should return None."""
        assert parse_date_string(None) is None

    def test_returns_none_for_empty_string(self) -> None:
        """parse_date_string('') should return None."""
        assert parse_date_string("") is None

    def test_returns_none_for_invalid_date_string(self) -> None:
        """Unparseable strings should return None (not raise)."""
        assert parse_date_string("not-a-date") is None
        assert parse_date_string("yesterday") is None


class TestUtcNow:
    """Tests for utcnow()."""

    def test_returns_aware_datetime(self) -> None:
        """utcnow() should return a timezone-aware datetime."""
        result = utcnow()
        assert result.tzinfo is not None

    def test_returns_utc_timezone(self) -> None:
        """utcnow() should be in UTC timezone."""
        result = utcnow()
        assert result.tzinfo == UTC


class TestFormatForFilename:
    """Tests for format_for_filename()."""

    def test_returns_correct_format(self) -> None:
        """Output should match YYYYMMDD_HHMMSS format."""
        dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
        result = format_for_filename(dt)
        assert result == "20240115_103000"

    def test_returns_string_type(self) -> None:
        """Return type should be str."""
        assert isinstance(format_for_filename(), str)

    def test_no_special_characters(self) -> None:
        """Output should contain no characters unsafe for filenames."""
        result = format_for_filename()
        import re

        assert re.match(r"^\d{8}_\d{6}$", result), f"Unexpected format: {result}"
