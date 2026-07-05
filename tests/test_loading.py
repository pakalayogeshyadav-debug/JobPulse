"""
tests/test_loading.py — Integration and Unit tests for PostgresLoader.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from jobpulse.loading.postgres_loader import PostgresLoader
from jobpulse.models.data_source import DataSource
from jobpulse.models.pipeline_run import PipelineRun


@pytest.fixture
def sample_load_df() -> pd.DataFrame:
    """Sample dataframe output from the transformation layer."""
    return pd.DataFrame(
        {
            "source_system": ["adzuna", "adzuna"],
            "source_job_id": ["adz-101", "adz-102"],
            "job_title": ["Data Engineer", "Data Analyst"],
            "company_name": ["Corp A", "Corp B"],
            "location_raw": ["Remote", "NY"],
            "salary_min": [100000, 80000],
            "salary_max": [150000, 100000],
            "currency_code": ["USD", "USD"],
            "is_remote": [True, False],
            "work_arrangement": ["FULL_TIME", "PART_TIME"],
            "description": ["Great job", "Nice job"],
            "posting_url": ["http://a.com", "http://b.com"],
            "posted_date": [datetime.now(UTC).date(), datetime.now(UTC).date()],
            "is_active": [True, True],
        }
    )


@pytest.fixture
def mock_session_factory():
    """Returns a factory that creates a mock SQLAlchemy session."""
    factory = MagicMock()
    session = MagicMock()

    # Setup context manager for session
    session.__enter__.return_value = session
    session.__exit__.return_value = False

    # Setup context manager for session.begin()
    transaction = MagicMock()
    transaction.__enter__.return_value = transaction
    transaction.__exit__.return_value = False
    session.begin.return_value = transaction

    factory.return_value = session
    return factory


def test_postgres_loader_successful_upsert(mock_session_factory, sample_load_df):
    """Verify that a successful run correctly commits records and manages pipeline runs."""
    # Setup mock data source resolution to return an ID
    session = mock_session_factory.return_value

    # Mock pipeline run object that session.get returns
    mock_pipeline_run = MagicMock(spec=PipelineRun)
    session.get.return_value = mock_pipeline_run

    # Mock data source object
    mock_data_source = MagicMock(spec=DataSource)
    mock_data_source.data_source_id = 42
    session.scalar.return_value = mock_data_source

    loader = PostgresLoader(session_factory=mock_session_factory)

    report = loader.run(sample_load_df)

    # Verify report metrics
    assert report.rows_received == 2
    assert report.rows_updated == 2  # UPSERT approximates as all updated
    assert report.rows_failed == 0
    assert report.batches_processed == 1
    assert report.success_rate == 100.0

    # Verify pipeline run was marked SUCCESS
    assert mock_pipeline_run.status == "SUCCESS"
    assert mock_pipeline_run.completed_at is not None

    # Verify session execute was called (the actual UPSERT statement)
    assert session.execute.called


def test_postgres_loader_transient_error_retry(mock_session_factory, sample_load_df):
    """Verify that OperationalErrors trigger tenacity retry logic."""
    session = mock_session_factory.return_value

    # Make session.execute fail once with OperationalError, then succeed
    op_err = OperationalError("connection dropped", {}, None)
    session.execute.side_effect = [op_err, MagicMock()]

    mock_pipeline_run = MagicMock(spec=PipelineRun)
    session.get.return_value = mock_pipeline_run

    mock_data_source = MagicMock(spec=DataSource)
    mock_data_source.data_source_id = 42
    session.scalar.return_value = mock_data_source

    # Patch tenacity wait time to speed up the test
    with patch("jobpulse.loading.postgres_loader.wait_exponential", return_value=0):
        loader = PostgresLoader(session_factory=mock_session_factory)
        report = loader.run(sample_load_df)

    assert report.success_rate == 100.0
    assert session.execute.call_count == 2  # 1 fail, 1 success


def test_postgres_loader_retry_exhaustion_rollback(
    mock_session_factory, sample_load_df
):
    """Verify that exhausting retries fails the chunk, rolls back, and fails the pipeline run."""
    session = mock_session_factory.return_value

    # Make session.execute ALWAYS fail with OperationalError
    op_err = OperationalError("connection refused", {}, None)
    session.execute.side_effect = op_err

    mock_pipeline_run = MagicMock(spec=PipelineRun)
    session.get.return_value = mock_pipeline_run

    mock_data_source = MagicMock(spec=DataSource)
    session.scalar.return_value = mock_data_source

    loader = PostgresLoader(session_factory=mock_session_factory)

    with patch("tenacity.wait_exponential", return_value=0):
        # We expect DataLoadingError to be caught by BaseLoader, marking chunk as failed
        report = loader.run(sample_load_df)

    assert report.rows_failed == 2
    assert report.success_rate == 0.0
    assert loader.extra["retry_count"] > 0

    # Pipeline run should be marked FAILED
    assert mock_pipeline_run.status == "FAILED"


def test_postgres_loader_integrity_error(mock_session_factory, sample_load_df):
    """Verify that IntegrityError fails immediately without retrying."""
    session = mock_session_factory.return_value

    int_err = IntegrityError("constraint violation", {}, None)
    session.execute.side_effect = int_err

    mock_pipeline_run = MagicMock(spec=PipelineRun)
    session.get.return_value = mock_pipeline_run

    loader = PostgresLoader(session_factory=mock_session_factory)

    report = loader.run(sample_load_df)

    # Integrity errors shouldn't retry
    assert session.execute.call_count == 1
    assert report.rows_failed == 2

    # Pipeline run marked FAILED
    assert mock_pipeline_run.status == "FAILED"


def test_postgres_loader_empty_df(mock_session_factory):
    """Verify behavior with an empty dataframe."""
    loader = PostgresLoader(session_factory=mock_session_factory)

    # BaseLoader validates empty DataFrames and raises LoadingValidationError
    from jobpulse.loading.base import LoadingValidationError

    with pytest.raises(LoadingValidationError):
        loader.run(pd.DataFrame())


def test_data_source_creation(mock_session_factory, sample_load_df):
    """Verify that a new data source is created if it does not exist in the database."""
    session = mock_session_factory.return_value

    mock_pipeline_run = MagicMock(spec=PipelineRun)
    session.get.return_value = mock_pipeline_run

    # Scalar returns None, indicating Data Source doesn't exist
    session.scalar.return_value = None

    loader = PostgresLoader(session_factory=mock_session_factory)
    loader.run(sample_load_df)

    # Verify that session.add was called for the new DataSource and PipelineRun
    add_calls = session.add.call_args_list
    assert len(add_calls) >= 2  # One for pipeline run, one for data source

    # Check that a DataSource was passed to one of the add() calls
    ds_added = any(isinstance(call_obj[0][0], DataSource) for call_obj in add_calls)
    assert ds_added
