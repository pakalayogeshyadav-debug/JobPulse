from datetime import UTC, datetime
from unittest.mock import MagicMock

from src.jobpulse.incremental.watermark import (
    InMemoryWatermarkStore,
    PostgresWatermarkStore,
)


def test_postgres_watermark_store_get():
    mock_engine = MagicMock()
    store = PostgresWatermarkStore(mock_engine)

    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    mock_result = MagicMock()
    mock_result.mappings.return_value.first.return_value = {
        "source_name": "adzuna",
        "last_successful_run_at": datetime(2024, 1, 1, tzinfo=UTC),
        "set_by_run_id": "run123",
        "late_arrival_buffer_hours": 24,
        "rows_new_in_last_run": 10,
        "rows_updated_in_last_run": 0,
        "rows_skipped_in_last_run": 0,
        "extra_state": {},
    }
    mock_conn.execute.return_value = mock_result

    wm = store.get_watermark("adzuna")
    assert wm.source_name == "adzuna"
    assert wm.last_successful_run_at == datetime(2024, 1, 1, tzinfo=UTC)
    assert wm.late_arrival_buffer_hours == 24


def test_postgres_watermark_store_set():
    mock_engine = MagicMock()
    store = PostgresWatermarkStore(mock_engine)

    mock_conn = MagicMock()
    mock_engine.begin.return_value.__enter__.return_value = mock_conn

    store.set_watermark("adzuna", datetime(2024, 1, 1, tzinfo=UTC))
    assert mock_conn.execute.call_count == 2


def test_in_memory_watermark_store():
    store = InMemoryWatermarkStore()

    assert store.get_watermark("adzuna") is None

    dt = datetime(2024, 1, 1, tzinfo=UTC)
    store.set_watermark("adzuna", dt)

    wm = store.get_watermark("adzuna")
    assert wm is not None
    assert wm.last_successful_run_at == dt

    history = store.get_history("adzuna")
    assert len(history) == 1
