from unittest.mock import patch

import pandas as pd
import pytest
from frontend.services.analytics_service import (
    get_company_hiring,
    get_home_kpis,
    get_live_jobs,
    get_pipeline_health,
    get_salary_by_role,
    get_top_skills,
)
from frontend.services.log_service import (
    get_available_log_files,
    parse_log_file,
)
from frontend.services.validation_service import (
    get_data_quality_stats,
    get_validation_history,
    get_validation_summary,
)
from frontend.services.warehouse_service import (
    get_columns_metadata,
    get_foreign_keys,
    get_indexes_metadata,
    get_tables_metadata,
)


@pytest.fixture(autouse=True)
def mock_streamlit_cache():
    """Mock Streamlit's cache decorators so tests can run without Streamlit context."""
    with (
        patch("streamlit.cache_data", lambda *args, **kwargs: lambda f: f),
        patch("streamlit.cache_resource", lambda *args, **kwargs: lambda f: f),
    ):
        yield


def test_get_home_kpis():
    kpis = get_home_kpis()
    assert isinstance(kpis, dict)


def test_get_live_jobs():
    df = get_live_jobs(limit=5)
    assert isinstance(df, pd.DataFrame)


def test_get_top_skills():
    df = get_top_skills()
    assert isinstance(df, pd.DataFrame)


def test_get_company_hiring():
    df = get_company_hiring()
    assert isinstance(df, pd.DataFrame)


def test_get_salary_by_role():
    df = get_salary_by_role()
    assert isinstance(df, pd.DataFrame)


def test_get_pipeline_health():
    df = get_pipeline_health()
    assert isinstance(df, pd.DataFrame)


# --- NEW TESTS FOR REMAINING SERVICES ---


def test_get_validation_summary():
    res = get_validation_summary()
    assert isinstance(res, dict)
    assert "total_validated" in res


def test_get_data_quality_stats():
    df = get_data_quality_stats()
    assert isinstance(df, pd.DataFrame)


def test_get_validation_history():
    df = get_validation_history()
    assert isinstance(df, pd.DataFrame)


def test_get_tables_metadata():
    df = get_tables_metadata()
    assert isinstance(df, pd.DataFrame)


def test_get_columns_metadata():
    df = get_columns_metadata("jobs")
    assert isinstance(df, pd.DataFrame)


def test_get_indexes_metadata():
    df = get_indexes_metadata("jobs")
    assert isinstance(df, pd.DataFrame)


def test_get_foreign_keys():
    df = get_foreign_keys("jobs")
    assert isinstance(df, pd.DataFrame)


def test_log_service():
    files = get_available_log_files()
    assert isinstance(files, list)
    if files:
        df = parse_log_file(files[0])
        assert isinstance(df, pd.DataFrame)
