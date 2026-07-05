"""jobpulse.utils.date_utils — Date and time utility functions.

Pure functions for date parsing and formatting in the pipeline.
All timestamps are stored in UTC — no local timezone assumptions.

Functions:
    parse_date_string()  → Parse common date formats to datetime
    to_utc()             → Convert aware datetime to UTC
    format_for_db()      → Format datetime for PostgreSQL insertion

Usage:
    >>> from jobpulse.utils.date_utils import parse_date_string
    >>> parse_date_string("2024-01-15")
    datetime.datetime(2024, 1, 15, 0, 0, tzinfo=datetime.timezone.utc)
"""

from __future__ import annotations

from datetime import UTC, datetime

# Common date formats encountered in job posting data sources
_DATE_FORMATS: list[str] = [
    "%Y-%m-%dT%H:%M:%SZ",  # ISO 8601 UTC (e.g., APIs)
    "%Y-%m-%dT%H:%M:%S",  # ISO 8601 no tz
    "%Y-%m-%d %H:%M:%S",  # SQL datetime
    "%Y-%m-%d",  # Simple date
    "%d/%m/%Y",  # UK format
    "%m/%d/%Y",  # US format
    "%d %B %Y",  # e.g., "15 January 2024"
    "%B %d, %Y",  # e.g., "January 15, 2024"
]


def parse_date_string(date_str: str | None) -> datetime | None:
    """Attempt to parse a date string using common formats.

    Args:
        date_str: Raw date string from source data.

    Returns:
        datetime | None: UTC-aware datetime if parsing succeeds, else None.

    Example:
        >>> parse_date_string("2024-01-15")
        datetime.datetime(2024, 1, 15, 0, 0, tzinfo=datetime.timezone.utc)
        >>> parse_date_string("not-a-date") is None
        True
    """
    if not date_str or not str(date_str).strip():
        return None

    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(str(date_str).strip(), fmt)
            # Assume UTC if no timezone info
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except ValueError:
            continue

    return None


def utcnow() -> datetime:
    """Return the current UTC datetime as an aware datetime object.

    Prefer this over datetime.utcnow() (which returns a naive datetime).

    Returns:
        datetime: Current UTC time with timezone info set to UTC.

    Example:
        >>> now = utcnow()
        >>> now.tzinfo == timezone.utc
        True
    """
    return datetime.now(tz=UTC)


def format_for_filename(dt: datetime | None = None) -> str:
    """Format a datetime as a safe filename timestamp string.

    Format: YYYYMMDD_HHMMSS (no special characters)

    Args:
        dt: Datetime to format. Defaults to current UTC time if None.

    Returns:
        str: Timestamp string safe for use in file names.

    Example:
        >>> from datetime import datetime, timezone
        >>> format_for_filename(datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc))
        '20240115_103000'
    """
    target = dt or utcnow()
    return target.strftime("%Y%m%d_%H%M%S")
