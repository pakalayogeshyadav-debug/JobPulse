"""jobpulse.validation.models — Core data models for the Data Quality Framework.

This module contains ONLY data models (dataclasses, enums, exceptions).
No business logic lives here.

Design Decision — Why separate models from logic?
    Single Responsibility Principle: these classes have one job — hold data.
    They are imported by both the check classes AND the test suite without
    pulling in any Pandas or business logic dependencies.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

# =============================================================================
# Enums
# =============================================================================


class CheckStatus(str, Enum):
    """Possible outcomes for a single data quality check.

    WHY inherit from str?
        JSON serialisation is automatic — enum members serialise as their
        string value without a custom encoder. This matters for report persistence.
    """

    PASS = "PASS"  # Check passed — no action required
    WARN = "WARN"  # Check exceeded warn threshold — log but continue
    FAIL = "FAIL"  # Check exceeded fail threshold — halt pipeline
    SKIP = "SKIP"  # Check was skipped (e.g., column not present in DataFrame)
    ERROR = "ERROR"  # Check itself raised an unexpected exception


class CheckSeverity(str, Enum):
    """How important a check failure is to pipeline health.

    CRITICAL: Failure halts the pipeline. Triggers DataQualityError.
    WARNING:  Failure is logged and included in the report. Pipeline continues.

    WHY two levels (not three or more)?
        In practice, operations teams respond to two states: "stop and fix it"
        vs "note it and keep going". More granularity creates alert fatigue
        and inconsistent responses.
    """

    CRITICAL = "CRITICAL"  # Must pass — pipeline fails if this check FAILs
    WARNING = "WARNING"  # Nice to have — pipeline continues even if FAIL


class ValidationStage(str, Enum):
    """Which ETL stage triggered the validation run.

    Allows report files to be named and grouped by stage for trend analysis.
    """

    POST_EXTRACT = "post_extract"  # Runs on raw extraction output
    POST_TRANSFORM = "post_transform"  # Runs on transformed output


# =============================================================================
# CheckResult — immutable value object for one check's outcome
# =============================================================================


@dataclass(frozen=True)
class CheckResult:
    """Immutable record of a single data quality check execution.

    Produced by every BaseCheck subclass after run() completes.
    Stored in ValidationReport and persisted to JSON.

    WHY frozen=True?
        A check result is an audit record. It should be impossible to mutate
        after the check completes — the same reason you wouldn't edit a signed
        contract. Immutability also makes CheckResult hashable (safe to use as
        dict key or in sets).

    Attributes:
        validation_name:    Unique human-readable identifier for the check.
                            Format: "<category>.<specific_check>"
                            e.g., "completeness.company_name", "uniqueness.duplicate_jobs"
        status:             Outcome of the check (PASS/WARN/FAIL/SKIP/ERROR).
        severity:           How bad a FAIL is for the pipeline.
        records_checked:    Total rows the check examined.
        records_failed:     Rows that violated the check rule.
        failure_percentage: records_failed / records_checked * 100. 0 if checked is 0.
        execution_time_ms:  Wall-clock time in milliseconds to run this check.
        column:             Which DataFrame column was checked (None for multi-col checks).
        threshold_pct:      The configured failure threshold (for reference in reports).
        details:            Human-readable explanation of the result.
        failed_indices:     Sample of row indices that failed (max 20, for debugging).
        extra:              Optional additional context dict (check-specific metadata).
    """

    validation_name: str
    status: CheckStatus
    severity: CheckSeverity
    records_checked: int
    records_failed: int
    failure_percentage: float
    execution_time_ms: float
    column: str | None = None
    threshold_pct: float | None = None
    details: str = ""
    failed_indices: tuple[int, ...] = field(default_factory=tuple)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for JSON persistence.

        All enum values are converted to their string representation.
        Tuples are converted to lists (JSON has no tuples).
        """
        return {
            "validation_name": self.validation_name,
            "status": self.status.value,
            "severity": self.severity.value,
            "records_checked": self.records_checked,
            "records_failed": self.records_failed,
            "failure_percentage": round(self.failure_percentage, 4),
            "execution_time_ms": round(self.execution_time_ms, 2),
            "column": self.column,
            "threshold_pct": self.threshold_pct,
            "details": self.details,
            "failed_indices": list(self.failed_indices)[:20],  # Cap at 20 for JSON size
            "extra": self.extra,
        }

    @property
    def passed(self) -> bool:
        """True if the check passed or was skipped."""
        return self.status in (CheckStatus.PASS, CheckStatus.SKIP)

    @property
    def is_critical_failure(self) -> bool:
        """True if this is a CRITICAL check that FAILed — pipeline must halt."""
        return (
            self.status == CheckStatus.FAIL and self.severity == CheckSeverity.CRITICAL
        )


# =============================================================================
# ValidationReport — aggregated result of all checks in one run
# =============================================================================


