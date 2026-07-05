"""jobpulse.incremental.runner — End-to-end incremental ETL orchestrator.

IncrementalRunner is the single entry-point that orchestrates:

    ┌──────────────────────────────────────────────────────────────┐
    │  1. Load watermark        → determine filter_from timestamp  │
    │  2. Filter DataFrame      → drop rows older than filter_from │
    │  3. Detect changes        → NEW | UPDATED | UNCHANGED        │
    │  4. Load actionable rows  → UPSERT NEW + UPDATED only        │
    │  5. Advance watermark     → only on success                  │
    │  6. Emit structured log   → IncrementalRunSummary            │
    └──────────────────────────────────────────────────────────────┘

The runner does NOT modify extraction or transformation logic.
It wraps the existing pipeline stages at the loading boundary.

═══════════════════════════════════════════════════════════════
  IDEMPOTENCY GUARANTEE
═══════════════════════════════════════════════════════════════
  A pipeline run is idempotent if running it twice with the same
  input produces the same final database state.

  This runner achieves idempotency through three mechanisms:

  1. UPSERT (ON CONFLICT DO UPDATE):
     Re-inserting a row that already exists updates it to the same
     value — the final state is identical.

  2. Watermark not advanced on failure:
     If the pipeline crashes after loading chunk 3 of 10, the
     watermark remains at the previous successful timestamp.
     The next run re-processes from that watermark — chunks 1–3
     are UPSERTed again (idempotent) and chunks 4–10 complete.

  3. Content-hash based skip:
     Re-processing already-loaded rows is detected by the
     ChangeDetector (hash matches → UNCHANGED) and skipped,
     avoiding redundant DB writes.

═══════════════════════════════════════════════════════════════
  LATE-ARRIVING DATA
═══════════════════════════════════════════════════════════════
  The filter applied in step 2 uses watermark.filter_from, which is:
      watermark.last_successful_run_at - timedelta(hours=buffer)

  Example with buffer=24h:
      Run on 2024-07-01 03:00. Last success: 2024-06-30 03:00.
      filter_from = 2024-06-29 03:00.

  Any row with modified_at or posted_date >= 2024-06-29 03:00
  is included in the incremental batch, even if it was originally
  posted on 2024-06-29 (i.e., before the last run).

  This catches jobs that:
    - Were posted before the last run but arrived in the source later
    - Had corrections/updates applied retroactively

═══════════════════════════════════════════════════════════════
  FIRST RUN (no watermark)
═══════════════════════════════════════════════════════════════
  If get_watermark() returns None (no prior successful run),
  the runner performs a FULL LOAD: all rows are passed to the
  IncrementalLoader. The ChangeDetector will classify all as NEW.

  The initial_full_load_since parameter allows restricting the
  initial load to a specific historical window:
      initial_full_load_since = datetime(2024, 1, 1, tzinfo=utc)
  This prevents accidentally loading years of historical data on
  the first run of a new source.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from jobpulse.incremental.loader import IncrementalLoader, IncrementalLoadResult
from jobpulse.incremental.watermark import AbstractWatermarkStore, WatermarkRecord
from jobpulse.logging.logger import get_logger

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Result value object
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class IncrementalRunSummary:
    """Complete record of one incremental ETL run.

    Combines watermark state, filtering stats, change detection, and load
    results into a single audit record that is:
    - Logged as structured JSON
    - Returned to the Airflow task for XCom
    - Used by PipelineMonitor to update pipeline_runs metrics

    Attributes:
        run_id:              Pipeline run identifier.
        source_name:         Data source being processed.
        watermark_before:    Watermark at the start of this run (None if first run).
        watermark_after:     Watermark after this run (None if run failed).
        filter_from:         Effective lower-bound timestamp used for filtering.
        rows_in_extract:     Total rows returned by the extractor.
        rows_after_filter:   Rows remaining after watermark filter.
        rows_filtered_out:   Rows dropped by the watermark filter.
        load_result:         IncrementalLoadResult (change breakdown, counts).
        run_status:          SUCCESS | PARTIAL | FAILED.
        error_message:       Set if an unhandled exception occurred.
        started_at:          UTC timestamp when the runner began.
        completed_at:        UTC timestamp when the runner finished.
        duration_ms:         Total wall-clock time in milliseconds.
    """

    run_id: str
    source_name: str
    watermark_before: WatermarkRecord | None
    watermark_after: datetime | None
    filter_from: datetime | None
    rows_in_extract: int
    rows_after_filter: int
    rows_filtered_out: int
    load_result: IncrementalLoadResult | None
    run_status: str = "SUCCESS"
    error_message: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    completed_at: datetime | None = None
    duration_ms: float = 0.0

    @property
    def is_success(self) -> bool:
        return self.run_status in ("SUCCESS", "PARTIAL")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "source_name": self.source_name,
            "run_status": self.run_status,
            "started_at": self.started_at.isoformat(),
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "duration_ms": round(self.duration_ms, 2),
            "watermark": {
                "before": (
                    self.watermark_before.last_successful_run_at.isoformat()
                    if self.watermark_before
                    else None
                ),
                "after": (
                    self.watermark_after.isoformat() if self.watermark_after else None
                ),
                "filter_from": (
                    self.filter_from.isoformat() if self.filter_from else None
                ),
                "buffer_hours": (
                    self.watermark_before.late_arrival_buffer_hours
                    if self.watermark_before
                    else None
                ),
            },
            "filtering": {
                "rows_in_extract": self.rows_in_extract,
                "rows_after_filter": self.rows_after_filter,
                "rows_filtered_out": self.rows_filtered_out,
            },
            "load": self.load_result.to_dict() if self.load_result else None,
            "error_message": self.error_message,
        }

    def to_log_string(self) -> str:
        load = self.load_result
        return (
            f"source={self.source_name!r} "
            f"status={self.run_status} "
            f"filtered_out={self.rows_filtered_out} "
            + (
                f"new={load.rows_new} updated={load.rows_updated} "
                f"unchanged={load.rows_unchanged} failed={load.rows_failed} "
                if load
                else "no_load "
            )
            + f"duration_ms={self.duration_ms:.0f}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Incremental Runner
# ─────────────────────────────────────────────────────────────────────────────


class IncrementalRunner:
    """Orchestrates a full incremental ETL run for one data source.

    Usage in Airflow task_function:
        runner = IncrementalRunner(
            engine=engine,
            session_factory=session_factory,
            watermark_store=PostgresWatermarkStore(engine),
            source_name="csv_kaggle_jobs",
            run_id=context["run_id"],
        )
        summary = runner.run(transformed_df)
        # summary.load_result has the full change breakdown

    Usage in tests:
        runner = IncrementalRunner(
            engine=engine,
            session_factory=session_factory,
            watermark_store=InMemoryWatermarkStore(),
            source_name="test_source",
            run_id="test-run-001",
        )

    Args:
        engine:                  SQLAlchemy engine for hash store reads/writes.
        session_factory:         Session factory for transactional UPSERT.
        watermark_store:         Where to read/write watermarks.
        source_name:             Data source identifier.
        run_id:                  Current pipeline run identifier.
        chunk_size:              Rows per UPSERT transaction.
        source_job_id_col:       Column holding the job natural key.
        timestamp_col:           Column used for watermark filtering.
                                 Expected to contain datetime values.
                                 Defaults to 'posted_date' — override for
                                 sources that have a 'modified_at' column.
        initial_full_load_since: On first run (no watermark), filter to rows
                                 after this timestamp. None = load everything.
        late_arrival_buffer_hours: Buffer subtracted from watermark for filter.
                                   Overrides the per-source setting if set.
        data_source_id:          FK → data_sources for the jobs table.
    """

    def __init__(
        self,
        engine: Engine,
        session_factory: sessionmaker[Session],
        watermark_store: AbstractWatermarkStore,
        source_name: str,
        run_id: str,
        chunk_size: int = 500,
        source_job_id_col: str = "source_job_id",
        timestamp_col: str = "posted_date",
        initial_full_load_since: datetime | None = None,
        late_arrival_buffer_hours: int | None = None,
        data_source_id: int | None = None,
    ) -> None:
        self._engine = engine
        self._session_factory = session_factory
        self._watermark_store = watermark_store
        self._source_name = source_name
        self._run_id = run_id
        self._chunk_size = chunk_size
        self._id_col = source_job_id_col
        self._ts_col = timestamp_col
        self._initial_since = initial_full_load_since
        self._buffer_override = late_arrival_buffer_hours
        self._data_source_id = data_source_id

        self._loader = IncrementalLoader(
            engine=engine,
            session_factory=session_factory,
            source_name=source_name,
            chunk_size=chunk_size,
            source_job_id_col=source_job_id_col,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Public entry point
    # ─────────────────────────────────────────────────────────────────────────

    def run(
        self,
        df: pd.DataFrame,
        pipeline_run_id: int | None = None,
    ) -> IncrementalRunSummary:
        """Execute a full incremental ETL run.

        Args:
            df:               Transformed DataFrame (full extract output).
            pipeline_run_id:  FK → pipeline_runs for the jobs table.

        Returns:
            IncrementalRunSummary: Complete audit record of this run.
        """
        t0 = time.perf_counter()
        started_at = datetime.now(tz=UTC)
        run_ts = datetime.now(tz=UTC)  # Candidate for new watermark

        logger.info(
            "IncrementalRunner starting | source=%s | run_id=%s | rows_in=%d",
            self._source_name,
            self._run_id,
            len(df),
        )

        # ── Step 1: Read watermark ────────────────────────────────────────────
        watermark = self._watermark_store.get_watermark(self._source_name)
        filter_from = self._resolve_filter_from(watermark)

        logger.info(
            "Watermark resolved | source=%s | filter_from=%s | is_first_run=%s",
            self._source_name,
            filter_from.isoformat() if filter_from else "None (full load)",
            watermark is None,
        )

        # ── Step 2: Filter DataFrame by watermark ────────────────────────────
        rows_in_extract = len(df)
        df_filtered = self._apply_watermark_filter(df, filter_from)
        rows_after_filter = len(df_filtered)
        rows_filtered_out = rows_in_extract - rows_after_filter

        if rows_filtered_out > 0:
            logger.info(
                "Watermark filter applied | dropped=%d rows older than %s",
                rows_filtered_out,
                filter_from.isoformat() if filter_from else "N/A",
            )

        if df_filtered.empty:
            logger.info(
                "No rows remain after watermark filter — nothing to load. "
                "Advancing watermark and exiting."
            )
            # Advance watermark even if no rows — confirms this window was scanned
            self._advance_watermark(run_ts, rows_new=0, rows_updated=0, rows_skipped=0)
            return IncrementalRunSummary(
                run_id=self._run_id,
                source_name=self._source_name,
                watermark_before=watermark,
                watermark_after=run_ts,
                filter_from=filter_from,
                rows_in_extract=rows_in_extract,
                rows_after_filter=0,
                rows_filtered_out=rows_filtered_out,
                load_result=None,
                run_status="SUCCESS",
                started_at=started_at,
                completed_at=datetime.now(tz=UTC),
                duration_ms=(time.perf_counter() - t0) * 1000.0,
            )

        # ── Step 3 + 4: Change detection + UPSERT ────────────────────────────
        load_result: IncrementalLoadResult | None = None
        run_status = "SUCCESS"
        error_msg = None
        watermark_after: datetime | None = None

        try:
            load_result = self._loader.load(
                df=df_filtered,
                run_id=self._run_id,
                data_source_id=self._data_source_id,
                pipeline_run_id=pipeline_run_id,
            )

            if load_result.rows_failed > 0:
                run_status = "PARTIAL"

            # ── Step 5: Advance watermark ONLY on success/partial ─────────────
            self._advance_watermark(
                watermark_ts=run_ts,
                rows_new=load_result.rows_new,
                rows_updated=load_result.rows_updated,
                rows_skipped=load_result.rows_unchanged,
            )
            watermark_after = run_ts

        except Exception as exc:
            run_status = "FAILED"
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.error(
                "IncrementalRunner FAILED | source=%s | error=%s",
                self._source_name,
                error_msg,
            )
            # Watermark is NOT advanced — next run re-processes from old watermark

        duration_ms = (time.perf_counter() - t0) * 1000.0
        completed_at = datetime.now(tz=UTC)

        summary = IncrementalRunSummary(
            run_id=self._run_id,
            source_name=self._source_name,
            watermark_before=watermark,
            watermark_after=watermark_after,
            filter_from=filter_from,
            rows_in_extract=rows_in_extract,
            rows_after_filter=rows_after_filter,
            rows_filtered_out=rows_filtered_out,
            load_result=load_result,
            run_status=run_status,
            error_message=error_msg,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
        )

        logger.info("IncrementalRunner complete | %s", summary.to_log_string())
        return summary

    # ─────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _resolve_filter_from(
        self,
        watermark: WatermarkRecord | None,
    ) -> datetime | None:
        """Determine the lower-bound timestamp for watermark filtering.

        Logic:
          - If watermark exists: use watermark.filter_from (applies buffer).
          - If no watermark (first run): use initial_full_load_since
            (may be None → full historical load).
          - If buffer is overridden in constructor: apply override.

        Args:
            watermark: Current watermark for this source (None if first run).

        Returns:
            datetime: Lower bound (UTC), or None for an unrestricted load.
        """
        if watermark is None:
            if self._initial_since is not None:
                logger.info(
                    "First run: applying initial_full_load_since=%s",
                    self._initial_since.isoformat(),
                )
                return self._initial_since
            logger.info(
                "First run with no initial_full_load_since — full historical load."
            )
            return None

        if self._buffer_override is not None:
            override_filter = watermark.last_successful_run_at - timedelta(
                hours=self._buffer_override
            )
            logger.info(
                "Using buffer_override=%dh → filter_from=%s",
                self._buffer_override,
                override_filter.isoformat(),
            )
            return override_filter

        return watermark.filter_from

    def _apply_watermark_filter(
        self,
        df: pd.DataFrame,
        filter_from: datetime | None,
    ) -> pd.DataFrame:
        """Filter the DataFrame to rows where timestamp_col >= filter_from.

        If filter_from is None → return df unchanged (full load).
        If timestamp_col is not in df → log warning, return df unchanged
        (defensive: don't crash the pipeline over a missing column).

        Args:
            df:          Full transformed DataFrame.
            filter_from: Lower bound for the timestamp filter.

        Returns:
            pd.DataFrame: Filtered (or unchanged) DataFrame.
        """
        if filter_from is None:
            logger.debug("No filter_from — returning all %d rows.", len(df))
            return df

        if self._ts_col not in df.columns:
            logger.warning(
                "Timestamp column '%s' not found in DataFrame — "
                "watermark filter cannot be applied. All %d rows will be processed. "
                "Tip: set timestamp_col= to the correct column name.",
                self._ts_col,
                len(df),
            )
            return df

        # Ensure the timestamp column is datetime with timezone
        ts_series = pd.to_datetime(df[self._ts_col], utc=True, errors="coerce")

        # Make filter_from timezone-aware if it isn't already
        if filter_from.tzinfo is None:
            filter_from = filter_from.replace(tzinfo=UTC)

        mask = ts_series >= filter_from
        filtered = df[mask].reset_index(drop=True)

        logger.info(
            "Watermark filter | col=%s | filter_from=%s | passed=%d | dropped=%d",
            self._ts_col,
            filter_from.isoformat(),
            len(filtered),
            len(df) - len(filtered),
        )
        return filtered

    def _advance_watermark(
        self,
        watermark_ts: datetime,
        rows_new: int,
        rows_updated: int,
        rows_skipped: int,
    ) -> None:
        """Advance the watermark for this source to watermark_ts.

        Called only AFTER a successful (or partial) load.
        Failed runs do NOT call this method.

        Args:
            watermark_ts: The new high-water mark timestamp.
            rows_new:     COUNT of NEW rows loaded in this run.
            rows_updated: COUNT of UPDATED rows loaded in this run.
            rows_skipped: COUNT of UNCHANGED rows skipped.
        """
        try:
            self._watermark_store.set_watermark(
                source_name=self._source_name,
                watermark_ts=watermark_ts,
                run_id=self._run_id,
                rows_new=rows_new,
                rows_updated=rows_updated,
                rows_skipped=rows_skipped,
            )
        except Exception as exc:
            # Watermark write failure is CRITICAL — log loudly but do not
            # crash the pipeline. The data is already in PostgreSQL.
            # The consequence: the next run will reprocess with the old
            # watermark — more work but correct final state (UPSERT is idempotent).
            logger.error(
                "CRITICAL: watermark write failed for source='%s': %s. "
                "Next run will re-process from old watermark. "
                "Data in PostgreSQL is correct.",
                self._source_name,
                exc,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Watermark management helpers (for CLI / Airflow operators)
    # ─────────────────────────────────────────────────────────────────────────

    def reset_watermark(self, to_timestamp: datetime) -> None:
        """Manually reset the watermark for this source.

        Use to force a re-load of recent data without a full historical reload.

        Example:
            # Re-process last 7 days:
            runner.reset_watermark(datetime.now(UTC) - timedelta(days=7))

        Args:
            to_timestamp: The timestamp to reset the watermark to (UTC).
        """
        logger.warning(
            "MANUALLY RESETTING watermark | source=%s | to=%s",
            self._source_name,
            to_timestamp.isoformat(),
        )
        self._watermark_store.set_watermark(
            source_name=self._source_name,
            watermark_ts=to_timestamp,
            run_id=f"manual_reset_{self._run_id}",
        )

    def get_current_watermark(self) -> WatermarkRecord | None:
        """Return the current watermark for this source (or None if first run)."""
        return self._watermark_store.get_watermark(self._source_name)
