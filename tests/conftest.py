"""
tests/conftest.py — Shared pytest fixtures for the JobPulse test suite.

Fixtures defined here are automatically available to ALL test files
without explicit imports (pytest discovers them automatically).

Fixture Scopes:
    function  (default) → Created fresh for each test function
    module              → Created once per test module file
    session             → Created once for the entire test session

Security Note:
    Integration test fixtures use a separate TEST database (jobpulse_test).
    NEVER run integration tests against a production database.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

if TYPE_CHECKING:
    import pandas as pd

import pytest

# ---------------------------------------------------------------------------
# Sample Data Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_raw_job_df() -> pd.DataFrame:
    """
    Provide a small sample DataFrame simulating raw extraction output.

    Returns:
        pd.DataFrame: 3-row DataFrame with realistic raw job posting data.
    """
    return pd.DataFrame(
        {
            "Job Title": ["  Senior Data Engineer  ", "data analyst", "ML Engineer"],
            "Company": ["Acme Corp", "WIDGETS INC", None],
            "Location": ["New York, NY", "Austin, TX", "Remote"],
            "Salary": ["$120,000 - $160,000", "$85k", None],
            "Source": ["adzuna", "adzuna", "adzuna"],
            "Source ID": ["adzuna-001", "adzuna-002", "adzuna-003"],
            "Posted": ["2024-01-15", "2024-01-14", "invalid-date"],
        }
    )


@pytest.fixture()
def sample_clean_job_df() -> pd.DataFrame:
    """
    Provide a small sample DataFrame simulating post-transformation output.

    Returns:
        pd.DataFrame: 3-row DataFrame with standardised job posting data.
    """
    return pd.DataFrame(
        {
            "source_id": ["adzuna-001", "adzuna-002", "adzuna-003"],
            "source_name": ["adzuna", "adzuna", "adzuna"],
            "title": ["Data Engineer", "Data Analyst", "MLOps Engineer"],
            "company_name": ["Acme Corp", "Widgets Inc", None],
            "city": ["New York", "Austin", None],
            "state": ["NY", "TX", None],
            "country": ["US", "US", None],
            "salary_min": [120000.0, 85000.0, None],
            "salary_max": [160000.0, 85000.0, None],
            "is_remote": [False, False, True],
            "is_active": [True, True, True],
        }
    )


# ---------------------------------------------------------------------------
# Path Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_data_dir(tmp_path: Path) -> Path:
    """
    Provide a temporary directory structure mirroring data/.

    pytest's built-in tmp_path fixture creates a unique temp dir per test.

    Returns:
        Path: Temporary base directory with raw/, staging/, processed/ subdirs.
    """
    (tmp_path / "raw").mkdir()
    (tmp_path / "staging").mkdir()
    (tmp_path / "processed").mkdir()
    (tmp_path / "archive").mkdir()
    return tmp_path


@pytest.fixture()
def sample_csv_file(tmp_data_dir: Path, sample_raw_job_df: pd.DataFrame) -> Path:
    """
    Write sample_raw_job_df to a CSV file in the temp raw directory.

    Returns:
        Path: Path to the created sample CSV file.
    """
    csv_path = tmp_data_dir / "raw" / "sample_jobs.csv"
    sample_raw_job_df.to_csv(csv_path, index=False)
    return csv_path


# ---------------------------------------------------------------------------
# Mock Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_db_session() -> MagicMock:
    """
    Provide a mock SQLAlchemy Session for unit tests.

    Avoids the need for a real database connection in unit tests.
    Use this when testing loaders or any code that accepts a Session.

    Returns:
        MagicMock: A mock object with Session interface.
    """
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    return session
