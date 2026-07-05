"""jobpulse.validation.checks — All concrete data quality check classes.

Each class:
    1. Inherits from BaseCheck
    2. Sets class variables: check_name, severity, column_required
    3. Implements _run(df) → (checked, failed, failed_indices)
    4. Returns ONLY raw counts — status determination is BaseCheck's job

Design Decision — Why one module, not 11 files?
    These checks are tightly related (all data quality, all same interface).
    One module with clear section headers is more navigable than 11 tiny files
    with one class each. If the module grows beyond ~600 lines, split by domain
    (completeness.py, consistency.py, etc.).

Adding a new check:
    1. Create a class that inherits BaseCheck
    2. Set check_name, severity, column_required (or None)
    3. Implement _run(df)
    4. Add it to the REGISTRY list at the bottom of this file
    That's it. Zero changes to any existing code.
"""

from __future__ import annotations

import re
import urllib.parse
from datetime import UTC, date, datetime, timezone
from typing import ClassVar

import pandas as pd

from jobpulse.validation.base_check import BaseCheck
from jobpulse.validation.models import CheckSeverity, ValidationConfig

# =============================================================================
# CHECK 1 — MissingValuesCheck
# =============================================================================


class MissingValuesCheck(BaseCheck):
    """Check: null/NaN rate in a specified column.

    WHY this matters:
        Columns like job_title and company_name drive every analytical query.
        A 30%+ null rate in these columns means dashboards show misleading
        aggregates — the "Top Hiring Companies" chart becomes meaningless
        if 30% of jobs have no company attribution.

    Configuration:
        config.missing_values_warn_pct  → warn threshold
        config.missing_values_fail_pct  → fail threshold
        config.critical_columns         → columns where ANY null = CRITICAL

    Severity:
        CRITICAL if the column is in config.critical_columns.
        WARNING  otherwise.
    """

    check_name: ClassVar[str] = "completeness.missing_values"

    def __init__(self, config: ValidationConfig, column: str) -> None:
        """Args:
        config: Shared validation config.
        column: Name of the DataFrame column to check.
        """
        super().__init__(config)
        self._column = column

    def _run(self, df: pd.DataFrame) -> tuple[int, int, list[int]]:
        col = df[self._column]
        null_mask = col.isna() | (col.astype(str).str.strip() == "")
        failed_idx = list(df.index[null_mask])
        return len(df), int(null_mask.sum()), failed_idx

    def _fail_threshold_pct(self) -> float:
        return self.config.missing_values_fail_pct

    def _warn_threshold_pct(self) -> float:
        return self.config.missing_values_warn_pct


# =============================================================================
# CHECK 2 — DuplicateJobsCheck
# =============================================================================


class DuplicateJobsCheck(BaseCheck):
    """Check: duplicate job postings in the DataFrame.

    WHY this matters:
        Duplicate rows directly inflate analytics metrics — "Total Active Jobs"
        would overcount, "Top Hiring Companies" would be biased toward companies
        that happen to have more duplicate postings. Downstream the UNIQUE
        constraint on (source_job_id, data_source_id) would cause constraint
        violations on INSERT.

    Strategy:
        Primary key: source_job_id (if present) — exact ID match.
        Fallback key: (job_title, company_name) — content-based match.
        A row is "duplicate" if it is NOT the first occurrence of its key.
    """

    check_name: ClassVar[str] = "uniqueness.duplicate_jobs"
    severity: ClassVar[CheckSeverity] = CheckSeverity.CRITICAL

    def _run(self, df: pd.DataFrame) -> tuple[int, int, list[int]]:
        if "source_job_id" in df.columns:
            # Use explicit job ID as the key
            valid_ids = df["source_job_id"].notna() & (
                df["source_job_id"].str.strip() != ""
            )
            dup_mask = valid_ids & df.duplicated(subset=["source_job_id"], keep="first")
        else:
            # Fallback: content-based
            fallback_cols = [
                c
                for c in ["job_title", "company_name", "location_raw"]
                if c in df.columns
            ]
            if not fallback_cols:
                return len(df), 0, []
            dup_mask = df.duplicated(subset=fallback_cols, keep="first")

        failed_idx = list(df.index[dup_mask])
        return len(df), int(dup_mask.sum()), failed_idx

    def _fail_threshold_pct(self) -> float:
        return self.config.duplicate_jobs_fail_pct

    def _warn_threshold_pct(self) -> float:
        return self.config.duplicate_jobs_warn_pct


# =============================================================================
# CHECK 3 — InvalidSalaryRangeCheck
# =============================================================================


