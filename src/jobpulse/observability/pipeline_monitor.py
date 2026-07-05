"""jobpulse.observability.pipeline_monitor — Context-manager orchestrator.

PipelineMonitor is the SINGLE entry point for callers (Airflow tasks,
main.py, test harnesses) to interact with the observability layer.

Design — Context Manager + Facade
    Callers simply:
        with PipelineMonitor(...) as monitor:
            monitor.record_extraction(...)
            monitor.record_transformation(...)
            monitor.record_loading(...)

    What happens automatically:
    ✓ JSON log handler is installed at __enter__
    ✓ pipeline_runs row is created with status=RUNNING at __enter__
    ✓ stage metrics are tracked with wall-clock timing
    ✓ On clean exit: status set to SUCCESS, row updated, JSON handler uninstalled
    ✓ On exception: error recorded, status set to FAILED, row updated, re-raises

Design — Facade Pattern
    PipelineMonitor hides the complexity of:
    - JsonStructuredLogger (install/uninstall lifecycle)
    - AbstractMetricStore (start/finish persistence)
    - PipelineRunMetrics (metric aggregation)
    - PipelineError (error structuring)

    The caller only sees: record_extraction, record_transformation,
    record_loading, record_validation_failure, record_error.

Design — No Mutation of ETL Code
    PipelineMonitor does NOT modify any extraction, transformation, or loading
    code. It is called BY the Airflow task_functions.py or main.py AROUND
    those calls. The ETL layer knows nothing about monitoring.
"""

from __future__ import annotations

import time
import traceback
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jobpulse.logging.logger import get_logger
from jobpulse.observability.db_store import AbstractMetricStore
from jobpulse.observability.json_logger import JsonStructuredLogger
from jobpulse.observability.metrics import (
    ErrorSeverity,
    PipelineError,
    PipelineRunMetrics,
    PipelineStatus,
    StageMetrics,
)

logger = get_logger(__name__)


