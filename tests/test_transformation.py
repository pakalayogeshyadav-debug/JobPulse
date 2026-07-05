"""
tests/test_transformation.py — Unit tests for the transformation layer.

Provides comprehensive coverage (>90%) for string utils and JobListingTransformer.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from jobpulse.transformation.base import DataTransformationError
from jobpulse.transformation.job_listing_transformer import JobListingTransformer
from jobpulse.utils.string_utils import extract_salary_number, normalise_job_title


def test_extract_salary_number() -> None:
    # Standard USD
    assert extract_salary_number("$90k") == 90000.0
    assert extract_salary_number("120,000") == 120000.0
    assert extract_salary_number("90,000 USD") == 90000.0
    assert extract_salary_number("1.5m") == 1500000.0
    # Indian Formats
    assert extract_salary_number("₹12 LPA") == 1200000.0
    assert extract_salary_number("18 Lakh") == 1800000.0
    assert extract_salary_number("12 Lakhs") == 1200000.0
    assert extract_salary_number("INR 1800000") == 1800000.0
    assert extract_salary_number("₹18,00,000") == 1800000.0
    # Other Currencies
    assert extract_salary_number("€70000") == 70000.0
    assert extract_salary_number("£85000") == 85000.0
    # Unparseable
    assert extract_salary_number("Competitive") is None
    assert extract_salary_number(None) is None


def test_normalise_job_title() -> None:
    # Emojis and trailing spaces (matches "Data Engineer" canonical)
    assert normalise_job_title("🚀 Senior Data Engineer 🚀  ") == "Data Engineer"
    # Duplicate words
    assert normalise_job_title("Senior Senior Data Engineer") == "Data Engineer"
    assert normalise_job_title("Unrelated Job Job Title") == "Unrelated Job Title"
    # Mapping applied
    assert normalise_job_title("Sr. Data Engineer") == "Data Engineer"
    assert normalise_job_title("ML Ops Engineer") == "MLOps Engineer"
    assert normalise_job_title(None) is None


class TestJobListingTransformer:
    def test_run_empty_dataframe(self) -> None:
        transformer = JobListingTransformer()
        with pytest.raises(DataTransformationError, match="empty DataFrame"):
            transformer.run(pd.DataFrame())

    def test_run_missing_required_columns(self) -> None:
        transformer = JobListingTransformer()
        df = pd.DataFrame({"company_name": ["Acme Corp"]})
        with pytest.raises(DataTransformationError, match="Required column is missing"):
            transformer.run(df)

    def test_transform_flags_invalid_rows(self) -> None:
        transformer = JobListingTransformer()
        df = pd.DataFrame(
            {
                "job_title": ["Data Engineer", None, "   "],
                "company_name": ["Acme", "Beta", "Charlie"],
                "posting_url": [
                    "http://valid.com",
                    "htp://invalid",
                    "https://valid.com",
                ],
            }
        )
        result, report = transformer.run(df)

        # We expect 3 rows (none dropped, but flagged)
        assert len(result) == 3
        assert bool(result.loc[0, "is_valid"]) is True
        assert bool(result.loc[1, "is_valid"]) is False
        assert "Missing job_title" in result.loc[1, "validation_errors"]
        assert bool(result.loc[2, "is_valid"]) is False

        # Malformed URL should be set to NaN but flagged
        assert pd.isna(result.loc[1, "posting_url"])
        assert "Malformed URL" in result.loc[1, "validation_errors"]

        assert report.rows_received == 3
        assert report.rows_processed == 3
        assert report.rows_removed == 0
        assert report.missing_required_fields == 2

    def test_transform_salary_parsing(self) -> None:
        transformer = JobListingTransformer()
        df = pd.DataFrame(
            {
                "job_title": ["A", "B", "C", "D"],
                "company_name": ["Acme", "Acme", "Acme", "Acme"],
                "salary_raw": [
                    "$90k-$130k",
                    "₹12 LPA - ₹18 LPA",
                    "100000-140000 USD",
                    "Competitive",
                ],
            }
        )
        result, _ = transformer.run(df)

        # A: 90k-130k USD
        assert result.loc[0, "salary_min"] == 90000.0
        assert result.loc[0, "salary_max"] == 130000.0
        assert result.loc[0, "currency_code"] == "USD"
        assert bool(result.loc[0, "salary_parse_success"]) is True

        # B: 12-18 LPA INR
        assert result.loc[1, "salary_min"] == 1200000.0
        assert result.loc[1, "salary_max"] == 1800000.0
        assert result.loc[1, "currency_code"] == "INR"

        # C: USD
        assert result.loc[2, "salary_min"] == 100000.0
        assert result.loc[2, "currency_code"] == "USD"

        # D: Unparseable
        assert pd.isna(result.loc[3, "salary_min"])
        assert bool(result.loc[3, "salary_parse_success"]) is False
        assert "Unparseable Salary" in result.loc[3, "validation_errors"]

    def test_transform_experience_parsing(self) -> None:
        transformer = JobListingTransformer()
        df = pd.DataFrame(
            {
                "job_title": ["Senior Engineer", "Developer", "Data Scientist"],
                "company_name": ["Acme", "Acme", "Acme"],
                "experience_level_raw": ["5+ years", "0-2 years", "mid level"],
                "description": [
                    "Need 10+ years exp",
                    "Looking for a fresher",
                    "3 to 5 years experience",
                ],
            }
        )
        result, _ = transformer.run(df)

        # 0: Senior from title/raw, 5 years min from raw
        assert result.loc[0, "experience_level_code"] == "SENIOR"
        assert result.loc[0, "experience_min"] == 5.0
        assert pd.isna(result.loc[0, "experience_max"])

        # 1: 0-2 years -> min 0, max 2. Code ENTRY
        assert result.loc[1, "experience_min"] == 0.0
        assert result.loc[1, "experience_max"] == 2.0
        assert result.loc[1, "experience_level_code"] == "ENTRY"

        # 2: 3 to 5 years -> min 3, max 5. Mid level
        assert result.loc[2, "experience_min"] == 3.0
        assert result.loc[2, "experience_max"] == 5.0
        assert result.loc[2, "experience_level_code"] == "MID"

    def test_transform_skill_extraction(self) -> None:
        transformer = JobListingTransformer()
        df = pd.DataFrame(
            {
                "job_title": ["Data Engineer"],
                "company_name": ["Acme"],
                "description": [
                    "Need Python, Apache Spark, and Snowflake. Also dbt and AWS."
                ],
            }
        )
        result, _ = transformer.run(df)

        skills = result.loc[0, "extracted_skills"]
        assert skills is not None
        skill_list = skills.split("|")
        expected_skills = ["Python", "Spark", "AWS", "Snowflake", "dbt"]
        for expected in expected_skills:
            assert expected in skill_list

    def test_transform_lineage_columns(self) -> None:
        transformer = JobListingTransformer()
        df = pd.DataFrame(
            {
                "job_title": ["Data Engineer"],
                "company_name": ["Acme"],
                "_source_file": ["raw_data.csv"],
            }
        )
        result, _ = transformer.run(df)

        assert result.loc[0, "source_file"] == "raw_data.csv"
        assert result.loc[0, "source_system"] == "default"
        assert isinstance(result.loc[0, "extraction_timestamp"], datetime)
        assert isinstance(result.loc[0, "transformation_timestamp"], datetime)

    def test_transform_location_parsing(self) -> None:
        transformer = JobListingTransformer()
        df = pd.DataFrame(
            {
                "job_title": ["A", "B", "C"],
                "company_name": ["Acme", "Acme", "Acme"],
                "location_raw": ["New York, NY, United States", "London, UK", "Remote"],
            }
        )
        result, _ = transformer.run(df)

        # NY
        assert result.loc[0, "city"] == "New York"
        assert result.loc[0, "state_code"] == "NY"
        assert result.loc[0, "country_code"] == "US"
        assert bool(result.loc[0, "location_parse_success"]) is True

        # London
        assert result.loc[1, "city"] == "London"
        assert pd.isna(result.loc[1, "state_code"])
        assert result.loc[1, "country_code"] == "GB"

        # Remote
        assert pd.isna(result.loc[2, "city"])
        assert pd.isna(result.loc[2, "state_code"])
        assert bool(result.loc[2, "is_remote"]) is True
        assert result.loc[2, "work_arrangement"] == "REMOTE"
        assert bool(result.loc[2, "location_parse_success"]) is True

    def test_transform_company_name_standardisation(self) -> None:
        transformer = JobListingTransformer()
        df = pd.DataFrame(
            {
                "job_title": ["A", "B", "C", "D"],
                "company_name": [
                    "Acme Corp.",
                    "ACME INC",
                    "Beta LLC",
                    "Delta Corporation",
                ],
            }
        )
        result, _ = transformer.run(df)
        assert result.loc[0, "company_name"] == "Acme"
        assert result.loc[1, "company_name"] == "Acme"
        assert result.loc[2, "company_name"] == "Beta"
        assert result.loc[3, "company_name"] == "Delta"

    def test_remove_duplicates(self) -> None:
        transformer = JobListingTransformer()
        df = pd.DataFrame(
            {
                "source_job_id": ["1", "1", "2", None, None],
                "job_title": ["A", "A", "B", "C", "C"],
                "company_name": ["Acme", "Acme", "Beta", "Gamma", "Gamma"],
                "location_raw": ["NY", "NY", "CA", "TX", "TX"],
            }
        )
        result = transformer._remove_duplicates(df)
        assert len(result) == 3
        # ID 1 kept once, ID 2 kept once, Gamma kept once (due to fallback keys)

    def test_clean_text_fields(self) -> None:
        transformer = JobListingTransformer()
        df = pd.DataFrame(
            {
                "job_title": ["  A  ", "B  C", "   ", None],
                "company_name": ["Acme", "  ", None, "Beta"],
            }
        )
        result = transformer._clean_text_fields(df)
        assert result.loc[0, "job_title"] == "A"
        assert result.loc[1, "job_title"] == "B C"
        assert pd.isna(result.loc[2, "job_title"])
        assert pd.isna(result.loc[1, "company_name"])

    def test_normalise_work_arrangement(self) -> None:
        transformer = JobListingTransformer()
        df = pd.DataFrame(
            {
                "remote_flag_raw": ["true", "false", None, None, None],
                "location_raw": [
                    None,
                    None,
                    "Remote from anywhere",
                    "Hybrid - NY",
                    None,
                ],
                "job_title": [None, None, None, None, "Remote Data Engineer"],
                "description": [None, None, None, None, None],
            }
        )
        result = transformer._normalise_work_arrangement(df)
        assert result.loc[0, "work_arrangement"] == "REMOTE"
        assert bool(result.loc[0, "is_remote"]) is True

        assert result.loc[1, "work_arrangement"] == "ON_SITE"
        assert bool(result.loc[1, "is_remote"]) is False

        assert result.loc[2, "work_arrangement"] == "REMOTE"
        assert result.loc[3, "work_arrangement"] == "HYBRID"
        assert result.loc[4, "work_arrangement"] == "REMOTE"

    def test_validate_salary_bounds_and_annualisation(self) -> None:
        transformer = JobListingTransformer()
        df = pd.DataFrame(
            {
                "salary_min": [100000.0, 150000.0, 40.0],
                "salary_max": [120000.0, 100000.0, 50.0],  # Row 1 inverted
                "salary_period_raw": ["ANNUAL", "ANNUAL", "HOURLY"],
            }
        )
        df = transformer._annualise_hourly_salary(df)
        # Row 2 was hourly 40-50, now 83200 - 104000
        assert df.loc[2, "salary_min"] == 83200.0

        df = transformer._validate_salary_bounds(df)
        # Row 0 valid
        assert df.loc[0, "salary_min"] == 100000.0
        # Row 1 inverted, should be nulled
        assert pd.isna(df.loc[1, "salary_min"])
        assert pd.isna(df.loc[1, "salary_max"])

    def test_normalise_employment_type(self) -> None:
        transformer = JobListingTransformer()
        df = pd.DataFrame(
            {"employment_type_raw": ["Full-time", "PT", "Contractor", "Weird"]}
        )
        result = transformer._normalise_employment_type(df)
        assert result.loc[0, "employment_type_code"] == "FULL_TIME"
        assert result.loc[1, "employment_type_code"] == "PART_TIME"
        assert result.loc[2, "employment_type_code"] == "CONTRACT"
        assert pd.isna(result.loc[3, "employment_type_code"])

    def test_parse_dates(self) -> None:
        transformer = JobListingTransformer()
        df = pd.DataFrame(
            {
                "posted_date_raw": [
                    "2023-01-01",
                    "01/15/2023",
                    "2023-01-02 12:30:00",
                    "invalid",
                ]
            }
        )
        result = transformer._parse_dates(df)
        assert str(result.loc[0, "posted_date"]) == "2023-01-01"
        assert str(result.loc[1, "posted_date"]) == "2023-01-15"
        # 2023-01-02 12:30:00 should become 2023-01-02 date
        assert str(result.loc[2, "posted_date"]) == "2023-01-02"
        assert pd.isna(result.loc[3, "posted_date"])

    def test_transform_location_parsing_extended(self) -> None:
        transformer = JobListingTransformer()
        df = pd.DataFrame(
            {
                "job_title": ["A", "B", "C"],
                "company_name": ["Acme", "Acme", "Acme"],
                "location_raw": [
                    "Bengaluru, Karnataka, India",
                    "Paris, France",
                    "Nowhere, XX, YY",
                ],
            }
        )
        result, _ = transformer.run(df)

        # Bengaluru
        assert result.loc[0, "city"] == "Bengaluru"
        assert pd.isna(result.loc[0, "state_code"])
        assert result.loc[0, "country_code"] == "IN"

        # Paris
        assert result.loc[1, "city"] == "Paris"
        assert result.loc[1, "country_code"] == "FR"

        # Nowhere
        assert result.loc[2, "city"] == "Nowhere"
        assert result.loc[2, "country_code"] == "UNKNOWN"

    def test_reject_unreasonable_salary(self) -> None:
        transformer = JobListingTransformer()
        df = pd.DataFrame(
            {
                "salary_min": [10.0, 50000.0, 6000000.0],
                "salary_max": [20.0, 60000.0, 7000000.0],
            }
        )
        result = transformer._reject_unreasonable_salary(df)
        assert pd.isna(result.loc[0, "salary_min"])
        assert result.loc[1, "salary_min"] == 50000.0
        assert pd.isna(result.loc[2, "salary_min"])