class InvalidSalaryRangeCheck(BaseCheck):
    """Check: salary values are within a plausible annual range.

    Rules applied (any violation = failed row):
        1. salary_min > 0 if present
        2. salary_max >= salary_min if both present
        3. salary_max <= config.salary_max_annual (below ceiling)
        4. salary_min >= config.salary_min_annual (above floor)

    WHY this matters:
        Salary analytics are the most-read KPI in the JobPulse dashboard.
        An hourly rate stored as an annual salary ($25 instead of $52,000),
        or a typoed salary ($1,300,000 for a junior role), silently corrupts
        every salary percentile and average calculation.

    Note:
        This check operates on the TRANSFORMED data where salary columns
        are numeric floats (salary_min, salary_max). On raw data, salaries
        are strings — do not run this check post-extract.
    """

    check_name: ClassVar[str] = "validity.invalid_salary_range"
    severity: ClassVar[CheckSeverity] = CheckSeverity.WARNING

    def _run(self, df: pd.DataFrame) -> tuple[int, int, list[int]]:
        # Only rows where at least one salary column is present
        salary_cols = [c for c in ["salary_min", "salary_max"] if c in df.columns]
        if not salary_cols:
            return len(df), 0, []

        has_salary = df[salary_cols].notna().any(axis=1)
        salary_df = df[has_salary].copy()

        if salary_df.empty:
            return len(df), 0, []

        invalid_mask = pd.Series(False, index=salary_df.index)

        if "salary_min" in salary_df.columns:
            min_col = pd.to_numeric(salary_df["salary_min"], errors="coerce")
            invalid_mask |= min_col < self.config.salary_min_annual
            invalid_mask |= min_col > self.config.salary_max_annual

        if "salary_max" in salary_df.columns:
            max_col = pd.to_numeric(salary_df["salary_max"], errors="coerce")
            invalid_mask |= max_col < self.config.salary_min_annual
            invalid_mask |= max_col > self.config.salary_max_annual

        if "salary_min" in salary_df.columns and "salary_max" in salary_df.columns:
            min_col = pd.to_numeric(salary_df["salary_min"], errors="coerce")
            max_col = pd.to_numeric(salary_df["salary_max"], errors="coerce")
            both_present = min_col.notna() & max_col.notna()
            invalid_mask |= both_present & (min_col > max_col)

        failed_idx = list(salary_df.index[invalid_mask])
        return int(has_salary.sum()), len(failed_idx), failed_idx

    def _fail_threshold_pct(self) -> float:
        return self.config.invalid_salary_fail_pct


# =============================================================================
# CHECK 4 — InvalidDatesCheck
# =============================================================================


class InvalidDatesCheck(BaseCheck):
    """Check: posting date values can be parsed as valid dates.

    A "valid date" must:
        - Be parseable (not NaT after pd.to_datetime)
        - Not be before 2000-01-01 (obviously wrong, likely a default/error)
        - Not be None/null (handled separately by MissingValuesCheck)

    WHY 2000-01-01 as the lower bound?
        Job posting data predating the year 2000 is almost certainly a data
        error — misformatted date, epoch timestamp divided wrong, etc.
        No modern job board existed before 2000.

    Applies to: posted_date, date_posted, job_posted_date — any column
    matching the posting date after transformation.
    """

    check_name: ClassVar[str] = "validity.invalid_dates"
    severity: ClassVar[CheckSeverity] = CheckSeverity.WARNING
    column_required: ClassVar[str | None] = "posted_date"

    _MIN_VALID_DATE: ClassVar[date] = date(2000, 1, 1)

    def _run(self, df: pd.DataFrame) -> tuple[int, int, list[int]]:
        col = pd.to_datetime(df["posted_date"], errors="coerce")
        has_value = df["posted_date"].notna()
        checked_df = df[has_value]

        if checked_df.empty:
            return len(df), 0, []

        parsed = col[has_value]
        # Invalid: could not parse OR before the minimum valid date
        invalid_mask = parsed.isna() | (parsed.dt.date < self._MIN_VALID_DATE)
        failed_idx = list(checked_df.index[invalid_mask])
        return int(has_value.sum()), len(failed_idx), failed_idx

    def _fail_threshold_pct(self) -> float:
        return self.config.invalid_date_fail_pct


# =============================================================================
# CHECK 5 — FuturePostingDatesCheck
# =============================================================================


