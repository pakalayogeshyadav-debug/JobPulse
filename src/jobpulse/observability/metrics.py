"""jobpulse.observability.metrics — Immutable metric dataclasses.

All metric objects are frozen dataclasses (value objects).

Design Decision — Why pure dataclasses, no business logic?
    These objects are the "data" in the observability system.
    They carry no knowledge of databases, logging, or formatting.
    This makes them trivially serialisable, testable, and portable
    (e.g. the same PipelineRunMetrics can be saved to PostgreSQL,
    sent to Prometheus, written to a JSON file, or logged — without
    changing the object itself).

    Following the Single Responsibility Principle: these classes
    have exactly one job — hold structured data.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

# =============================================================================
# Enums
# =============================================================================


class PipelineStatus(str, Enum):
    """Possible states of a pipeline run.
    Inherits from str for JSON-serialisable enum values.
    """

    RUNNING = "RUNNING"  # Pipeline is currently executing
    SUCCESS = "SUCCESS"  # Completed without any failures
    PARTIAL = "PARTIAL"  # Completed but some records failed
    FAILED = "FAILED"  # Terminated due to an unrecoverable error
    UNKNOWN = "UNKNOWN"  # Status could not be determined


class ErrorSeverity(str, Enum):
    """Severity classification for pipeline errors."""

    CRITICAL = "CRITICAL"  # Pipeline halted; data not loaded
    WARNING = "WARNING"  # Pipeline continued; partial data quality issue
    INFO = "INFO"  # Informational; no impact on data


# =============================================================================
# StageMetrics — timing + counts for one ETL stage
# =============================================================================


@dataclass
class StageMetrics:
    """Timing and record counts for a single ETL stage (extract/transform/load/validate).

    WHY a separate dataclass per stage?
        Each ETL stage has different meaningful metrics:
        - Extraction: rows_extracted, source_name, duration
        - Transformation: rows_in, rows_out, rows_dropped, duration
        - Loading: rows_inserted, rows_updated, rows_failed, duration
        Merging these into one flat object would either lose specificity
        (renaming everything rows_in_1, rows_in_2) or create a sparse
        object with many None fields.

    Attributes:
        stage_name:     Identifier (e.g. "extract", "transform", "load", "validate")
        started_at:     UTC timestamp when this stage began
        completed_at:   UTC timestamp when this stage ended (None if still running)
        rows_in:        Records received by this stage
        rows_out:       Records produced by this stage
        rows_failed:    Records that failed processing in this stage
        duration_ms:    Wall-clock duration in milliseconds
        extra:          Stage-specific additional metadata (free-form)
    """

    stage_name: str
    started_at: datetime
    rows_in: int = 0
    rows_out: int = 0
    rows_failed: int = 0
    completed_at: datetime | None = None
    duration_ms: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        return round(self.duration_ms / 1000.0, 3)

    @property
    def rows_dropped(self) -> int:
        return max(0, self.rows_in - self.rows_out - self.rows_failed)

    @property
    def success_rate_pct(self) -> float:
        if self.rows_in == 0:
            return 100.0
        return round((self.rows_out / self.rows_in) * 100.0, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage_name": self.stage_name,
            "started_at": self.started_at.isoformat(),
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "duration_ms": round(self.duration_ms, 2),
            "duration_seconds": self.duration_seconds,
            "rows_in": self.rows_in,
            "rows_out": self.rows_out,
            "rows_failed": self.rows_failed,
            "rows_dropped": self.rows_dropped,
            "success_rate_pct": self.success_rate_pct,
            "extra": self.extra,
        }


# =============================================================================
# PipelineError — one error event
# =============================================================================


@dataclass
class PipelineError:
    """A single error or warning event that occurred during a pipeline run.

    WHY capture errors separately (not just in logs)?
        Log files are append-only text — hard to aggregate, query, or trend.
        Storing errors in pipeline_errors table enables:
        - "How many CRITICAL errors occurred in the last 7 days?"
        - "Which error message appears most frequently?"
        - Automated alerting triggers on error count thresholds
        None of this is possible with unstructured log files.

    Attributes:
        run_id:         Airflow / application run identifier
        error_id:       UUID for this specific error event
        stage:          Which ETL stage raised this error
        error_type:     Exception class name (e.g. "DataExtractionError")
        message:        Human-readable error description
        severity:       CRITICAL (pipeline halted) / WARNING / INFO
        occurred_at:    UTC timestamp of the error
        stack_trace:    Full traceback (stored for debugging, not shown in reports)
        context:        Additional structured context (row index, column name, etc.)
    """

    run_id: str
    stage: str
    error_type: str
    message: str
    severity: ErrorSeverity = ErrorSeverity.WARNING
    occurred_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    error_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    stack_trace: str | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_id": self.error_id,
            "run_id": self.run_id,
            "stage": self.stage,
            "error_type": self.error_type,
            "message": self.message,
            "severity": self.severity.value,
            "occurred_at": self.occurred_at.isoformat(),
            "stack_trace": self.stack_trace,
            "context": self.context,
        }


# =============================================================================
# PipelineRunMetrics — full metrics for one pipeline execution
# =============================================================================


@dataclass
class PipelineRunMetrics:
    """Comprehensive metrics snapshot for a complete pipeline run.

    This is the central object in the observability layer.
    One instance is created by PipelineMonitor at pipeline start,
    updated throughout execution, and persisted to pipeline_runs
    table when the pipeline finishes.

    WHY one object (not separate objects per concern)?
        A single PipelineRunMetrics is the "receipt" for one pipeline run.
        It must be atomic — either the entire run is recorded or it isn't.
        Splitting it across multiple objects would complicate the
        "did this run succeed?" query from pipeline_runs.

    Attributes:
        run_id:              Unique identifier (Airflow run_id or UUID)
        source_name:         Data source being processed
        pipeline_version:    Git tag / version string for audit
        environment:         development / staging / production
        status:              Current state of the run
        started_at:          UTC timestamp when pipeline started
        completed_at:        UTC timestamp when pipeline finished (None if running)
        stage_metrics:       Per-stage timing and record counts
        errors:              All errors/warnings raised during the run

        --- Record counts (denormalised from stage_metrics for fast querying) ---
        rows_extracted:      Total rows returned from extraction
        rows_transformed:    Total rows after transformation
        rows_loaded:         Rows successfully written to database
        rows_failed:         Rows that could not be processed (any stage)
        validation_failures: Number of data quality check failures
        critical_failures:   Number of CRITICAL validation failures

        --- Timing ---
        extract_duration_ms:   Wall-clock time for extraction stage
        transform_duration_ms: Wall-clock time for transformation stage
        load_duration_ms:      Wall-clock time for loading stage
        db_execution_time_ms:  Time spent in PostgreSQL (load + refresh)

        --- Derived ---
        success_rate_pct:    rows_loaded / rows_extracted * 100
    """

    run_id: str
    source_name: str
    pipeline_version: str = "unknown"
    environment: str = "development"
    status: PipelineStatus = PipelineStatus.RUNNING
    started_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    completed_at: datetime | None = None
    stage_metrics: list[StageMetrics] = field(default_factory=list)
    errors: list[PipelineError] = field(default_factory=list)

    # Denormalised record counts (faster to query than joining stage_metrics JSON)
    rows_extracted: int = 0
    rows_transformed: int = 0
    rows_loaded: int = 0
    rows_failed: int = 0
    validation_failures: int = 0
    critical_failures: int = 0

    # Stage timing
    extract_duration_ms: float = 0.0
    transform_duration_ms: float = 0.0
    load_duration_ms: float = 0.0
    db_execution_time_ms: float = 0.0

    # ── Computed properties ───────────────────────────────────────────────────

    @property
    def total_duration_ms(self) -> float:
        """Wall-clock time from pipeline start to finish."""
        if self.completed_at and self.started_at:
            delta = self.completed_at - self.started_at
            return delta.total_seconds() * 1000.0
        return 0.0

    @property
    def total_duration_seconds(self) -> float:
        return round(self.total_duration_ms / 1000.0, 2)

    @property
    def success_rate_pct(self) -> float:
        """Percentage of extracted rows that were successfully loaded."""
        if self.rows_extracted == 0:
            return 0.0
        return round((self.rows_loaded / self.rows_extracted) * 100.0, 2)

    @property
    def drop_rate_pct(self) -> float:
        """Percentage of extracted rows that were dropped or failed."""
        if self.rows_extracted == 0:
            return 0.0
        return round((self.rows_failed / self.rows_extracted) * 100.0, 2)

    @property
    def is_healthy(self) -> bool:
        """True if the run completed without critical failures."""
        return self.status == PipelineStatus.SUCCESS

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict. Suitable for JSON logging and API responses."""
        return {
            "run_id": self.run_id,
            "source_name": self.source_name,
            "pipeline_version": self.pipeline_version,
            "environment": self.environment,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "total_duration_seconds": self.total_duration_seconds,
            "record_counts": {
                "rows_extracted": self.rows_extracted,
                "rows_transformed": self.rows_transformed,
                "rows_loaded": self.rows_loaded,
                "rows_failed": self.rows_failed,
                "success_rate_pct": self.success_rate_pct,
                "drop_rate_pct": self.drop_rate_pct,
            },
            "validation": {
                "total_failures": self.validation_failures,
                "critical_failures": self.critical_failures,
            },
            "timing_ms": {
                "extract": round(self.extract_duration_ms, 2),
                "transform": round(self.transform_duration_ms, 2),
                "load": round(self.load_duration_ms, 2),
                "db_execution": round(self.db_execution_time_ms, 2),
                "total": round(self.total_duration_ms, 2),
            },
            "stages": [s.to_dict() for s in self.stage_metrics],
            "errors": [e.to_dict() for e in self.errors],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    # ── Prometheus text exposition format ─────────────────────────────────────

    def to_prometheus_metrics(self) -> str:
        """Format metrics in Prometheus text exposition format.

        WHY this format?
            Prometheus scrapes metrics via HTTP in a standard text format.
            By generating this format here, we can expose a /metrics endpoint
            (e.g., via Flask or FastAPI) that Prometheus scrapes every 15 seconds
            without any Prometheus client library dependency in this class.

            The prometheus_client library is NOT imported here — this keeps
            the metrics module dependency-free and testable without installing
            the Prometheus stack.

        Returns:
            str: Prometheus text exposition format string.
        """
        labels = f'source="{self.source_name}",env="{self.environment}",run_id="{self.run_id}"'
        ts_ms = int(self.started_at.timestamp() * 1000)

        lines = [
            "# HELP jobpulse_rows_extracted Total rows extracted from source",
            "# TYPE jobpulse_rows_extracted gauge",
            f"jobpulse_rows_extracted{{{labels}}} {self.rows_extracted} {ts_ms}",
            "# HELP jobpulse_rows_loaded Rows successfully loaded into PostgreSQL",
            "# TYPE jobpulse_rows_loaded gauge",
            f"jobpulse_rows_loaded{{{labels}}} {self.rows_loaded} {ts_ms}",
            "# HELP jobpulse_rows_failed Rows that failed processing",
            "# TYPE jobpulse_rows_failed gauge",
            f"jobpulse_rows_failed{{{labels}}} {self.rows_failed} {ts_ms}",
            "# HELP jobpulse_success_rate_pct Pipeline success rate (0-100)",
            "# TYPE jobpulse_success_rate_pct gauge",
            f"jobpulse_success_rate_pct{{{labels}}} {self.success_rate_pct} {ts_ms}",
            "# HELP jobpulse_validation_failures Total DQ check failures",
            "# TYPE jobpulse_validation_failures gauge",
            f"jobpulse_validation_failures{{{labels}}} {self.validation_failures} {ts_ms}",
            "# HELP jobpulse_critical_failures Critical DQ check failures",
            "# TYPE jobpulse_critical_failures gauge",
            f"jobpulse_critical_failures{{{labels}}} {self.critical_failures} {ts_ms}",
            "# HELP jobpulse_extract_duration_ms Extraction stage duration",
            "# TYPE jobpulse_extract_duration_ms gauge",
            f"jobpulse_extract_duration_ms{{{labels}}} {self.extract_duration_ms:.2f} {ts_ms}",
            "# HELP jobpulse_transform_duration_ms Transformation stage duration",
            "# TYPE jobpulse_transform_duration_ms gauge",
            f"jobpulse_transform_duration_ms{{{labels}}} {self.transform_duration_ms:.2f} {ts_ms}",
            "# HELP jobpulse_load_duration_ms Loading stage duration",
            "# TYPE jobpulse_load_duration_ms gauge",
            f"jobpulse_load_duration_ms{{{labels}}} {self.load_duration_ms:.2f} {ts_ms}",
            "# HELP jobpulse_db_execution_time_ms Total PostgreSQL execution time",
            "# TYPE jobpulse_db_execution_time_ms gauge",
            f"jobpulse_db_execution_time_ms{{{labels}}} {self.db_execution_time_ms:.2f} {ts_ms}",
            "# HELP jobpulse_pipeline_status Pipeline run status (1=SUCCESS 0=other)",
            "# TYPE jobpulse_pipeline_status gauge",
            f"jobpulse_pipeline_status{{{labels}}} {1 if self.status == PipelineStatus.SUCCESS else 0} {ts_ms}",
        ]
        return "\n".join(lines) + "\n"
