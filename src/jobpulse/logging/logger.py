"""jobpulse.logging.logger — Logging factory and configuration.

Provides:
    setup_logging()  : Call once at startup to configure root logger.
    get_logger()     : Call in every module to get a named child logger.

Log Output Format:
    2026-01-15 10:30:45,123 | INFO     | jobpulse.extraction.csv | Message here

Handlers:
    1. StreamHandler  → stdout (always active)
    2. RotatingFileHandler → logs/jobpulse.log (active if log_file is set)

Usage:
    In main.py (startup):
        >>> from jobpulse.logging.logger import setup_logging
        >>> setup_logging()

    In any module:
        >>> from jobpulse.logging.logger import get_logger
        >>> logger = get_logger(__name__)
        >>> logger.info("Processing %d records", len(records))
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

# Default log format — consistent across all handlers
_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Track whether setup has been run to prevent double-initialisation
_logging_configured: bool = False


def setup_logging(
    level: str = "INFO",
    log_file: Path | None = None,
    max_bytes: int = 10_485_760,  # 10 MB
    backup_count: int = 5,
) -> None:
    """Configure the root logger with console and (optionally) file handlers.

    This function should be called ONCE at application startup (main.py).
    Subsequent calls are no-ops to prevent duplicate handlers.

    Args:
        level:        Logging level name (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_file:     Absolute path for the rotating log file.
                      If None, file logging is disabled.
        max_bytes:    Maximum size in bytes before the log file rotates.
                      Defaults to 10 MB.
        backup_count: Number of rotated log files to retain.

    Returns:
        None

    Example:
        >>> from pathlib import Path
        >>> setup_logging(level="DEBUG", log_file=Path("logs/jobpulse.log"))
    """
    global _logging_configured

    if _logging_configured:
        return  # Prevent duplicate handler registration

    numeric_level = logging.getLevelName(level.upper())
    if not isinstance(numeric_level, int):
        raise ValueError(
            f"Invalid log level: '{level}'. "
            "Choose from: DEBUG, INFO, WARNING, ERROR, CRITICAL."
        )

    formatter = logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT)
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # ------------------------------------------------------------------
    # Console Handler — logs to stdout
    # ------------------------------------------------------------------
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # ------------------------------------------------------------------
    # Rotating File Handler — logs to file (if path provided)
    # ------------------------------------------------------------------
    if log_file is not None:
        # Ensure the logs directory exists
        log_file.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.handlers.RotatingFileHandler(
            filename=log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # Silence noisy third-party loggers in non-DEBUG mode
    if numeric_level > logging.DEBUG:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("requests").setLevel(logging.WARNING)

    _logging_configured = True
    root_logger.debug("Logging initialised at level '%s'.", level)


def get_logger(name: str) -> logging.Logger:
    """Return a named child logger for a module.

    Call this at module level, not inside functions, so the logger
    instance is created once per module import.

    Args:
        name: Typically ``__name__`` of the calling module.
              This creates a dotted hierarchy (e.g. ``jobpulse.extraction.csv``).

    Returns:
        logging.Logger: A named child logger inheriting root configuration.

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Extracted %d rows from source.", row_count)
    """
    return logging.getLogger(name)