class FuturePostingDatesCheck(BaseCheck):
    """Check: posting dates are not in the future.

    WHY this matters:
        A job posted in the future (e.g., 2029-01-01) is almost certainly
        a data quality issue — placeholder date, timezone error, or test data.
        Future postings distort "Monthly Hiring Trends" charts by creating
        phantom future bars.

    Tolerance:
        Up to 1 day in the future is allowed (timezone differences between
        source and pipeline runner). More than 1 day = flagged as suspicious.
    """

    check_name: ClassVar[str] = "validity.future_posting_dates"
    severity: ClassVar[CheckSeverity] = CheckSeverity.WARNING
    column_required: ClassVar[str | None] = "posted_date"

    _TOLERANCE_DAYS: ClassVar[int] = 1  # Allow 1-day slack for timezone differences

    def _run(self, df: pd.DataFrame) -> tuple[int, int, list[int]]:
        col = pd.to_datetime(df["posted_date"], errors="coerce")
        has_valid_date = col.notna()
        checked_df = df[has_valid_date]

        if checked_df.empty:
            return len(df), 0, []

        today = datetime.now(tz=UTC).date()
        max_allowed = pd.Timestamp(today) + pd.Timedelta(days=self._TOLERANCE_DAYS)
        future_mask = col[has_valid_date] > max_allowed
        failed_idx = list(checked_df.index[future_mask])
        return int(has_valid_date.sum()), len(failed_idx), failed_idx

    def _fail_threshold_pct(self) -> float:
        return self.config.future_date_fail_pct

    def _warn_threshold_pct(self) -> float:
        return self.config.future_date_warn_pct


# =============================================================================
# CHECK 6 — NullCompanyNameCheck
# =============================================================================


class NullCompanyNameCheck(BaseCheck):
    """Check: proportion of jobs with no company name.

    WHY this matters:
        Company name is the second most important analytical dimension after
        job title. "Top Hiring Companies" — the flagship visualisation — becomes
        meaningless if a large fraction of jobs have no company attribution.

    Different from MissingValuesCheck?
        MissingValuesCheck is for ANY column. This check has domain-specific
        context: the company_name column is nullable by design (some aggregators
        scrape listings without employer names), so the threshold is intentionally
        more lenient than a generic missing-values check.
    """

    check_name: ClassVar[str] = "completeness.null_company_name"
    severity: ClassVar[CheckSeverity] = CheckSeverity.WARNING
    column_required: ClassVar[str | None] = "company_name"

    def _run(self, df: pd.DataFrame) -> tuple[int, int, list[int]]:
        null_mask = df["company_name"].isna() | (df["company_name"].str.strip() == "")
        failed_idx = list(df.index[null_mask])
        return len(df), int(null_mask.sum()), failed_idx

    def _fail_threshold_pct(self) -> float:
        return self.config.null_company_name_fail_pct

    def _warn_threshold_pct(self) -> float:
        return self.config.null_company_name_warn_pct


# =============================================================================
# CHECK 7 — InvalidURLCheck
# =============================================================================


class InvalidURLCheck(BaseCheck):
    """Check: posting URLs are well-formed (valid scheme + netloc).

    A URL is valid if:
        1. It starts with http:// or https://
        2. urllib.parse.urlparse() extracts a non-empty netloc (domain)
        3. The netloc contains at least one dot (e.g., "linkedin.com")

    WHY this matters:
        Malformed URLs are unusable — candidates can't apply, and the
        "Apply Now" button in Power BI drill-throughs would navigate to
        a broken page. Detecting them here allows early remediation.

    Column: posting_url (optional — check is SKIPPED if column absent)
    """

    check_name: ClassVar[str] = "validity.invalid_url"
    severity: ClassVar[CheckSeverity] = CheckSeverity.WARNING
    column_required: ClassVar[str | None] = "posting_url"

    _VALID_SCHEMES: ClassVar[frozenset[str]] = frozenset({"http", "https"})

    def _run(self, df: pd.DataFrame) -> tuple[int, int, list[int]]:
        has_url = df["posting_url"].notna() & (df["posting_url"].str.strip() != "")
        url_df = df[has_url]

        if url_df.empty:
            return len(df), 0, []

        def _is_invalid_url(url: str) -> bool:
            try:
                parsed = urllib.parse.urlparse(str(url).strip())
                return not (
                    parsed.scheme in self._VALID_SCHEMES
                    and parsed.netloc
                    and "." in parsed.netloc
                )
            except Exception:
                return True

        invalid_mask = url_df["posting_url"].apply(_is_invalid_url)
        failed_idx = list(url_df.index[invalid_mask])
        return int(has_url.sum()), len(failed_idx), failed_idx

    def _fail_threshold_pct(self) -> float | None:
        return None  # URLs missing is a WARN, not a FAIL condition

    def _warn_threshold_pct(self) -> float:
        return self.config.invalid_url_warn_pct


# =============================================================================
# CHECK 8 — InvalidCurrencyCheck
# =============================================================================


