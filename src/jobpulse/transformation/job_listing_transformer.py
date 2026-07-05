"""jobpulse.transformation.job_listing_transformer — Full production transformer.

Transforms raw job posting DataFrames (as returned by the extraction layer)
into the standardised, typed, clean schema expected by the PostgreSQL tables:
    jobs, companies, locations, salary_ranges, job_skills

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TRANSFORMATION PIPELINE (order matters — each step depends on the previous)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Step 1 │ _validate_input_schema      Guard against missing required columns
  Step 2 │ _remove_duplicates          Eliminate repeated postings early
  Step 3 │ _clean_text_fields          Fix whitespace, encoding, empty strings
  Step 4 │ _drop_invalid_rows          Remove rows with no title or source_id
  Step 5 │ _standardise_company_names  Title-case, remove LLC/Inc suffixes
  Step 6 │ _parse_location             Split raw location into city/state/country
  Step 7 │ _normalise_work_arrangement Map free-text to REMOTE/HYBRID/ON_SITE
  Step 8 │ _normalise_salary           Parse salary strings to numeric min/max
  Step 9 │ _validate_salary_bounds     Reject salary rows where min > max
  Step 10│ _normalise_employment_type  Map free-text to controlled vocabulary
  Step 11│ _normalise_experience_level Map free-text to controlled vocabulary
  Step 12│ _extract_skills             Extract skill keywords from description
  Step 13│ _parse_dates                Parse raw date strings to date objects
  Step 14│ _convert_types              Cast all output columns to correct dtypes
  Step 15│ _validate_output_schema     Final guard: required output columns present

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

WHY NORMALISE HERE (not in the database)?

  Normalisation in Python (Pandas) is preferable to SQL-level cleaning because:
    1. Unit-testable — each step is a pure method testable in isolation.
    2. Auditable — the TransformationReport records per-step metrics.
    3. Flexible — regex patterns and mappings are Python dicts, not SQL CASE.
    4. Type-safe — Pandas dtype system enforces types before loading.
    5. Separation of concerns — the DB should only receive clean data.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EXAMPLE INPUT (raw from CsvExtractor or ApiExtractor):
    job_title     │ Company Name      │ location            │ salary
    Data Engineer │  ACME CORP.       │ New York, NY        │ $90k - $130k
    Sr. DE        │  acme corp        │ new york, new york  │ 90,000-130,000 USD
    data analyst  │  Beta Inc., LLC   │ Remote              │

EXAMPLE OUTPUT (after all 15 steps):
    job_title     │ canonical_title│ company_name │ city     │ state_code │ salary_min │ salary_max │ is_remote
    Data Engineer │ Data Engineer  │ Acme Corp    │ New York │ NY         │ 90000.0    │ 130000.0   │ False
    Data Analyst  │ Data Analyst   │ Beta Inc     │ None     │ None       │ None       │ None       │ True
"""

from __future__ import annotations

import re
from datetime import date

import pandas as pd

from jobpulse.transformation.base import BaseTransformer, DataTransformationError
from jobpulse.utils.date_utils import parse_date_string
from jobpulse.utils.string_utils import (
    clean_text,
    extract_salary_number,
    normalise_job_title,
)

# =============================================================================
# Column name mapping: raw source column → standard internal column
# This is the first thing applied — all downstream steps use standard names.
# =============================================================================

# Default mapping for Kaggle LinkedIn Job Postings dataset.
# Override by passing column_map to __init__ for other sources.
_DEFAULT_COLUMN_MAP: dict[str, str] = {
    # Kaggle / LinkedIn CSV headers → standard names
    "job_title": "job_title",
    "title": "job_title",
    "position": "job_title",
    "job_id": "source_job_id",
    "id": "source_job_id",
    "company_name": "company_name",
    "company": "company_name",
    "employer": "company_name",
    "location": "location_raw",
    "job_location": "location_raw",
    "city": "location_raw",
    "description": "description",
    "job_description": "description",
    "details": "description",
    "salary": "salary_raw",
    "salary_range": "salary_raw",
    "compensation": "salary_raw",
    "salary_min": "salary_min_raw",
    "min_salary": "salary_min_raw",
    "salary_max": "salary_max_raw",
    "max_salary": "salary_max_raw",
    "work_type": "employment_type_raw",
    "employment_type": "employment_type_raw",
    "job_type": "employment_type_raw",
    "contract_type": "employment_type_raw",
    "experience_level": "experience_level_raw",
    "seniority_level": "experience_level_raw",
    "level": "experience_level_raw",
    "experience": "experience_level_raw",
    "remote_allowed": "remote_flag_raw",
    "remote": "remote_flag_raw",
    "work_from_home": "remote_flag_raw",
    "posted_date": "posted_date_raw",
    "date_posted": "posted_date_raw",
    "job_posted_date": "posted_date_raw",
    "listed_time": "posted_date_raw",
    "url": "posting_url",
    "job_url": "posting_url",
    "apply_url": "posting_url",
    "skills": "skills_raw",
    "required_skills": "skills_raw",
    "currency": "currency_code",
    "pay_period": "salary_period_raw",
}

# Required columns that MUST be present in the input (before mapping)
# We accept any of the alternative names for each requirement.
_REQUIRED_INPUT_COLUMNS: list[frozenset[str]] = [
    # At least one of these must exist as a job title column
    frozenset({"job_title", "title", "position"}),
]

# Required columns that MUST be present in the output (after all steps)
_REQUIRED_OUTPUT_COLUMNS: frozenset[str] = frozenset(
    {
        "job_title",
        "company_name",
    }
)

# ─── Employment type controlled vocabulary ───────────────────────────────────
_EMPLOYMENT_TYPE_MAP: dict[str, str] = {
    # Maps lowercased source values → standard type_code
    "full-time": "FULL_TIME",
    "full time": "FULL_TIME",
    "fulltime": "FULL_TIME",
    "ft": "FULL_TIME",
    "f": "FULL_TIME",
    "part-time": "PART_TIME",
    "part time": "PART_TIME",
    "parttime": "PART_TIME",
    "pt": "PART_TIME",
    "contract": "CONTRACT",
    "contractor": "CONTRACT",
    "consulting": "CONTRACT",
    "freelance": "FREELANCE",
    "self-employed": "FREELANCE",
    "internship": "INTERNSHIP",
    "intern": "INTERNSHIP",
    "co-op": "INTERNSHIP",
    "temporary": "TEMPORARY",
    "temp": "TEMPORARY",
    "seasonal": "TEMPORARY",
}

# ─── Experience level controlled vocabulary ───────────────────────────────────
_EXPERIENCE_LEVEL_MAP: dict[str, str] = {
    "fresher": "ENTRY",
    "entry level": "ENTRY",
    "entry-level": "ENTRY",
    "junior": "ENTRY",
    "jr": "ENTRY",
    "graduate": "ENTRY",
    "associate": "ENTRY",
    "0-2": "ENTRY",
    "mid level": "MID",
    "mid-level": "MID",
    "intermediate": "MID",
    "2-5": "MID",
    "senior": "SENIOR",
    "sr": "SENIOR",
    "experienced": "SENIOR",
    "5+": "SENIOR",
    "lead": "LEAD",
    "principal": "LEAD",
    "staff": "LEAD",
    "architect": "LEAD",
    "director": "EXECUTIVE",
    "vp": "EXECUTIVE",
    "head": "EXECUTIVE",
    "chief": "EXECUTIVE",
    "c-level": "EXECUTIVE",
    "executive": "EXECUTIVE",
}

