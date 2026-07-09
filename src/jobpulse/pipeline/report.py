"""jobpulse.pipeline.report — Unified ETL Pipeline Report.

Aggregates Extraction, Transformation, and Load reports into a single
summary object for logging, alerting, and observability.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from jobpulse.loading.base import LoadReport
from jobpulse.transformation.base import TransformationReport
from jobpulse.validation.report import ValidationReport


@dataclass(frozen=True)
class ETLReport:
    """Unified summary of an end-to-end ETL execution.

    Aggregates metrics from Extract, Transform, and Load phases.
    """

    pipeline_start: datetime
    pipeline_end: datetime
    total_duration_seconds: float

    # Extraction
    files_processed: int
    rows_extracted: int

    # Transformation
    rows_transformed: int
    duplicates_removed: int
    rejected_rows: int

    # Validation
    rows_validated: int
    rows_valid: int
    rows_invalid: int
    validation_warnings: int

    # Loading
    rows_inserted: int
    rows_updated: int
    rows_failed: int

    status: Literal["SUCCESS", "PARTIAL SUCCESS", "FAILURE", "SUCCESS_WITH_REPORT_WARNING"]
    warnings: list[str]
    reports_generated: bool

    @classmethod
    def from_reports(
        cls,
        start_time: datetime,
        end_time: datetime,
        files_processed: int,
        rows_extracted: int,
        transform_report: TransformationReport | None,
        validation_report: ValidationReport | None,
        load_report: LoadReport | None,
        status: Literal["SUCCESS", "PARTIAL SUCCESS", "FAILURE", "SUCCESS_WITH_REPORT_WARNING"],
        warnings: list[str] | None = None,
        reports_generated: bool = False,
    ) -> ETLReport:
        """Construct an ETLReport from constituent layer reports."""
        duration = (end_time - start_time).total_seconds()

        return cls(
            pipeline_start=start_time,
            pipeline_end=end_time,
            total_duration_seconds=duration,
            files_processed=files_processed,
            rows_extracted=rows_extracted,
            rows_transformed=transform_report.rows_processed if transform_report else 0,
            duplicates_removed=(
                transform_report.duplicate_rows_removed if transform_report else 0
            ),
            rejected_rows=(
                (
                    transform_report.missing_required_fields
                    + transform_report.invalid_salary_rows
                    + transform_report.invalid_locations
                )
                if transform_report
                else 0
            ),
            rows_validated=validation_report.rows_checked if validation_report else 0,
            rows_valid=validation_report.rows_valid if validation_report else 0,
            rows_invalid=validation_report.rows_invalid if validation_report else 0,
            validation_warnings=(
                validation_report.rows_warning if validation_report else 0
            ),
            rows_inserted=load_report.rows_inserted if load_report else 0,
            rows_updated=load_report.rows_updated if load_report else 0,
            rows_failed=load_report.rows_failed if load_report else 0,
            status=status,
            warnings=warnings or [],
            reports_generated=reports_generated,
        )

    def render_console_summary(self) -> str:
        """Render a formatted ASCII summary box for console output."""
        header = "=" * 40 + "\nJobPulse ETL Summary\n" + "=" * 40
        footer = "=" * 40

        # Format the numbers for readability
        content = (
            f"Files Processed      : {self.files_processed}\n"
            f"Rows Extracted       : {self.rows_extracted:,}\n"
            f"Rows Transformed     : {self.rows_transformed:,}\n"
            f"Rows Validated       : {self.rows_validated:,}\n"
            f"  - Valid            : {self.rows_valid:,}\n"
            f"  - Invalid          : {self.rows_invalid:,}\n"
            f"  - Warnings         : {self.validation_warnings:,}\n"
            f"Rows Loaded          : {(self.rows_inserted + self.rows_updated):,}\n"
            f"Rows Updated         : {self.rows_updated:,}\n"
            f"Duplicates Removed   : {self.duplicates_removed:,}\n"
            f"Rejected Rows        : {self.rejected_rows:,}\n"
            f"Reports Generated    : {self.reports_generated}\n\n"
            f"Pipeline Duration    : {self.total_duration_seconds:.1f} seconds\n\n"
            f"Database             : PostgreSQL\n\n"
            f"Status               : {self.status}\n"
        )

        if self.warnings:
            content += f"\nWarnings             :\n"
            for w in self.warnings:
                content += f"  - {w}\n"

        return f"\n{header}\n\n{content}\n\n{footer}\n"
