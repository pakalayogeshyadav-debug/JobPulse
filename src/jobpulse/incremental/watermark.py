"""jobpulse.incremental.watermark — ETL watermark management.

A "watermark" is the high-water mark of successfully processed data for
one data source. It is the answer to the question:
    "What is the last point in time from which we know all data has been
     successfully loaded into the warehouse?"

The watermark advances only on SUCCESSFUL pipeline completion. If a run
fails, the watermark is NOT advanced — the next run will reprocess from
the previous good watermark, guaranteeing no data is silently skipped.

═══════════════════════════════════════════════════════════════
  WHY A DEDICATED WATERMARK TABLE (not pipeline_runs)?
═══════════════════════════════════════════════════════════════
  pipeline_runs already stores started_at/completed_at but:
  1. It stores ALL runs (succeeded and failed).
     A failed run's completed_at must NOT be used as a watermark.
  2. Querying "last successful run" requires a filtered MAX() join
     every time the extractor calls for the watermark.
  3. The watermark table is write-tiny (1 row per source, updated once
     per run) and read-constant (1 SELECT per source per run).
     This schema is optimal for a high-frequency cache pattern.

═══════════════════════════════════════════════════════════════
  IDEMPOTENCY GUARANTEE
═══════════════════════════════════════════════════════════════
  set_watermark() uses INSERT ... ON CONFLICT DO UPDATE (UPSERT).
  Running set_watermark() twice with the same arguments is safe —
  the second call is a no-op in effect (it sets the same value again).
  This means Airflow task retries after a watermark write cannot
  corrupt the watermark by writing it twice.

═══════════════════════════════════════════════════════════════
  LATE-ARRIVING DATA
═══════════════════════════════════════════════════════════════
  The WatermarkRecord includes a late_arrival_buffer_hours field.
  The IncrementalRunner subtracts this buffer from the watermark
  before using it as a filter lower-bound:

      filter_from = watermark_ts - timedelta(hours=late_arrival_buffer_hours)

  Example: watermark = 2024-06-29 03:00, buffer = 24h
      filter_from = 2024-06-28 03:00

  This means records that were posted on 2024-06-28 but arrived in
  the source on 2024-06-29 are still picked up by the next run,
  even though they are "old" by posting_date.

  The trade-off: larger buffers → more rows re-examined → slower runs.
  Default: 24 hours. Production tuning: match the SLA of your slowest
  upstream data provider.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, text

from jobpulse.logging.logger import get_logger

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# DDL
# ─────────────────────────────────────────────────────────────────────────────

_CREATE_ETL_WATERMARKS_TABLE = """
CREATE TABLE IF NOT EXISTS public.etl_watermarks (
    -- One row per data source. The primary key is the source name.
    source_name             TEXT        NOT NULL PRIMARY KEY,

    -- The high-water mark: last successful ETL run timestamp for this source.
    -- Only updated on SUCCESS. Failed runs do NOT advance the watermark.
    last_successful_run_at  TIMESTAMPTZ NOT NULL,

    -- The pipeline run_id that produced this watermark.
    -- Useful for tracing: "which run set the current watermark?"
    set_by_run_id           TEXT,

    -- Configurable late-arrival buffer in hours.
    -- The incremental filter uses: filter_from = watermark - this buffer.
    late_arrival_buffer_hours INTEGER NOT NULL DEFAULT 24,

    -- How many rows were NEW vs UPDATED in the run that set this watermark.
    rows_new_in_last_run     INTEGER NOT NULL DEFAULT 0,
    rows_updated_in_last_run INTEGER NOT NULL DEFAULT 0,
    rows_skipped_in_last_run INTEGER NOT NULL DEFAULT 0,

    -- Free-form JSON for source-specific state (e.g., API cursor, page token).
    extra_state             JSONB,

    -- Standard audit columns
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.etl_watermarks IS
    'ETL high-water marks — one row per data source. '
    'Watermark advances only on successful pipeline completion.';

COMMENT ON COLUMN public.etl_watermarks.last_successful_run_at IS
    'UTC timestamp of the last SUCCESSFUL load for this source. '
    'The next incremental run filters rows with: '
    'modified_at >= (last_successful_run_at - late_arrival_buffer_hours).';

-- Track all historical watermark changes for audit / rollback
CREATE TABLE IF NOT EXISTS public.etl_watermark_history (
    history_id              BIGSERIAL   PRIMARY KEY,
    source_name             TEXT        NOT NULL,
    watermark_ts            TIMESTAMPTZ NOT NULL,
    set_by_run_id           TEXT,
    rows_new                INTEGER     NOT NULL DEFAULT 0,
    rows_updated            INTEGER     NOT NULL DEFAULT 0,
    rows_skipped            INTEGER     NOT NULL DEFAULT 0,
    recorded_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.etl_watermark_history IS
    'Append-only log of every watermark advancement. '
    'Enables rollback: set etl_watermarks.last_successful_run_at '
    'to a previous history_id value to replay from that point.';

CREATE INDEX IF NOT EXISTS ix_watermark_history_source
    ON public.etl_watermark_history (source_name, recorded_at DESC);

-- Content-hash table — stores SHA-256 of job content to detect updates
CREATE TABLE IF NOT EXISTS public.job_content_hashes (
    -- Natural key: source_job_id scoped to its data source
    source_job_id   TEXT    NOT NULL,
    source_name     TEXT    NOT NULL,

    -- SHA-256 hex digest of the canonical content columns
    content_hash    TEXT    NOT NULL,

    -- When this hash was first computed (= when we first saw this job)
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- When the hash was last updated (= last time the job content changed)
    last_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- How many times this job's content has changed
    update_count    INTEGER NOT NULL DEFAULT 0,

    PRIMARY KEY (source_job_id, source_name)
);

COMMENT ON TABLE public.job_content_hashes IS
    'SHA-256 content fingerprints for every known job posting. '
    'Used by the incremental ETL to detect true updates vs. identical re-delivers.';

CREATE INDEX IF NOT EXISTS ix_job_hashes_source
    ON public.job_content_hashes (source_name);
"""


# ─────────────────────────────────────────────────────────────────────────────
# Value Object
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class WatermarkRecord:
    """Immutable snapshot of a watermark for one data source.

    Attributes:
        source_name:              Data source identifier (e.g., "csv_kaggle_jobs").
        last_successful_run_at:   UTC timestamp of the last successful ETL run.
        set_by_run_id:            The run_id that last advanced this watermark.
        late_arrival_buffer_hours: Hours subtracted from watermark for filter.
        rows_new_in_last_run:     NEW rows recorded in the last run.
        rows_updated_in_last_run: UPDATED rows recorded in the last run.
        rows_skipped_in_last_run: UNCHANGED rows skipped in the last run.
        extra_state:              Source-specific state (API cursor, etc.).
    """

    source_name: str
    last_successful_run_at: datetime
    set_by_run_id: str | None = None
    late_arrival_buffer_hours: int = 24
    rows_new_in_last_run: int = 0
    rows_updated_in_last_run: int = 0
    rows_skipped_in_last_run: int = 0
    extra_state: dict[str, Any] = field(default_factory=dict)

    @property
    def filter_from(self) -> datetime:
        """The effective lower-bound timestamp for incremental filtering.

        Subtracts the late-arrival buffer so delayed records are not missed.
        This is the timestamp passed to the extractor:
            "Give me all rows where source_modified_at >= filter_from"

        Returns:
            datetime: UTC timestamp (watermark minus buffer).
        """
        return self.last_successful_run_at - timedelta(
            hours=self.late_arrival_buffer_hours
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "last_successful_run_at": self.last_successful_run_at.isoformat(),
            "filter_from": self.filter_from.isoformat(),
            "set_by_run_id": self.set_by_run_id,
            "late_arrival_buffer_hours": self.late_arrival_buffer_hours,
            "rows_new_in_last_run": self.rows_new_in_last_run,
            "rows_updated_in_last_run": self.rows_updated_in_last_run,
            "rows_skipped_in_last_run": self.rows_skipped_in_last_run,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Abstract Interface
# ─────────────────────────────────────────────────────────────────────────────


class AbstractWatermarkStore(ABC):
    """Interface for reading and writing ETL watermarks.

    Concrete implementations:
        PostgresWatermarkStore  — production (etl_watermarks table)
        InMemoryWatermarkStore  — unit tests (Python dict)
    """

    @abstractmethod
    def ensure_tables(self) -> None:
        """Create watermark, history, and content-hash tables if absent."""
        ...

    @abstractmethod
    def get_watermark(self, source_name: str) -> WatermarkRecord | None:
        """Retrieve the current watermark for a data source.

        Args:
            source_name: Identifier of the data source.

        Returns:
            WatermarkRecord if a watermark exists, None if this is the
            first run for this source (no prior successful load).

        WHY return None (not a sentinel timestamp)?
            Returning None forces the caller to explicitly decide what to
            do on the first run — typically a full historical load from
            the earliest possible date. A sentinel like epoch (1970-01-01)
            would silently cause a full reload on first run, which might
            be surprising for large historical datasets.
        """
        ...

    @abstractmethod
    def set_watermark(
        self,
        source_name: str,
        watermark_ts: datetime,
        run_id: str | None = None,
        rows_new: int = 0,
        rows_updated: int = 0,
        rows_skipped: int = 0,
        extra_state: dict[str, Any] | None = None,
    ) -> None:
        """Advance the watermark for a source to the given timestamp.

        MUST be called only after a SUCCESSFUL pipeline run.
        MUST be idempotent (calling twice with same args is safe).

        Args:
            source_name:  Data source identifier.
            watermark_ts: The new high-water mark (UTC).
            run_id:       The run that is setting this watermark.
            rows_new:     Count of NEW rows in this run.
            rows_updated: Count of UPDATED rows in this run.
            rows_skipped: Count of UNCHANGED rows skipped.
            extra_state:  Optional source-specific state to persist.
        """
        ...

    @abstractmethod
    def get_all_watermarks(self) -> list[WatermarkRecord]:
        """Return all watermark records (for dashboards / health checks)."""
        ...

    @abstractmethod
    def rollback_watermark(
        self,
        source_name: str,
        history_id: int,
    ) -> bool:
        """Roll back a source's watermark to a historical entry.

        This is the "undo" operation. If a bad pipeline run corrupted data,
        you can roll back the watermark to a prior good point and re-run.

        Args:
            source_name: Source to roll back.
            history_id:  The etl_watermark_history.history_id to roll back to.

        Returns:
            bool: True if rollback succeeded, False if history_id not found.
        """
        ...


# ─────────────────────────────────────────────────────────────────────────────
# PostgreSQL implementation
# ─────────────────────────────────────────────────────────────────────────────


class PostgresWatermarkStore(AbstractWatermarkStore):
    """PostgreSQL-backed watermark store.

    Uses a dedicated session (NOT the ETL session) so watermark writes
    are committed independently from ETL data writes.

    WHY an isolated transaction?
        If the ETL transaction is rolled back (bulk insert failure),
        we do NOT want the watermark write to be rolled back too.
        A rolled-back watermark would cause the next run to re-scan
        from the old watermark — correct behaviour. But if we wrote
        the watermark inside the ETL transaction, a partial failure
        (e.g., chunk 3 of 10 fails) would roll back the watermark even
        though chunks 1–2 were committed. The watermark must reflect
        "everything up to here is safely in the DB."

        Solution: The watermark write uses its own connection.begin()
        that commits independently of any ongoing ETL transaction.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def ensure_tables(self) -> None:
        """Create etl_watermarks, etl_watermark_history, job_content_hashes."""
        logger.info("Ensuring incremental ETL tables exist...")
        with self._engine.begin() as conn:
            conn.execute(text(_CREATE_ETL_WATERMARKS_TABLE))
        logger.info("Incremental ETL tables ready.")

    def get_watermark(self, source_name: str) -> WatermarkRecord | None:
        """Read the current watermark for source_name. Returns None if first run."""
        sql = text("""
            SELECT
                source_name,
                last_successful_run_at,
                set_by_run_id,
                late_arrival_buffer_hours,
                rows_new_in_last_run,
                rows_updated_in_last_run,
                rows_skipped_in_last_run,
                extra_state
            FROM public.etl_watermarks
            WHERE source_name = :source_name
        """)
        with self._engine.connect() as conn:
            row = conn.execute(sql, {"source_name": source_name}).mappings().first()

        if row is None:
            logger.info(
                "No watermark found for source '%s' — this appears to be a first run.",
                source_name,
            )
            return None

        ts = row["last_successful_run_at"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)

        wm = WatermarkRecord(
            source_name=row["source_name"],
            last_successful_run_at=ts,
            set_by_run_id=row["set_by_run_id"],
            late_arrival_buffer_hours=row["late_arrival_buffer_hours"],
            rows_new_in_last_run=row["rows_new_in_last_run"] or 0,
            rows_updated_in_last_run=row["rows_updated_in_last_run"] or 0,
            rows_skipped_in_last_run=row["rows_skipped_in_last_run"] or 0,
            extra_state=row["extra_state"] or {},
        )
        logger.info(
            "Watermark loaded | source=%s | last_run=%s | filter_from=%s",
            source_name,
            wm.last_successful_run_at.isoformat(),
            wm.filter_from.isoformat(),
        )
        return wm

    def set_watermark(
        self,
        source_name: str,
        watermark_ts: datetime,
        run_id: str | None = None,
        rows_new: int = 0,
        rows_updated: int = 0,
        rows_skipped: int = 0,
        extra_state: dict[str, Any] | None = None,
    ) -> None:
        """Advance the watermark for source_name to watermark_ts.

        Uses INSERT ... ON CONFLICT DO UPDATE (UPSERT) for idempotency.
        Appends a record to etl_watermark_history for audit/rollback.
        """
        logger.info(
            "Advancing watermark | source=%s | ts=%s | new=%d | updated=%d | skipped=%d",
            source_name,
            watermark_ts.isoformat(),
            rows_new,
            rows_updated,
            rows_skipped,
        )

        upsert_sql = text("""
            INSERT INTO public.etl_watermarks (
                source_name, last_successful_run_at, set_by_run_id,
                rows_new_in_last_run, rows_updated_in_last_run,
                rows_skipped_in_last_run, extra_state, updated_at
            ) VALUES (
                :source_name, :watermark_ts, :run_id,
                :rows_new, :rows_updated, :rows_skipped,
                :extra_state, NOW()
            )
            ON CONFLICT (source_name) DO UPDATE SET
                last_successful_run_at  = EXCLUDED.last_successful_run_at,
                set_by_run_id           = EXCLUDED.set_by_run_id,
                rows_new_in_last_run    = EXCLUDED.rows_new_in_last_run,
                rows_updated_in_last_run = EXCLUDED.rows_updated_in_last_run,
                rows_skipped_in_last_run = EXCLUDED.rows_skipped_in_last_run,
                extra_state             = EXCLUDED.extra_state,
                updated_at              = NOW()
        """)

        history_sql = text("""
            INSERT INTO public.etl_watermark_history
                (source_name, watermark_ts, set_by_run_id,
                 rows_new, rows_updated, rows_skipped)
            VALUES
                (:source_name, :watermark_ts, :run_id,
                 :rows_new, :rows_updated, :rows_skipped)
        """)

        params: dict[str, Any] = {
            "source_name": source_name,
            "watermark_ts": watermark_ts,
            "run_id": run_id,
            "rows_new": rows_new,
            "rows_updated": rows_updated,
            "rows_skipped": rows_skipped,
            "extra_state": json.dumps(extra_state or {}),
        }

        # Both writes in the same transaction — they sink or swim together
        with self._engine.begin() as conn:
            conn.execute(upsert_sql, params)
            conn.execute(history_sql, params)

        logger.info(
            "Watermark advanced for source '%s' to %s.",
            source_name,
            watermark_ts.isoformat(),
        )

    def get_all_watermarks(self) -> list[WatermarkRecord]:
        """Return all watermark records, ordered by source_name."""
        sql = text("""
            SELECT
                source_name, last_successful_run_at, set_by_run_id,
                late_arrival_buffer_hours,
                rows_new_in_last_run, rows_updated_in_last_run,
                rows_skipped_in_last_run, extra_state
            FROM public.etl_watermarks
            ORDER BY source_name
        """)
        records = []
        with self._engine.connect() as conn:
            for row in conn.execute(sql).mappings():
                ts = row["last_successful_run_at"]
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                records.append(
                    WatermarkRecord(
                        source_name=row["source_name"],
                        last_successful_run_at=ts,
                        set_by_run_id=row["set_by_run_id"],
                        late_arrival_buffer_hours=row["late_arrival_buffer_hours"],
                        rows_new_in_last_run=row["rows_new_in_last_run"] or 0,
                        rows_updated_in_last_run=row["rows_updated_in_last_run"] or 0,
                        rows_skipped_in_last_run=row["rows_skipped_in_last_run"] or 0,
                        extra_state=row["extra_state"] or {},
                    )
                )
        return records

    def rollback_watermark(self, source_name: str, history_id: int) -> bool:
        """Roll back a source's watermark to a specific history entry.

        Usage:
            store.rollback_watermark("csv_kaggle_jobs", history_id=42)

        This sets etl_watermarks.last_successful_run_at to the timestamp
        stored in etl_watermark_history WHERE history_id = 42.
        The next incremental run will reprocess from that earlier point.

        Returns:
            bool: True if rollback succeeded, False if history_id not found.
        """
        # Fetch the historical entry
        fetch_sql = text("""
            SELECT watermark_ts, set_by_run_id
            FROM public.etl_watermark_history
            WHERE history_id = :history_id AND source_name = :source_name
        """)
        with self._engine.connect() as conn:
            row = (
                conn.execute(
                    fetch_sql,
                    {"history_id": history_id, "source_name": source_name},
                )
                .mappings()
                .first()
            )

        if row is None:
            logger.warning(
                "Rollback failed: history_id=%d not found for source='%s'.",
                history_id,
                source_name,
            )
            return False

        rollback_ts: datetime = row["watermark_ts"]
        logger.warning(
            "ROLLING BACK watermark | source=%s | from=current | to=%s | history_id=%d",
            source_name,
            rollback_ts.isoformat(),
            history_id,
        )
        self.set_watermark(
            source_name=source_name,
            watermark_ts=rollback_ts,
            run_id=f"rollback_to_history_{history_id}",
        )
        return True


# ─────────────────────────────────────────────────────────────────────────────
# In-memory implementation (tests)
# ─────────────────────────────────────────────────────────────────────────────


class InMemoryWatermarkStore(AbstractWatermarkStore):
    """In-memory watermark store for unit tests.

    Thread-safe for single-threaded tests. Does not require PostgreSQL.

    Usage in tests:
        store = InMemoryWatermarkStore()
        # Seed a watermark for testing incremental logic:
        store.set_watermark("csv", datetime(2024, 6, 29, tzinfo=timezone.utc))
        wm = store.get_watermark("csv")
        assert wm.filter_from < datetime(2024, 6, 29, tzinfo=timezone.utc)
    """

    def __init__(self) -> None:
        self._watermarks: dict[str, WatermarkRecord] = {}
        self._history: list[dict[str, Any]] = []
        self._hashes: dict[tuple[str, str], str] = {}  # (job_id, source) → hash

    def ensure_tables(self) -> None:
        pass  # no-op for in-memory

    def get_watermark(self, source_name: str) -> WatermarkRecord | None:
        return self._watermarks.get(source_name)

    def set_watermark(
        self,
        source_name: str,
        watermark_ts: datetime,
        run_id: str | None = None,
        rows_new: int = 0,
        rows_updated: int = 0,
        rows_skipped: int = 0,
        extra_state: dict[str, Any] | None = None,
    ) -> None:
        wm = WatermarkRecord(
            source_name=source_name,
            last_successful_run_at=watermark_ts,
            set_by_run_id=run_id,
            rows_new_in_last_run=rows_new,
            rows_updated_in_last_run=rows_updated,
            rows_skipped_in_last_run=rows_skipped,
            extra_state=extra_state or {},
        )
        self._watermarks[source_name] = wm
        self._history.append(
            {
                "source_name": source_name,
                "watermark_ts": watermark_ts,
                "run_id": run_id,
                "rows_new": rows_new,
                "rows_updated": rows_updated,
                "rows_skipped": rows_skipped,
                "recorded_at": datetime.now(tz=UTC),
                "history_id": len(self._history) + 1,
            }
        )

    def get_all_watermarks(self) -> list[WatermarkRecord]:
        return list(self._watermarks.values())

    def rollback_watermark(self, source_name: str, history_id: int) -> bool:
        entry = next(
            (
                h
                for h in self._history
                if h["source_name"] == source_name and h["history_id"] == history_id
            ),
            None,
        )
        if entry is None:
            return False
        self.set_watermark(
            source_name=source_name,
            watermark_ts=entry["watermark_ts"],
            run_id=f"rollback_to_history_{history_id}",
        )
        return True

    # Extra helpers for test assertions
    def get_history(self, source_name: str) -> list[dict[str, Any]]:
        return [h for h in self._history if h["source_name"] == source_name]
