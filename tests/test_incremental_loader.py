from unittest.mock import MagicMock

import pandas as pd
from src.jobpulse.incremental.change_detector import (
    ChangeClassification,
    ChangeDetectionResult,
    RowChange,
)
from src.jobpulse.incremental.loader import IncrementalLoader


def test_incremental_loader_init():
    mock_engine = MagicMock()
    mock_session_factory = MagicMock()
    loader = IncrementalLoader(mock_engine, mock_session_factory, source_name="test_src")
    assert loader._source_name == "test_src"

def test_incremental_loader_load():
    mock_engine = MagicMock()
    mock_session_factory = MagicMock()
    loader = IncrementalLoader(mock_engine, mock_session_factory, source_name="test_src")
    
    # Mock the internal change detector
    mock_detector = MagicMock()
    
    df_load = pd.DataFrame([
        {"source_job_id": "job1", "title": "A", "company_name": "C", "location_raw": "L"}
    ])
    df_unchanged = pd.DataFrame()
    row_changes = [RowChange(source_job_id="job1", source_name="test_src", classification=ChangeClassification.NEW, new_hash="h")]
    
    detect_res = ChangeDetectionResult(
        rows_to_load=df_load,
        rows_unchanged=df_unchanged,
        row_changes=row_changes,
        source_name="test_src",
        detected_at=pd.Timestamp.utcnow(),
        duration_ms=10.0
    )
    mock_detector.detect.return_value = detect_res
    loader._detector = mock_detector
    
    # Mock the actual execution
    loader._upsert_chunk = MagicMock(return_value=(1, 0)) # new, updated
    
    df_in = pd.DataFrame([
        {"source_job_id": "job1", "title": "A", "company_name": "C", "location_raw": "L"}
    ])
    
    res = loader.load(df_in)
    
    assert res.rows_new == 1
    assert res.rows_updated == 0
    assert res.rows_loaded == 1
    mock_detector.persist_hashes.assert_called_once_with(row_changes)

def test_incremental_loader_empty():
    mock_engine = MagicMock()
    mock_session_factory = MagicMock()
    loader = IncrementalLoader(mock_engine, mock_session_factory, source_name="test_src")
    
    # Mock the internal change detector
    mock_detector = MagicMock()
    
    df_load = pd.DataFrame()
    df_unchanged = pd.DataFrame([{"source_job_id": "job1"}])
    row_changes = [RowChange(source_job_id="job1", source_name="test_src", classification=ChangeClassification.UNCHANGED, new_hash="h")]
    
    detect_res = ChangeDetectionResult(
        rows_to_load=df_load,
        rows_unchanged=df_unchanged,
        row_changes=row_changes,
        source_name="test_src",
        detected_at=pd.Timestamp.utcnow(),
        duration_ms=10.0
    )
    mock_detector.detect.return_value = detect_res
    loader._detector = mock_detector
    
    df_in = pd.DataFrame([{"source_job_id": "job1"}])
    res = loader.load(df_in)
    
    assert res.rows_new == 0
    assert res.rows_updated == 0
    assert res.rows_loaded == 0
    assert res.rows_unchanged == 1
    mock_detector.persist_hashes.assert_not_called()