@dataclass
class ValidationReport:
    """Aggregated result of all data quality checks for a single pipeline stage.

    This object is the "report card" for a DataFrame passing through the
    validation layer. It is produced by ValidationRunner.run() and:
        1. Logged to the pipeline log
        2. Saved as a JSON file in the reports directory
        3. Used to decide whether to halt the pipeline

    Attributes:
        stage:          Which ETL stage triggered this validation.
        source_name:    Identifier for the data source being validated.
        run_id:         Unique identifier for this validation run (typically Airflow run_id).
        started_at:     UTC timestamp when validation began.
        completed_at:   UTC timestamp when validation completed.
        results:        List of CheckResult objects, one per check.
        total_rows:     Total rows in the DataFrame that was validated.
    """

    stage: ValidationStage
    source_name: str
    run_id: str
    started_at: datetime
    results: list[CheckResult] = field(default_factory=list)
    total_rows: int = 0
    completed_at: datetime | None = None

    # ── Computed properties ───────────────────────────────────────────────────

    @property
    def overall_status(self) -> CheckStatus:
        """Overall validation outcome.

        Returns FAIL if ANY critical check failed.
        Returns WARN if any warning check failed (but no critical failures).
        Returns PASS if all checks passed or were skipped.
        Returns ERROR if any check raised an unexpected exception.
        """
        if any(r.status == CheckStatus.ERROR for r in self.results):
            return CheckStatus.ERROR
        if any(r.is_critical_failure for r in self.results):
            return CheckStatus.FAIL
        if any(r.status in (CheckStatus.FAIL, CheckStatus.WARN) for r in self.results):
            return CheckStatus.WARN
        return CheckStatus.PASS

    @property
    def passed_count(self) -> int:
        """Number of checks that passed."""
        return sum(1 for r in self.results if r.status == CheckStatus.PASS)

    @property
    def failed_count(self) -> int:
        """Number of checks that failed (any severity)."""
        return sum(1 for r in self.results if r.status == CheckStatus.FAIL)

    @property
    def warn_count(self) -> int:
        """Number of checks that produced a warning."""
        return sum(1 for r in self.results if r.status == CheckStatus.WARN)

    @property
    def skipped_count(self) -> int:
        """Number of checks that were skipped."""
        return sum(1 for r in self.results if r.status == CheckStatus.SKIP)

    @property
    def critical_failures(self) -> list[CheckResult]:
        """All critical checks that failed."""
        return [r for r in self.results if r.is_critical_failure]

    @property
    def total_execution_time_ms(self) -> float:
        """Sum of all individual check execution times in milliseconds."""
        return sum(r.execution_time_ms for r in self.results)

    @property
    def pipeline_should_halt(self) -> bool:
        """True if the pipeline should be stopped based on these results."""
        return self.overall_status == CheckStatus.FAIL

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialise the full report to a plain dict for JSON persistence."""
        return {
            "schema_version": "1.0",
            "stage": self.stage.value,
            "source_name": self.source_name,
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "total_execution_ms": round(self.total_execution_time_ms, 2),
            "total_rows": self.total_rows,
            "overall_status": self.overall_status.value,
            "pipeline_should_halt": self.pipeline_should_halt,
            "summary": {
                "total_checks": len(self.results),
                "passed": self.passed_count,
                "warned": self.warn_count,
                "failed": self.failed_count,
                "skipped": self.skipped_count,
            },
            "results": [r.to_dict() for r in self.results],
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialise to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def save(self, reports_dir: Path) -> Path:
        """Persist this report as a JSON file in the given directory.

        File naming convention:
            dq_report_{stage}_{source}_{timestamp}.json

        WHY include timestamp in filename?
            Multiple pipeline runs should NOT overwrite each other's reports.
            A timestamped filename gives you a full history of data quality
            across every run — essential for trend analysis.

        Args:
            reports_dir: Directory to write the report file into.
                         Created if it does not exist.

        Returns:
            Path: Absolute path of the written report file.
        """
        reports_dir.mkdir(parents=True, exist_ok=True)
        ts = (self.started_at or datetime.now(tz=UTC)).strftime("%Y%m%d_%H%M%S")
        filename = f"dq_report_{self.stage.value}_{self.source_name}_{ts}.json"
        report_path = reports_dir / filename
        report_path.write_text(self.to_json(), encoding="utf-8")
        return report_path

    def summary_line(self) -> str:
        """One-line human-readable summary for log output."""
        return (
            f"[{self.overall_status.value}] "
            f"stage={self.stage.value} source={self.source_name!r} "
            f"rows={self.total_rows} checks={len(self.results)} "
            f"pass={self.passed_count} warn={self.warn_count} "
            f"fail={self.failed_count} skip={self.skipped_count} "
            f"total_ms={self.total_execution_time_ms:.0f}"
        )


# =============================================================================
# Exception
# =============================================================================


class DataQualityError(Exception):
    """Raised by ValidationRunner when one or more CRITICAL checks fail.

    The exception carries the full ValidationReport so callers (e.g., Airflow
    tasks) can log, persist, and alert on the complete picture — not just
    the first failure.

    WHY carry the report in the exception?
        Airflow's on_failure_callback receives the TaskInstance context but
        not the validation report. By embedding the report in the exception,
        the callback can extract it from context["exception"].report and
        send the full report to Slack or email.

    Attributes:
        report: The ValidationReport that triggered the exception.
    """

    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        failed_names = ", ".join(r.validation_name for r in report.critical_failures)
        super().__init__(
            f"Data quality validation FAILED for '{report.source_name}' "
            f"at stage '{report.stage.value}'. "
            f"Critical failures: [{failed_names}]. "
            f"Report: {report.summary_line()}"
        )


# =============================================================================
# ValidationConfig — all configurable thresholds in one place
# =============================================================================


@dataclass
class ValidationConfig:
    """All configurable thresholds for the data quality framework.

    WHY a dedicated config dataclass?
        Thresholds scattered as magic numbers inside check classes become
        impossible to tune per-environment without editing source code.
        A config dataclass lets you load thresholds from YAML/environment
        variables and pass them to the ValidationRunner — no code changes.

    All percentage thresholds are in the range [0.0, 100.0].
    "warn" threshold must be <= "fail" threshold for each check.

    Attributes:
        # Missing values
        missing_values_warn_pct:     Warn if null % > this value.
        missing_values_fail_pct:     Fail if null % > this value.
        critical_columns:            Columns where any null is a CRITICAL failure.

        # Duplicates
        duplicate_jobs_warn_pct:     Warn if duplicate % > this value.
        duplicate_jobs_fail_pct:     Fail if duplicate % > this value.

        # Salary
        salary_min_annual:           Minimum valid annual salary (USD).
        salary_max_annual:           Maximum valid annual salary (USD).
        invalid_salary_fail_pct:     Fail if invalid salary % > this value.

        # Dates
        invalid_date_fail_pct:       Fail if invalid date % > this value.
        future_date_warn_pct:        Warn if future date % > this value.
        future_date_fail_pct:        Fail if future date % > this value.

        # URL
        invalid_url_warn_pct:        Warn if invalid URL % > this value.

        # Description
        empty_description_warn_pct:  Warn if empty description % > this value.
        empty_description_fail_pct:  Fail if empty description % > this value.

        # Skills
        duplicate_skills_warn_pct:   Warn if duplicate skills % > this value.

        # Reports
        reports_dir:                 Directory to persist JSON report files.
    """

    # ── Missing values ────────────────────────────────────────────────────────
    missing_values_warn_pct: float = 10.0
    missing_values_fail_pct: float = 30.0
    critical_columns: tuple[str, ...] = ("job_title", "source_job_id")

    # ── Duplicates ─────────────────────────────────────────────────────────────
    duplicate_jobs_warn_pct: float = 5.0
    duplicate_jobs_fail_pct: float = 20.0

    # ── Salary ─────────────────────────────────────────────────────────────────
    salary_min_annual: float = 1_000.0
    salary_max_annual: float = 5_000_000.0
    invalid_salary_fail_pct: float = 50.0

    # ── Dates ──────────────────────────────────────────────────────────────────
    invalid_date_fail_pct: float = 20.0
    future_date_warn_pct: float = 1.0
    future_date_fail_pct: float = 10.0

    # ── URL ───────────────────────────────────────────────────────────────────
    invalid_url_warn_pct: float = 5.0

    # ── Company name ──────────────────────────────────────────────────────────
    null_company_name_warn_pct: float = 5.0
    null_company_name_fail_pct: float = 30.0

    # ── Currency ──────────────────────────────────────────────────────────────
    invalid_currency_warn_pct: float = 5.0
    valid_currency_codes: tuple[str, ...] = (
        "USD",
        "EUR",
        "GBP",
        "CAD",
        "AUD",
        "INR",
        "SGD",
        "CHF",
        "JPY",
        "CNY",
        "NZD",
    )

    # ── Description ───────────────────────────────────────────────────────────
    empty_description_warn_pct: float = 10.0
    empty_description_fail_pct: float = 50.0
    min_description_length: int = 20

    # ── Skills ────────────────────────────────────────────────────────────────
    duplicate_skills_warn_pct: float = 5.0

    # ── Location ──────────────────────────────────────────────────────────────
    invalid_location_warn_pct: float = 10.0

    # ── Reports ───────────────────────────────────────────────────────────────
    reports_dir: Path = Path("reports/data_quality")

    @classmethod
    def for_production(cls) -> ValidationConfig:
        """Return a stricter config suitable for production environments."""
        return cls(
            missing_values_fail_pct=20.0,
            duplicate_jobs_fail_pct=10.0,
            invalid_date_fail_pct=10.0,
            future_date_fail_pct=5.0,
            empty_description_fail_pct=30.0,
        )

    @classmethod
    def for_development(cls) -> ValidationConfig:
        """Return a lenient config suitable for development/testing."""
        return cls(
            missing_values_fail_pct=50.0,
            duplicate_jobs_fail_pct=40.0,
            invalid_date_fail_pct=40.0,
            future_date_fail_pct=20.0,
            empty_description_fail_pct=70.0,
        )
