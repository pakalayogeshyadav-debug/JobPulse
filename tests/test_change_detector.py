from unittest.mock import MagicMock

import pandas as pd
from src.jobpulse.incremental.change_detector import (
    ChangeClassification,
    ChangeDetector,
    RowChange,
)


def test_change_detector_new_and_updated():
    mock_engine = MagicMock()
    detector = ChangeDetector(mock_engine, source_name="test_src")

    # Mock the computed hashes for the input DF
    detector._compute_hashes = MagicMock(
        return_value={"job1": "h1", "job2": "h2", "job3": "h3"}
    )

    # Mock DB state
    detector._fetch_known_hashes = MagicMock(
        return_value={"job1": "h1", "job2": "oldhash"}  # Unchanged  # Updated
    )

    # Input DataFrame
    df = pd.DataFrame(
        [
            {"source_job_id": "job1", "title": "Engineer"},
            {"source_job_id": "job2", "title": "Senior Engineer"},
            {"source_job_id": "job3", "title": "Staff Engineer"},
        ]
    )

    result = detector.detect(df)

    assert result.count_new == 1
    assert result.count_updated == 1
    assert result.count_unchanged == 1

    assert len(result.rows_to_load) == 2

    load_ids = result.rows_to_load["source_job_id"].tolist()
    assert "job2" in load_ids
    assert "job3" in load_ids
    assert "job1" not in load_ids


def test_change_detector_all_new():
    mock_engine = MagicMock()
    detector = ChangeDetector(mock_engine, source_name="test_src")
    detector._fetch_known_hashes = MagicMock(return_value={})

    df = pd.DataFrame(
        [
            {"source_job_id": "job1", "title": "Engineer"},
            {"source_job_id": "job2", "title": "Senior Engineer"},
        ]
    )

    result = detector.detect(df)
    assert result.count_new == 2
    assert result.count_updated == 0
    assert result.count_unchanged == 0
    assert len(result.rows_to_load) == 2


def test_change_detector_empty_df():
    mock_engine = MagicMock()
    detector = ChangeDetector(mock_engine, source_name="test_src")

    df = pd.DataFrame(columns=["source_job_id", "title"])
    result = detector.detect(df)
    assert result.count_new == 0
    assert len(result.rows_to_load) == 0


def test_change_detector_persist_hashes():
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.begin.return_value.__enter__.return_value = mock_conn

    detector = ChangeDetector(mock_engine, source_name="test_src")

    detector.persist_hashes(
        [
            RowChange(
                source_job_id="job1",
                source_name="test_src",
                classification=ChangeClassification.NEW,
                new_hash="h1",
            ),
            RowChange(
                source_job_id="job2",
                source_name="test_src",
                classification=ChangeClassification.UPDATED,
                new_hash="h2",
                old_hash="h1",
            ),
        ]
    )

    # Verify execute was called
    assert mock_conn.execute.call_count == 1