# ─── Skills catalog (case-insensitive, checked against description text) ─────
_SKILL_PATTERNS: dict[str, list[str]] = {
    "Python": [r"\bpython\b"],
    "SQL": [r"\bsql\b"],
    "PostgreSQL": [r"\bpostgresql\b", r"\bpostgres\b"],
    "MySQL": [r"\bmysql\b"],
    "Oracle": [r"\boracle\b"],
    "MongoDB": [r"\bmongodb\b", r"\bmongo\b"],
    "Spark": [r"\bspark\b", r"\bapache spark\b"],
    "PySpark": [r"\bpyspark\b"],
    "Kafka": [r"\bkafka\b", r"\bapache kafka\b"],
    "Airflow": [r"\bairflow\b", r"\bapache airflow\b"],
    "AWS": [r"\baws\b", r"\bamazon web services\b"],
    "Azure": [r"\bazure\b", r"\bmicrosoft azure\b"],
    "GCP": [r"\bgcp\b", r"\bgoogle cloud\b"],
    "Snowflake": [r"\bsnowflake\b"],
    "Databricks": [r"\bdatabricks\b"],
    "dbt": [r"\bdbt\b", r"\bdata build tool\b"],
    "Docker": [r"\bdocker\b"],
    "Kubernetes": [r"\bkubernetes\b", r"\bk8s\b"],
    "Power BI": [r"\bpower bi\b", r"\bpowerbi\b"],
    "Tableau": [r"\btableau\b"],
    "Git": [r"\bgit\b(?!hub)"],
    "GitHub": [r"\bgithub\b"],
    "Linux": [r"\blinux\b"],
    "Pandas": [r"\bpandas\b"],
    "NumPy": [r"\bnumpy\b"],
    "Hadoop": [r"\bhadoop\b"],
    "Hive": [r"\bhive\b", r"\bapache hive\b"],
    "Delta Lake": [r"\bdelta lake\b", r"\bdelta-lake\b"],
    "Java": [r"\bjava\b"],
    "Scala": [r"\bscala\b"],
    "Go": [r"\bgolang\b", r"\bgo\b(?!\s*to)"],
    "C++": [r"\bc\+\+\b"],
    "C#": [r"\bc#\b", r"\bc sharp\b"],
    "R": [r"\br\b(?!\s*and)"],
    "TensorFlow": [r"\btensorflow\b"],
    "PyTorch": [r"\bpytorch\b"],
    "Scikit-Learn": [r"\bscikit-learn\b", r"\bsklearn\b"],
    "LLM": [r"\bllm\b", r"\blarge language model\b"],
    "Redis": [r"\bredis\b"],
    "Elasticsearch": [r"\belasticsearch\b", r"\belk\b"],
    "Redshift": [r"\bredshift\b"],
    "BigQuery": [r"\bbigquery\b"],
    "Cassandra": [r"\bcassandra\b"],
    "Fivetran": [r"\bfivetran\b"],
    "Airbyte": [r"\bairbyte\b"],
    "Looker": [r"\blooker\b"],
    "Terraform": [r"\bterraform\b"],
    "CI/CD": [r"\bci/cd\b", r"\bcontinuous integration\b"],
    "Jenkins": [r"\bjenkins\b"],
    "React": [r"\breact\b", r"\breactjs\b"],
    "TypeScript": [r"\btypescript\b", r"\bts\b"],
}

# US state abbreviation lookup (for location parsing)
_US_STATE_ABBR: dict[str, str] = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
    "district of columbia": "DC",
    "washington dc": "DC",
    "washington d.c.": "DC",
}

# Reverse lookup: abbreviation → full name
_US_STATE_ABBR_REVERSE: dict[str, str] = {
    v: k.title() for k, v in _US_STATE_ABBR.items()
}

# Patterns that indicate a remote-only position
_REMOTE_PATTERNS: list[str] = [
    r"\bremote\b",
    r"\bwork from home\b",
    r"\bwfh\b",
    r"\bfully remote\b",
    r"\bvirtual\b",
    r"\banywhere\b",
    r"\bremote-first\b",
    r"\bremote first\b",
]

# Patterns that indicate a hybrid position
_HYBRID_PATTERNS: list[str] = [
    r"\bhybrid\b",
    r"\bflexible\b",
    r"\bpartially remote\b",
    r"\b2 days.*office\b",
    r"\b3 days.*office\b",
]

