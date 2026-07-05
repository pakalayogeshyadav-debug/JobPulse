"""jobpulse.validation.rules — Concrete validation rules implemented in native Pandas."""

import hashlib

import pandas as pd

from jobpulse.logging.logger import get_logger
from jobpulse.validation.base import BaseValidationRule, Severity
from jobpulse.validation.config import VALIDATION_CONFIG
from jobpulse.validation.registry import RuleRegistry

logger = get_logger(__name__)

# Master Skill Catalog (Mocked for this phase, typically loaded from DB/Config)
MASTER_SKILL_CATALOG = {
    "python",
    "sql",
    "aws",
    "react",
    "java",
    "docker",
    "kubernetes",
    "pandas",
    "azure",
    "gcp",
}


@RuleRegistry.register("SchemaValidationRule")
class SchemaValidationRule(BaseValidationRule):
    @property
    def rule_name(self) -> str:
        return "Schema Validation"

    @property
    def description(self) -> str:
        return "Ensures critical columns exist in the DataFrame."

    @property
    def severity(self) -> Severity:
        return VALIDATION_CONFIG.schema_validation.severity

    def validate(self, df: pd.DataFrame) -> tuple[pd.Series, str]:
        critical_cols = ["job_title", "company_name", "source_job_id", "source_name"]
        missing = [col for col in critical_cols if col not in df.columns]
        mask = pd.Series(False, index=df.index)
        if missing:
            mask[:] = True  # Entire DF fails if schema is broken
            return mask, f"Missing critical columns: {missing}"
        return mask, ""


@RuleRegistry.register("RequiredFieldsRule")
class RequiredFieldsRule(BaseValidationRule):
    @property
    def rule_name(self) -> str:
        return "Required Fields"

    @property
    def description(self) -> str:
        return "Ensures critical fields are not null."

    @property
    def severity(self) -> Severity:
        return VALIDATION_CONFIG.required_fields.severity

    def validate(self, df: pd.DataFrame) -> tuple[pd.Series, str]:
        required = ["job_title", "company_name", "source_job_id", "source_name"]
        existing = [c for c in required if c in df.columns]
        if not existing:
            return pd.Series(False, index=df.index), ""

        mask = df[existing].isnull().any(axis=1) | (df[existing] == "").any(axis=1)
        return (
            mask,
            "Missing one or more required fields (job_title, company, source_id)",
        )


@RuleRegistry.register("LocationValidationRule")
class LocationValidationRule(BaseValidationRule):
    @property
    def rule_name(self) -> str:
        return "Location Validation"

    @property
    def description(self) -> str:
        return "Validates city, state, country, ISO codes."

    @property
    def severity(self) -> Severity:
        return VALIDATION_CONFIG.location_validation.severity

    def validate(self, df: pd.DataFrame) -> tuple[pd.Series, str]:
        mask = pd.Series(False, index=df.index)
        if "country_code" in df.columns:
            # Country validation using typical ISO 3166 length
            invalid_country = df["country_code"].notnull() & (
                df["country_code"].str.len() != 2
            )
            mask = mask | invalid_country
        return mask, "Invalid country code or location structure."


@RuleRegistry.register("SalaryValidationRule")
class SalaryValidationRule(BaseValidationRule):
    @property
    def rule_name(self) -> str:
        return "Salary Validation"

    @property
    def description(self) -> str:
        return "Validates salary ranges and limits."

    @property
    def severity(self) -> Severity:
        return VALIDATION_CONFIG.salary_validation.severity

    def validate(self, df: pd.DataFrame) -> tuple[pd.Series, str]:
        mask = pd.Series(False, index=df.index)
        max_limit = VALIDATION_CONFIG.salary_validation.parameters.get(
            "max_salary", 2000000
        )

        if "salary_min" in df.columns and "salary_max" in df.columns:
            has_salaries = df["salary_min"].notnull() & df["salary_max"].notnull()

            # min > max
            invalid_range = has_salaries & (df["salary_min"] > df["salary_max"])
            # negative salaries
            negative = has_salaries & ((df["salary_min"] < 0) | (df["salary_max"] < 0))
            # extreme values
            extreme = has_salaries & (
                (df["salary_min"] > max_limit) | (df["salary_max"] > max_limit)
            )

            mask = mask | invalid_range | negative | extreme

        return mask, f"Salary invalid (min > max, negative, or > {max_limit})"


@RuleRegistry.register("ExperienceValidationRule")
class ExperienceValidationRule(BaseValidationRule):
    @property
    def rule_name(self) -> str:
        return "Experience Validation"

    @property
    def description(self) -> str:
        return "Validates experience_min <= experience_max and >= 0."

    @property
    def severity(self) -> Severity:
        return VALIDATION_CONFIG.experience_validation.severity

    def validate(self, df: pd.DataFrame) -> tuple[pd.Series, str]:
        mask = pd.Series(False, index=df.index)
        if "experience_min" in df.columns and "experience_max" in df.columns:
            has_exp = df["experience_min"].notnull() & df["experience_max"].notnull()
            invalid_range = has_exp & (df["experience_min"] > df["experience_max"])
            negative = has_exp & (
                (df["experience_min"] < 0) | (df["experience_max"] < 0)
            )
            mask = mask | invalid_range | negative
        return mask, "Experience range invalid or negative."


