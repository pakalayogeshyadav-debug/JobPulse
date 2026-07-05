"""jobpulse.observability.db_store — Persist pipeline metrics to PostgreSQL.

Responsible for:
    1. Creating the pipeline_runs and pipeline_errors tables (DDL)
    2. Inserting / upserting PipelineRunMetrics into pipeline_runs
    3. Inserting PipelineError records into pipeline_errors
    4. Querying historical run summaries for the report generator

Design Decision — Why raw SQL (text()) instead of an ORM model?
    The monitoring tables are observability infrastructure — they are NOT
    part of the job market domain schema. Adding ORM models for them would
    require including them in Base.metadata, which could trigger accidental
    table creation in unrelated migration runs.

    Using text() with explicit DDL:
    - The tables are created by the MetricStore itself (self-contained)
    - No interference with Alembic migrations on the domain tables
    - The DDL is co-located with the insert logic — easier to review
    - Monitoring tables can be on a DIFFERENT PostgreSQL schema/database
      (pass a different engine) without touching the domain models

Design Decision — AbstractMetricStore + PostgresMetricStore (Dependency Inversion)
    PipelineMonitor depends on AbstractMetricStore, not PostgresMetricStore.
    This allows:
    - Unit tests to inject InMemoryMetricStore (no PostgreSQL needed)
    - Future: swap to a time-series store (TimescaleDB, InfluxDB) without
      changing PipelineMonitor at all
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from jobpulse.database.session import db_session
from jobpulse.logging.logger import get_logger
from jobpulse.observability.metrics import (
    PipelineError,
    PipelineRunMetrics,
)

logger = get_logger(__name__)


# =============================================================================
# DDL — Table creation SQL
# =============================================================================

_CREATE_PIPELINE_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS public.pipeline_runs (
    -- Primary key
    run_id              TEXT        NOT NULL PRIMARY KEY,

    -- Identity
    source_name         TEXT        NOT NULL,
    pipeline_version    TEXT        NOT NULL DEFAULT 'unknown',
    environment         TEXT        NOT NULL DEFAULT 'development',

    -- Lifecycle
    status              TEXT        NOT NULL DEFAULT 'RUNNING',
    started_at          TIMESTAMPTZ NOT NULL,
    completed_at        TIMESTAMPTZ,
    total_duration_ms   NUMERIC(12, 2),

    -- Record counts
    rows_extracted      INTEGER     NOT NULL DEFAULT 0,
    rows_transformed    INTEGER     NOT NULL DEFAULT 0,
    rows_loaded         INTEGER     NOT NULL DEFAULT 0,
    rows_failed         INTEGER     NOT NULL DEFAULT 0,
    success_rate_pct    NUMERIC(5, 2),

    -- Data quality
    validation_failures INTEGER     NOT NULL DEFAULT 0,
    critical_failures   INTEGER     NOT NULL DEFAULT 0,

    -- Stage timing (ms)
    extract_duration_ms  NUMERIC(12, 2),
    transform_duration_ms NUMERIC(12, 2),
    load_duration_ms     NUMERIC(12, 2),
    db_execution_time_ms NUMERIC(12, 2),

    -- Full metrics snapshot (enables future schema evolution without migrations)
    metrics_json        JSONB,

    -- Audit
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.pipeline_runs IS
    'One row per ETL pipeline execution. Populated by PipelineMonitor.';

COMMENT ON COLUMN public.pipeline_runs.metrics_json IS
    'Full PipelineRunMetrics snapshot in JSON. Used for detailed drill-down and future fields.';

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS ix_pipeline_runs_source_name
    ON public.pipeline_runs (source_name);

CREATE INDEX IF NOT EXISTS ix_pipeline_runs_status
    ON public.pipeline_runs (status);

CREATE INDEX IF NOT EXISTS ix_pipeline_runs_started_at
    ON public.pipeline_runs (started_at DESC);

-- Partial index: quickly find all failed runs
CREATE INDEX IF NOT EXISTS ix_pipeline_runs_failed
    ON public.pipeline_runs (started_at DESC)
    WHERE status IN ('FAILED', 'PARTIAL');
"""