class InvalidCurrencyCheck(BaseCheck):
    """Check: currency codes are from the known valid set.

    Valid codes are defined in config.valid_currency_codes (ISO 4217).
    Default: USD, EUR, GBP, CAD, AUD, INR, SGD, CHF, JPY, CNY, NZD.

    WHY this matters:
        An unrecognised currency code (e.g., "US$", "dollar", "K") means
        the salary cannot be normalised to a common currency for comparison.
        Salary analytics that mix currencies without conversion produce
        nonsensical averages (mixing GBP and USD as if they're equal).

    Column: currency_code (skipped if absent)
    """

    check_name: ClassVar[str] = "validity.invalid_currency"
    severity: ClassVar[CheckSeverity] = CheckSeverity.WARNING
    column_required: ClassVar[str | None] = "currency_code"

    def _run(self, df: pd.DataFrame) -> tuple[int, int, list[int]]:
        has_currency = df["currency_code"].notna() & (
            df["currency_code"].str.strip() != ""
        )
        currency_df = df[has_currency]

        if currency_df.empty:
            return len(df), 0, []

        valid_codes = set(self.config.valid_currency_codes)
        invalid_mask = (
            ~currency_df["currency_code"].str.upper().str.strip().isin(valid_codes)
        )
        failed_idx = list(currency_df.index[invalid_mask])
        return int(has_currency.sum()), len(failed_idx), failed_idx

    def _warn_threshold_pct(self) -> float:
        return self.config.invalid_currency_warn_pct


# =============================================================================
# CHECK 9 — EmptyJobDescriptionCheck
# =============================================================================


class EmptyJobDescriptionCheck(BaseCheck):
    """Check: job descriptions are present and meet a minimum length.

    A description is "empty" if:
        - It is null/NaN
        - It is whitespace-only
        - It is shorter than config.min_description_length characters (default 20)

    WHY this matters:
        Job descriptions are the SOURCE of skill extraction. If the description
        is empty, the pipeline cannot extract any skills for that posting.
        A high empty-description rate means the skills data is sparse,
        which makes "Most In-Demand Skills" charts inaccurate.
    """

    check_name: ClassVar[str] = "completeness.empty_job_description"
    severity: ClassVar[CheckSeverity] = CheckSeverity.WARNING
    column_required: ClassVar[str | None] = "description"

    def _run(self, df: pd.DataFrame) -> tuple[int, int, list[int]]:
        min_len = self.config.min_description_length
        empty_mask = (
            df["description"].isna()
            | (df["description"].str.strip() == "")
            | (df["description"].str.len() < min_len)
        )
        failed_idx = list(df.index[empty_mask])
        return len(df), int(empty_mask.sum()), failed_idx

    def _fail_threshold_pct(self) -> float:
        return self.config.empty_description_fail_pct

    def _warn_threshold_pct(self) -> float:
        return self.config.empty_description_warn_pct


# =============================================================================
# CHECK 10 — DuplicateSkillsCheck
# =============================================================================


class DuplicateSkillsCheck(BaseCheck):
    """Check: skills extracted for a job contain no duplicate entries.

    After transformation, skills are stored as a pipe-separated string:
        "Python|SQL|Apache Spark|Python"   ← 'Python' appears twice — FAIL

    A row is "failed" if its skills string contains any repeated skill
    after splitting on '|' and stripping whitespace.

    WHY this matters:
        Duplicate skills in the skills string cause double-counting in the
        "Top Skills by Demand" chart. If Python appears twice for a job,
        that job counts twice toward Python's demand score.
    """

    check_name: ClassVar[str] = "uniqueness.duplicate_skills"
    severity: ClassVar[CheckSeverity] = CheckSeverity.WARNING
    column_required: ClassVar[str | None] = "skills"

    def _run(self, df: pd.DataFrame) -> tuple[int, int, list[int]]:
        has_skills = df["skills"].notna() & (df["skills"].str.strip() != "")
        skills_df = df[has_skills]

        if skills_df.empty:
            return len(df), 0, []

        def _has_duplicate_skills(skills_str: str) -> bool:
            skills = [s.strip() for s in str(skills_str).split("|") if s.strip()]
            return len(skills) != len(set(skills))

        dup_mask = skills_df["skills"].apply(_has_duplicate_skills)
        failed_idx = list(skills_df.index[dup_mask])
        return int(has_skills.sum()), len(failed_idx), failed_idx

    def _warn_threshold_pct(self) -> float:
        return self.config.duplicate_skills_warn_pct


# =============================================================================
# CHECK 11 — InvalidLocationCheck
# =============================================================================


