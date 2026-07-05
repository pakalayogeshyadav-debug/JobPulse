"""jobpulse.validation.validator — Core Validation Engine."""

import hashlib
import time

import pandas as pd

from jobpulse.logging.logger import get_logger
from jobpulse.validation.base import RuleResult
from jobpulse.validation.exceptions import CriticalValidationError
from jobpulse.validation.registry import RuleRegistry
from jobpulse.validation.report import ValidationReport
from jobpulse.validation.rules import MASTER_SKILL_CATALOG

logger = get_logger(__name__)


class DataValidator:
    """Production-grade validation engine.
    Executes all registered rules, tags rows, and returns a clean DataFrame and a Report.
    """

    def __init__(self) -> None:
        self.rules = RuleRegistry.get_all_rules()
        if not self.rules:
            logger.warning("No validation rules registered!")

    def _generate_content_hash(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generates SHA256 content hash for duplicate detection."""
        if df.empty:
            return df

        hash_cols = [
            c
            for c in [
                "job_title",
                "company_name",
                "location",
                "description",
                "salary_min",
                "salary_max",
                "experience_min",
            ]
            if c in df.columns
        ]
        if not hash_cols:
            return df

        # Create a single string per row, then hash it
        def hash_row(row):
            content = "|".join(str(x) for x in row.values)
            return hashlib.sha256(content.encode("utf-8")).hexdigest()

        df["content_hash"] = df[hash_cols].apply(hash_row, axis=1)
        return df

    def _extract_unknown_skills(self, df: pd.DataFrame, report: ValidationReport):
        """Extracts and counts unknown skills for reporting."""
        if "skills" not in df.columns:
            return

        unknown_set = set()
        for skills in df["skills"].dropna():
            if isinstance(skills, list):
                for s in skills:
                    if s.lower() not in MASTER_SKILL_CATALOG:
                        unknown_set.add(s)
        report.unknown_skills = sorted(list(unknown_set))

    def validate(self, df: pd.DataFrame) -> tuple[pd.DataFrame, ValidationReport]:
        """Validates a dataframe against all registered rules.

        Args:
            df: The transformed dataframe.

        Returns:
            A tuple of (Validated DataFrame, ValidationReport).
        """
        logger.info(f"Starting validation on {len(df)} rows.")
        start_time = time.time()

        # Initialize flags
        df_validated = df.copy()
        df_validated["is_valid"] = True
        df_validated["validation_errors"] = ""
        df_validated["validation_warnings"] = ""

        df_validated = self._generate_content_hash(df_validated)

        report = ValidationReport()
        report.rows_checked = len(df)
        report.rules_executed = len(self.rules)

        critical_failed = False
        critical_error_msg = ""

        for rule in self.rules:
            rule_start = time.time()
            try:
                failed_mask, error_msg = rule.validate(df_validated)
            except Exception as e:
                logger.error(f"Rule {rule.rule_name} raised an exception: {e}")
                continue

            rule_time = time.time() - rule_start
            failed_count = int(failed_mask.sum())

            # Log execution
            logger.info(
                f"Rule: {rule.rule_name} | Severity: {rule.severity} | Checked: {len(df)} | Failed: {failed_count} | Time: {rule_time:.3f}s"
            )

            result = RuleResult(
                rule_name=rule.rule_name,
                severity=rule.severity,
                rows_checked=len(df),
                rows_failed=failed_count,
                execution_time=rule_time,
                failed_indices=df_validated[failed_mask].index.tolist(),
                error_message=error_msg,
            )
            report.rule_results.append(result)

            if failed_count > 0:
                if rule.severity == "CRITICAL":
                    critical_failed = True
                    critical_error_msg = (
                        f"{rule.rule_name} failed on {failed_count} rows: {error_msg}"
                    )
                    report.critical_failures += 1
                elif rule.severity == "ERROR":
                    df_validated.loc[failed_mask, "is_valid"] = False
                    # Append error message
                    df_validated.loc[
                        failed_mask, "validation_errors"
                    ] += f"[{rule.rule_name}] "
                elif rule.severity == "WARNING":
                    df_validated.loc[
                        failed_mask, "validation_warnings"
                    ] += f"[{rule.rule_name}] "

                # Update specific report counters
                if "Salary" in rule.rule_name:
                    report.salary_errors += failed_count
                elif "Location" in rule.rule_name:
                    report.location_errors += failed_count
                elif "Duplicate" in rule.rule_name:
                    report.duplicate_rows += failed_count
                elif "Required" in rule.rule_name:
                    report.missing_required_fields += failed_count
                elif "Schema" in rule.rule_name:
                    report.schema_errors += failed_count
                elif "Experience" in rule.rule_name:
                    report.experience_errors += failed_count
                elif "Currency" in rule.rule_name:
                    report.currency_errors += failed_count
                elif "Company" in rule.rule_name:
                    report.company_errors += failed_count

        self._extract_unknown_skills(df_validated, report)

        report.execution_time = time.time() - start_time
        report.rows_valid = int(df_validated["is_valid"].sum())
        report.rows_invalid = report.rows_checked - report.rows_valid
        report.rows_warning = int((df_validated["validation_warnings"] != "").sum())

        if critical_failed:
            raise CriticalValidationError(
                f"Pipeline stopped due to CRITICAL validation failure: {critical_error_msg}"
            )

        logger.info(
            f"Validation complete. Valid: {report.rows_valid}, Invalid: {report.rows_invalid}, Warnings: {report.rows_warning}"
        )

        # Filter out invalid rows before returning
        df_clean = df_validated[df_validated["is_valid"] == True].copy()
        # Clean up internal tracking columns if desired, but retaining them aids debugging/warehouse loads

        return df_clean, report
