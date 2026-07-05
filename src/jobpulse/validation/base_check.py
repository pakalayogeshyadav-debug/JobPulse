"""jobpulse.validation.base_check — Abstract base class for all data quality checks.

Every check in the framework inherits from BaseCheck and implements exactly
one method: _run(df) → tuple[int, int, list[int]].

The Template Method in BaseCheck.run() handles:
    ✓ Column existence guard (returns SKIP if column is absent)
    ✓ Wall-clock timing (execution_time_ms in CheckResult)
    ✓ Structured logging (before and after every check)
    ✓ Exception isolation (returns ERROR status instead of crashing the pipeline)
    ✓ Building the CheckResult value object

Design Principles Applied:
    Template Method Pattern:
        BaseCheck.run() defines the algorithm skeleton.
        Subclasses implement only _run() — the domain logic.

    Open/Closed Principle:
        Adding a new check = creating a new class that implements _run().
        No existing code is modified.

    Liskov Substitution Principle:
        All checks implement the same run() → CheckResult interface.
        The ValidationRunner treats them identically.

    Interface Segregation:
        BaseCheck exposes only what a check needs: _run(), column_required,
        check_name, severity. No "kitchen sink" interface.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import ClassVar

import pandas as pd

from jobpulse.logging.logger import get_logger
from jobpulse.validation.models import (
    CheckResult,
    CheckSeverity,
    CheckStatus,
    ValidationConfig,
)

logger = get_logger(__name__)


class BaseCheck(ABC):
    """Abstract base class for all data quality checks.

    Subclasses implement _run(df) which returns:
        (records_checked, records_failed, failed_indices)

    The run() Template Method wraps _run() with timing, logging,
    column guards, and exception isolation.

    Class Attributes:
        check_name:      Unique dotted name for this check.
                         Convention: "<category>.<specific>", e.g. "completeness.company_name"
        severity:        Whether a FAIL halts the pipeline (CRITICAL) or just warns (WARNING).
        column_required: If set, run() returns SKIP if this column is absent in the DataFrame.
                         If None, the check is responsible for handling missing columns itself.

    Instance Attributes:
        config:          Shared ValidationConfig with all configurable thresholds.
    """

    check_name: ClassVar[str]  # Must be set by each subclass
    severity: ClassVar[CheckSeverity]  # Must be set by each subclass
    column_required: ClassVar[str | None] = None  # Optional: auto-skip guard

    def __init__(self, config: ValidationConfig) -> None:
        """Initialise the check with the shared validation config.

        Args:
            config: ValidationConfig containing all configurable thresholds.
        """
        self.config = config
        self._logger = get_logger(f"jobpulse.validation.{self.check_name}")

    # ──────────────────────────────────────────────────────────────────────────
    # Template Method — public entry point (DO NOT OVERRIDE)
    # ──────────────────────────────────────────────────────────────────────────

    def run(self, df: pd.DataFrame) -> CheckResult:
        """Execute the check and return a CheckResult.

        This is the Template Method — it defines the algorithm skeleton.
        Subclasses MUST NOT override this method.

        Algorithm:
            1. Guard: if column_required is set and absent → return SKIP
            2. Start wall-clock timer
            3. Call _run(df) to get (checked, failed, failed_indices)
            4. Derive status from failure_pct vs thresholds
            5. Build and return CheckResult
            6. On any unexpected exception → return ERROR CheckResult

        Args:
            df: The DataFrame to check. Should not be mutated.

        Returns:
            CheckResult: Immutable result record for this check.
        """
        # ── Guard: column existence ───────────────────────────────────────────
        if self.column_required and self.column_required not in df.columns:
            self._logger.debug(
                "SKIP | check=%s | reason='%s' column not present",
                self.check_name,
                self.column_required,
            )
            return CheckResult(
                validation_name=self.check_name,
                status=CheckStatus.SKIP,
                severity=self.severity,
                records_checked=0,
                records_failed=0,
                failure_percentage=0.0,
                execution_time_ms=0.0,
                column=self.column_required,
                details=f"Column '{self.column_required}' not present in DataFrame — check skipped.",
            )

        self._logger.debug("START | check=%s | rows=%d", self.check_name, len(df))
        t0 = time.perf_counter()

        try:
            records_checked, records_failed, failed_indices = self._run(df)
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self._logger.error(
                "ERROR | check=%s | exception=%s: %s",
                self.check_name,
                type(exc).__name__,
                exc,
            )
            return CheckResult(
                validation_name=self.check_name,
                status=CheckStatus.ERROR,
                severity=self.severity,
                records_checked=len(df),
                records_failed=0,
                failure_percentage=0.0,
                execution_time_ms=round(elapsed_ms, 2),
                details=f"Check raised unexpected exception: {type(exc).__name__}: {exc}",
            )

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        failure_pct = (
            records_failed / records_checked * 100.0 if records_checked > 0 else 0.0
        )

        status, details = self._determine_status(
            records_checked, records_failed, failure_pct
        )

        result = CheckResult(
            validation_name=self.check_name,
            status=status,
            severity=self.severity,
            records_checked=records_checked,
            records_failed=records_failed,
            failure_percentage=round(failure_pct, 4),
            execution_time_ms=round(elapsed_ms, 2),
            column=self.column_required,
            threshold_pct=self._fail_threshold_pct(),
            details=details,
            failed_indices=tuple(failed_indices[:20]),  # Keep at most 20 for the report
        )

        log_method = (
            self._logger.error
            if status == CheckStatus.FAIL
            else (
                self._logger.warning
                if status == CheckStatus.WARN
                else self._logger.info
            )
        )
        log_method(
            "%s | check=%s | checked=%d | failed=%d | pct=%.2f%% | ms=%.1f | threshold=%.1f%%",
            status.value,
            self.check_name,
            records_checked,
            records_failed,
            failure_pct,
            elapsed_ms,
            self._fail_threshold_pct() or 0.0,
        )
        return result

    # ──────────────────────────────────────────────────────────────────────────
    # Abstract method — subclasses implement the domain logic here
    # ──────────────────────────────────────────────────────────────────────────

    @abstractmethod
    def _run(self, df: pd.DataFrame) -> tuple[int, int, list[int]]:
        """Execute the domain-specific data quality check.

        Args:
            df: DataFrame to inspect. MUST NOT be mutated.

        Returns:
            tuple of:
                records_checked: Number of rows this check examined.
                records_failed:  Number of rows that violated the check rule.
                failed_indices:  List of integer row indices that failed.
                                 Used for debugging. May be empty if computing
                                 indices is too expensive for large datasets.

        Raises:
            Any exception is caught by the template method, which returns
            an ERROR CheckResult instead of crashing the pipeline.
        """
        ...

    # ──────────────────────────────────────────────────────────────────────────
    # Protected helpers — available to all subclasses
    # ──────────────────────────────────────────────────────────────────────────

    def _determine_status(
        self,
        records_checked: int,
        records_failed: int,
        failure_pct: float,
    ) -> tuple[CheckStatus, str]:
        """Determine CheckStatus and detail message from failure metrics.

        Default behaviour uses _fail_threshold_pct() and _warn_threshold_pct().
        Subclasses may override if they need more nuanced status logic.

        Args:
            records_checked: Rows examined.
            records_failed:  Rows that failed the rule.
            failure_pct:     Percentage of records that failed.

        Returns:
            tuple of (CheckStatus, details_string)
        """
        fail_threshold = self._fail_threshold_pct()
        warn_threshold = self._warn_threshold_pct()

        if fail_threshold is not None and failure_pct > fail_threshold:
            return (
                CheckStatus.FAIL,
                (
                    f"{records_failed}/{records_checked} records failed "
                    f"({failure_pct:.2f}% > fail threshold {fail_threshold:.1f}%)."
                ),
            )

        if warn_threshold is not None and failure_pct > warn_threshold:
            return (
                CheckStatus.WARN,
                (
                    f"{records_failed}/{records_checked} records failed "
                    f"({failure_pct:.2f}% > warn threshold {warn_threshold:.1f}%)."
                ),
            )

        return (
            CheckStatus.PASS,
            (
                f"{records_failed}/{records_checked} records failed "
                f"({failure_pct:.2f}%). Within acceptable thresholds."
            ),
        )

    def _fail_threshold_pct(self) -> float | None:
        """Return the FAIL threshold percentage for this check.

        Default returns None (no threshold — always PASS unless overridden).
        Most subclasses override this to return a value from self.config.
        """
        return None

    def _warn_threshold_pct(self) -> float | None:
        """Return the WARN threshold percentage for this check.

        Default returns None (no warn threshold).
        """
        return None

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(check_name={self.check_name!r}, severity={self.severity.value})"
