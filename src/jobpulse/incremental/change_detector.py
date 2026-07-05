"""jobpulse.incremental.change_detector — Row-level change classification.

Classifies each row in the incoming DataFrame as:
    NEW       — source_job_id has never been seen before
    UPDATED   — source_job_id exists but content hash has changed
    UNCHANGED — source_job_id exists and content hash is identical

═══════════════════════════════════════════════════════════════
  WHY CONTENT HASHING?
═══════════════════════════════════════════════════════════════
  Many data sources re-deliver the same jobs on every extract.
  A Kaggle CSV loaded daily will re-deliver 100% of records even
  if only 0.1% changed. Without change detection, the loader would
  UPSERT every row — wasting DB I/O and resetting updated_at
  timestamps on unchanged rows (corrupting "when was this job updated?").

  Content hashing solves this:
  1. Compute SHA-256 of the canonical fields for each incoming row.
  2. Compare against the stored hash in job_content_hashes.
  3. Only rows with a DIFFERENT hash are passed to the loader.

  This reduces load by the proportion of truly unchanged records.
  Typical expected ratios for a daily job market pipeline:
    NEW:       5–15%  (genuinely new job postings)
    UPDATED:   1–5%   (title/salary correction, status change)
    UNCHANGED: 80–94% (identical to previous delivery)

═══════════════════════════════════════════════════════════════
  CANONICAL FIELDS FOR HASHING
═══════════════════════════════════════════════════════════════
  The hash covers columns that represent meaningful job content:
    - job_title
    - company_name
    - location_raw
    - salary_min / salary_max / salary_currency
    - employment_type
    - description (first 2000 chars — balance precision vs speed)
    - is_remote

  Columns deliberately EXCLUDED from the hash:
    - posted_date   (sometimes retroactively corrected by sources)
    - posting_url   (URL parameters change but content is same)
    - source_job_id (it's the key, not content)
    - created_at / updated_at (our own audit columns)

  This set is configurable via HASH_COLUMNS. The hash is computed
  after transformation (canonical names, cleaned values) — never
  on raw extracted data.

═══════════════════════════════════════════════════════════════
  PERFORMANCE DESIGN
═══════════════════════════════════════════════════════════════
  The naive approach — querying job_content_hashes once per row —
  would be N round trips to PostgreSQL (N = batch size). At 50k
  rows this is catastrophically slow.

  Instead, ChangeDetector:
  1. Collects ALL source_job_ids from the incoming batch.
  2. Issues ONE bulk SELECT to fetch all known hashes for those IDs.
  3. Loads the result into a Python dict for O(1) lookup per row.
  4. Classifies all rows in-memory — zero additional DB round trips.
  5. Returns two DataFrames: rows_to_load (NEW+UPDATED), rows_unchanged.

  This is the "lookup table" pattern used at scale in Spark, dbt,
  and Flink — load the lookup once, apply it in-memory.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

import pandas as pd
from sqlalchemy import Engine, text

from jobpulse.logging.logger import get_logger

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# Columns used to compute the content hash (post-transformation names)
HASH_COLUMNS: list[str] = [
    "job_title",
    "company_name",
    "location_raw",
    "salary_min",
    "salary_max",
    "salary_currency",
    "employment_type",
    "is_remote",
    "description",
]

# Fallback columns tried if the canonical names are not in the DataFrame
_HASH_COLUMN_ALIASES: dict[str, list[str]] = {
    "job_title": ["title", "job_name"],
    "company_name": ["company", "employer_name", "company_raw"],
    "location_raw": ["location", "city", "location_normalized"],
    "salary_min": ["min_salary", "salary_from"],
    "salary_max": ["max_salary", "salary_to"],
    "salary_currency": ["currency"],
    "employment_type": ["employment_type_name", "job_type"],
    "is_remote": ["remote", "work_from_home"],
    "description": ["job_description", "details"],
}

# Number of characters of description to include in the hash.
# Full descriptions can be MB-sized. 2000 chars captures all meaningful
# changes while keeping hash computation fast.
_DESCRIPTION_HASH_CHARS = 2_000


# ─────────────────────────────────────────────────────────────────────────────
# Enums and Data Classes
# ─────────────────────────────────────────────────────────────────────────────


class ChangeClassification(str, Enum):
    """Classification of a single row relative to the current database state.
    Inherits from str for JSON serialisation.
    """

    NEW = "NEW"  # Never seen before — pure insert
    UPDATED = "UPDATED"  # Seen before but content changed — upsert
    UNCHANGED = "UNCHANGED"  # Seen before, content identical — skip


@dataclass
class RowChange:
    """Classification result for a single incoming row.

    Attributes:
        source_job_id:    Natural key from the source.
        source_name:      Data source identifier.
        classification:   NEW | UPDATED | UNCHANGED
        old_hash:         Previous content hash (None for NEW rows).
        new_hash:         Computed hash for this row's content.
        changed_at:       UTC timestamp when this classification was computed.
    """

    source_job_id: str
    source_name: str
    classification: ChangeClassification
    new_hash: str
    old_hash: str | None = None
    changed_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))

    @property
    def is_actionable(self) -> bool:
        """True if this row should be loaded (NEW or UPDATED)."""
        return self.classification != ChangeClassification.UNCHANGED


@dataclass
class ChangeDetectionResult:
    """Aggregate result of classifying an entire batch of rows.

    Attributes:
        rows_to_load:    DataFrame containing only NEW and UPDATED rows.
        rows_unchanged:  DataFrame containing UNCHANGED rows (not loaded).
        row_changes:     List of RowChange for each input row.
        source_name:     Data source being processed.
        detected_at:     UTC timestamp when detection ran.
        duration_ms:     Time taken for detection in milliseconds.
    """

    rows_to_load: pd.DataFrame
    rows_unchanged: pd.DataFrame
    row_changes: list[RowChange]
    source_name: str
    detected_at: datetime
    duration_ms: float

    @property
    def count_new(self) -> int:
        return sum(
            1 for r in self.row_changes if r.classification == ChangeClassification.NEW
        )

    @property
    def count_updated(self) -> int:
        return sum(
            1
            for r in self.row_changes
            if r.classification == ChangeClassification.UPDATED
        )

    @property
    def count_unchanged(self) -> int:
        return sum(
            1
            for r in self.row_changes
            if r.classification == ChangeClassification.UNCHANGED
        )

    @property
    def total_rows_in(self) -> int:
        return len(self.row_changes)

    @property
    def skip_rate_pct(self) -> float:
        if self.total_rows_in == 0:
            return 0.0
        return round(self.count_unchanged / self.total_rows_in * 100.0, 2)

    def to_log_string(self) -> str:
        return (
            f"source={self.source_name!r} "
            f"total_in={self.total_rows_in} "
            f"new={self.count_new} "
            f"updated={self.count_updated} "
            f"unchanged={self.count_unchanged} "
            f"skip_rate={self.skip_rate_pct:.1f}% "
            f"duration={self.duration_ms:.0f}ms"
        )


# ─────────────────────────────────────────────────────────────────────────────
# ChangeDetector
# ─────────────────────────────────────────────────────────────────────────────


class ChangeDetector:
    """Classifies incoming rows as NEW, UPDATED, or UNCHANGED.

    Works in three phases:
    1. HASH:   Compute a SHA-256 fingerprint for each incoming row.
    2. LOOKUP: Bulk-fetch known hashes from job_content_hashes (1 DB round-trip).
    3. CLASSIFY: Compare incoming hashes to known hashes in-memory.

    Args:
        engine:         SQLAlchemy engine for the job_content_hashes table.
        source_name:    Data source identifier.
        source_job_id_col: Column in the DataFrame holding the natural key.
                           Defaults to 'source_job_id'. Can be overridden for
                           sources that use different ID column names.
        hash_columns:   Columns to include in the content hash.
                        Defaults to HASH_COLUMNS. Overridable for testing.
    """

    def __init__(
        self,
        engine: Engine,
        source_name: str,
        source_job_id_col: str = "source_job_id",
        hash_columns: list[str] | None = None,
    ) -> None:
        self._engine = engine
        self._source_name = source_name
        self._id_col = source_job_id_col
        self._hash_columns = hash_columns or HASH_COLUMNS

    # ─────────────────────────────────────────────────────────────────────────
    # Public entry point
    # ─────────────────────────────────────────────────────────────────────────

    def detect(self, df: pd.DataFrame) -> ChangeDetectionResult:
        """Classify all rows in df as NEW, UPDATED, or UNCHANGED.

        Args:
            df: Transformed DataFrame ready for loading.
                MUST contain the source_job_id_col column.

        Returns:
            ChangeDetectionResult with rows_to_load (NEW+UPDATED) separated
            from rows_unchanged (UNCHANGED).

        Raises:
            KeyError: If source_job_id_col is not in df.columns.
        """
        import time

        t0 = time.perf_counter()

        if self._id_col not in df.columns:
            raise KeyError(
                f"ChangeDetector: column '{self._id_col}' not found in DataFrame. "
                f"Available columns: {list(df.columns)}"
            )

        if df.empty:
            logger.info("ChangeDetector: empty DataFrame — nothing to classify.")
            return ChangeDetectionResult(
                rows_to_load=df.copy(),
                rows_unchanged=df.iloc[0:0].copy(),
                row_changes=[],
                source_name=self._source_name,
                detected_at=datetime.now(tz=UTC),
                duration_ms=0.0,
            )

        logger.info(
            "ChangeDetector starting | source=%s | rows=%d",
            self._source_name,
            len(df),
        )

        # Phase 1: Compute content hashes for all incoming rows
        incoming_hashes: dict[str, str] = self._compute_hashes(df)

        # Phase 2: Bulk-fetch known hashes from DB (ONE round-trip)
        known_hashes: dict[str, str] = self._fetch_known_hashes(
            list(incoming_hashes.keys())
        )

        # Phase 3: Classify each row
        row_changes: list[RowChange] = []
        actionable_indices: list[int] = []
        unchanged_indices: list[int] = []

        for idx, row in df.iterrows():
            job_id = str(row[self._id_col])
            new_hash = incoming_hashes.get(job_id, "")
            old_hash = known_hashes.get(job_id)

            if old_hash is None:
                classification = ChangeClassification.NEW
                actionable_indices.append(idx)  # type: ignore[arg-type]
            elif old_hash != new_hash:
                classification = ChangeClassification.UPDATED
                actionable_indices.append(idx)  # type: ignore[arg-type]
            else:
                classification = ChangeClassification.UNCHANGED
                unchanged_indices.append(idx)  # type: ignore[arg-type]

            row_changes.append(
                RowChange(
                    source_job_id=job_id,
                    source_name=self._source_name,
                    classification=classification,
                    new_hash=new_hash,
                    old_hash=old_hash,
                )
            )

        rows_to_load = (
            df.loc[actionable_indices].copy()
            if actionable_indices
            else df.iloc[0:0].copy()
        )
        rows_unchanged = (
            df.loc[unchanged_indices].copy()
            if unchanged_indices
            else df.iloc[0:0].copy()
        )

        # Stamp the computed hash onto rows_to_load so the loader can persist it
        if not rows_to_load.empty:
            hash_map = {
                r.source_job_id: r.new_hash for r in row_changes if r.is_actionable
            }
            rows_to_load["_content_hash"] = rows_to_load[self._id_col].map(hash_map)

        duration_ms = (time.perf_counter() - t0) * 1000.0
        result = ChangeDetectionResult(
            rows_to_load=rows_to_load,
            rows_unchanged=rows_unchanged,
            row_changes=row_changes,
            source_name=self._source_name,
            detected_at=datetime.now(tz=UTC),
            duration_ms=duration_ms,
        )

        logger.info("ChangeDetector complete | %s", result.to_log_string())
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Hash persistence — called AFTER a successful load
    # ─────────────────────────────────────────────────────────────────────────

    def persist_hashes(self, row_changes: list[RowChange]) -> int:
        """Persist or update content hashes for all actionable rows.

        Call this AFTER a successful load — not before.
        If called before and the load fails, the hash store would reflect
        hashes for rows that were never actually loaded.

        Uses INSERT ... ON CONFLICT DO UPDATE for idempotency.
        Safe to call on partial re-runs.

        Args:
            row_changes: List of RowChange objects from detect().

        Returns:
            int: Number of hash records written.
        """
        actionable = [r for r in row_changes if r.is_actionable]
        if not actionable:
            logger.debug("persist_hashes: no actionable rows — nothing to write.")
            return 0

        logger.info(
            "Persisting content hashes | source=%s | count=%d",
            self._source_name,
            len(actionable),
        )

        sql = text("""
            INSERT INTO public.job_content_hashes
                (source_job_id, source_name, content_hash,
                 first_seen_at, last_updated_at, update_count)
            VALUES
                (:source_job_id, :source_name, :content_hash,
                 NOW(), NOW(), 0)
            ON CONFLICT (source_job_id, source_name) DO UPDATE SET
                content_hash    = EXCLUDED.content_hash,
                last_updated_at = NOW(),
                update_count    = public.job_content_hashes.update_count + 1
        """)

        params = [
            {
                "source_job_id": r.source_job_id,
                "source_name": r.source_name,
                "content_hash": r.new_hash,
            }
            for r in actionable
        ]

        with self._engine.begin() as conn:
            conn.execute(sql, params)

        logger.info("Content hashes persisted | count=%d", len(actionable))
        return len(actionable)

    # ─────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _compute_hashes(self, df: pd.DataFrame) -> dict[str, str]:
        """Compute a SHA-256 content hash for every row.

        Returns:
            dict[source_job_id → sha256_hex_digest]

        Implementation notes:
        - Uses hashlib.sha256 — fast, deterministic, available in stdlib.
        - Concatenates column values with a null-byte separator (\x00).
          This prevents hash collisions where different column splits produce
          the same concatenated string (e.g., "ab" + "c" vs "a" + "bc").
        - NaN/None → empty string (so missing values hash consistently).
        - Description truncated to _DESCRIPTION_HASH_CHARS chars for speed.
        - The hash is hexdigest (64 chars) — compact, indexable, collision-resistant.
        """
        hashes: dict[str, str] = {}
        available_cols = self._resolve_hash_columns(df)

        for _, row in df.iterrows():
            job_id = str(row[self._id_col])
            parts: list[str] = []

            for col in available_cols:
                val = row.get(col)
                if val is None or (isinstance(val, float) and pd.isna(val)):
                    parts.append("")
                elif col == "description" and isinstance(val, str):
                    parts.append(val[:_DESCRIPTION_HASH_CHARS])
                else:
                    parts.append(str(val))

            raw = "\x00".join(parts).encode("utf-8")
            hashes[job_id] = hashlib.sha256(raw).hexdigest()

        return hashes

    def _resolve_hash_columns(self, df: pd.DataFrame) -> list[str]:
        """Resolve canonical column names against the actual DataFrame columns.

        Some sources may use non-canonical column names after transformation.
        This method tries aliases defined in _HASH_COLUMN_ALIASES before
        skipping a column (with a warning).

        Returns:
            list[str]: Columns to use for hashing (subset of df.columns).
        """
        resolved: list[str] = []
        for canonical in self._hash_columns:
            if canonical in df.columns:
                resolved.append(canonical)
                continue
            # Try aliases
            found_alias = None
            for alias in _HASH_COLUMN_ALIASES.get(canonical, []):
                if alias in df.columns:
                    found_alias = alias
                    break
            if found_alias:
                resolved.append(found_alias)
            else:
                logger.debug(
                    "Hash column '%s' not found in DataFrame — excluded from hash.",
                    canonical,
                )
        if not resolved:
            logger.warning(
                "No hash columns resolved. Falling back to all columns. "
                "This may produce unstable hashes across pipeline runs."
            )
            resolved = [c for c in df.columns if c != self._id_col]
        return resolved

    def _fetch_known_hashes(self, source_job_ids: list[str]) -> dict[str, str]:
        """Bulk-fetch content hashes from job_content_hashes for a list of job IDs.

        Uses a single SQL query with ANY(:ids) array parameter — much faster
        than N individual SELECT statements.

        Args:
            source_job_ids: List of job IDs to look up.

        Returns:
            dict[source_job_id → content_hash] for all IDs that exist in DB.
            IDs not in the dict are NEW rows.
        """
        if not source_job_ids:
            return {}

        # Chunk the lookup if the list is very large (PostgreSQL has a
        # practical limit on the ANY() array size at ~65535 elements)
        chunk_size = 50_000
        result: dict[str, str] = {}

        for i in range(0, len(source_job_ids), chunk_size):
            chunk = source_job_ids[i : i + chunk_size]
            sql = text("""
                SELECT source_job_id, content_hash
                FROM public.job_content_hashes
                WHERE source_name = :source_name
                  AND source_job_id = ANY(:ids)
            """)
            with self._engine.connect() as conn:
                rows = conn.execute(
                    sql,
                    {
                        "source_name": self._source_name,
                        "ids": chunk,
                    },
                ).fetchall()
            for row in rows:
                result[row[0]] = row[1]

        logger.debug(
            "Known hashes fetched | source=%s | looked_up=%d | found=%d",
            self._source_name,
            len(source_job_ids),
            len(result),
        )
        return result
