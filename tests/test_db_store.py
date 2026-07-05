from datetime import datetime
from unittest.mock import MagicMock, patch

from src.jobpulse.observability.db_store import InMemoryMetricStore, PostgresMetricStore
from src.jobpulse.observability.metrics import (
    ErrorSeverity,
    PipelineError,
    PipelineRunMetrics,
)


def test_postgres_metric_store_ensure_tables():
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.begin.return_value.__enter__.return_value = mock_conn

    store = PostgresMetricStore(mock_engine)
    store.ensure_tables()

    assert mock_conn.execute.call_count == 2  # two tables created


@patch("src.jobpulse.observability.db_store.db_session")
def test_postgres_metric_store_upsert_run(mock_db_session):
    mock_session = MagicMock()
    mock_db_session.return_value.__enter__.return_value = mock_session

    mock_engine = MagicMock()
    store = PostgresMetricStore(mock_engine)

    metrics = PipelineRunMetrics(
        run_id="test_run", source_name="test_source", pipeline_version="1.0"
    )

    store.upsert_run(metrics)
    mock_session.execute.assert_called_once()

    # Check parameters
    call_args = mock_session.execute.call_args[0]
    sql_params = call_args[1]
    assert sql_params["run_id"] == "test_run"
    assert sql_params["source_name"] == "test_source"


@patch("src.jobpulse.observability.db_store.db_session")
def test_postgres_metric_store_insert_error(mock_db_session):
    mock_session = MagicMock()
    mock_db_session.return_value.__enter__.return_value = mock_session

    mock_engine = MagicMock()
    store = PostgresMetricStore(mock_engine)

    error = PipelineError(
        error_id="err_1",
        run_id="test_run",
        stage="extract",
        error_type="NetworkError",
        message="timeout",
        severity=ErrorSeverity.CRITICAL,
    )

    store.insert_error(error)
    mock_session.execute.assert_called_once()

    call_args = mock_session.execute.call_args[0]
    sql_params = call_args[1]
    assert sql_params["error_id"] == "err_1"
    assert sql_params["severity"] == "CRITICAL"


def test_postgres_metric_store_get_runs_summary():
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    mock_row = MagicMock()
    mock_row._mapping = {"run_id": "test_1", "status": "SUCCESS"}
    mock_conn.execute.return_value = [mock_row]

    store = PostgresMetricStore(mock_engine)
    now = datetime.now()

    res1 = store.get_runs_summary(since=now)
    assert len(res1) == 1
    assert res1[0]["run_id"] == "test_1"

    res2 = store.get_runs_summary(since=now, source_name="src")
    assert len(res2) == 1


def test_in_memory_metric_store():
    store = InMemoryMetricStore()
    store.ensure_tables()  # no-op

    now = datetime.now()
    metrics = PipelineRunMetrics(run_id="run_1", source_name="src1")
    metrics.started_at = now
    store.upsert_run(metrics)
    assert len(store.runs) == 1

    metrics.rows_extracted = 100
    store.upsert_run(metrics)
    assert len(store.runs) == 1
    assert store.runs[0].rows_extracted == 100

    metrics2 = PipelineRunMetrics(run_id="run_2", source_name="src2")
    metrics2.started_at = now
    store.upsert_run(metrics2)
    assert len(store.runs) == 2

    err = PipelineError(
        error_id="e1", run_id="run_1", stage="ex", error_type="t", message="m"
    )
    store.insert_error(err)
    assert len(store.errors) == 1

    summary = store.get_runs_summary(since=now)
    assert len(summary) == 2

    summary_src = store.get_runs_summary(since=now, source_name="src1")
    assert len(summary_src) == 1
    assert summary_src[0]["run_id"] == "run_1"
