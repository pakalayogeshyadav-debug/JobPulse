"""
tests/test_pipeline.py — Integration tests for PipelineOrchestrator.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from jobpulse.config.settings import Settings
from jobpulse.loading.base import DataLoadingError
from jobpulse.pipeline.orchestrator import PipelineOrchestrator


@pytest.fixture
def mock_settings():
    """Provides a dummy configuration."""
    return Settings(
        environment="development",
        log_level="DEBUG",
        db_host="localhost",
        db_port=5432,
        db_name="test_db",
        db_user="test",
        db_password="password",
        batch_size=10,
    )


@pytest.fixture
def mock_session_factory():
    """Provides a MagicMock for the session_factory."""
    return MagicMock()


@pytest.fixture
def temp_raw_dir(tmp_path: Path):
    """Creates a temporary raw data directory with a sample CSV."""
    raw_dir = tmp_path / "data" / "raw"
    raw_dir.mkdir(parents=True)

    sample_csv = raw_dir / "sample.csv"

    # Create a small valid CSV
    df = pd.DataFrame(
        {
            "job_title": ["Senior Data Engineer", "Data Analyst"],
            "company_name": ["Tech Corp", "Finance Inc"],
            "location": ["New York", "Remote"],
            "salary": ["$150k", "$80,000"],
            "description": ["Must know Python", "Must know SQL"],
            "source_name": ["test_source", "test_source"],
            "job_id": ["TS-01", "TS-02"],
        }
    )
    df.to_csv(sample_csv, index=False)

    return raw_dir


def test_pipeline_orchestrator_success(
    mock_session_factory, temp_raw_dir, mock_settings
):
    """Verify that a successful run flows from Extract to Load cleanly."""

    # Mocking the session and its methods
    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = False

    transaction = MagicMock()
    transaction.__enter__.return_value = transaction
    transaction.__exit__.return_value = False
    session.begin.return_value = transaction

    mock_session_factory.return_value = session

    # Setup Data Source scalar return
    mock_ds = MagicMock()
    mock_ds.data_source_id = 1
    session.scalar.return_value = mock_ds

    # Run orchestrator
    orchestrator = PipelineOrchestrator(
        settings=mock_settings,
        session_factory=mock_session_factory,
        raw_data_dir=temp_raw_dir,
    )
    report = orchestrator.run()

    # Assertions
    assert report.status == "SUCCESS"
    assert report.files_processed == 1
    assert report.rows_extracted == 2
    assert report.rows_transformed == 2
    assert report.rows_inserted + report.rows_updated == 2
    assert report.total_duration_seconds > 0

    # Verify the SQL UPSERT was called
    assert session.execute.called


def test_pipeline_orchestrator_load_failure(
    mock_session_factory, temp_raw_dir, mock_settings
):
    """Verify that a database load failure marks the pipeline as FAILED."""

    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    mock_session_factory.return_value = session

    # Force loader to throw a critical error (e.g. IntegrityError triggering DataLoadingError)
    # We patch PostgresLoader's run method to simulate total failure
    with patch(
        "jobpulse.pipeline.orchestrator.PostgresLoader.run",
        side_effect=DataLoadingError("jobs", "Mocked failure"),
    ):
        orchestrator = PipelineOrchestrator(
            settings=mock_settings,
            session_factory=mock_session_factory,
            raw_data_dir=temp_raw_dir,
        )

        report = orchestrator.run()
        assert report.status == "FAILURE"


def test_pipeline_orchestrator_empty_dir(tmp_path, mock_settings, mock_session_factory):
    """Verify that an empty directory gracefully aborts early."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    orchestrator = PipelineOrchestrator(
        settings=mock_settings,
        session_factory=mock_session_factory,
        raw_data_dir=empty_dir,
    )
    report = orchestrator.run()

    assert report.status == "FAILURE"
    assert report.files_processed == 0
    assert report.rows_extracted == 0
    assert report.rows_transformed == 0
