"""jobpulse.transformation.base — Abstract base class and result type for transformers.

Defines the contract every transformer must fulfil and provides the
Template Method orchestration that all concrete transformers inherit.

Design Patterns:
    Template Method:
        BaseTransformer.run() defines the algorithm skeleton:
            1. Guard: reject empty input
            2. Snapshot pre-transform row count
            3. Call transform()  ← subclass implements
            4. Guard: reject None return
            5. Log row delta (how many rows were added/dropped)
        Subclasses only override transform() — not run().

    Strategy:
        The pipeline orchestrator accepts any BaseTransformer, so concrete
        implementations (JobListingTransformer, future SkillTransformer) are
        hot-swappable at runtime via configuration.

Custom Exception:
    DataTransformationError — raised on any unrecoverable transformation failure.

Value Object:
    TransformationReport — immutable summary of a completed transformation run.
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
# Custom Exception
# =============================================================================


class DataTransformationError(Exception):
    """Raised when a data transformation step fails in an unrecoverable way.

    Unrecoverable means the step cannot produce a usable output even after
    best-effort repairs (e.g., a required column is absent entirely).
    Recoverable problems (e.g., a few bad salary strings) are handled
    by converting bad values to NaN and logging a warning — not by raising.

    Attributes:
        step_name: Name of the transformation step that failed.
        message:   Human-readable description of the failure.

    Examples:
        - Required input column is completely missing from the DataFrame
        - Input DataFrame has 0 rows (nothing to transform)
        - A column mapping configuration is malformed
    """

    def __init__(self, message: str, step_name: str = "unknown") -> None:
        self.step_name = step_name
        self.message = message
        super().__init__(f"[{step_name}] Transformation error: {message}")


# =============================================================================
# Transformation Report Value Object
# =============================================================================


@dataclass(frozen=True)
class TransformationReport:
    """Immutable summary of a single transformer run.

    Produced by BaseTransformer.run() after every successful transformation.
    Used by the pipeline orchestrator for logging, alerting, and audit trails.

    Attributes:
        transformer_name: Name of the transformer that produced this report.
        input_rows:       Number of rows received by the transformer.
        output_rows:      Number of rows returned after transformation.
        rows_dropped:     Rows removed during transformation (computed).
        started_at:       UTC timestamp when transformation began.
        completed_at:     UTC timestamp when transformation completed.
        duration_ms:      Wall-clock duration in milliseconds.
        warnings:         List of non-fatal issues encountered.
        step_metrics:     Per-step statistics (e.g., {'duplicates_removed': 12}).
    """

    transformer_name: str
    input_rows: int
    output_rows: int
    started_at: datetime
    completed_at: datetime
    duration_ms: float
    warnings: list[str] = field(default_factory=list)
    step_metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def rows_received(self) -> int:
        return self.input_rows

    @property
    def rows_processed(self) -> int:
        return self.output_rows

    @property
    def rows_removed(self) -> int:
        """Number of rows removed during transformation (can be negative on expansion)."""
        return self.input_rows - self.output_rows

    @property
    def drop_rate_pct(self) -> float:
        """Percentage of input rows that were dropped. 0.0 if input was empty."""
        if self.input_rows == 0:
            return 0.0
        return round(self.rows_removed / self.input_rows * 100, 2)

    @property
    def processing_time_seconds(self) -> float:
        """Duration in seconds rounded to 3 decimal places."""
        return round(self.duration_ms / 1000.0, 3)

    @property
    def success_rate(self) -> float:
        """Percentage of received rows that were successfully processed."""
        if self.rows_received == 0:
            return 0.0
        return round((self.rows_processed / self.rows_received) * 100, 2)

    @property
    def duplicate_rows_removed(self) -> int:
        return self.step_metrics.get("duplicates_removed", 0)

    @property
    def invalid_salary_rows(self) -> int:
        return self.step_metrics.get("invalid_salary_rows", 0)

    @property
    def missing_required_fields(self) -> int:
        return self.step_metrics.get("missing_required_fields", 0)

    @property
    def invalid_dates(self) -> int:
        return self.step_metrics.get("invalid_dates", 0)

    @property
    def invalid_locations(self) -> int:
        return self.step_metrics.get("invalid_locations", 0)

    def to_log_string(self) -> str:
        """Format as a single-line log message."""
        return (
            f"transformer={self.transformer_name!r} "
            f"in={self.rows_received} out={self.rows_processed} "
            f"dropped={self.rows_removed} ({self.drop_rate_pct}%) "
            f"duration={self.processing_time_seconds:.3f}s "
            f"warnings={len(self.warnings)}"
        )


# =============================================================================
# Abstract Base Transformer
# =============================================================================


class BaseTransformer(ABC):
    """Abstract base class for all data transformers.

    All concrete transformers inherit from this class and implement transform().

    The run() method is the public entry point. It orchestrates the full
    transformation lifecycle and is NOT meant to be overridden.

    Attributes:
        transformer_name: Short identifier (e.g., 'job_listing').
        _logger:          Named child logger for this transformer instance.
        _warnings:        Non-fatal issues accumulated during the current run.
        _step_metrics:    Per-step statistics accumulated during the current run.
    """

    def __init__(self, transformer_name: str) -> None:
        """Initialise the base transformer.

        Args:
            transformer_name: Short, machine-readable identifier for this transformer.
                              Used in log messages, errors, and the report.
        """
        self.transformer_name: str = transformer_name
        self._logger = get_logger(f"jobpulse.transformation.{transformer_name}")
        self._warnings: list[str] = []
        self._step_metrics: dict[str, Any] = {}

    # ─────────────────────────────────────────────────────────────────────────
    # Abstract Interface
    # ─────────────────────────────────────────────────────────────────────────

    @abstractmethod
    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply all transformation steps to the input DataFrame.

        Contract:
            - MUST return a new DataFrame (never mutate the input df).
            - MUST raise DataTransformationError on unrecoverable failures.
            - Individual bad values should be set to NaN (not raise).
            - All output column names must be valid Python identifiers.

        Args:
            df: Raw DataFrame from the extraction layer. All values are strings.

        Returns:
            pd.DataFrame: Cleaned, typed, and standardised DataFrame.

        Raises:
            DataTransformationError: If transformation cannot be completed.
        """
        ...

    # ─────────────────────────────────────────────────────────────────────────
    # Template Method — public entry point
    # ─────────────────────────────────────────────────────────────────────────

    def run(self, df: pd.DataFrame) -> tuple[pd.DataFrame, TransformationReport]:
        """Execute the full transformation lifecycle (Template Method).

        Orchestrates: guard → transform → report.

        Args:
            df: Raw DataFrame from the extraction layer.

        Returns:
            tuple[pd.DataFrame, TransformationReport]:
                - Cleaned DataFrame ready for the validation layer.
                - Report containing timing, row delta, and warnings.

        Raises:
            DataTransformationError: If df is empty or transform() raises.
        """
        # Reset per-run accumulators
        self._warnings = []
        self._step_metrics = {}

        self._logger.info(
            "Starting transformation | transformer=%r | input_rows=%d",
            self.transformer_name,
            len(df),
        )

        # Guard: empty input
        if df.empty:
            raise DataTransformationError(
                message="Received an empty DataFrame (0 rows). Nothing to transform.",
                step_name=self.transformer_name,
            )

        input_rows = len(df)
        started_at = datetime.now(tz=UTC)
        t0 = time.perf_counter()

        result_df = self.transform(df)

        duration_ms = (time.perf_counter() - t0) * 1000.0
        completed_at = datetime.now(tz=UTC)

        report = TransformationReport(
            transformer_name=self.transformer_name,
            input_rows=input_rows,
            output_rows=len(result_df),
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            warnings=list(self._warnings),
            step_metrics=dict(self._step_metrics),
        )

        self._logger.info("Transformation complete | %s", report.to_log_string())

        if self._warnings:
            self._logger.warning(
                "Transformation produced %d warning(s):", len(self._warnings)
            )
            for w in self._warnings:
                self._logger.warning("  ⚠ %s", w)

        return result_df, report

    # ─────────────────────────────────────────────────────────────────────────
    # Protected helpers — used by subclasses
    # ─────────────────────────────────────────────────────────────────────────

    def _warn(self, message: str) -> None:
        """Record a non-fatal warning that will appear in the TransformationReport.

        Args:
            message: Human-readable description of the warning.
        """
        self._logger.warning("⚠ %s", message)
        self._warnings.append(message)

    def _record_metric(self, key: str, value: Any) -> None:
        """Record a step-level metric in the TransformationReport.

        Args:
            key:   Short metric name (e.g., 'duplicates_removed').
            value: Numeric or string metric value.
        """
        self._step_metrics[key] = value
        self._logger.debug("  metric: %s = %s", key, value)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.transformer_name!r})"
