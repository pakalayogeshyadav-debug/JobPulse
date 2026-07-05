"""
tests.test_validation — Unit tests for the validation engine.
"""

from datetime import datetime, timedelta

import pandas as pd
import pytest

from jobpulse.validation.exceptions import CriticalValidationError
from jobpulse.validation.history import save_validation_history
from jobpulse.validation.html_report import generate_html_report
from jobpulse.validation.validator import DataValidator


@pytest.fixture
def valid_df():
    return pd.DataFrame(
        {
            "job_title": ["Data Engineer", "Data Scientist"],
            "company_name": ["Netflix", "Airbnb"],
            "source_job_id": ["n123", "a456"],
            "source_name": ["builtin", "linkedin"],
            "city": ["Los Gatos", "San Francisco"],
            "state": ["CA", "CA"],
            "country": ["US", "US"],
            "salary_min": [120000, 130000],
            "salary_max": [180000, 190000],
            "experience_min": [3, 5],
            "experience_max": [6, 8],
            "posted_date": [
                datetime.now(tz=None).isoformat(),
                datetime.now(tz=None).isoformat(),
            ],
            "skills": [["python", "sql", "aws"], ["python", "pandas", "ml"]],
            "description": ["Great job", "Awesome job"],
        }
    )


def test_validator_success(valid_df):
    validator = DataValidator()
    df_clean, report = validator.validate(valid_df)

    assert len(df_clean) == 2
    assert report.rows_checked == 2
    assert report.rows_valid == 2
    assert report.rows_invalid == 0
    assert report.success_rate == 1.0


def test_missing_required_fields(valid_df):
    # Make one row invalid by dropping job_title
    valid_df.loc[0, "job_title"] = None

    validator = DataValidator()
    df_clean, report = validator.validate(valid_df)

    assert len(df_clean) == 1
    assert report.missing_required_fields == 1
    assert report.rows_valid == 1
    assert report.rows_invalid == 1


def test_salary_validation(valid_df):
    # min > max
    valid_df.loc[0, "salary_min"] = 200000
    valid_df.loc[0, "salary_max"] = 100000
    # negative
    valid_df.loc[1, "salary_min"] = -100

    validator = DataValidator()
    df_clean, report = validator.validate(valid_df)

    # Salary is configured as WARNING in config by default, so it doesn't fail the row
    # Wait, in the config I set salary to WARNING? Let me check config.py
    # If it is WARNING, it will flag it but not drop it. Let's see if df_clean has 2 rows.
    # Actually, the user says "Validation failures must NEVER crash... Non-critical flag rows while allowing them to continue."
    assert len(df_clean) == 2
    assert report.salary_errors == 2
    assert report.rows_warning == 2


def test_schema_validation_critical(valid_df):
    # Drop source_name completely to trigger a critical schema error
    df_broken = valid_df.drop(columns=["source_name"])

    validator = DataValidator()
    with pytest.raises(CriticalValidationError):
        validator.validate(df_broken)


def test_duplicate_detection(valid_df):
    # Add a duplicate row
    df_dupe = pd.concat([valid_df, valid_df.iloc[[0]]], ignore_index=True)

    validator = DataValidator()
    df_clean, report = validator.validate(df_dupe)

    # Duplicate is an ERROR severity by default
    assert len(df_clean) == 2
    assert report.duplicate_rows >= 1
    assert report.rows_invalid == 1


def test_future_dates(valid_df):
    # Set future date
    future = datetime.now() + timedelta(days=5)
    valid_df.loc[0, "posted_date"] = future.isoformat()

    validator = DataValidator()
    with pytest.raises(CriticalValidationError):
        validator.validate(valid_df)


def test_skill_validation_unknowns(valid_df):
    valid_df.at[0, "skills"] = ["python", "magic_skill"]

    validator = DataValidator()
    df_clean, report = validator.validate(valid_df)

    assert len(df_clean) == 2
    assert "magic_skill" in report.unknown_skills


def test_empty_dataframe():
    validator = DataValidator()
    df_clean, report = validator.validate(pd.DataFrame())
    assert len(df_clean) == 0
    assert report.rows_checked == 0
    assert report.success_rate == 0.0


def test_html_and_history_generation(valid_df, tmp_path):
    validator = DataValidator()
    _, report = validator.validate(valid_df)

    html_path = generate_html_report(report, output_dir=str(tmp_path))
    assert html_path.endswith("validation_report.html")
    with open(html_path, encoding="utf-8") as f:
        assert "Validation Report" in f.read()

    save_validation_history(report, run_id="test-run", output_dir=str(tmp_path))
    history_file = tmp_path / "validation_history.csv"
    assert history_file.exists()

    # Test append
    save_validation_history(report, run_id="test-run-2", output_dir=str(tmp_path))
    with open(history_file) as f:
        lines = f.readlines()
        assert len(lines) == 3  # Header + 2 rows
