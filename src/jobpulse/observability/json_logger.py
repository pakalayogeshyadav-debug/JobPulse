"""jobpulse.observability.json_logger — Structured JSON logging handler.

Adds a JSON log handler alongside (not replacing) the existing text logger.

Design Decision — Why a new handler, not a new logger?
    The existing setup_logging() and get_logger() infrastructure already works
    well for human operators reading terminal output. Replacing it would break
    the existing ETL code. Instead, we ADD a JSON handler to the same logger
    hierarchy — human-readable text goes to stdout/file, machine-readable JSON
    goes to a separate JSON log file. Both streams are active simultaneously.

    This follows the Open/Closed Principle: the existing logger.py is not
    modified. We extend behaviour by adding a handler.

Design Decision — Why JSON logs?
    JSON logs are the standard for log aggregation tools:
    - AWS CloudWatch Logs Insights: native JSON field querying
    - Datadog Log Management: automatic JSON parsing
    - ELK Stack (Elasticsearch/Logstash/Kibana): structured JSON indexing
    - Google Cloud Logging: native JSON support

    With JSON logs, you can query:
    - "All ERROR events where stage='load' in the last 24 hours"
    - "Average duration_ms for extract stage per source"
    - "Count of CRITICAL validation failures per day"
    None of this is possible with plain-text log files.

JSON Log Record Format:
    {
        "timestamp":  "2024-06-30T03:47:22.143+00:00",
        "level":      "ERROR",
        "logger":     "jobpulse.loading.postgres_loader",
        "message":    "Bulk insert failed after 3 retries",
        "run_id":     "scheduled__2024-06-30T03:00:00+00:00",
        "source":     "csv_kaggle_jobs",
        "stage":      "load",
        "duration_ms": 1234.5,
        "extra":      { ... }
    }
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class JsonFormatter(logging.Formatter):
    """Custom log formatter that serialises log records to JSON.

    WHY a custom Formatter (not a Handler)?
        Python's logging architecture separates formatting (Formatter)
        from output destination (Handler). Using a Formatter means the
        JSON format can be applied to ANY handler — a file, a stream,
        a network socket, etc. This is more flexible than hard-coding
        the format into a custom handler.

    WHY include extra fields in every record?
        Structured log queries in Kibana/Datadog require consistent field
        names across all records. If some records have a 'run_id' field
        and others don't, you can't filter by run_id reliably.
        The _STANDARD_FIELDS list defines what goes into every record.
    """

    _STANDARD_FIELDS = frozenset(
        {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "taskName",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        """Serialise a LogRecord to a single-line JSON string.

        Args:
            record: Standard Python logging.LogRecord.

        Returns:
            str: JSON-encoded log entry (one line, no trailing newline).
        """
        # Build the base record
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Append exception information if present
        if record.exc_info:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "stacktrace": traceback.format_exception(*record.exc_info),
            }

        # Append any extra fields the caller attached via logger.info(..., extra={...})
        for key, value in record.__dict__.items():
            if key not in self._STANDARD_FIELDS and not key.startswith("_"):
                try:
                    json.dumps(value)  # Guard: only include JSON-serialisable extras
                    log_entry[key] = value
                except (TypeError, ValueError):
                    log_entry[key] = str(value)

        return json.dumps(log_entry, default=str)


class JsonStructuredLogger:
    """Augments the existing Python logger with a JSON file handler.

    This class follows the Decorator pattern — it wraps the existing
    jobpulse logger without modifying logger.py.

    Usage:
        json_logger = JsonStructuredLogger(
            log_dir=Path("logs"),
            run_id="run-001",
            source_name="csv_kaggle_jobs",
        )
        json_logger.install()   # Attaches the JSON handler to the jobpulse logger

        # After install(), all existing logger.info/warning/error calls
        # automatically also write to the JSON file. No code changes needed.

        # Additionally, call emit_event() for structured operational events:
        json_logger.emit_event("pipeline_started", {"rows_expected": 5000})
    """

    def __init__(
        self,
        log_dir: Path,
        run_id: str,
        source_name: str,
        log_level: str = "INFO",
        max_bytes: int = 52_428_800,  # 50 MB
        backup_count: int = 10,
    ) -> None:
        """Args:
        log_dir:      Directory to write the JSON log file into.
        run_id:       Pipeline run identifier (stamped on every record).
        source_name:  Data source name (stamped on every record).
        log_level:    Minimum level for the JSON handler.
        max_bytes:    Maximum JSON log file size before rotation (default: 50 MB).
        backup_count: Number of rotated JSON log files to keep.
        """
        self._log_dir = log_dir
        self._run_id = run_id
        self._source_name = source_name
        self._log_level = log_level
        self._max_bytes = max_bytes
        self._backup_count = backup_count
        self._handler: logging.Handler | None = None
        self._event_logger = logging.getLogger("jobpulse.observability.events")

    def install(self) -> Path:
        """Attach the JSON handler to the root 'jobpulse' logger.

        Creates the log directory if it doesn't exist.
        The handler is idempotent — calling install() twice is safe.

        Returns:
            Path: Absolute path of the JSON log file.

        WHY attach to 'jobpulse' logger (not root logger)?
            Attaching to root would capture logs from every library
            (sqlalchemy, urllib3, pandas), generating enormous JSON logs
            full of noise. Attaching to 'jobpulse' captures only pipeline
            code logs — exactly what we need.
        """
        if self._handler is not None:
            return self._json_log_path()

        self._log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self._json_log_path()

        formatter = JsonFormatter()
        handler = logging.handlers.RotatingFileHandler(
            filename=log_path,
            maxBytes=self._max_bytes,
            backupCount=self._backup_count,
            encoding="utf-8",
        )
        handler.setFormatter(formatter)
        handler.setLevel(logging.getLevelName(self._log_level.upper()))

        # Add a filter that stamps run_id and source on every record
        handler.addFilter(self._StampFilter(self._run_id, self._source_name))

        logging.getLogger("jobpulse").addHandler(handler)
        self._handler = handler

        self._event_logger.info(
            "JSON structured logging installed | path=%s | run_id=%s",
            log_path,
            self._run_id,
        )
        return log_path

    def uninstall(self) -> None:
        """Remove the JSON handler from the jobpulse logger.

        Call at the end of a pipeline run to flush buffers and close the file.
        Safe to call even if install() was never called.
        """
        if self._handler is not None:
            logging.getLogger("jobpulse").removeHandler(self._handler)
            self._handler.close()
            self._handler = None

    def emit_event(self, event_name: str, payload: dict[str, Any]) -> None:
        """Emit a structured operational event to the JSON log.

        Unlike regular log messages (which are free-form text), events
        are typed entries with a consistent schema. They're meant for
        machine consumption — log aggregation queries, dashboards, alerts.

        Args:
            event_name: Short identifier for the event type.
                        Convention: snake_case, e.g. "extraction_complete"
            payload:    Structured data associated with this event.

        Example:
            json_logger.emit_event("extraction_complete", {
                "rows_extracted": 5000,
                "source_path": "/data/raw/jobs.csv",
                "duration_ms": 1234.5,
            })
        """
        self._event_logger.info(
            "EVENT:%s",
            event_name,
            extra={
                "event_name": event_name,
                "run_id": self._run_id,
                "source_name": self._source_name,
                "payload": payload,
            },
        )

    def _json_log_path(self) -> Path:
        """Compute the JSON log file path from log_dir and run_id."""
        # Sanitise run_id for use in a filename (Airflow run IDs contain colons and slashes)
        safe_run_id = self._run_id.replace(":", "_").replace("/", "_").replace("+", "_")
        return self._log_dir / f"jobpulse_{safe_run_id}.jsonl"

    class _StampFilter(logging.Filter):
        """Logging filter that stamps run_id and source_name onto every record.

        WHY a Filter instead of adding these in the Formatter?
            Formatters in Python logging cannot MODIFY records — they only
            READ them to produce output. Filters CAN modify records (they
            receive and return the mutable LogRecord). Stamping here means
            the extra fields are available whether the record goes to the
            JSON handler or any other handler.
        """

        def __init__(self, run_id: str, source_name: str) -> None:
            super().__init__()
            self._run_id = run_id
            self._source_name = source_name

        def filter(self, record: logging.LogRecord) -> bool:
            if not hasattr(record, "run_id"):
                record.run_id = self._run_id  # type: ignore[attr-defined]
            if not hasattr(record, "source_name"):
                record.source_name = self._source_name  # type: ignore[attr-defined]
            return True