@RuleRegistry.register("DateValidationRule")
class DateValidationRule(BaseValidationRule):
    @property
    def rule_name(self) -> str:
        return "Date Validation"

    @property
    def description(self) -> str:
        return "Ensures posted dates are not in the future."

    @property
    def severity(self) -> Severity:
        return VALIDATION_CONFIG.future_dates.severity

    def validate(self, df: pd.DataFrame) -> tuple[pd.Series, str]:
        mask = pd.Series(False, index=df.index)
        if "posted_date" in df.columns:
            # Convert to datetime if it's not already
            dates = pd.to_datetime(df["posted_date"], errors="coerce")
            future_mask = dates > pd.Timestamp.now(tz="UTC" if dates.dt.tz else None)
            mask = mask | future_mask
        return mask, "Posted date is in the future."


@RuleRegistry.register("DuplicateDetectionRule")
class DuplicateDetectionRule(BaseValidationRule):
    @property
    def rule_name(self) -> str:
        return "Duplicate Detection"

    @property
    def description(self) -> str:
        return "Generates content hashes and detects duplicates."

    @property
    def severity(self) -> Severity:
        return VALIDATION_CONFIG.duplicate_validation.severity

    def validate(self, df: pd.DataFrame) -> tuple[pd.Series, str]:
        mask = pd.Series(False, index=df.index)
        if df.empty:
            return mask, ""

        # 1. Source ID Duplicates
        if "source_job_id" in df.columns and "source_name" in df.columns:
            dupes = df.duplicated(subset=["source_name", "source_job_id"], keep="first")
            mask = mask | dupes

        # 2. Content Hash Generation
        hash_cols = [
            c
            for c in [
                "job_title",
                "company_name",
                "location_raw",
                "description",
                "salary_min",
                "salary_max",
                "experience_min",
            ]
            if c in df.columns
        ]

        if hash_cols:
            # Vectorized hash generation
            str_series = (
                df[hash_cols]
                .fillna("")
                .astype(str)
                .apply(lambda r: "".join(r.values), axis=1)
            )
            # Create a true SHA256 hash
            df["content_hash"] = str_series.apply(
                lambda text: hashlib.sha256(text.encode("utf-8")).hexdigest()
            )

            content_dupes = df.duplicated(subset=["content_hash"], keep="first")
            mask = mask | content_dupes

        return mask, "Duplicate source_job_id or identical content hash detected."


@RuleRegistry.register("CurrencyValidationRule")
class CurrencyValidationRule(BaseValidationRule):
    @property
    def rule_name(self) -> str:
        return "Currency Validation"

    @property
    def description(self) -> str:
        return "Validates currency codes against ISO 4217."

    @property
    def severity(self) -> Severity:
        return VALIDATION_CONFIG.currency_validation.severity

    def validate(self, df: pd.DataFrame) -> tuple[pd.Series, str]:
        mask = pd.Series(False, index=df.index)
        valid_currencies = {"USD", "EUR", "GBP", "INR", "CAD", "AUD"}
        if "currency_code" in df.columns:
            invalid_curr = df["currency_code"].notnull() & ~df["currency_code"].isin(
                valid_currencies
            )
            mask = mask | invalid_curr
        return mask, "Invalid or unsupported currency code."


@RuleRegistry.register("CompanyValidationRule")
class CompanyValidationRule(BaseValidationRule):
    @property
    def rule_name(self) -> str:
        return "Company Validation"

    @property
    def description(self) -> str:
        return "Flags overly short or unparseable company names."

    @property
    def severity(self) -> Severity:
        return VALIDATION_CONFIG.company_validation.severity

    def validate(self, df: pd.DataFrame) -> tuple[pd.Series, str]:
        mask = pd.Series(False, index=df.index)
        if "company_name" in df.columns:
            invalid_company = df["company_name"].notnull() & (
                df["company_name"].str.strip().str.len() < 2
            )
            mask = mask | invalid_company
        return mask, "Company name is suspiciously short or invalid."


@RuleRegistry.register("SkillValidationRule")
class SkillValidationRule(BaseValidationRule):
    @property
    def rule_name(self) -> str:
        return "Skill Validation"

    @property
    def description(self) -> str:
        return "Checks against master skill catalog (Non-rejecting)."

    @property
    def severity(self) -> Severity:
        return "WARNING"  # Never fails pipeline, just tracks

    def validate(self, df: pd.DataFrame) -> tuple[pd.Series, str]:
        # This rule flags rows with unknown skills for WARNING reporting
        mask = pd.Series(False, index=df.index)
        if "skills" not in df.columns:
            return mask, ""

        # Assume skills are lists of strings
        def has_unknown(skill_list):
            if not isinstance(skill_list, list):
                return False
            for s in skill_list:
                if s.lower() not in MASTER_SKILL_CATALOG:
                    return True
            return False

        mask = df["skills"].apply(has_unknown)
        return mask, "Contains unknown skills not in Master Catalog."