class InvalidLocationCheck(BaseCheck):
    """Check: location fields have internally consistent values.

    Checks that if state_code is present, it is a valid 2-letter US state code.
    Also checks that country_code (if present) is a valid ISO 3166-1 alpha-2 code.

    WHY this matters:
        "Salary by City" and "Geographic Analysis" Power BI maps are driven
        by location data. A state_code of "NY" and country_code of "GB" is
        internally inconsistent — New York is not in Great Britain.
        Invalid location combinations create phantom entries in the locations
        dimension table.
    """

    check_name: ClassVar[str] = "consistency.invalid_location"
    severity: ClassVar[CheckSeverity] = CheckSeverity.WARNING

    # All valid US state codes (including DC and territories)
    _VALID_US_STATES: ClassVar[frozenset[str]] = frozenset(
        {
            "AL",
            "AK",
            "AZ",
            "AR",
            "CA",
            "CO",
            "CT",
            "DE",
            "FL",
            "GA",
            "HI",
            "ID",
            "IL",
            "IN",
            "IA",
            "KS",
            "KY",
            "LA",
            "ME",
            "MD",
            "MA",
            "MI",
            "MN",
            "MS",
            "MO",
            "MT",
            "NE",
            "NV",
            "NH",
            "NJ",
            "NM",
            "NY",
            "NC",
            "ND",
            "OH",
            "OK",
            "OR",
            "PA",
            "RI",
            "SC",
            "SD",
            "TN",
            "TX",
            "UT",
            "VT",
            "VA",
            "WA",
            "WV",
            "WI",
            "WY",
            "DC",
            "PR",
            "VI",
            "GU",
            "AS",
            "MP",
        }
    )

    # Commonly seen valid ISO 3166-1 alpha-2 country codes
    _VALID_COUNTRY_CODES: ClassVar[frozenset[str]] = frozenset(
        {
            "US",
            "GB",
            "CA",
            "AU",
            "DE",
            "FR",
            "IN",
            "SG",
            "NL",
            "CH",
            "SE",
            "NO",
            "DK",
            "FI",
            "BE",
            "AT",
            "NZ",
            "IE",
            "JP",
            "CN",
            "BR",
            "MX",
            "ZA",
            "AE",
            "HK",
            "PL",
            "PT",
            "ES",
            "IT",
        }
    )

    def _run(self, df: pd.DataFrame) -> tuple[int, int, list[int]]:
        if "state_code" not in df.columns and "country_code" not in df.columns:
            return len(df), 0, []

        invalid_mask = pd.Series(False, index=df.index)

        if "state_code" in df.columns:
            has_state = df["state_code"].notna() & (df["state_code"].str.strip() != "")
            # State code must be in the valid US state list
            invalid_state = has_state & ~df["state_code"].str.upper().isin(
                self._VALID_US_STATES
            )
            invalid_mask |= invalid_state

        if "country_code" in df.columns:
            has_country = df["country_code"].notna() & (
                df["country_code"].str.strip() != ""
            )
            invalid_country = has_country & ~df["country_code"].str.upper().isin(
                self._VALID_COUNTRY_CODES
            )
            invalid_mask |= invalid_country

        failed_idx = list(df.index[invalid_mask])
        return len(df), len(failed_idx), failed_idx

    def _warn_threshold_pct(self) -> float:
        return self.config.invalid_location_warn_pct


# =============================================================================
# REGISTRY — all checks available for use by ValidationRunner
# =============================================================================
# Checks here are in the DEFAULT order that ValidationRunner applies them.
# Ordering rationale:
#   1. Existence checks first (missing values) — most fundamental
#   2. Uniqueness checks — upstream duplicate → downstream pollution
#   3. Validity checks — format / range problems
#   4. Consistency checks — cross-field logic
#
# Note: MissingValuesCheck is NOT in this registry because it requires a
# column argument to instantiate. ValidationRunner creates one instance
# per column separately. All other checks take only (config) as argument.
# =============================================================================

ALL_CHECKS_REGISTRY: list[type[BaseCheck]] = [
    DuplicateJobsCheck,
    InvalidSalaryRangeCheck,
    InvalidDatesCheck,
    FuturePostingDatesCheck,
    NullCompanyNameCheck,
    InvalidURLCheck,
    InvalidCurrencyCheck,
    EmptyJobDescriptionCheck,
    DuplicateSkillsCheck,
    InvalidLocationCheck,
]

# Columns to run MissingValuesCheck against (in order)
MISSING_VALUES_COLUMNS: list[str] = [
    "job_title",
    "source_job_id",
    "company_name",
    "posted_date",
    "location_raw",
    "description",
]