# Company name suffixes to strip for normalisation
_COMPANY_SUFFIX_PATTERN = re.compile(
    r"""
    \s*                                  # leading whitespace
    [\.,]?                               # optional trailing punctuation
    \s*
    (?:                                  # suffix group (non-capturing)
        LLC|L\.L\.C\.|Inc|Inc\.|
        Ltd|Ltd\.|Limited|Corp|Corp\.|
        Corporation|Co\.|Company|
        PLC|plc|GmbH|S\.A\.|AG|B\.V\.|
        Associates|Partners|Group|
        Holdings|Technologies|Solutions|
        Consulting|Ventures|Services|
        International|Worldwide|Global|
        Enterprises|Systems|Networks
    )
    \.?                                  # optional trailing period
    \s*$                                 # end of string
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Maximum salary sanity check (annual)
_MAX_REASONABLE_SALARY: float = 5_000_000.0
_MIN_REASONABLE_SALARY: float = 1_000.0  # Below this is probably hourly or garbage


class JobListingTransformer(BaseTransformer):
    """Production transformer for raw job listing DataFrames.

    Applies 15 ordered transformation steps to convert raw extraction output
    into a clean, typed, schema-validated DataFrame ready for the validation
    and loading layers.

    Each step is an isolated method that takes a DataFrame and returns a
    new DataFrame. This design makes each step independently unit-testable.

    Design Decision — Fail Row, Not Pipeline:
        Most steps that encounter bad data (unparseable salary, invalid date)
        set the value to NaN and log a warning. Only truly unrecoverable
        failures (missing required column entirely) raise DataTransformationError.
        This ensures the pipeline loads 95% of good data even if 5% is malformed.

    Attributes:
        source_name:  Identifier for the data source (e.g., 'linkedin_csv').
                      Used to look up the correct column mapping.
        column_map:   Dict mapping raw column names → standard column names.
                      Defaults to _DEFAULT_COLUMN_MAP if not provided.
    """

    def __init__(
        self,
        source_name: str = "default",
        column_map: dict[str, str] | None = None,
    ) -> None:
        """Initialise the job listing transformer.

        Args:
            source_name: Short identifier for the data source.
                         Used in logs and the TransformationReport.
            column_map:  Optional custom column name mapping.
                         If None, uses the default Kaggle/LinkedIn mapping.
        """
        super().__init__(transformer_name=f"job_listing_{source_name}")
        self.source_name = source_name
        self.column_map: dict[str, str] = column_map or _DEFAULT_COLUMN_MAP

    # =========================================================================
    # Public entry point — delegates to BaseTransformer.run()
    # =========================================================================

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply all 15 transformation steps in sequence.

        Args:
            df: Raw DataFrame from the extraction layer.
                All values are expected to be strings (dtype=object).

        Returns:
            pd.DataFrame: Fully cleaned, typed, schema-validated DataFrame.

        Raises:
            DataTransformationError: If input schema validation fails or any
                                     unrecoverable step fails.
        """
        result = df.copy()

        # ── Step 1: Validate input schema ─────────────────────────────────────
        result = self._map_columns(result)
        self._validate_input_schema(result)

        # ── Step 2: Remove duplicates ─────────────────────────────────────────
        result = self._remove_duplicates(result)

        # ── Step 3: Clean all text fields ─────────────────────────────────────
        result = self._clean_text_fields(result)

        # ── Step 4: Drop rows missing mandatory fields ────────────────────────
        result = self._drop_invalid_rows(result)

        # ── Step 5: Standardise company names ─────────────────────────────────
        result = self._standardise_company_names(result)

        # ── Step 6: Parse location into components ────────────────────────────
        result = self._parse_location(result)

        # ── Step 7: Normalise work arrangement ────────────────────────────────
        result = self._normalise_work_arrangement(result)

        # ── Step 8: Parse salary strings to numeric min/max ───────────────────
        result = self._normalise_salary(result)

        # ── Step 9: Validate salary logical bounds ────────────────────────────
        result = self._validate_salary_bounds(result)

        # ── Step 10: Normalise employment type ────────────────────────────────
        result = self._normalise_employment_type(result)

        # ── Step 11: Normalise experience level ───────────────────────────────
        result = self._normalise_experience_level(result)

        # ── Step 12: Extract skills from description ──────────────────────────
        result = self._extract_skills(result)

        # ── Step 13: Parse date fields ────────────────────────────────────────
        result = self._parse_dates(result)

        # ── Step 14: Convert all columns to correct dtypes ───────────────────
        result = self._convert_types(result)

        # ── Step 15: Validate output schema ───────────────────────────────────
        self._validate_output_schema(result)

        return result

    # =========================================================================
    # Step 1a — Column mapping
    # =========================================================================

    def _map_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Rename raw source columns to the standard internal schema names.

        WHY:
            Every data source uses different column names ('Job Title' vs 'title'
            vs 'position'). Centralising the mapping here means all downstream
            steps work against a single consistent set of names.

        Strategy:
            1. Build a rename dict from the intersection of actual columns
               and the mapping keys.
            2. Columns not in the mapping are kept as-is (not dropped here).
            3. Logs any columns that were not recognised.
        """
        self._logger.info("Step 1: Mapping columns from source '%s'", self.source_name)

        # Build the rename mapping (only for columns that exist in the DataFrame)
        rename_map = {
            raw_col: std_col
            for raw_col, std_col in self.column_map.items()
            if raw_col in df.columns
        }

        if rename_map:
            self._logger.debug(
                "  Renaming %d column(s): %s", len(rename_map), rename_map
            )
        else:
            self._logger.debug(
                "  No columns renamed (all already standard or unrecognised)."
            )

        df = df.rename(columns=rename_map)

        # Log unmapped columns so engineers know to update the map
        standard_cols = set(self.column_map.values()) | {"_source_file"}
        unmapped = [c for c in df.columns if c not in standard_cols]
        if unmapped:
            self._logger.debug("  Unmapped columns (kept as-is): %s", unmapped)

        self._record_metric("columns_mapped", len(rename_map))
        return df

    # =========================================================================
    # Step 1b — Input schema validation
    # =========================================================================

    def _validate_input_schema(self, df: pd.DataFrame) -> None:
        """Guard that required source columns are present before transformation begins.

        WHY:
            Failing fast on missing columns is better than cryptic KeyError
            exceptions deep inside a later step. This gives the operator a clear
            message about which columns to add to the source or column_map.

        Raises:
            DataTransformationError: If none of the alternative names for a
                                     required column group are present.
        """
        self._logger.info("Step 1b: Validating input schema")

        for group in _REQUIRED_INPUT_COLUMNS:
            if not group.intersection(df.columns):
                raise DataTransformationError(
                    message=(
                        f"Required column is missing from input DataFrame. "
                        f"Expected one of: {sorted(group)}. "
                        f"Available columns: {sorted(df.columns)}. "
                        f"Update the column_map for source '{self.source_name}'."
                    ),
                    step_name="_validate_input_schema",
                )

        self._logger.debug("  Input schema validation PASSED.")

    # =========================================================================
    # Step 2 — Remove duplicates
    # =========================================================================

    def _remove_duplicates(self, df: pd.DataFrame) -> pd.DataFrame:
        """Remove duplicate job postings based on business-key columns.

        WHY:
            Duplicate rows arise from:
              1. The same job posted multiple times in one file (refreshed listing).
              2. Multiple CSV files containing overlapping date ranges.
              3. Re-running the pipeline on the same data.
            Loading duplicates bloats the database, inflates analytics counts,
            and violates the UNIQUE(source_job_id, data_source_id) constraint.

        Strategy:
            Primary key: source_job_id (if present) — most reliable.
            Fallback key: (job_title, company_name, location_raw) — when
              source_job_id is absent, treat same job+company+location as duplicate.
            Keeps the FIRST occurrence (assumes earlier = more original).
        """
        self._logger.info("Step 2: Removing duplicates")
        before = len(df)

        if "source_job_id" in df.columns:
            # Drop rows where source_job_id is null, then dedup on it
            has_id = df["source_job_id"].notna() & (
                df["source_job_id"].str.strip() != ""
            )
            df_with_id = df[has_id].drop_duplicates(
                subset=["source_job_id"], keep="first"
            )
            df_without_id = df[~has_id]

            # Also dedup the rows that lack an ID using fallback keys
            fallback_keys = [
                c
                for c in ["job_title", "company_name", "location_raw"]
                if c in df.columns
            ]
            if fallback_keys and not df_without_id.empty:
                df_without_id = df_without_id.drop_duplicates(
                    subset=fallback_keys, keep="first"
                )

            df = pd.concat([df_with_id, df_without_id], ignore_index=True)
            self._logger.debug("  Deduped on 'source_job_id' and fallback keys")
        else:
            # Fallback: content-based deduplication
            fallback_keys = [
                c
                for c in ["job_title", "company_name", "location_raw"]
                if c in df.columns
            ]
            if fallback_keys:
                df = df.drop_duplicates(subset=fallback_keys, keep="first")
                self._logger.debug("  Deduped on fallback keys: %s", fallback_keys)

        removed = before - len(df)
        self._record_metric("duplicates_removed", removed)
        if removed:
            self._warn(f"Removed {removed} duplicate row(s) in step 2.")
        else:
            self._logger.debug("  No duplicates found.")
        return df.reset_index(drop=True)

    # =========================================================================
    # Step 3 — Clean text fields
    # =========================================================================

    def _clean_text_fields(self, df: pd.DataFrame) -> pd.DataFrame:
        """Strip whitespace, collapse internal spaces, and blank-out empty strings.

        WHY:
            Raw data from CSVs and APIs frequently contains:
              - Leading/trailing whitespace ("  Data Engineer  ")
              - Multiple internal spaces ("Data  Engineer")
              - Cells containing only whitespace ("   ") that should be NULL
              - Mixed case for the same company ("ACME", "acme", "Acme")
            Cleaning text before any downstream step ensures all comparisons
            and lookups work on consistent input.

        WHY convert whitespace-only cells to None:
            Storing "   " in PostgreSQL is misleading — it looks filled but
            is semantically empty. Explicit NULL is unambiguous.
        """
        self._logger.info("Step 3: Cleaning text fields")

        text_columns = [
            "job_title",
            "company_name",
            "location_raw",
            "description",
            "salary_raw",
            "employment_type_raw",
            "experience_level_raw",
            "posting_url",
            "skills_raw",
            "source_job_id",
            "currency_code",
            "salary_period_raw",
            "remote_flag_raw",
        ]

        total_blanked = 0
        for col in text_columns:
            if col not in df.columns:
                continue
            # Apply clean_text row-wise using vectorised where possible
            original_nulls = df[col].isna().sum()
            df[col] = df[col].apply(
                lambda v: clean_text(str(v)) if pd.notna(v) and str(v).strip() else None
            )
            new_nulls = df[col].isna().sum()
            blanked = new_nulls - original_nulls
            total_blanked += blanked

        self._record_metric("cells_blanked_to_null", total_blanked)
        self._logger.debug(
            "  Blanked %d whitespace-only cell(s) to None.", total_blanked
        )
        return df

    # =========================================================================
    # Step 4 — Drop invalid rows
    # =========================================================================

    def _drop_invalid_rows(self, df: pd.DataFrame) -> pd.DataFrame:
        """Flag rows that cannot be usefully loaded instead of dropping them."""
        self._logger.info("Step 4: Flagging invalid rows")

        # Initialize flags
        df["is_valid"] = True
        df["validation_errors"] = ""
        df["salary_parse_success"] = True
        df["location_parse_success"] = True

        n_no_title = 0
        if "job_title" in df.columns:
            invalid_title = df["job_title"].isna() | (df["job_title"].str.strip() == "")
            n_no_title = invalid_title.sum()
            if n_no_title:
                self._warn(
                    f"Flagging {n_no_title} row(s) as invalid due to missing job_title."
                )
                df.loc[invalid_title, "is_valid"] = False
                df.loc[invalid_title, "validation_errors"] += "Missing job_title. "

        if "posting_url" in df.columns:
            url_mask = df["posting_url"].notna()
            bad_url_mask = url_mask & ~df["posting_url"].str.lower().str.startswith(
                ("http://", "https://")
            )
            n_bad_url = bad_url_mask.sum()
            if n_bad_url:
                self._warn(f"Flagging {n_bad_url} malformed posting_url(s).")
                df.loc[bad_url_mask, "validation_errors"] += "Malformed URL. "
                df.loc[bad_url_mask, "posting_url"] = None

        self._record_metric("invalid_rows_flagged", int(n_no_title))
        self._record_metric("missing_required_fields", int(n_no_title))
        return df

    # =========================================================================
    # Step 5 — Standardise company names
    # =========================================================================

    def _standardise_company_names(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalise company names to consistent title-case, removing legal suffixes.

        WHY:
            The same employer appears as: 'ACME CORP', 'Acme Corp.', 'acme corp',
            'Acme Corp, Inc.', 'Acme Corp LLC'. Without normalisation, each variant
            becomes a separate company record in the database, fragmenting analytics
            (Top Hiring Companies chart would show the same company 5 times).

        Transformations applied:
            1. Strip the string.
            2. Remove legal suffixes (LLC, Inc, Ltd, Corp, etc.) via regex.
            3. Apply Title Case (so 'DATA ENGINEER INC' → 'Data Engineer').
            4. Collapse any trailing/leading punctuation left after suffix removal.
            5. Final strip.

        WHY Title Case and not preserve original casing:
            Title Case is the correct English convention for proper nouns (company
            names). All-caps and all-lowercase are data quality issues, not intent.
        """
        self._logger.info("Step 5: Standardising company names")

        if "company_name" not in df.columns:
            self._logger.debug("  No 'company_name' column — skipping.")
            return df

        def _normalise(name: str | None) -> str | None:
            if not name or not str(name).strip():
                return None
            cleaned = str(name).strip()
            # Remove legal suffix (may need multiple passes for e.g. 'Corp. Inc.')
            for _ in range(3):
                prev = cleaned
                cleaned = _COMPANY_SUFFIX_PATTERN.sub("", cleaned).strip(" .,")
                if cleaned == prev:
                    break
            # Title-case the result
            cleaned_final = cleaned.strip(" .,").title() if cleaned else None
            # Re-strip (title() can add leading/trailing whitespace rarely)
            return cleaned_final.strip() if cleaned_final else None

        before_unique = df["company_name"].nunique(dropna=True)
        df["company_name"] = df["company_name"].apply(_normalise)
        after_unique = df["company_name"].nunique(dropna=True)

        collapsed = before_unique - after_unique
        self._record_metric("company_names_collapsed", collapsed)
        if collapsed:
            self._logger.debug(
                "  Company name deduplication: %d unique → %d unique (%d collapsed).",
                before_unique,
                after_unique,
                collapsed,
            )

        # Derive canonical title while we're processing
        if "job_title" in df.columns:
            df["canonical_title"] = df["job_title"].apply(normalise_job_title)
        return df

    # =========================================================================
    # Step 6 — Parse location
    # =========================================================================

    def _parse_location(self, df: pd.DataFrame) -> pd.DataFrame:
        """Parse the raw location string into city, state_code, country_code components.

        WHY:
            The locations table in the 3NF schema stores city, state, and country
            as separate columns. The source data contains free-form strings like:
              'New York, NY'  →  city='New York', state_code='NY', country_code='US'
              'San Francisco' →  city='San Francisco', state_code=None, country_code='US'
              'London, UK'    →  city='London', state_code=None, country_code='GB'
              'Remote'        →  city=None, state_code=None (remote flag set in step 7)

        Strategy:
            1. If the raw value contains 'remote' (any case) → skip (handled by step 7).
            2. Split on comma: last part checked against US state abbreviation dict.
            3. If the last part is a 2-letter code, treat as country code or state code.
            4. Everything before the last comma is city.
            5. Default country to 'US' for North American datasets.
        """
        self._logger.info("Step 6: Parsing location")

        if "location_raw" not in df.columns:
            self._logger.debug("  No 'location_raw' column — skipping.")
            df["city"] = None
            df["state_code"] = None
            df["country_code"] = None
            return df

        parsed = df["location_raw"].apply(self._parse_single_location)
        parsed_df = pd.DataFrame(
            parsed.tolist(),
            columns=["city", "state_code", "country_code"],
            index=df.index,
        )
        df = pd.concat([df, parsed_df], axis=1)

        # Flag parse failures
        failed_parse = (
            df["location_raw"].notna()
            & df["city"].isna()
            & df["state_code"].isna()
            & df["country_code"].isna()
        )
        # Exempt remote strings from being flagged as failed parses
        is_remote_str = (
            df["location_raw"]
            .fillna("")
            .str.lower()
            .apply(lambda x: any(re.search(pat, x) for pat in _REMOTE_PATTERNS))
        )
        failed_actual = failed_parse & ~is_remote_str
        df.loc[failed_actual, "location_parse_success"] = False
        df.loc[failed_actual, "validation_errors"] += "Unparseable Location. "

        self._record_metric("invalid_locations", int(failed_actual.sum()))

        parsed_count = parsed_df["city"].notna().sum()
        self._record_metric("locations_parsed", int(parsed_count))
        self._logger.debug(
            "  Parsed %d/%d location(s) into city/state/country.",
            parsed_count,
            len(df),
        )
        return df

    def _parse_single_location(
        self, raw: str | None
    ) -> tuple[str | None, str | None, str | None]:
        """Parse one raw location string into (city, state_code, country_code).

        Args:
            raw: Raw location string (e.g., 'New York, NY', 'London, UK').

        Returns:
            Tuple of (city, state_code, country_code).
            All elements may be None if the location cannot be parsed.
        """
        if not raw or not str(raw).strip():
            return None, None, None

        raw = str(raw).strip()

        # Check for fully remote indicator — city/state not meaningful
        if any(re.search(pat, raw, re.IGNORECASE) for pat in _REMOTE_PATTERNS):
            return None, None, None

        parts = [p.strip() for p in raw.split(",")]
        parts = [p for p in parts if p]  # Remove empty strings

        if not parts:
            return None, None, None

        if len(parts) == 1:
            # Single part: e.g. 'New York' or 'CA'
            city_or_state = parts[0]
            state_code = self._resolve_state(city_or_state)
            if state_code:
                return None, state_code, "US"
            return city_or_state.title(), None, "US"

        if len(parts) == 2:
            city_part, region_part = parts[0], parts[1]
            state_code = self._resolve_state(region_part)
            country_code = self._resolve_country(region_part)

            if state_code:
                return city_part.title(), state_code, "US"
            if country_code:
                return city_part.title(), None, country_code
            # Unknown region — keep as-is
            return city_part.title(), region_part.upper()[:10], "US"

        # 3+ parts: e.g. 'New York, NY, United States' or 'Bengaluru, Karnataka, India'
        city_part = parts[0]
        state_code = self._resolve_state(parts[1])
        country_code = self._resolve_country(parts[-1])

        # If it's 3 parts but we can't find a known country for the last part,
        # it might just be City, Region, Country we don't track well.
        # Fallback to US if entirely unsure, but if we found a valid country code we use it.
        # And if state is unknown, it's None.
        return (
            city_part.title(),
            state_code,
            country_code or ("US" if state_code else "UNKNOWN"),
        )

    @staticmethod
    def _resolve_state(token: str) -> str | None:
        """Resolve a token to a US state abbreviation code."""
        token = token.strip().lower()
        # Already an abbreviation (e.g. 'NY')
        if token.upper() in _US_STATE_ABBR_REVERSE:
            return token.upper()
        # Full state name (e.g. 'New York')
        return _US_STATE_ABBR.get(token)

    @staticmethod
    def _resolve_country(token: str) -> str | None:
        """Resolve a token to an ISO-3166 alpha-2 country code."""
        _COUNTRY_MAP = {
            "united states": "US",
            "usa": "US",
            "us": "US",
            "u.s.": "US",
            "united kingdom": "GB",
            "uk": "GB",
            "gb": "GB",
            "england": "GB",
            "canada": "CA",
            "ca": "CA",
            "australia": "AU",
            "au": "AU",
            "india": "IN",
            "in": "IN",
            "germany": "DE",
            "de": "DE",
            "france": "FR",
            "fr": "FR",
            "netherlands": "NL",
            "nl": "NL",
            "singapore": "SG",
            "sg": "SG",
            "ireland": "IE",
            "ie": "IE",
            "spain": "ES",
            "es": "ES",
            "italy": "IT",
            "it": "IT",
            "brazil": "BR",
            "br": "BR",
            "mexico": "MX",
            "mx": "MX",
            "japan": "JP",
            "jp": "JP",
            "china": "CN",
            "cn": "CN",
            "south africa": "ZA",
            "za": "ZA",
            "united arab emirates": "AE",
            "uae": "AE",
            "sweden": "SE",
            "se": "SE",
            "switzerland": "CH",
            "ch": "CH",
        }
        return _COUNTRY_MAP.get(token.strip().lower())

    # =========================================================================
    # Step 7 — Normalise work arrangement
    # =========================================================================

    def _normalise_work_arrangement(self, df: pd.DataFrame) -> pd.DataFrame:
        """Classify each posting as REMOTE, HYBRID, ON_SITE, or UNSPECIFIED.

        WHY:
            'Remote vs On-site jobs' is one of the core analytics requirements.
            Source data expresses this in wildly different ways: a dedicated
            column in some datasets, embedded in job title in others ('Remote
            Data Engineer'), or in the description text. A single normalised
            column makes the analytics query trivially simple.

        Strategy:
            Priority 1: remote_flag_raw column (if present — most reliable).
            Priority 2: location_raw contains 'remote', 'wfh', etc.
            Priority 3: job_title contains 'remote'.
            Priority 4: description contains remote/hybrid keywords.
            Default: UNSPECIFIED.
        """
        self._logger.info("Step 7: Normalising work arrangement")

        def _classify(row: pd.Series) -> tuple[str, bool | None]:
            """Return (work_arrangement_code, is_remote_bool)."""
            # ── Priority 1: explicit remote column ───────────────────────────
            if "remote_flag_raw" in row.index and pd.notna(row.get("remote_flag_raw")):
                flag = str(row["remote_flag_raw"]).strip().lower()
                if flag in {"1", "true", "yes", "y", "remote", "allowed"}:
                    return "REMOTE", True
                if flag in {"0", "false", "no", "n"}:
                    return "ON_SITE", False

            # ── Priority 2: location text ─────────────────────────────────────
            location = str(row.get("location_raw") or "").lower()
            if any(re.search(p, location) for p in _REMOTE_PATTERNS):
                return "REMOTE", True
            if any(re.search(p, location) for p in _HYBRID_PATTERNS):
                return "HYBRID", False

            # ── Priority 3: job title text ────────────────────────────────────
            title = str(row.get("job_title") or "").lower()
            if any(re.search(p, title) for p in _REMOTE_PATTERNS):
                return "REMOTE", True

            # ── Priority 4: description text (expensive — last resort) ────────
            desc = str(row.get("description") or "").lower()[:2000]  # cap cost
            if any(re.search(p, desc) for p in _REMOTE_PATTERNS):
                return "REMOTE", True
            if any(re.search(p, desc) for p in _HYBRID_PATTERNS):
                return "HYBRID", False

            return "UNSPECIFIED", None

        classifications = df.apply(_classify, axis=1)
        df["work_arrangement"] = [c[0] for c in classifications]
        df["is_remote"] = [c[1] for c in classifications]

        dist = df["work_arrangement"].value_counts().to_dict()
        self._record_metric("work_arrangement_distribution", dist)
        self._logger.debug("  Work arrangement distribution: %s", dist)
        return df

    # =========================================================================
    # Step 8 — Normalise salary
    # =========================================================================

    def _normalise_salary(self, df: pd.DataFrame) -> pd.DataFrame:
        """Parse salary strings into numeric salary_min and salary_max columns.

        WHY:
            'Salary trends' is a core analytics requirement. Source data stores
            salary as free-form strings: '$90k-$130k', '90,000 - 130,000 USD',
            '£75K', 'Competitive', '90000'. Without parsing, no arithmetic
            (averages, percentiles, medians) is possible.

        Strategy:
            1. If salary_min_raw and salary_max_raw exist separately → use them.
            2. If only salary_raw exists → try to split on '–', '-', 'to'.
               Take the left number as salary_min, right as salary_max.
            3. Apply extract_salary_number() to each bound.
            4. Normalise values that look like hourly pay to annual (×2080).
            5. Reject values outside reasonable bounds [1_000, 5_000_000].

        WHY Decimal for salary:
            Decimal avoids floating-point rounding errors that could corrupt
            financial comparisons. We store as Python float here (Pandas
            doesn't have a native Decimal dtype) but use NUMERIC in PostgreSQL.
        """
        self._logger.info("Step 8: Normalising salary values")

        # ── Case A: Separate min/max columns already exist ───────────────────
        if "salary_min_raw" in df.columns and "salary_max_raw" in df.columns:
            df["salary_min"] = df["salary_min_raw"].apply(extract_salary_number)
            df["salary_max"] = df["salary_max_raw"].apply(extract_salary_number)

        # ── Case B: Single combined salary column ────────────────────────────
        elif "salary_raw" in df.columns:
            splits = df["salary_raw"].apply(self._split_salary_range)
            df["salary_min"] = splits.apply(lambda x: x[0])
            df["salary_max"] = splits.apply(lambda x: x[1])
        else:
            df["salary_min"] = None
            df["salary_max"] = None

        # Attempt to detect hourly salary and annualise (×2080 = 40hr × 52wk)
        df = self._annualise_hourly_salary(df)

        # Coerce to float
        df["salary_min"] = pd.to_numeric(df["salary_min"], errors="coerce")
        df["salary_max"] = pd.to_numeric(df["salary_max"], errors="coerce")

        # Reject values outside sanity bounds
        df = self._reject_unreasonable_salary(df)

        # Currency code — default to USD if not present
        if "currency_code" not in df.columns:
            df["currency_code"] = "USD"
        else:
            df["currency_code"] = (
                df["currency_code"].fillna("USD").str.upper().str.strip()
            )

        # Try to infer currency from raw salary string if default was applied
        if "salary_raw" in df.columns:
            raw_lower = df["salary_raw"].fillna("").str.lower()
            mask_inr = raw_lower.str.contains(r"₹|inr|lakh|lpa", na=False)
            mask_gbp = raw_lower.str.contains(r"£|gbp", na=False)
            mask_eur = raw_lower.str.contains(r"€|eur", na=False)
            df.loc[mask_inr, "currency_code"] = "INR"
            df.loc[mask_gbp, "currency_code"] = "GBP"
            df.loc[mask_eur, "currency_code"] = "EUR"

        # Flag parse failures for salaries
        if "salary_raw" in df.columns:
            failed_salary = (
                df["salary_raw"].notna()
                & df["salary_min"].isna()
                & df["salary_max"].isna()
            )
            df.loc[failed_salary, "salary_parse_success"] = False
            df.loc[failed_salary, "validation_errors"] += "Unparseable Salary. "
            self._record_metric("invalid_salary_rows", int(failed_salary.sum()))

        # Salary period — default ANNUAL
        if "salary_period_raw" not in df.columns:
            df["salary_period"] = "ANNUAL"
        else:
            df["salary_period"] = (
                df["salary_period_raw"]
                .apply(self._normalise_salary_period)
                .fillna("ANNUAL")
            )

        # How many rows have parseable salary?
        has_salary = df["salary_min"].notna() | df["salary_max"].notna()
        self._record_metric("rows_with_salary", int(has_salary.sum()))
        self._record_metric("rows_without_salary", int((~has_salary).sum()))
        self._logger.debug(
            "  Salary parsed: %d/%d rows have at least one salary bound.",
            has_salary.sum(),
            len(df),
        )
        return df

    def _split_salary_range(
        self, salary_str: str | None
    ) -> tuple[float | None, float | None]:
        """Split a combined salary string into (min, max) numeric values.

        Handles formats: '$90k-$130k', '90000-130000', '90,000 to 130,000', '1.2 - 1.5 Crores'
        """
        if not salary_str:
            return None, None

        raw = str(salary_str).strip()

        # Try common delimiters between two numbers
        split_pattern = re.compile(
            r"([\$£€₹]?[\d,]+\.?\d*\s*[kmKM]?(?:\s*LPA|\s*Lakh|\s*Lakhs|\s*Crores?|\s*Cr)?)\s*[-–—to]+\s*([\$£€₹]?[\d,]+\.?\d*\s*[kmKM]?(?:\s*LPA|\s*Lakh|\s*Lakhs|\s*Crores?|\s*Cr)?)",
            re.IGNORECASE,
        )
        match = split_pattern.search(raw)
        if match:
            lo = extract_salary_number(match.group(1))
            hi = extract_salary_number(match.group(2))
            return lo, hi

        # Single value — treat as exact salary (min == max)
        single = extract_salary_number(raw)
        return single, single

    def _annualise_hourly_salary(self, df: pd.DataFrame) -> pd.DataFrame:
        """Convert hourly wages to annual equivalent by multiplying by 2080.

        WHY:
            Mixing hourly ($45/hr → $93,600/yr) with annual values in the same
            column destroys salary analytics. Without annualisation, a $45/hr
            Data Engineer appears to earn less than a $40,000/yr junior analyst.

        Heuristic: if salary_max is below 500 and salary_period is HOURLY,
        assume it is hourly. Applied conservatively to avoid false positives.
        """
        annual_multiplier = 2080  # 40 hours × 52 weeks

        period_col = (
            "salary_period" if "salary_period" in df.columns else "salary_period_raw"
        )
        if period_col not in df.columns:
            return df

        hourly_mask = df[period_col].str.upper().str.contains("HOUR", na=False)
        if hourly_mask.any():
            n_hourly = hourly_mask.sum()
            self._logger.debug(
                "  Annualising %d hourly salary row(s) (×%d).",
                n_hourly,
                annual_multiplier,
            )
            df.loc[hourly_mask, "salary_min"] = (
                pd.to_numeric(df.loc[hourly_mask, "salary_min"], errors="coerce")
                * annual_multiplier
            )
            df.loc[hourly_mask, "salary_max"] = (
                pd.to_numeric(df.loc[hourly_mask, "salary_max"], errors="coerce")
                * annual_multiplier
            )
            self._record_metric("hourly_salaries_annualised", int(n_hourly))

        return df

    def _reject_unreasonable_salary(self, df: pd.DataFrame) -> pd.DataFrame:
        """Null-out salary values that fall outside plausible annual salary bounds.

        WHY:
            '$5' or '$50,000,000' are clearly data entry errors. Including them
            would bias mean salary calculations catastrophically. Setting to NaN
            is safer than dropping the row (the job posting itself is still useful).
        """
        for col in ["salary_min", "salary_max"]:
            if col not in df.columns:
                continue
            bad_mask = df[col].notna() & (
                (df[col] < _MIN_REASONABLE_SALARY) | (df[col] > _MAX_REASONABLE_SALARY)
            )
            n_bad = bad_mask.sum()
            if n_bad:
                self._warn(
                    f"Nulling {n_bad} unreasonable {col} value(s) "
                    f"(outside [{_MIN_REASONABLE_SALARY:,.0f}, {_MAX_REASONABLE_SALARY:,.0f}])."
                )
                df.loc[bad_mask, col] = None

        return df

    @staticmethod
    def _normalise_salary_period(raw: str | None) -> str:
        """Map raw pay period strings to the controlled vocabulary."""
        if not raw:
            return "ANNUAL"
        raw_lower = str(raw).strip().lower()
        _PERIOD_MAP = {
            "annual": "ANNUAL",
            "yearly": "ANNUAL",
            "year": "ANNUAL",
            "yr": "ANNUAL",
            "monthly": "MONTHLY",
            "month": "MONTHLY",
            "mo": "MONTHLY",
            "hourly": "HOURLY",
            "hour": "HOURLY",
            "hr": "HOURLY",
            "weekly": "WEEKLY",
            "week": "WEEKLY",
            "wk": "WEEKLY",
            "daily": "DAILY",
            "day": "DAILY",
        }
        for key, val in _PERIOD_MAP.items():
            if key in raw_lower:
                return val
        return "ANNUAL"

    # =========================================================================
    # Step 9 — Validate salary bounds
    # =========================================================================

    def _validate_salary_bounds(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ensure salary_min ≤ salary_max; null-out both if the invariant is broken.

        WHY:
            The salary_ranges table has a CHECK constraint: salary_min <= salary_max.
            If we try to insert a row where min > max, the database will reject it.
            Better to detect and null these out here with a warning than to fail at
            load time and lose the entire batch.

        WHY null both (not just swap):
            Swapping min/max silently 'corrects' data that may have a different
            error (e.g., the columns were transposed in the source). Nulling both
            is the conservative, auditable choice — we record the count in metrics.
        """
        self._logger.info("Step 9: Validating salary bounds (min <= max)")

        if "salary_min" not in df.columns or "salary_max" not in df.columns:
            return df

        both_present = df["salary_min"].notna() & df["salary_max"].notna()
        inverted = both_present & (df["salary_min"] > df["salary_max"])
        n_inverted = inverted.sum()

        if n_inverted:
            self._warn(
                f"Nulling {n_inverted} salary row(s) where salary_min > salary_max "
                "(constraint violation — set both to None)."
            )
            df.loc[inverted, "salary_min"] = None
            df.loc[inverted, "salary_max"] = None

        self._record_metric("inverted_salary_bounds_nulled", int(n_inverted))
        return df

    # =========================================================================
    # Step 10 — Normalise employment type
    # =========================================================================

    def _normalise_employment_type(self, df: pd.DataFrame) -> pd.DataFrame:
        """Map raw employment type strings to the controlled vocabulary type_code.

        WHY:
            The employment_types table uses a controlled vocabulary (FULL_TIME,
            PART_TIME, CONTRACT, etc.). Without normalisation, 'Full-time', 'FT',
            'Full Time', and 'fulltime' would all fail the FK lookup or produce
            four separate rows in the dimension table.

        Strategy:
            Lowercase the raw value and look it up in _EMPLOYMENT_TYPE_MAP.
            Unrecognised values become None (NULL in the database), which means
            the jobs.employment_type_id FK will be NULL — acceptable.
        """
        self._logger.info("Step 10: Normalising employment type")

        if "employment_type_raw" not in df.columns:
            df["employment_type_code"] = None
            return df

        def _map_type(raw: str | None) -> str | None:
            if not raw:
                return None
            return _EMPLOYMENT_TYPE_MAP.get(str(raw).strip().lower())

        df["employment_type_code"] = df["employment_type_raw"].apply(_map_type)

        unrecognised = (
            df["employment_type_raw"].notna() & df["employment_type_code"].isna()
        )
        n_unrecognised = unrecognised.sum()
        if n_unrecognised:
            sample = (
                df.loc[unrecognised, "employment_type_raw"]
                .value_counts()
                .head(5)
                .to_dict()
            )
            self._warn(
                f"{n_unrecognised} employment_type value(s) not in controlled vocabulary. "
                f"Sample: {sample}. Consider adding to _EMPLOYMENT_TYPE_MAP."
            )

        dist = df["employment_type_code"].value_counts(dropna=False).to_dict()
        self._record_metric("employment_type_distribution", dist)
        return df

    # =========================================================================
    # Step 11 — Normalise experience level
    # =========================================================================

    def _normalise_experience_level(self, df: pd.DataFrame) -> pd.DataFrame:
        """Map raw experience level strings and extract min/max years."""
        self._logger.info("Step 11: Normalising and extracting experience level")

        df["experience_level_code"] = None
        df["experience_min"] = None
        df["experience_max"] = None

        def _get_exp_text(row: pd.Series) -> str:
            parts = [
                str(row.get("experience_level_raw") or ""),
                str(row.get("job_title") or ""),
                str(row.get("description") or "")[:500],
            ]
            return " ".join(parts).lower()

        exp_texts = df.apply(_get_exp_text, axis=1)

        # 1. Normalise level from level_raw
        if "experience_level_raw" in df.columns:

            def _map_level(raw: str | None) -> str | None:
                if not raw:
                    return None
                lowered = str(raw).strip().lower()
                for pattern, code in _EXPERIENCE_LEVEL_MAP.items():
                    if pattern in lowered:
                        return code
                return None

            df["experience_level_code"] = df["experience_level_raw"].apply(_map_level)

        # 2. Extract numeric years
        def _extract_years(text: str) -> tuple[float | None, float | None]:
            pattern = r"(\d+)\s*(?:-|to)\s*(\d+)\s*years?|(\d+)\s*\+?\s*years?"
            matches = re.finditer(pattern, text)
            for match in matches:
                if match.group(1) and match.group(2):
                    return float(match.group(1)), float(match.group(2))
                elif match.group(3):
                    return float(match.group(3)), None
            return None, None

        years = exp_texts.apply(_extract_years)
        df["experience_min"] = years.apply(lambda x: x[0])
        df["experience_max"] = years.apply(lambda x: x[1])

        # 3. Infer missing level from years
        mask_entry = df["experience_level_code"].isna() & (df["experience_min"] <= 2)
        mask_mid = (
            df["experience_level_code"].isna()
            & (df["experience_min"] > 2)
            & (df["experience_min"] <= 5)
        )
        mask_senior = df["experience_level_code"].isna() & (df["experience_min"] > 5)

        df.loc[mask_entry, "experience_level_code"] = "ENTRY"
        df.loc[mask_mid, "experience_level_code"] = "MID"
        df.loc[mask_senior, "experience_level_code"] = "SENIOR"

        # Try to infer from text if still missing
        missing_level = df["experience_level_code"].isna()

        def _infer_level(text: str) -> str | None:
            for pattern, code in _EXPERIENCE_LEVEL_MAP.items():
                if pattern in text:
                    return code
            return None

        if missing_level.any():
            df.loc[missing_level, "experience_level_code"] = exp_texts[
                missing_level
            ].apply(_infer_level)

        dist = df["experience_level_code"].value_counts(dropna=False).to_dict()
        self._record_metric("experience_level_distribution", dist)
        return df

    # =========================================================================
    # Step 12 — Extract skills
    # =========================================================================

    def _extract_skills(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract skill keywords from the job description and skills_raw columns.

        WHY:
            'Most In-Demand Skills' is one of the primary analytics requirements.
            Skills are rarely in a structured column — they are embedded in the
            description text as natural language: 'Experience with Python, Spark,
            and Kafka required'. Regex pattern matching extracts them into a
            pipe-separated list that the loading layer can convert to job_skills rows.

        Output column: 'extracted_skills'
            A pipe-separated string of canonical skill names found in the row.
            Example: 'Python|Apache Spark|Apache Kafka|SQL'

        WHY pipe-separated (not a list):
            Pandas stores lists in object columns, which complicates CSV
            serialisation and staging. A delimited string is safe for all
            downstream IO. The loading layer splits on '|' when building
            job_skills records.
        """
        self._logger.info("Step 12: Extracting skills from description")

        # Combine description and skills_raw into one search target
        def _get_search_text(row: pd.Series) -> str:
            parts = [
                str(row.get("description") or ""),
                str(row.get("skills_raw") or ""),
                str(row.get("job_title") or ""),
            ]
            return " ".join(parts).lower()

        def _extract_skills_from_text(text: str) -> str:
            found: list[str] = []
            for skill_name, patterns in _SKILL_PATTERNS.items():
                if any(re.search(pat, text, re.IGNORECASE) for pat in patterns):
                    found.append(skill_name)
            return "|".join(found)

        df["extracted_skills"] = df.apply(
            lambda row: _extract_skills_from_text(_get_search_text(row)), axis=1
        )

        # Replace empty string with None
        df["extracted_skills"] = df["extracted_skills"].replace("", None)

        has_skills = df["extracted_skills"].notna().sum()
        total_skills = df["extracted_skills"].dropna().str.split("|").apply(len).sum()
        self._record_metric("rows_with_extracted_skills", int(has_skills))
        self._record_metric("total_skill_mentions", int(total_skills))
        self._logger.debug(
            "  Skills extracted: %d row(s) with skills, %d total skill mentions.",
            has_skills,
            total_skills,
        )
        return df

    # =========================================================================
    # Step 13 — Parse dates
    # =========================================================================

    def _parse_dates(self, df: pd.DataFrame) -> pd.DataFrame:
        """Parse raw date strings into Python date objects.

        WHY:
            'Hiring Trends Over Time' requires date-based aggregation (GROUP BY
            month, quarter, year). String dates cannot be aggregated — they must
            be native date/datetime types. Without parsing, every date-based
            query requires an expensive CAST in SQL.

        WHY date (not datetime):
            The posted_date column in the jobs table is DATE (not TIMESTAMPTZ).
            The exact time of posting is irrelevant for trend analytics. Using
            DATE also makes the data source-agnostic (some sources give full
            timestamps, others give only dates).

        Strategy:
            parse_date_string() tries 8 common formats. Unparseable values
            become None (not an error — some sources omit the posted date).
        """
        self._logger.info("Step 13: Parsing dates")

        date_columns = {
            "posted_date_raw": "posted_date",
        }

        for raw_col, out_col in date_columns.items():
            if raw_col not in df.columns:
                df[out_col] = None
                continue

            def _to_date(raw: str | None) -> date | None:
                if not raw or not str(raw).strip():
                    return None
                dt = parse_date_string(str(raw).strip())
                return dt.date() if dt else None

            before_nulls = df[raw_col].isna().sum()
            df[out_col] = df[raw_col].apply(_to_date)
            after_nulls = df[out_col].isna().sum()

            n_unparsed = after_nulls - before_nulls
            if n_unparsed:
                self._warn(
                    f"{n_unparsed} value(s) in '{raw_col}' could not be parsed "
                    "as a date (set to None)."
                )

            self._record_metric(f"{out_col}_parsed", int(df[out_col].notna().sum()))
            self._record_metric(f"{out_col}_failed", int(n_unparsed))

        return df

    # =========================================================================
    # Step 14 — Convert data types
    # =========================================================================

    def _convert_types(self, df: pd.DataFrame) -> pd.DataFrame:
        """Cast all output columns to their correct Python/Pandas dtypes.

        WHY:
            The extraction layer reads everything as str (object dtype) for
            safety. Before loading into PostgreSQL (which is strongly typed),
            each column must be in the correct Python type:
              - salary_min/max → float (maps to PostgreSQL NUMERIC)
              - is_remote → bool (maps to BOOLEAN)
              - posted_date → date (maps to DATE)
              - string columns → str or None (maps to VARCHAR/TEXT)

        WHY not cast earlier:
            Casting after all cleaning steps ensures we only cast values that
            have already been validated. Casting raw data directly would cause
            pd.to_numeric(errors='coerce') to silently swallow useful debug info.
        """
        self._logger.info("Step 14: Converting data types")

        # Float columns
        for col in ["salary_min", "salary_max", "experience_min", "experience_max"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Boolean: is_active
        df["is_active"] = True

        # Boolean: is_remote
        if "is_remote" in df.columns:
            df["is_remote"] = df["is_remote"].where(df["is_remote"].notna(), other=None)

        # Boolean quality flags
        for col in ["is_valid", "salary_parse_success", "location_parse_success"]:
            if col in df.columns:
                df[col] = df[col].astype(bool)

        # String columns
        str_columns = [
            "job_title",
            "canonical_title",
            "company_name",
            "location_raw",
            "city",
            "state_code",
            "country_code",
            "work_arrangement",
            "employment_type_code",
            "experience_level_code",
            "source_job_id",
            "posting_url",
            "currency_code",
            "salary_period",
            "extracted_skills",
            "validation_errors",
            "source_file",
            "source_system",
        ]

        # Add lineage data before casting
        df["source_file"] = df.get("_source_file", "unknown")
        df["source_system"] = self.source_name

        for col in str_columns:
            if col in df.columns:
                df[col] = df[col].where(df[col].notna() & (df[col] != ""), other=None)

        # datetime columns
        now_utc = pd.Timestamp.now(tz="UTC")
        if "extraction_timestamp" not in df.columns:
            df["extraction_timestamp"] = now_utc
        else:
            df["extraction_timestamp"] = pd.to_datetime(
                df["extraction_timestamp"], errors="coerce"
            ).fillna(now_utc)

        df["transformation_timestamp"] = now_utc

        if "posted_date" in df.columns:
            df["posted_date"] = pd.to_datetime(
                df["posted_date"], errors="coerce"
            ).dt.date

        self._logger.debug("  Type conversion and lineage stamping complete.")
        return df

    # =========================================================================
    # Step 15 — Validate output schema
    # =========================================================================

    def _validate_output_schema(self, df: pd.DataFrame) -> None:
        """Final guard: ensure all required output columns are present.

        WHY:
            The loading layer assumes certain column names exist. If a bug in
            any earlier step accidentally dropped or renamed a required column,
            this check catches it here — not during the database INSERT when
            the error message would be much harder to interpret.

        Raises:
            DataTransformationError: If any required output column is missing.
        """
        self._logger.info("Step 15: Validating output schema")

        missing = _REQUIRED_OUTPUT_COLUMNS - set(df.columns)
        if missing:
            raise DataTransformationError(
                message=(
                    f"Transformed DataFrame is missing required output columns: {missing}. "
                    "This is likely a bug in one of the transformation steps."
                ),
                step_name="_validate_output_schema",
            )

        # Warn if the DataFrame is suspiciously small compared to input
        if len(df) == 0:
            raise DataTransformationError(
                message=(
                    "All rows were dropped during transformation. "
                    "Check step metrics in the TransformationReport for the cause."
                ),
                step_name="_validate_output_schema",
            )

        self._logger.debug(
            "  Output schema validation PASSED: %d rows × %d columns.",
            len(df),
            len(df.columns),
        )

    # =========================================================================
    # Public utility
    # =========================================================================

    def get_output_columns(self) -> list[str]:
        """Return the list of standard output column names produced by this transformer.

        Useful for documentation and test assertions.

        Returns:
            list[str]: Sorted list of expected output column names.
        """
        return sorted(
            [
                # Job identity
                "job_title",
                "canonical_title",
                "source_job_id",
                # Company
                "company_name",
                # Location
                "location_raw",
                "city",
                "state_code",
                "country_code",
                # Work arrangement
                "work_arrangement",
                "is_remote",
                "is_active",
                # Employment classification
                "employment_type_code",
                "experience_level_code",
                # Salary
                "salary_min",
                "salary_max",
                "currency_code",
                "salary_period",
                # Skills
                "extracted_skills",
                # Dates
                "posted_date",
                # Content
                "description",
                "posting_url",
            ]
        )
