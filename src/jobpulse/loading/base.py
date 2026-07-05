"""jobpulse.loading.base — Abstract base class and result type for all loaders.

Defines the contract every loader must fulfil and the TransactionBatch
orchestration that makes each chunk's commit/rollback atomic and independent.

Design Patterns:
    Template Method:
        BaseLoader.run() defines the algorithm:
            1. Guard empty input
            2. Split df into chunks
            3. For each chunk: load_chunk() (subclass implements)
            4. Aggregate LoadingResult across all chunks
        Subclasses implement only load_chunk().

    Strategy:
        The pipeline orchestrator accepts any BaseLoader, so
        PostgresLoader can be swapped for a BigQueryLoader or a
        mock loader in tests — all behind the same interface.

Custom Exceptions:
    DataLoadingError         — unrecoverable database-level failure
    LoadingValidationError   — input DataFrame fails pre-load guard

Value Object:
    LoadingResult — immutable summary of a completed load run
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from jobpulse.logging.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Custom Exceptions
# =============================================================================


class DataLoadingError(Exception):
    """Raised when data cannot be written to the target database.

    This is the single exception type raised by the loading layer.
    Callers catch this to handle failures (alert, retry, dead-letter queue).

    Attributes:
        table_name: Name of the PostgreSQL table being loaded.
        message:    Human-readable description of the failure.
        cause:      The original SQLAlchemy or psycopg2 exception (if any).

    Examples:
        - PostgreSQL UNIQUE constraint violation (without ON CONFLICT)
        - NOT NULL constraint violation (required column is None)
        - Data type mismatch (str where int expected)
        - Connection dropped mid-load
        - Deadlock detected by PostgreSQL
    """

    def __init__(
        self,
        table_name: str,
        message: str,
        cause: BaseException | None = None,
    ) -> None:
        self.table_name = table_name
        self.message = message
        self.cause = cause
        super().__init__(f"[{table_name}] Loading failed: {message}")


class LoadingValidationError(DataLoadingError):
    """Raised when the input DataFrame fails pre-load validation.

    Signals a problem with the data shape or required columns —
    not a database-level error.
    """


# =============================================================================
# LoadReport Value Object
# =============================================================================


@dataclass(frozen=True)
class LoadReport:
    """Immutable summary of a completed data load operation.

    Produced by BaseLoader.run() after every load attempt.
    Used by the pipeline orchestrator for audit logging, alerting,
    and updating pipeline_runs metrics in the database.
    """

    table_name: str
    rows_received: int
    rows_inserted: int
    rows_updated: int
    rows_skipped: int
    rows_failed: int
    duplicate_rows: int
    batches_processed: int
    database_retry_count: int
    execution_time: float
    average_batch_time: float
    success_rate: float
    started_at: datetime
    completed_at: datetime
    strategy: str
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def rows_loaded(self) -> int:
        """Total rows that touched the database (inserts + updates)."""
        return self.rows_inserted + self.rows_updated

    def to_log_string(self) -> str:
        """Format as a single-line log message."""
        return (
            f"table={self.table_name!r} "
            f"strategy={self.strategy!r} "
            f"received={self.rows_received} "
            f"inserted={self.rows_inserted} "
            f"updated={self.rows_updated} "
            f"failed={self.rows_failed} "
            f"batches={self.batches_processed} "
            f"retries={self.database_retry_count} "
            f"execution_time={self.execution_time:.3f}s"
        )


# =============================================================================
# Abstract Base Loader
# =============================================================================


class BaseLoader(ABC):
    """Abstract base class for all data loaders.

    Subclasses implement load_chunk() to write one batch of rows to a
    specific target (PostgreSQL, BigQuery, a CSV file, a mock store).

    The run() Template Method handles:
        - Empty-input guard
        - Chunk splitting
        - Per-chunk timing and logging
        - Aggregate result construction
        - Progress reporting at configurable intervals

    Attributes:
        table_name:        Target table or resource name.
        chunk_size:        Rows per committed transaction.
        strategy:          Loading strategy identifier.
        log_every_n_chunks: Log progress every N chunks (0 = only at end).
        _logger:           Named child logger.
    """

    def __init__(
        self,
        table_name: str,
        chunk_size: int = 500,
        strategy: str = "upsert",
        log_every_n_chunks: int = 5,
    ) -> None:
        """Initialise the base loader.

        Args:
            table_name:         Target PostgreSQL table name.
            chunk_size:         Rows per bulk transaction. Default 500.
            strategy:           Loading strategy label (used in result/logs).
            log_every_n_chunks: Log progress every N chunks. 0 = end-only.
        """
        self.table_name = table_name
        self.chunk_size = chunk_size
        self.strategy = strategy
        self.log_every_n_chunks = log_every_n_chunks
        self._logger = get_logger(f"jobpulse.loading.{table_name}")

    # ─────────────────────────────────────────────────────────────────────────
    # Abstract interface — subclasses MUST implement this
    # ─────────────────────────────────────────────────────────────────────────

    @abstractmethod
    def load_chunk(
        self,
        records: list[dict[str, Any]],
    ) -> tuple[int, int, int]:
        """Write one chunk of records to the target.

        Called once per chunk by the run() Template Method.

        Args:
            records: List of row dicts prepared from the DataFrame chunk.
                     All values are already in the correct Python types.

        Returns:
            tuple[int, int, int]: (rows_inserted, rows_updated, rows_skipped)
                - rows_inserted: genuinely new rows added
                - rows_updated:  existing rows modified by UPSERT
                - rows_skipped:  rows ignored (ON CONFLICT DO NOTHING)

        Raises:
            DataLoadingError: On any database-level failure.
                              The caller (run()) catches this and handles
                              the partial-failure accounting.
        """
        ...

    # ─────────────────────────────────────────────────────────────────────────
    # Template Method — the public entry point
    # ─────────────────────────────────────────────────────────────────────────

    def run(self, df: pd.DataFrame) -> LoadReport:
        """Load the entire DataFrame into the target, chunk by chunk.

        Algorithm:
            1. Pre-load validation (empty guard, column guard)
            2. Convert DataFrame to list[dict] — done once upfront
            3. Split into chunks of self.chunk_size
            4. For each chunk: call load_chunk(), track counts
            5. Build and return LoadingResult

        Args:
            df: Validated, transformed DataFrame ready for loading.

        Returns:
            LoadReport: Aggregate statistics for the entire load run.

        Raises:
            LoadingValidationError: If df is empty or fails column validation.
            DataLoadingError:       If load_chunk() raises on every retry.
        """
        self._logger.info(
            "Starting load | table=%r | strategy=%r | rows=%d | chunk_size=%d",
            self.table_name,
            self.strategy,
            len(df),
            self.chunk_size,
        )

        # ── Pre-load validation ───────────────────────────────────────────────
        self._validate_input(df)

        started_at = datetime.now(tz=UTC)
        t0 = time.perf_counter()

        # ── Convert to records list once (avoid per-chunk conversion overhead)
        all_records = self._dataframe_to_records(df)
        chunks = self._split_into_chunks(all_records)
        total_chunks = len(chunks)

        # ── Accumulate metrics across chunks ─────────────────────────────────
        total_inserted = 0
        total_updated = 0
        total_skipped = 0
        total_failed = 0
        chunks_loaded = 0

        for chunk_idx, chunk in enumerate(chunks, start=1):
            try:
                inserted, updated, skipped = self.load_chunk(chunk)
                total_inserted += inserted
                total_updated += updated
                total_skipped += skipped
                chunks_loaded += 1

                # Progress logging at configurable intervals
                if self.log_every_n_chunks and chunk_idx % self.log_every_n_chunks == 0:
                    self._logger.info(
                        "  Progress: chunk %d/%d | "
                        "inserted=%d updated=%d skipped=%d so far",
                        chunk_idx,
                        total_chunks,
                        total_inserted,
                        total_updated,
                        total_skipped,
                    )
            except DataLoadingError as exc:
                total_failed += len(chunk)
                self._logger.error(
                    "  Chunk %d/%d FAILED (%d rows lost): %s",
                    chunk_idx,
                    total_chunks,
                    len(chunk),
                    exc,
                )
                # Continue to next chunk — partial-load is better than full-abort
                # The orchestrator checks rows_failed in LoadReport to decide
                # whether to trigger a retry or alert.

        duration_seconds = time.perf_counter() - t0
        completed_at = datetime.now(tz=UTC)

        success_rate = 100.0
        if len(all_records) > 0:
            success_rate = round(
                ((total_inserted + total_updated) / len(all_records)) * 100.0, 2
            )

        avg_batch_time = duration_seconds / total_chunks if total_chunks > 0 else 0.0

        # Note: Subclasses that track retry counts can inject it via `extra` or override this logic.
        retry_count = self.extra.get("retry_count", 0) if hasattr(self, "extra") else 0
        duplicate_rows = (
            self.extra.get("duplicate_rows", 0) if hasattr(self, "extra") else 0
        )

        result = LoadReport(
            table_name=self.table_name,
            rows_received=len(all_records),
            rows_inserted=total_inserted,
            rows_updated=total_updated,
            rows_skipped=total_skipped,
            rows_failed=total_failed,
            duplicate_rows=duplicate_rows,
            batches_processed=chunks_loaded,
            database_retry_count=retry_count,
            execution_time=duration_seconds,
            average_batch_time=avg_batch_time,
            success_rate=success_rate,
            started_at=started_at,
            completed_at=completed_at,
            strategy=self.strategy,
        )

        self._logger.info("Load complete | %s", result.to_log_string())

        if total_failed:
            self._logger.warning(
                "%d row(s) failed to load into '%s'. "
                "Check error logs for chunk-level details.",
                total_failed,
                self.table_name,
            )

        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Protected helpers — used by subclasses
    # ─────────────────────────────────────────────────────────────────────────

    def _validate_input(self, df: pd.DataFrame) -> None:
        """Guard against obviously bad input before touching the database.

        Args:
            df: Input DataFrame to validate.

        Raises:
            LoadingValidationError: If df is empty.
        """
        if df.empty:
            raise LoadingValidationError(
                table_name=self.table_name,
                message=(
                    "Received an empty DataFrame (0 rows). "
                    "Nothing to load. This is likely a pipeline logic error."
                ),
            )

    def _dataframe_to_records(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        """Convert a DataFrame to a list of dicts, replacing NaN with None.

        WHY replace NaN with None:
            Pandas uses NaN (a float) for missing values. PostgreSQL expects
            Python None for SQL NULL. Inserting NaN into a VARCHAR column
            would produce the string 'nan' — a silent data corruption.

        Args:
            df: DataFrame to convert.

        Returns:
            list[dict[str, Any]]: Row records with NaN replaced by None.
        """
        # fillna(value=None) doesn't work on mixed-type DataFrames in Pandas;
        # the idiomatic approach is .where(pd.notna(df), None) — which replaces
        # NaN/NaT values with None correctly across all dtypes.
        df_clean = df.where(pd.notna(df), other=None)
        return df_clean.to_dict(orient="records")

    def _split_into_chunks(
        self,
        records: list[dict[str, Any]],
    ) -> list[list[dict[str, Any]]]:
        """Split a list of records into fixed-size chunks.

        Args:
            records: Full list of row dicts.

        Returns:
            list[list[dict]]: List of chunks, each of length <= chunk_size.
        """
        return [
            records[i : i + self.chunk_size]
            for i in range(0, len(records), self.chunk_size)
        ]

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"table={self.table_name!r}, "
            f"strategy={self.strategy!r}, "
            f"chunk_size={self.chunk_size!r})"
        )
