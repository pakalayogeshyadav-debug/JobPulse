"""jobpulse.incremental.loader — Incremental loader for JobPulse.

Wraps the existing PostgreSQL UPSERT pattern with:
  1. Change-awareness: only loads rows classified as NEW or UPDATED.
  2. Duplicate deduplication: handles duplicate source_job_ids within
     the same batch (keeps the first occurrence — source ordering is trusted).
  3. Detailed result reporting: breaks rows_loaded into new vs updated.
  4. Hash persistence: updates job_content_hashes after a successful load.

Design Decision — Composition over Inheritance
    IncrementalLoader does NOT extend BaseLoader. It WRAPS the existing
    loading pattern (using raw SQLAlchemy text() UPSERT) instead.

    WHY not extend BaseLoader?
        BaseLoader.load_chunk() is already defined and tested. The existing
        postgres_loader.py is still a stub (NotImplementedError). We implement
        the full production UPSERT here, using the same SQLAlchemy dialect-
        specific INSERT ... ON CONFLICT DO UPDATE syntax documented in postgres_loader.py.

        This avoids the "inherit and override" trap that would create tight
        coupling between BaseLoader's template method and the incremental logic.

Design Decision — Separate transactions for NEW vs UPDATED
    All rows (NEW and UPDATED) go into the SAME UPSERT statement
    (INSERT ... ON CONFLICT DO UPDATE). PostgreSQL's UPSERT is atomic
    at the statement level — there is no benefit to separating them.
    Counting new vs updated is done by examining xmax:
        xmax = 0  → the row was inserted (NEW)
        xmax > 0  → the row was updated (UPDATED)
    This is a PostgreSQL-internal implementation detail but is reliable
    and widely used for tracking UPSERT outcomes without triggers.

Design Decision — Idempotent duplicate handling
    The same source_job_id may appear TWICE in one batch (e.g., a data
    source sends duplicates). Loading both would produce a PostgreSQL
    "duplicate key" error BEFORE the ON CONFLICT clause applies, because
    PostgreSQL evaluates uniqueness within the VALUES list.

    Solution: deduplicate in Python before hitting the DB.
    Strategy: keep the FIRST occurrence (sources typically deliver
    the most recent version first, but this is configurable).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from jobpulse.database.session import db_session
from jobpulse.incremental.change_detector import ChangeDetectionResult, ChangeDetector
from jobpulse.loading.base import DataLoadingError
from jobpulse.logging.logger import get_logger

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Result Value Object
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class IncrementalLoadResult:
    """Immutable summary of one incremental load operation.

    Extends the information in LoadingResult with change-classification
    breakdown (how many were NEW vs UPDATED) and skip statistics.

    Attributes:
        source_name:        Data source that was loaded.
        rows_in:            Total rows received from transformation.
        rows_new:           Rows that were genuinely new (INSERT).
        rows_updated:       Rows that were modified (UPSERT → UPDATE path).
        rows_unchanged:     Rows skipped because content hash matched.
        rows_duplicate:     Intra-batch duplicates deduplicated before load.
        rows_failed:        Rows that caused DB errors and were not loaded.
        chunks_loaded:      Number of committed transaction chunks.
        change_detection_ms: Time spent classifying rows.
        load_duration_ms:   Time spent in PostgreSQL.
        started_at:         UTC timestamp when the load began.
        completed_at:       UTC timestamp when the load finished.
    """

    source_name: str
    rows_in: int
    rows_new: int
    rows_updated: int
    rows_unchanged: int
    rows_duplicate: int
    rows_failed: int
    chunks_loaded: int
    change_detection_ms: float
    load_duration_ms: float
    started_at: datetime
    completed_at: datetime

    @property
    def rows_loaded(self) -> int:
        return self.rows_new + self.rows_updated

    @property
    def total_duration_ms(self) -> float:
        delta = self.completed_at - self.started_at
        return delta.total_seconds() * 1000.0

    @property
    def skip_rate_pct(self) -> float:
        if self.rows_in == 0:
            return 0.0
        return round(self.rows_unchanged / self.rows_in * 100.0, 2)

    @property
    def success_rate_pct(self) -> float:
        attempted = self.rows_new + self.rows_updated + self.rows_failed
        if attempted == 0:
            return 100.0
        return round((self.rows_new + self.rows_updated) / attempted * 100.0, 2)

    def to_log_string(self) -> str:
        return (
            f"source={self.source_name!r} "
            f"in={self.rows_in} "
            f"new={self.rows_new} "
            f"updated={self.rows_updated} "
            f"unchanged={self.rows_unchanged} "
            f"dup={self.rows_duplicate} "
            f"failed={self.rows_failed} "
            f"skip_rate={self.skip_rate_pct:.1f}% "
            f"load_ms={self.load_duration_ms:.0f} "
            f"detect_ms={self.change_detection_ms:.0f}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "rows_in": self.rows_in,
            "rows_new": self.rows_new,
            "rows_updated": self.rows_updated,
            "rows_unchanged": self.rows_unchanged,
            "rows_duplicate": self.rows_duplicate,
            "rows_failed": self.rows_failed,
            "rows_loaded": self.rows_loaded,
            "chunks_loaded": self.chunks_loaded,
            "skip_rate_pct": self.skip_rate_pct,
            "success_rate_pct": self.success_rate_pct,
            "change_detection_ms": round(self.change_detection_ms, 2),
            "load_duration_ms": round(self.load_duration_ms, 2),
            "total_duration_ms": round(self.total_duration_ms, 2),
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Incremental Loader
# ─────────────────────────────────────────────────────────────────────────────


class IncrementalLoader:
    """Loads only NEW and UPDATED job rows into PostgreSQL.

    Workflow per call to load():
        1. Deduplicate intra-batch duplicates.
        2. Run ChangeDetector to classify NEW / UPDATED / UNCHANGED.
        3. If rows_to_load is empty → return immediately (nothing to do).
        4. Split rows_to_load into chunks.
        5. For each chunk: execute UPSERT with ON CONFLICT DO UPDATE.
        6. After successful load: persist content hashes.
        7. Return IncrementalLoadResult.

    Args:
        engine:              SQLAlchemy engine (for UPSERT and hash store).
        session_factory:     Session factory for transactional writes.
        source_name:         Data source identifier.
        chunk_size:          Rows per committed transaction. Default: 500.
        source_job_id_col:   Column holding the natural key. Default: 'source_job_id'.
        dedupe_keep:         Which duplicate to keep: 'first' or 'last'. Default: 'first'.
    """

    def __init__(
        self,
        engine: Engine,
        session_factory: sessionmaker[Session],
        source_name: str,
        chunk_size: int = 500,
        source_job_id_col: str = "source_job_id",
        dedupe_keep: str = "first",
    ) -> None:
        self._engine = engine
        self._session_factory = session_factory
        self._source_name = source_name
        self._chunk_size = chunk_size
        self._id_col = source_job_id_col
        self._dedupe_keep = dedupe_keep
        self._detector = ChangeDetector(
            engine=engine,
            source_name=source_name,
            source_job_id_col=source_job_id_col,
        )
        self._logger = get_logger(f"jobpulse.incremental.loader.{source_name}")

    # ─────────────────────────────────────────────────────────────────────────
    # Public entry point
    # ─────────────────────────────────────────────────────────────────────────

    def load(
        self,
        df: pd.DataFrame,
        run_id: str | None = None,
        data_source_id: int | None = None,
        pipeline_run_id: int | None = None,
    ) -> IncrementalLoadResult:
        """Incrementally load a transformed DataFrame into PostgreSQL.

        Args:
            df:               Transformed, validated DataFrame.
            run_id:           Pipeline run identifier (for logging).
            data_source_id:   FK value for jobs.data_source_id.
            pipeline_run_id:  FK value for jobs.pipeline_run_id.

        Returns:
            IncrementalLoadResult: Detailed result including change breakdown.

        Raises:
            DataLoadingError: If a chunk fails and cannot be recovered.
        """
        started_at = datetime.now(tz=UTC)
        rows_in = len(df)

        self._logger.info(
            "Incremental load starting | source=%s | run_id=%s | rows_in=%d",
            self._source_name,
            run_id,
            rows_in,
        )

        # ── Step 1: Deduplicate intra-batch duplicates ────────────────────────
        df_deduped, rows_duplicate = self._deduplicate(df)

        if rows_duplicate > 0:
            self._logger.warning(
                "Dropped %d intra-batch duplicate(s) | source=%s | keep=%s",
                rows_duplicate,
                self._source_name,
                self._dedupe_keep,
            )

        # ── Step 2: Change detection ──────────────────────────────────────────
        detection: ChangeDetectionResult = self._detector.detect(df_deduped)

        # ── Step 3: Short-circuit if nothing actionable ───────────────────────
        if detection.rows_to_load.empty:
            self._logger.info(
                "All %d rows unchanged — skipping DB load | source=%s",
                detection.count_unchanged,
                self._source_name,
            )
            return IncrementalLoadResult(
                source_name=self._source_name,
                rows_in=rows_in,
                rows_new=0,
                rows_updated=0,
                rows_unchanged=detection.count_unchanged,
                rows_duplicate=rows_duplicate,
                rows_failed=0,
                chunks_loaded=0,
                change_detection_ms=detection.duration_ms,
                load_duration_ms=0.0,
                started_at=started_at,
                completed_at=datetime.now(tz=UTC),
            )

        self._logger.info(
            "Loading %d actionable rows (new=%d, updated=%d) | skip=%d",
            len(detection.rows_to_load),
            detection.count_new,
            detection.count_updated,
            detection.count_unchanged,
        )

        # ── Step 4: Split into chunks and UPSERT ─────────────────────────────
        t_load_start = time.perf_counter()
        records = self._prepare_records(
            detection.rows_to_load,
            data_source_id=data_source_id,
            pipeline_run_id=pipeline_run_id,
        )
        chunks = [
            records[i : i + self._chunk_size]
            for i in range(0, len(records), self._chunk_size)
        ]

        total_new: int = 0
        total_updated: int = 0
        total_failed: int = 0
        chunks_loaded: int = 0

        for chunk_idx, chunk in enumerate(chunks, start=1):
            try:
                inserted, updated = self._upsert_chunk(chunk)
                total_new += inserted
                total_updated += updated
                chunks_loaded += 1
                self._logger.debug(
                    "  Chunk %d/%d | inserted=%d updated=%d",
                    chunk_idx,
                    len(chunks),
                    inserted,
                    updated,
                )
            except DataLoadingError as exc:
                total_failed += len(chunk)
                self._logger.error(
                    "  Chunk %d/%d FAILED (%d rows lost): %s",
                    chunk_idx,
                    len(chunks),
                    len(chunk),
                    exc,
                )
                # Continue — partial load is better than full abort.
                # The caller checks rows_failed in the result.

        load_duration_ms = (time.perf_counter() - t_load_start) * 1000.0

        # ── Step 5: Persist content hashes (only after successful load) ───────
        if total_new + total_updated > 0:
            try:
                self._detector.persist_hashes(detection.row_changes)
            except Exception as exc:
                # Hash persistence failure is non-fatal: the data is already
                # in PostgreSQL. The consequence: the NEXT run will re-classify
                # these rows as NEW (because no hash exists) and UPSERT again
                # — correct, idempotent behaviour.
                self._logger.error(
                    "Hash persistence failed (non-fatal — next run will re-detect): %s",
                    exc,
                )

        completed_at = datetime.now(tz=UTC)
        result = IncrementalLoadResult(
            source_name=self._source_name,
            rows_in=rows_in,
            rows_new=total_new,
            rows_updated=total_updated,
            rows_unchanged=detection.count_unchanged,
            rows_duplicate=rows_duplicate,
            rows_failed=total_failed,
            chunks_loaded=chunks_loaded,
            change_detection_ms=detection.duration_ms,
            load_duration_ms=load_duration_ms,
            started_at=started_at,
            completed_at=completed_at,
        )

        self._logger.info("Incremental load complete | %s", result.to_log_string())

        if total_failed:
            self._logger.warning(
                "%d row(s) failed to load. Check chunk-level error logs.",
                total_failed,
            )

        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Private: deduplication
    # ─────────────────────────────────────────────────────────────────────────

    def _deduplicate(self, df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
        """Remove intra-batch duplicates based on source_job_id.

        WHY necessary?
            Some sources re-deliver the same job multiple times in one batch
            (e.g., a paginated API that returns overlapping pages). Attempting
            to UPSERT both rows in the same transaction will fail with:
            "ON CONFLICT DO UPDATE command cannot affect row a second time"
            PostgreSQL raises this when the VALUES list contains two rows
            that map to the same conflict target.

        Args:
            df: Input DataFrame.

        Returns:
            tuple: (deduped_df, rows_dropped_count)
        """
        if self._id_col not in df.columns:
            return df, 0

        before = len(df)
        df_deduped = df.drop_duplicates(
            subset=[self._id_col],
            keep=self._dedupe_keep,
        ).reset_index(drop=True)
        dropped = before - len(df_deduped)
        return df_deduped, dropped

    # ─────────────────────────────────────────────────────────────────────────
    # Private: record preparation
    # ─────────────────────────────────────────────────────────────────────────

    def _prepare_records(
        self,
        df: pd.DataFrame,
        data_source_id: int | None,
        pipeline_run_id: int | None,
    ) -> list[dict[str, Any]]:
        """Convert the DataFrame to a list of dicts, replacing NaN with None
        and injecting FK values (data_source_id, pipeline_run_id).

        Args:
            df:               Rows to load.
            data_source_id:   FK → data_sources.
            pipeline_run_id:  FK → pipeline_runs.

        Returns:
            list[dict]: Records ready for the UPSERT statement.
        """
        df_clean = df.where(pd.notna(df), other=None)
        records = df_clean.to_dict(orient="records")

        for rec in records:
            if data_source_id is not None:
                rec.setdefault("data_source_id", data_source_id)
            if pipeline_run_id is not None:
                rec.setdefault("pipeline_run_id", pipeline_run_id)
            # Remove the internal hash column — it's stored in job_content_hashes,
            # not in the jobs table.
            rec.pop("_content_hash", None)

        return records

    # ─────────────────────────────────────────────────────────────────────────
    # Private: UPSERT
    # ─────────────────────────────────────────────────────────────────────────

    def _upsert_chunk(self, records: list[dict[str, Any]]) -> tuple[int, int]:
        """UPSERT one chunk into the jobs table.

        Uses PostgreSQL's INSERT ... ON CONFLICT DO UPDATE (the only
        production-safe UPSERT for idempotent pipelines).

        Conflict target: (source_job_id, data_source_id)
            — the natural business key for a job posting.

        Returns counts of (inserted, updated) rows using the xmax trick:
            xmax = 0  → row was inserted  (new tuple, no old version)
            xmax > 0  → row was updated   (old tuple was replaced)

        Args:
            records: List of row dicts (post-prepare_records).

        Returns:
            tuple[int, int]: (rows_inserted, rows_updated)

        Raises:
            DataLoadingError: On any SQLAlchemy or psycopg2 exception.
        """
        if not records:
            return 0, 0

        # Build a parameterised VALUES clause
        # We use positional params and build the SQL dynamically per chunk
        # to support arbitrary column sets (the DataFrame may have varying columns
        # depending on which transformation steps ran).
        columns = [
            c
            for c in records[0].keys()
            if c not in ("_content_hash",)  # internal cols excluded
        ]

        # The conflict target matches the unique constraint on the jobs table:
        # uq_jobs_source_job_id_per_source (source_job_id, data_source_id)
        update_cols = [
            c
            for c in columns
            if c not in ("source_job_id", "data_source_id", "pipeline_run_id")
        ]

        col_list = ", ".join(columns)
        param_list = ", ".join(f":{c}" for c in columns)
        update_set = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)

        sql = text(f"""
            INSERT INTO public.jobs ({col_list})
            VALUES ({param_list})
            ON CONFLICT (source_job_id, data_source_id) DO UPDATE SET
                {update_set},
                updated_at = NOW()
            RETURNING
                (xmax = 0)::int AS was_inserted
        """)  # noqa: S608 — no user input in SQL structure

        try:
            with db_session(self._session_factory) as session:
                result = session.execute(sql, records)
                rows = result.fetchall()

            inserted = sum(1 for r in rows if r[0] == 1)
            updated = sum(1 for r in rows if r[0] == 0)
            return inserted, updated

        except Exception as exc:
            raise DataLoadingError(
                table_name="jobs",
                message=f"UPSERT chunk failed: {exc}",
                cause=exc,
            ) from exc