class PipelineMonitor:
    """Context-manager that tracks an entire pipeline run end-to-end.

    Responsibilities:
        1. Install/uninstall the JSON log handler
        2. Create/update the pipeline_runs record
        3. Provide stage-level metric recording methods
        4. Persist pipeline errors to pipeline_errors table
        5. Expose the current metrics snapshot at any time

    Thread Safety:
        PipelineMonitor is NOT thread-safe by design. One monitor instance
        per pipeline run. If processing multiple sources concurrently,
        create one PipelineMonitor per source (which is the natural mapping:
        one Airflow task = one source = one monitor).

    Usage:
        with PipelineMonitor(
            run_id="scheduled__2024-06-30",
            source_name="csv_kaggle_jobs",
            metric_store=PostgresMetricStore(engine),
            log_dir=Path("logs"),
        ) as monitor:
            monitor.record_extraction(rows_extracted=5000)
            monitor.record_transformation(rows_in=5000, rows_out=4850)
            monitor.record_loading(rows_inserted=4800, rows_updated=50, rows_failed=0)
    """

    def __init__(
        self,
        run_id: str,
        source_name: str,
        metric_store: AbstractMetricStore,
        log_dir: Path = Path("logs"),
        pipeline_version: str = "unknown",
        environment: str = "development",
    ) -> None:
        """Args:
        run_id:           Unique run identifier. Use Airflow's context["run_id"].
        source_name:      Data source being processed (e.g., "csv_kaggle_jobs").
        metric_store:     Where to persist run metrics (PostgresMetricStore or InMemoryMetricStore).
        log_dir:          Directory for the JSON structured log file.
        pipeline_version: Git tag / commit hash for audit trail.
        environment:      development / staging / production.
        """
        self._run_id = run_id
        self._source_name = source_name
        self._store = metric_store
        self._log_dir = log_dir

        # Build the metrics object — mutated throughout the run
        self._metrics = PipelineRunMetrics(
            run_id=run_id,
            source_name=source_name,
            pipeline_version=pipeline_version,
            environment=environment,
        )

        # JSON logger — installed/uninstalled in __enter__/__exit__
        self._json_logger = JsonStructuredLogger(
            log_dir=log_dir,
            run_id=run_id,
            source_name=source_name,
        )

        # Stage timer state
        self._stage_timers: dict[str, float] = {}

    # ──────────────────────────────────────────────────────────────────────────
    # Context Manager protocol
    # ──────────────────────────────────────────────────────────────────────────

    def __enter__(self) -> PipelineMonitor:
        """Start monitoring:
        1. Ensure monitoring tables exist
        2. Install JSON log handler
        3. Persist RUNNING status to pipeline_runs
        4. Emit pipeline_started event
        """
        logger.info(
            "PipelineMonitor starting | run_id=%s | source=%s",
            self._run_id,
            self._source_name,
        )
        try:
            self._store.ensure_tables()
            self._json_logger.install()
            self._store.upsert_run(self._metrics)  # status = RUNNING
            self._json_logger.emit_event(
                "pipeline_started",
                {
                    "run_id": self._run_id,
                    "source_name": self._source_name,
                    "started_at": self._metrics.started_at.isoformat(),
                },
            )
        except Exception as exc:
            # Monitoring failures must NEVER crash the pipeline
            logger.error(
                "PipelineMonitor.__enter__ failed (non-fatal): %s: %s",
                type(exc).__name__,
                exc,
            )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Finish monitoring:
        - If no exception: mark SUCCESS, update pipeline_runs
        - If exception: record error, mark FAILED, update pipeline_runs
        - Always: uninstall JSON log handler

        Returns:
            False — never suppress exceptions. The pipeline's exception
            propagates naturally to Airflow for proper task failure handling.
        """
        self._metrics.completed_at = datetime.now(tz=UTC)

        if exc_val is None:
            # Determine if it was a partial run (some records failed)
            if self._metrics.rows_failed > 0 or self._metrics.critical_failures > 0:
                self._metrics.status = PipelineStatus.PARTIAL
            else:
                self._metrics.status = PipelineStatus.SUCCESS
        else:
            self._metrics.status = PipelineStatus.FAILED
            # Record the unhandled exception as a CRITICAL error
            self.record_error(
                stage="pipeline",
                error_type=type(exc_val).__name__,
                message=str(exc_val),
                severity=ErrorSeverity.CRITICAL,
                stack_trace="".join(
                    traceback.format_exception(exc_type, exc_val, exc_tb)
                ),
            )

        try:
            self._store.upsert_run(self._metrics)  # Update with final status
            self._json_logger.emit_event(
                "pipeline_finished",
                {
                    "status": self._metrics.status.value,
                    "total_duration_s": self._metrics.total_duration_seconds,
                    "rows_loaded": self._metrics.rows_loaded,
                    "rows_failed": self._metrics.rows_failed,
                    "success_rate_pct": self._metrics.success_rate_pct,
                },
            )
        except Exception as persist_exc:
            logger.error(
                "PipelineMonitor.__exit__ persistence failed (non-fatal): %s",
                persist_exc,
            )
        finally:
            self._json_logger.uninstall()

        logger.info(
            "PipelineMonitor finished | run_id=%s | status=%s | duration=%.1fs | "
            "extracted=%d | loaded=%d | failed=%d | success_rate=%.1f%%",
            self._run_id,
            self._metrics.status.value,
            self._metrics.total_duration_seconds,
            self._metrics.rows_extracted,
            self._metrics.rows_loaded,
            self._metrics.rows_failed,
            self._metrics.success_rate_pct,
        )

        # Never suppress exceptions

    # ──────────────────────────────────────────────────────────────────────────
    # Stage recording methods — called by ETL code or Airflow tasks
    # ──────────────────────────────────────────────────────────────────────────

    def record_extraction(
        self,
        rows_extracted: int,
        duration_ms: float = 0.0,
        source_path: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Record metrics for the extraction stage.

        Args:
            rows_extracted: Number of rows returned by the extractor.
            duration_ms:    Wall-clock time for extraction in milliseconds.
            source_path:    File path or API endpoint (logged for audit).
            extra:          Additional stage-specific metadata.
        """
        self._metrics.rows_extracted = rows_extracted
        self._metrics.extract_duration_ms = duration_ms

        stage = StageMetrics(
            stage_name="extract",
            started_at=self._metrics.started_at,
            rows_in=0,
            rows_out=rows_extracted,
            duration_ms=duration_ms,
            extra={"source_path": source_path, **(extra or {})},
        )
        self._metrics.stage_metrics.append(stage)

        self._json_logger.emit_event(
            "extraction_complete",
            {
                "rows_extracted": rows_extracted,
                "duration_ms": duration_ms,
                "source_path": source_path,
            },
        )
        logger.info(
            "Extraction complete | rows=%d | duration=%.1fms",
            rows_extracted,
            duration_ms,
        )

    def record_transformation(
        self,
        rows_in: int,
        rows_out: int,
        rows_dropped: int = 0,
        duration_ms: float = 0.0,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Record metrics for the transformation stage.

        Args:
            rows_in:      Rows received from extraction.
            rows_out:     Rows after all transformation steps (ready to load).
            rows_dropped: Rows explicitly dropped (invalid title, etc.).
            duration_ms:  Wall-clock time in milliseconds.
        """
        self._metrics.rows_transformed = rows_out
        self._metrics.transform_duration_ms = duration_ms

        stage = StageMetrics(
            stage_name="transform",
            started_at=self._metrics.started_at,
            rows_in=rows_in,
            rows_out=rows_out,
            rows_failed=rows_dropped,
            duration_ms=duration_ms,
            extra=extra or {},
        )
        self._metrics.stage_metrics.append(stage)

        self._json_logger.emit_event(
            "transformation_complete",
            {
                "rows_in": rows_in,
                "rows_out": rows_out,
                "rows_dropped": rows_dropped,
                "drop_pct": (
                    round(rows_dropped / rows_in * 100.0, 2) if rows_in else 0.0
                ),
                "duration_ms": duration_ms,
            },
        )
        logger.info(
            "Transformation complete | in=%d | out=%d | dropped=%d | duration=%.1fms",
            rows_in,
            rows_out,
            rows_dropped,
            duration_ms,
        )

    def record_loading(
        self,
        rows_inserted: int,
        rows_updated: int = 0,
        rows_failed: int = 0,
        duration_ms: float = 0.0,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Record metrics for the loading stage.

        Args:
            rows_inserted: Rows newly inserted into PostgreSQL.
            rows_updated:  Rows updated via UPSERT (existed before, refreshed).
            rows_failed:   Rows that could not be inserted (constraint violations, etc.).
            duration_ms:   Wall-clock time in milliseconds.
        """
        total_loaded = rows_inserted + rows_updated
        self._metrics.rows_loaded = total_loaded
        self._metrics.rows_failed += rows_failed
        self._metrics.load_duration_ms = duration_ms
        self._metrics.db_execution_time_ms += duration_ms

        stage = StageMetrics(
            stage_name="load",
            started_at=self._metrics.started_at,
            rows_in=self._metrics.rows_transformed,
            rows_out=total_loaded,
            rows_failed=rows_failed,
            duration_ms=duration_ms,
            extra={
                "rows_inserted": rows_inserted,
                "rows_updated": rows_updated,
                **(extra or {}),
            },
        )
        self._metrics.stage_metrics.append(stage)

        self._json_logger.emit_event(
            "loading_complete",
            {
                "rows_inserted": rows_inserted,
                "rows_updated": rows_updated,
                "rows_failed": rows_failed,
                "total_loaded": total_loaded,
                "duration_ms": duration_ms,
            },
        )
        logger.info(
            "Loading complete | inserted=%d | updated=%d | failed=%d | duration=%.1fms",
            rows_inserted,
            rows_updated,
            rows_failed,
            duration_ms,
        )

    def record_db_time(self, duration_ms: float) -> None:
        """Add to the cumulative db_execution_time_ms counter.

        Call this for any additional DB operations (e.g., REFRESH MATERIALIZED VIEW)
        that are not tracked by record_loading().

        Args:
            duration_ms: Time spent in PostgreSQL for this operation.
        """
        self._metrics.db_execution_time_ms += duration_ms

    def record_validation_failure(
        self,
        check_name: str,
        critical: bool = False,
        records_failed: int = 0,
    ) -> None:
        """Record that a data quality check failed.

        Args:
            check_name:      Dotted name of the failed check (e.g., "completeness.job_title").
            critical:        True if this failure should halt the pipeline.
            records_failed:  Number of records that failed this check.
        """
        self._metrics.validation_failures += 1
        if critical:
            self._metrics.critical_failures += 1

        self._json_logger.emit_event(
            "validation_failure",
            {
                "check_name": check_name,
                "critical": critical,
                "records_failed": records_failed,
            },
        )
        log_fn = logger.error if critical else logger.warning
        log_fn(
            "Validation failure | check=%s | critical=%s | records_failed=%d",
            check_name,
            critical,
            records_failed,
        )

    def record_error(
        self,
        stage: str,
        error_type: str,
        message: str,
        severity: ErrorSeverity = ErrorSeverity.WARNING,
        stack_trace: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Record a pipeline error event.

        Creates a PipelineError, appends it to self._metrics.errors,
        persists it to pipeline_errors table, and emits a JSON log event.

        Args:
            stage:       ETL stage where the error occurred (extract/transform/load/validate).
            error_type:  Exception class name or short error code.
            message:     Human-readable description.
            severity:    CRITICAL (stops pipeline) / WARNING (continues).
            stack_trace: Full exception traceback (optional).
            context:     Additional structured context (row index, column, etc.).
        """
        error = PipelineError(
            run_id=self._run_id,
            stage=stage,
            error_type=error_type,
            message=message,
            severity=severity,
            stack_trace=stack_trace,
            context=context or {},
        )
        self._metrics.errors.append(error)

        try:
            self._store.insert_error(error)
        except Exception as exc:
            logger.error("Failed to persist pipeline error to DB (non-fatal): %s", exc)

        self._json_logger.emit_event("pipeline_error", error.to_dict())
        log_fn = logger.error if severity == ErrorSeverity.CRITICAL else logger.warning
        log_fn(
            "Pipeline error | stage=%s | type=%s | severity=%s | msg=%s",
            stage,
            error_type,
            severity.value,
            message,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Stage timer helpers
    # ──────────────────────────────────────────────────────────────────────────

    @contextmanager
    def time_stage(self, stage_name: str) -> Generator[None, None, None]:
        """Context manager to automatically measure the duration of an ETL stage.

        Usage:
            with monitor.time_stage("extract") as t:
                data = extractor.extract(path)
            # After the block, call record_extraction(..., duration_ms=t.elapsed_ms)

        Actually, this context manager just measures time — you still call
        record_extraction/transformation/loading with the elapsed time.

        Usage:
            t0 = time.perf_counter()
            with monitor.time_stage("extract"):
                data = extractor.extract(path)
            elapsed = (time.perf_counter() - t0) * 1000
            monitor.record_extraction(rows_extracted=len(data), duration_ms=elapsed)
        """
        self._stage_timers[stage_name] = time.perf_counter()
        logger.debug("Stage started | stage=%s", stage_name)
        yield
        elapsed_ms = (time.perf_counter() - self._stage_timers[stage_name]) * 1000.0
        logger.debug(
            "Stage complete | stage=%s | duration=%.1fms", stage_name, elapsed_ms
        )

    def get_stage_elapsed_ms(self, stage_name: str) -> float:
        """Return elapsed time in milliseconds since time_stage() was entered.

        Useful when the context manager ends before record_*() is called.
        """
        if stage_name not in self._stage_timers:
            return 0.0
        return (time.perf_counter() - self._stage_timers[stage_name]) * 1000.0

    # ──────────────────────────────────────────────────────────────────────────
    # Snapshot access
    # ──────────────────────────────────────────────────────────────────────────

    @property
    def metrics(self) -> PipelineRunMetrics:
        """Read-only access to the current metrics snapshot."""
        return self._metrics

    @property
    def run_id(self) -> str:
        return self._run_id

    def prometheus_metrics(self) -> str:
        """Return Prometheus text exposition format of current metrics."""
        return self._metrics.to_prometheus_metrics()
