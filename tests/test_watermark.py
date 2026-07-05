from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from src.jobpulse.incremental.watermark import (
    InMemoryWatermarkStore,
    PostgresWatermarkStore,
)


def test_watermark_manager_init():
    wm = InMemoryWatermarkStore()
    assert wm is not None


def test_watermark_manager_get_last_none():
    wm = InMemoryWatermarkStore()
    val = wm.get_watermark("src")
    assert val is None


def test_watermark_manager_set():
    wm = InMemoryWatermarkStore()
    now = datetime.now(UTC)
    wm.set_watermark("src", now, run_id="run1")

    val = wm.get_watermark("src")
    assert val is not None
    assert val.last_successful_run_at == now
    assert val.set_by_run_id == "run1"


def test_watermark_rollback():
    wm = InMemoryWatermarkStore()
    now1 = datetime.now(UTC)
    wm.set_watermark("src", now1, run_id="run1")

    now2 = now1 + timedelta(hours=1)
    wm.set_watermark("src", now2, run_id="run2")

    # history_id=1 should be the first run
    assert wm.rollback_watermark("src", 1) is True
    val = wm.get_watermark("src")
    assert val.last_successful_run_at == now1
    assert val.set_by_run_id == "rollback_to_history_1"


def test_postgres_watermark_store_ensure_tables():
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.begin.return_value.__enter__.return_value = mock_conn

    store = PostgresWatermarkStore(mock_engine)
    store.ensure_tables()
    mock_conn.execute.assert_called_once()


def test_postgres_watermark_store_get_none():
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    mock_conn.execute.return_value.mappings.return_value.first.return_value = None

    store = PostgresWatermarkStore(mock_engine)
    assert store.get_watermark("src") is None


def test_postgres_watermark_store_get_existing():
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    now = datetime.now(UTC)
    mock_conn.execute.return_value.mappings.return_value.first.return_value = {
        "source_name": "src",
        "last_successful_run_at": now,
        "set_by_run_id": "run1",
        "late_arrival_buffer_hours": 24,
        "rows_new_in_last_run": 10,
        "rows_updated_in_last_run": 5,
        "rows_skipped_in_last_run": 0,
        "extra_state": {},
    }

    store = PostgresWatermarkStore(mock_engine)
    wm = store.get_watermark("src")
    assert wm is not None
    assert wm.source_name == "src"
    assert wm.last_successful_run_at == now
    assert wm.rows_new_in_last_run == 10


def test_postgres_watermark_store_set():
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.begin.return_value.__enter__.return_value = mock_conn

    store = PostgresWatermarkStore(mock_engine)
    now = datetime.now(UTC)
    store.set_watermark("src", now, "run1")

    assert mock_conn.execute.call_count == 2


def test_postgres_watermark_store_get_all():
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    now = datetime.now(UTC)
    mock_conn.execute.return_value.mappings.return_value = [
        {
            "source_name": "src",
            "last_successful_run_at": now,
            "set_by_run_id": "run1",
            "late_arrival_buffer_hours": 24,
            "rows_new_in_last_run": 10,
            "rows_updated_in_last_run": 5,
            "rows_skipped_in_last_run": 0,
            "extra_state": {},
        }
    ]

    store = PostgresWatermarkStore(mock_engine)
    wms = store.get_all_watermarks()
    assert len(wms) == 1
    assert wms[0].source_name == "src"


def test_postgres_watermark_store_rollback_missing():
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.mappings.return_value.first.return_value = None

    store = PostgresWatermarkStore(mock_engine)
    assert store.rollback_watermark("src", 999) is False


def test_postgres_watermark_store_rollback_success():
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    # first call is connect() for get, second is begin() for set
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    mock_engine.begin.return_value.__enter__.return_value = mock_conn

    now = datetime.now(UTC)
    mock_conn.execute.return_value.mappings.return_value.first.return_value = {
        "watermark_ts": now,
        "set_by_run_id": "run1",
    }

    store = PostgresWatermarkStore(mock_engine)
    assert store.rollback_watermark("src", 1) is True