_CREATE_PIPELINE_ERRORS_TABLE = """
CREATE TABLE IF NOT EXISTS public.pipeline_errors (
    -- Primary key
    error_id            TEXT        NOT NULL PRIMARY KEY,

    -- Foreign key to the run
    run_id              TEXT        NOT NULL
        REFERENCES public.pipeline_runs(run_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,

    -- Error details
    stage               TEXT        NOT NULL,
    error_type          TEXT        NOT NULL,
    message             TEXT        NOT NULL,
    severity            TEXT        NOT NULL DEFAULT 'WARNING',
    occurred_at         TIMESTAMPTZ NOT NULL,

    -- Debug info (not exposed in reports by default — requires explicit query)
    stack_trace         TEXT,
    context_json        JSONB,

    -- Audit
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.pipeline_errors IS
    'One row per error/warning event raised during a pipeline run.';

-- Indexes for alert queries
CREATE INDEX IF NOT EXISTS ix_pipeline_errors_run_id
    ON public.pipeline_errors (run_id);

CREATE INDEX IF NOT EXISTS ix_pipeline_errors_severity
    ON public.pipeline_errors (severity, occurred_at DESC);

CREATE INDEX IF NOT EXISTS ix_pipeline_errors_stage
    ON public.pipeline_errors (stage, occurred_at DESC);
"""


# =============================================================================
# Abstract Interface (Dependency Inversion Principle)
# =============================================================================


class AbstractMetricStore(ABC):
    """Interface for persisting pipeline metrics.

    PipelineMonitor depends on this interface — not on any concrete
    implementation. This enables:
    - PostgresMetricStore  for production
    - InMemoryMetricStore  for unit tests
    - NullMetricStore      for dry-run mode (no writes)
    """

    @abstractmethod
    def ensure_tables(self) -> None:
        """Create the pipeline_runs and pipeline_errors tables if absent."""
        ...

    @abstractmethod
    def upsert_run(self, metrics: PipelineRunMetrics) -> None:
        """Insert or update a pipeline run record.

        WHY upsert (not insert)?
            PipelineMonitor calls this TWICE per run:
            1. At start (status=RUNNING) — creates the row
            2. At finish (status=SUCCESS/FAILED) — updates the row

            Using ON CONFLICT DO UPDATE makes the operation idempotent.
            If the pipeline is interrupted and re-run, the record is
            cleanly updated rather than causing a primary key violation.
        """
        ...

    @abstractmethod
    def insert_error(self, error: PipelineError) -> None:
        """Insert one pipeline error record."""
        ...

    @abstractmethod
    def get_runs_summary(
        self,
        since: datetime,
        source_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch pipeline run summaries for report generation.

        Args:
            since:       Return only runs started after this UTC datetime.
            source_name: Optional filter by source name.

        Returns:
            List of row dicts from pipeline_runs.
        """
        ...


# =============================================================================
# PostgresMetricStore — production implementation
# =============================================================================


class PostgresMetricStore(AbstractMetricStore):
    """Persists pipeline metrics to PostgreSQL.

    Uses a dedicated sessionmaker so monitoring writes are ISOLATED
    from the ETL data writes. This means:
    - A failure in ETL (transaction rollback) does NOT roll back the
      monitoring record — you still have a record of the failed run.
    - Monitoring writes use a short pool timeout (5s) so a slow
      monitoring DB never blocks the ETL pipeline.

    WHY a separate engine for monitoring (not shared with ETL)?
        In production, you may want monitoring data on a DIFFERENT
        database (e.g., a smaller RDS instance or a TimescaleDB cluster)
        separate from the job market data warehouse. Accepting a separate
        engine here makes this refactor trivial — no code changes needed.

    Args:
        engine: SQLAlchemy Engine connected to the monitoring database.
                Can be the same engine as the ETL database or a different one.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._session_factory: sessionmaker[Session] = sessionmaker(
            bind=engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )

    def ensure_tables(self) -> None:
        """Create pipeline_runs and pipeline_errors tables (idempotent — IF NOT EXISTS).

        Call this once at pipeline startup, before any metrics are written.
        Safe to call on every startup — will not re-create existing tables.
        """
        logger.info("Ensuring monitoring tables exist...")
        with self._engine.begin() as conn:
            conn.execute(text(_CREATE_PIPELINE_RUNS_TABLE))
            conn.execute(text(_CREATE_PIPELINE_ERRORS_TABLE))
        logger.info("Monitoring tables ready.")

    def upsert_run(self, metrics: PipelineRunMetrics) -> None:
        """Insert or update a pipeline_runs row.

        Uses ON CONFLICT DO UPDATE (PostgreSQL UPSERT) so the operation
        is idempotent — safe to call at start (status=RUNNING) and at
        finish (status=SUCCESS/FAILED) without primary key violations.
        """
        logger.debug(
            "Upserting pipeline_runs | run_id=%s | status=%s",
            metrics.run_id,
            metrics.status.value,
        )
        sql = text("""
            INSERT INTO public.pipeline_runs (
                run_id,             source_name,          pipeline_version,
                environment,        status,               started_at,
                completed_at,       total_duration_ms,
                rows_extracted,     rows_transformed,     rows_loaded,
                rows_failed,        success_rate_pct,
                validation_failures, critical_failures,
                extract_duration_ms, transform_duration_ms, load_duration_ms,
                db_execution_time_ms, metrics_json
            ) VALUES (
                :run_id,            :source_name,         :pipeline_version,
                :environment,       :status,              :started_at,
                :completed_at,      :total_duration_ms,
                :rows_extracted,    :rows_transformed,    :rows_loaded,
                :rows_failed,       :success_rate_pct,
                :validation_failures, :critical_failures,
                :extract_duration_ms, :transform_duration_ms, :load_duration_ms,
                :db_execution_time_ms, :metrics_json
            )
            ON CONFLICT (run_id) DO UPDATE SET
                status               = EXCLUDED.status,
                completed_at         = EXCLUDED.completed_at,
                total_duration_ms    = EXCLUDED.total_duration_ms,
                rows_extracted       = EXCLUDED.rows_extracted,
                rows_transformed     = EXCLUDED.rows_transformed,
                rows_loaded          = EXCLUDED.rows_loaded,
                rows_failed          = EXCLUDED.rows_failed,
                success_rate_pct     = EXCLUDED.success_rate_pct,
                validation_failures  = EXCLUDED.validation_failures,
                critical_failures    = EXCLUDED.critical_failures,
                extract_duration_ms  = EXCLUDED.extract_duration_ms,
                transform_duration_ms = EXCLUDED.transform_duration_ms,
                load_duration_ms     = EXCLUDED.load_duration_ms,
                db_execution_time_ms = EXCLUDED.db_execution_time_ms,
                metrics_json         = EXCLUDED.metrics_json
        """)

        params: dict[str, Any] = {
            "run_id": metrics.run_id,
            "source_name": metrics.source_name,
            "pipeline_version": metrics.pipeline_version,
            "environment": metrics.environment,
            "status": metrics.status.value,
            "started_at": metrics.started_at,
            "completed_at": metrics.completed_at,
            "total_duration_ms": round(metrics.total_duration_ms, 2),
            "rows_extracted": metrics.rows_extracted,
            "rows_transformed": metrics.rows_transformed,
            "rows_loaded": metrics.rows_loaded,
            "rows_failed": metrics.rows_failed,
            "success_rate_pct": round(metrics.success_rate_pct, 2),
            "validation_failures": metrics.validation_failures,
            "critical_failures": metrics.critical_failures,
            "extract_duration_ms": round(metrics.extract_duration_ms, 2),
            "transform_duration_ms": round(metrics.transform_duration_ms, 2),
            "load_duration_ms": round(metrics.load_duration_ms, 2),
            "db_execution_time_ms": round(metrics.db_execution_time_ms, 2),
            "metrics_json": json.dumps(metrics.to_dict(), default=str),
        }

        with db_session(self._session_factory) as session:
            session.execute(sql, params)

        logger.debug("pipeline_runs upserted | run_id=%s", metrics.run_id)

    def insert_error(self, error: PipelineError) -> None:
        """Insert one error event into pipeline_errors."""
        logger.debug(
            "Inserting pipeline_error | run_id=%s | type=%s",
            error.run_id,
            error.error_type,
        )
        sql = text("""
            INSERT INTO public.pipeline_errors (
                error_id,   run_id,     stage,      error_type,
                message,    severity,   occurred_at, stack_trace, context_json
            ) VALUES (
                :error_id,  :run_id,    :stage,     :error_type,
                :message,   :severity,  :occurred_at, :stack_trace, :context_json
            )
            ON CONFLICT (error_id) DO NOTHING
        """)

        with db_session(self._session_factory) as session:
            session.execute(
                sql,
                {
                    "error_id": error.error_id,
                    "run_id": error.run_id,
                    "stage": error.stage,
                    "error_type": error.error_type,
                    "message": error.message,
                    "severity": error.severity.value,
                    "occurred_at": error.occurred_at,
                    "stack_trace": error.stack_trace,
                    "context_json": json.dumps(error.context, default=str),
                },
            )

    def get_runs_summary(
        self,
        since: datetime,
        source_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch pipeline run summaries for a date range.

        Args:
            since:       Lower bound on started_at (inclusive).
            source_name: Optional filter.

        Returns:
            list[dict]: Rows from pipeline_runs as plain dicts.
        """
        filters = "WHERE started_at >= :since"
        params: dict[str, Any] = {"since": since}
        if source_name:
            filters += " AND source_name = :source_name"
            params["source_name"] = source_name

        sql = text(f"""
            SELECT
                run_id, source_name, status, started_at, completed_at,
                total_duration_ms, rows_extracted, rows_loaded, rows_failed,
                success_rate_pct, validation_failures, critical_failures
            FROM public.pipeline_runs
            {filters}
            ORDER BY started_at DESC
        """)  # noqa: S608 — parameterised; source_name is safe

        with self._engine.connect() as conn:
            result = conn.execute(sql, params)
            return [dict(row._mapping) for row in result]


# =============================================================================
# InMemoryMetricStore — for unit tests
# =============================================================================


class InMemoryMetricStore(AbstractMetricStore):
    """In-memory implementation of AbstractMetricStore for unit testing.

    Stores all metrics in plain Python lists — no database required.
    Allows tests to assert on what was recorded without mocking.

    Usage in tests:
        store = InMemoryMetricStore()
        monitor = PipelineMonitor(run_id="test-1", ..., metric_store=store)
        with monitor:
            monitor.record_extraction(rows_extracted=100)

        assert store.runs[0].rows_extracted == 100
        assert store.runs[0].status == PipelineStatus.SUCCESS
    """

    def __init__(self) -> None:
        self.runs: list[PipelineRunMetrics] = []
        self.errors: list[PipelineError] = []

    def ensure_tables(self) -> None:
        """No-op for in-memory store."""
        pass

    def upsert_run(self, metrics: PipelineRunMetrics) -> None:
        """Replace existing record with same run_id, or append new."""
        for i, existing in enumerate(self.runs):
            if existing.run_id == metrics.run_id:
                self.runs[i] = metrics
                return
        self.runs.append(metrics)

    def insert_error(self, error: PipelineError) -> None:
        self.errors.append(error)

    def get_runs_summary(
        self,
        since: datetime,
        source_name: str | None = None,
    ) -> list[dict[str, Any]]:
        results = [
            r.to_dict()
            for r in self.runs
            if r.started_at >= since
            and (source_name is None or r.source_name == source_name)
        ]
        return results
