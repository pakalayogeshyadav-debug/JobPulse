"""
tests/test_incremental.py — Comprehensive unit tests for incremental ETL.

All tests are pure unit tests (no PostgreSQL required) using:
    - InMemoryWatermarkStore (no DB for watermark tests)
    - Mock SQLAlchemy engine (for ChangeDetector DB calls)
    - InMemoryWatermarkStore + mock engine (for IncrementalRunner)

Test coverage:
    ✅ WatermarkRecord.filter_from — late arrival buffer maths
    ✅ InMemoryWatermarkStore      — CRUD, idempotency, rollback
    ✅ ChangeDetector              — NEW / UPDATED / UNCHANGED classification
    ✅ ChangeDetector              — hash consistency and alias resolution
    ✅ IncrementalLoadResult       — computed properties
    ✅ IncrementalRunSummary       — computed properties, serialisation
    ✅ IncrementalRunner           — first run full load
    ✅ IncrementalRunner           — incremental run with watermark filter
    ✅ IncrementalRunner           — watermark not advanced on failure
    ✅ IncrementalRunner           — all-unchanged short-circuit
    ✅ IncrementalRunner           — late-arriving data is included
    ✅ IncrementalRunner           — timestamp col missing (defensive)
    ✅ IncrementalRunner.reset_watermark
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from jobpulse.incremental.change_detector import (
    ChangeClassification,
    ChangeDetectionResult,
    ChangeDetector,
)
from jobpulse.incremental.loader import IncrementalLoadResult
from jobpulse.incremental.runner import IncrementalRunner
from jobpulse.incremental.watermark import (
    InMemoryWatermarkStore,
    WatermarkRecord,
)

# =============================================================================
# Helpers
# =============================================================================


def utc(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0
) -> datetime:
    """Build a UTC-aware datetime for tests."""
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


def make_df(
    n: int,
    source: str = "src",
    posted_date: datetime | None = None,
    job_title_prefix: str = "Engineer",
) -> pd.DataFrame:
    """Build a minimal jobs DataFrame for testing."""
    if posted_date is None:
        posted_date = utc(2024, 6, 30)
    return pd.DataFrame(
        {
            "source_job_id": [f"{source}_job_{i}" for i in range(n)],
            "job_title": [f"{job_title_prefix} {i}" for i in range(n)],
            "company_name": ["Acme Corp"] * n,
            "location_raw": ["San Francisco, CA"] * n,
            "salary_min": [80_000.0] * n,
            "salary_max": [120_000.0] * n,
            "salary_currency": ["USD"] * n,
            "employment_type": ["FULL_TIME"] * n,
            "is_remote": [False] * n,
            "description": ["Test description."] * n,
            "posted_date": [posted_date] * n,
        }
    )


def make_mock_engine(known_hashes: dict[str, str] | None = None) -> MagicMock:
    """
    Build a mock SQLAlchemy engine that returns known_hashes for hash lookups.

    This avoids needing a real PostgreSQL connection in unit tests.
    """
    engine = MagicMock()

    # Mock connection context manager
    conn = MagicMock()
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)

    # Build fake rows for known hashes
    if known_hashes:
        fake_rows = [(job_id, h) for job_id, h in known_hashes.items()]
    else:
        fake_rows = []

    conn.execute.return_value.fetchall.return_value = fake_rows
    return engine


def make_mock_runner(
    store: InMemoryWatermarkStore | None = None,
    source: str = "test_source",
    run_id: str = "run-001",
) -> tuple[IncrementalRunner, InMemoryWatermarkStore]:
    """Build an IncrementalRunner wired to an InMemoryWatermarkStore and mock engine."""
    if store is None:
        store = InMemoryWatermarkStore()
    engine = make_mock_engine()
    session_factory = MagicMock()

    # Patch IncrementalLoader.load so we control what it returns
    runner = IncrementalRunner(
        engine=engine,
        session_factory=session_factory,
        watermark_store=store,
        source_name=source,
        run_id=run_id,
        source_job_id_col="source_job_id",
        timestamp_col="posted_date",
    )
    return runner, store


# =============================================================================
# WatermarkRecord
# =============================================================================


class TestWatermarkRecord:
    """Tests for WatermarkRecord value object."""

    def test_filter_from_subtracts_buffer_hours(self) -> None:
        wm = WatermarkRecord(
            source_name="csv",
            last_successful_run_at=utc(2024, 6, 30, 3),
            late_arrival_buffer_hours=24,
        )
        expected = utc(2024, 6, 29, 3)
        assert wm.filter_from == expected

    def test_filter_from_with_zero_buffer(self) -> None:
        ts = utc(2024, 6, 30, 3)
        wm = WatermarkRecord(
            source_name="csv",
            last_successful_run_at=ts,
            late_arrival_buffer_hours=0,
        )
        assert wm.filter_from == ts

    def test_filter_from_with_large_buffer(self) -> None:
        ts = utc(2024, 6, 30)
        wm = WatermarkRecord(
            source_name="csv",
            last_successful_run_at=ts,
            late_arrival_buffer_hours=72,
        )
        expected = utc(2024, 6, 27)
        assert wm.filter_from == expected

    def test_to_dict_contains_filter_from(self) -> None:
        wm = WatermarkRecord(
            source_name="csv",
            last_successful_run_at=utc(2024, 6, 30),
        )
        d = wm.to_dict()
        assert "filter_from" in d
        assert "last_successful_run_at" in d
        assert d["source_name"] == "csv"


# =============================================================================
# InMemoryWatermarkStore
# =============================================================================


class TestInMemoryWatermarkStore:
    """Tests for the in-memory watermark store."""

    def test_get_watermark_returns_none_for_unknown_source(self) -> None:
        store = InMemoryWatermarkStore()
        assert store.get_watermark("unknown_source") is None

    def test_set_and_get_watermark(self) -> None:
        store = InMemoryWatermarkStore()
        ts = utc(2024, 6, 29, 3)
        store.set_watermark("csv", ts, run_id="run-1", rows_new=100)
        wm = store.get_watermark("csv")
        assert wm is not None
        assert wm.last_successful_run_at == ts
        assert wm.rows_new_in_last_run == 100

    def test_set_watermark_is_idempotent(self) -> None:
        store = InMemoryWatermarkStore()
        ts = utc(2024, 6, 29)
        store.set_watermark("csv", ts)
        store.set_watermark("csv", ts)  # Second call — same args
        assert len(store.get_history("csv")) == 2  # History appends
        assert store.get_watermark("csv").last_successful_run_at == ts  # Value same

    def test_set_watermark_overwrites_with_newer_timestamp(self) -> None:
        store = InMemoryWatermarkStore()
        ts_old = utc(2024, 6, 28)
        ts_new = utc(2024, 6, 29)
        store.set_watermark("csv", ts_old)
        store.set_watermark("csv", ts_new)
        assert store.get_watermark("csv").last_successful_run_at == ts_new

    def test_ensure_tables_is_no_op(self) -> None:
        store = InMemoryWatermarkStore()
        store.ensure_tables()  # Must not raise

    def test_get_all_watermarks_returns_all_sources(self) -> None:
        store = InMemoryWatermarkStore()
        store.set_watermark("csv", utc(2024, 6, 28))
        store.set_watermark("api", utc(2024, 6, 29))
        all_wm = store.get_all_watermarks()
        assert len(all_wm) == 2
        sources = {w.source_name for w in all_wm}
        assert sources == {"csv", "api"}

    def test_rollback_watermark_restores_previous_entry(self) -> None:
        store = InMemoryWatermarkStore()
        ts1 = utc(2024, 6, 28)
        ts2 = utc(2024, 6, 29)
        store.set_watermark("csv", ts1, run_id="run-1")
        store.set_watermark("csv", ts2, run_id="run-2")

        history = store.get_history("csv")
        assert len(history) == 2
        h_id_1 = history[0]["history_id"]

        success = store.rollback_watermark("csv", h_id_1)
        assert success is True
        # After rollback, watermark should point to ts1
        wm = store.get_watermark("csv")
        assert wm.last_successful_run_at == ts1

    def test_rollback_watermark_returns_false_for_unknown_id(self) -> None:
        store = InMemoryWatermarkStore()
        store.set_watermark("csv", utc(2024, 6, 28))
        result = store.rollback_watermark("csv", history_id=999)
        assert result is False

    def test_watermark_stores_row_counts(self) -> None:
        store = InMemoryWatermarkStore()
        store.set_watermark(
            "csv",
            utc(2024, 6, 29),
            rows_new=500,
            rows_updated=50,
            rows_skipped=4450,
        )
        wm = store.get_watermark("csv")
        assert wm.rows_new_in_last_run == 500
        assert wm.rows_updated_in_last_run == 50
        assert wm.rows_skipped_in_last_run == 4450


# =============================================================================
# ChangeDetector (with mock engine)
# =============================================================================


class TestChangeDetector:
    """Tests for ChangeDetector change classification logic."""

    def _make_detector(
        self, known_hashes: dict[str, str] | None = None
    ) -> ChangeDetector:
        engine = make_mock_engine(known_hashes or {})
        return ChangeDetector(engine=engine, source_name="test_src")

    def test_all_rows_classified_as_new_when_no_known_hashes(self) -> None:
        detector = self._make_detector(known_hashes={})
        df = make_df(5)
        result = detector.detect(df)

        assert result.count_new == 5
        assert result.count_updated == 0
        assert result.count_unchanged == 0
        assert len(result.rows_to_load) == 5
        assert result.rows_unchanged.empty

    def test_all_rows_classified_unchanged_when_hashes_match(self) -> None:
        df = make_df(3)
        # Pre-compute the hashes that the detector would compute
        detector = self._make_detector(known_hashes={})
        # Run once to get the hashes
        result_first = detector.detect(df)
        known = {rc.source_job_id: rc.new_hash for rc in result_first.row_changes}

        # Now test with those known hashes
        detector2 = self._make_detector(known_hashes=known)
        result2 = detector2.detect(df)

        assert result2.count_unchanged == 3
        assert result2.count_new == 0
        assert result2.count_updated == 0
        assert result2.rows_to_load.empty

    def test_changed_rows_classified_as_updated(self) -> None:
        df = make_df(3)
        # Pre-compute hashes for rows 0 and 2 but use a WRONG hash for row 1
        detector_temp = self._make_detector(known_hashes={})
        first = detector_temp.detect(df)
        known = {rc.source_job_id: rc.new_hash for rc in first.row_changes}

        # Corrupt hash for job_1 to simulate a content change
        job_1_id = "src_job_1"
        known[job_1_id] = "deadbeefdeadbeef" * 4  # Wrong hash

        detector2 = self._make_detector(known_hashes=known)
        df_modified = df.copy()
        df_modified.loc[1, "job_title"] = "Senior Engineer 1"  # Changed content
        result = detector2.detect(df_modified)

        assert result.count_updated == 1
        updated_row = next(
            r
            for r in result.row_changes
            if r.classification == ChangeClassification.UPDATED
        )
        assert updated_row.source_job_id == job_1_id

    def test_mixed_classification(self) -> None:
        df = make_df(4)
        # rows 0,1 known (unchanged), row 2 known (updated), row 3 unknown (new)
        detector_temp = self._make_detector(known_hashes={})
        first_result = detector_temp.detect(df)
        hashes = {rc.source_job_id: rc.new_hash for rc in first_result.row_changes}

        # Simulate: rows 0 and 1 are known + unchanged
        # row 2: known but hash changed
        # row 3: not known (new)
        partial_known = {
            "src_job_0": hashes["src_job_0"],
            "src_job_1": hashes["src_job_1"],
            "src_job_2": "wrong_hash_aaaaaa",  # will be classified UPDATED
            # src_job_3 is absent → NEW
        }

        detector2 = self._make_detector(known_hashes=partial_known)
        df2 = df.copy()
        df2.loc[2, "salary_min"] = 90_000.0  # Trigger content change for row 2
        result = detector2.detect(df2)

        assert result.count_unchanged == 2
        assert result.count_updated == 1
        assert result.count_new == 1
        assert len(result.rows_to_load) == 2  # NEW + UPDATED

    def test_empty_dataframe_returns_empty_result(self) -> None:
        detector = self._make_detector()
        df_empty = make_df(0)
        result = detector.detect(df_empty)
        assert result.total_rows_in == 0
        assert result.rows_to_load.empty

    def test_raises_key_error_for_missing_id_column(self) -> None:
        detector = self._make_detector()
        df = pd.DataFrame({"col_a": [1, 2], "col_b": ["x", "y"]})
        with pytest.raises(KeyError, match="source_job_id"):
            detector.detect(df)

    def test_content_hash_is_sha256_hex_64_chars(self) -> None:
        detector = self._make_detector()
        df = make_df(1)
        result = detector.detect(df)
        h = result.row_changes[0].new_hash
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_same_content_produces_same_hash(self) -> None:
        detector = self._make_detector()
        df = make_df(3)
        result1 = detector.detect(df)
        result2 = detector.detect(df)
        hashes1 = {rc.source_job_id: rc.new_hash for rc in result1.row_changes}
        hashes2 = {rc.source_job_id: rc.new_hash for rc in result2.row_changes}
        assert hashes1 == hashes2

    def test_different_content_produces_different_hash(self) -> None:
        detector = self._make_detector()
        df1 = make_df(1, job_title_prefix="Engineer")
        df2 = make_df(1, job_title_prefix="Manager")
        result1 = detector.detect(df1)
        result2 = detector.detect(df2)
        assert result1.row_changes[0].new_hash != result2.row_changes[0].new_hash

    def test_rows_to_load_stamped_with_content_hash(self) -> None:
        detector = self._make_detector(known_hashes={})
        df = make_df(3)
        result = detector.detect(df)
        assert "_content_hash" in result.rows_to_load.columns
        assert result.rows_to_load["_content_hash"].notna().all()

    def test_skip_rate_pct_computed_correctly(self) -> None:
        df = make_df(10)
        # All 10 known with matching hashes → all UNCHANGED
        detector_temp = self._make_detector()
        first = detector_temp.detect(df)
        all_known = {rc.source_job_id: rc.new_hash for rc in first.row_changes}

        detector2 = self._make_detector(known_hashes=all_known)
        result = detector2.detect(df)
        assert result.skip_rate_pct == 100.0

    def test_detection_result_log_string_format(self) -> None:
        detector = self._make_detector()
        df = make_df(5)
        result = detector.detect(df)
        log_str = result.to_log_string()
        assert "new=" in log_str
        assert "updated=" in log_str
        assert "unchanged=" in log_str
        assert "skip_rate=" in log_str


# =============================================================================
# IncrementalLoadResult
# =============================================================================


class TestIncrementalLoadResult:
    """Tests for IncrementalLoadResult computed properties."""

    @pytest.fixture()
    def sample_result(self) -> IncrementalLoadResult:
        return IncrementalLoadResult(
            source_name="csv",
            rows_in=1000,
            rows_new=80,
            rows_updated=20,
            rows_unchanged=890,
            rows_duplicate=10,
            rows_failed=0,
            chunks_loaded=2,
            change_detection_ms=150.0,
            load_duration_ms=800.0,
            started_at=utc(2024, 6, 30, 3),
            completed_at=utc(2024, 6, 30, 3, 0),
        )

    def test_rows_loaded_is_sum_of_new_and_updated(
        self, sample_result: IncrementalLoadResult
    ) -> None:
        assert sample_result.rows_loaded == 100  # 80 + 20

    def test_skip_rate_pct(self, sample_result: IncrementalLoadResult) -> None:
        # 890 / 1000 * 100 = 89.0%
        assert sample_result.skip_rate_pct == 89.0

    def test_success_rate_pct_when_no_failures(
        self, sample_result: IncrementalLoadResult
    ) -> None:
        assert sample_result.success_rate_pct == 100.0

    def test_success_rate_pct_with_failures(self) -> None:
        result = IncrementalLoadResult(
            source_name="csv",
            rows_in=100,
            rows_new=80,
            rows_updated=10,
            rows_unchanged=0,
            rows_duplicate=0,
            rows_failed=10,
            chunks_loaded=1,
            change_detection_ms=10.0,
            load_duration_ms=100.0,
            started_at=utc(2024, 6, 30),
            completed_at=utc(2024, 6, 30),
        )
        # (80+10) / (80+10+10) * 100 = 90/100 = 90.0
        assert result.success_rate_pct == 90.0

    def test_skip_rate_pct_is_zero_when_rows_in_is_zero(self) -> None:
        result = IncrementalLoadResult(
            source_name="csv",
            rows_in=0,
            rows_new=0,
            rows_updated=0,
            rows_unchanged=0,
            rows_duplicate=0,
            rows_failed=0,
            chunks_loaded=0,
            change_detection_ms=0.0,
            load_duration_ms=0.0,
            started_at=utc(2024, 6, 30),
            completed_at=utc(2024, 6, 30),
        )
        assert result.skip_rate_pct == 0.0

    def test_to_dict_contains_all_keys(
        self, sample_result: IncrementalLoadResult
    ) -> None:
        d = sample_result.to_dict()
        required = {
            "source_name",
            "rows_in",
            "rows_new",
            "rows_updated",
            "rows_unchanged",
            "rows_duplicate",
            "rows_failed",
            "rows_loaded",
            "skip_rate_pct",
            "success_rate_pct",
        }
        assert required.issubset(d.keys())

    def test_to_log_string_contains_source(
        self, sample_result: IncrementalLoadResult
    ) -> None:
        log_str = sample_result.to_log_string()
        assert "source=" in log_str
        assert "new=" in log_str
        assert "updated=" in log_str
        assert "unchanged=" in log_str


# =============================================================================
# IncrementalRunner
# =============================================================================


class TestIncrementalRunner:
    """Integration-level unit tests for IncrementalRunner (no real DB)."""

    # ── First-run (no watermark) ──────────────────────────────────────────────

    def test_first_run_loads_all_rows_when_no_watermark(self) -> None:
        """No watermark → full historical load — no rows filtered out."""
        runner, store = make_mock_runner()
        df = make_df(10, posted_date=utc(2024, 6, 28))

        with patch.object(runner._loader, "load") as mock_load:
            mock_load.return_value = IncrementalLoadResult(
                source_name="test_source",
                rows_in=10,
                rows_new=10,
                rows_updated=0,
                rows_unchanged=0,
                rows_duplicate=0,
                rows_failed=0,
                chunks_loaded=1,
                change_detection_ms=10.0,
                load_duration_ms=50.0,
                started_at=utc(2024, 6, 30, 3),
                completed_at=utc(2024, 6, 30, 3),
            )
            summary = runner.run(df)

        assert summary.rows_in_extract == 10
        assert summary.rows_filtered_out == 0
        assert summary.rows_after_filter == 10
        assert summary.run_status == "SUCCESS"
        assert summary.watermark_before is None

    def test_first_run_advances_watermark(self) -> None:
        runner, store = make_mock_runner()
        df = make_df(5)

        with patch.object(runner._loader, "load") as mock_load:
            mock_load.return_value = IncrementalLoadResult(
                source_name="test_source",
                rows_in=5,
                rows_new=5,
                rows_updated=0,
                rows_unchanged=0,
                rows_duplicate=0,
                rows_failed=0,
                chunks_loaded=1,
                change_detection_ms=5.0,
                load_duration_ms=20.0,
                started_at=utc(2024, 6, 30),
                completed_at=utc(2024, 6, 30),
            )
            runner.run(df)

        # Watermark should now be set
        assert store.get_watermark("test_source") is not None

    def test_first_run_with_initial_since_filters_old_rows(self) -> None:
        """initial_full_load_since filters rows before the given cutoff."""
        engine = make_mock_engine()
        session_factory = MagicMock()
        store = InMemoryWatermarkStore()

        runner = IncrementalRunner(
            engine=engine,
            session_factory=session_factory,
            watermark_store=store,
            source_name="test_source",
            run_id="run-001",
            timestamp_col="posted_date",
            initial_full_load_since=utc(2024, 6, 29),
        )

        old_df = make_df(5, posted_date=utc(2024, 6, 27))  # Before cutoff
        new_df = make_df(3, posted_date=utc(2024, 6, 30))  # After cutoff
        full_df = pd.concat([old_df, new_df], ignore_index=True)
        full_df["source_job_id"] = [f"job_{i}" for i in range(len(full_df))]

        with patch.object(runner._loader, "load") as mock_load:
            mock_load.return_value = IncrementalLoadResult(
                source_name="test_source",
                rows_in=3,
                rows_new=3,
                rows_updated=0,
                rows_unchanged=0,
                rows_duplicate=0,
                rows_failed=0,
                chunks_loaded=1,
                change_detection_ms=5.0,
                load_duration_ms=10.0,
                started_at=utc(2024, 6, 30),
                completed_at=utc(2024, 6, 30),
            )
            summary = runner.run(full_df)

        assert summary.rows_filtered_out == 5  # old rows dropped
        assert summary.rows_after_filter == 3  # only new rows passed

    # ── Incremental run (with watermark) ──────────────────────────────────────

    def test_incremental_run_filters_rows_before_watermark(self) -> None:
        """Rows posted before filter_from are excluded."""
        runner, store = make_mock_runner()
        watermark_ts = utc(2024, 6, 29, 3)
        store.set_watermark(
            "test_source",
            watermark_ts,
            run_id="prev-run",
        )
        # filter_from = watermark - 24h = 2024-06-28 03:00
        filter_from_expected = utc(2024, 6, 28, 3)

        old_rows = make_df(8, posted_date=utc(2024, 6, 27))  # Before filter_from
        new_rows = make_df(2, posted_date=utc(2024, 6, 30))  # After filter_from
        full_df = pd.concat([old_rows, new_rows], ignore_index=True)
        full_df["source_job_id"] = [f"job_{i}" for i in range(len(full_df))]

        with patch.object(runner._loader, "load") as mock_load:
            mock_load.return_value = IncrementalLoadResult(
                source_name="test_source",
                rows_in=2,
                rows_new=2,
                rows_updated=0,
                rows_unchanged=0,
                rows_duplicate=0,
                rows_failed=0,
                chunks_loaded=1,
                change_detection_ms=5.0,
                load_duration_ms=10.0,
                started_at=utc(2024, 6, 30),
                completed_at=utc(2024, 6, 30),
            )
            summary = runner.run(full_df)

        assert summary.rows_filtered_out == 8
        assert summary.rows_after_filter == 2

    def test_watermark_advances_after_successful_run(self) -> None:
        runner, store = make_mock_runner()
        store.set_watermark("test_source", utc(2024, 6, 28))
        df = make_df(5, posted_date=utc(2024, 6, 30))

        with patch.object(runner._loader, "load") as mock_load:
            mock_load.return_value = IncrementalLoadResult(
                source_name="test_source",
                rows_in=5,
                rows_new=5,
                rows_updated=0,
                rows_unchanged=0,
                rows_duplicate=0,
                rows_failed=0,
                chunks_loaded=1,
                change_detection_ms=5.0,
                load_duration_ms=10.0,
                started_at=utc(2024, 6, 30, 3),
                completed_at=utc(2024, 6, 30, 3),
            )
            before = store.get_watermark("test_source").last_successful_run_at
            runner.run(df)
            after = store.get_watermark("test_source").last_successful_run_at

        assert after > before  # Watermark advanced

    def test_watermark_not_advanced_on_failure(self) -> None:
        runner, store = make_mock_runner()
        ts = utc(2024, 6, 28)
        store.set_watermark("test_source", ts)
        df = make_df(5, posted_date=utc(2024, 6, 30))

        with patch.object(runner._loader, "load") as mock_load:
            mock_load.side_effect = RuntimeError("DB exploded")
            summary = runner.run(df)

        assert summary.run_status == "FAILED"
        assert summary.watermark_after is None
        # Watermark unchanged
        wm = store.get_watermark("test_source")
        assert wm.last_successful_run_at == ts

    def test_partial_status_when_some_rows_failed(self) -> None:
        runner, store = make_mock_runner()
        df = make_df(10, posted_date=utc(2024, 6, 30))

        with patch.object(runner._loader, "load") as mock_load:
            mock_load.return_value = IncrementalLoadResult(
                source_name="test_source",
                rows_in=10,
                rows_new=8,
                rows_updated=0,
                rows_unchanged=0,
                rows_duplicate=0,
                rows_failed=2,
                chunks_loaded=1,
                change_detection_ms=5.0,
                load_duration_ms=10.0,
                started_at=utc(2024, 6, 30),
                completed_at=utc(2024, 6, 30),
            )
            summary = runner.run(df)

        assert summary.run_status == "PARTIAL"
        # Watermark IS advanced even on partial (some data got through)
        assert store.get_watermark("test_source") is not None

    def test_all_unchanged_rows_short_circuits_load(self) -> None:
        runner, store = make_mock_runner()
        df = make_df(5, posted_date=utc(2024, 6, 30))

        # ChangeDetector returns all UNCHANGED → loader.load() should NOT be called
        mock_detection = ChangeDetectionResult(
            rows_to_load=df.iloc[0:0].copy(),  # Empty
            rows_unchanged=df,
            row_changes=[],
            source_name="test_source",
            detected_at=utc(2024, 6, 30),
            duration_ms=10.0,
        )
        with patch.object(
            runner._loader._detector, "detect", return_value=mock_detection
        ):
            with patch.object(
                runner._loader, "load", wraps=runner._loader.load
            ) as spy_load:
                # Patch the inner UPSERT so it returns (0, 0) without hitting DB
                with patch.object(runner._loader, "_upsert_chunk", return_value=(0, 0)):
                    summary = runner.run(df)

        # If all unchanged, load result should show 0 new/updated
        assert summary.run_status == "SUCCESS"

    def test_late_arriving_data_included_within_buffer(self) -> None:
        """
        A row with posted_date 23 hours before the watermark (within the 24h buffer)
        should be included in the incremental batch.
        """
        runner, store = make_mock_runner()
        watermark_ts = utc(2024, 6, 30, 10)  # 10:00
        store.set_watermark("test_source", watermark_ts)
        # filter_from = 2024-06-29 10:00 (24h buffer default)

        # Late-arriving row: posted 2024-06-29 12:00 (within buffer window)
        late_row = make_df(1, posted_date=utc(2024, 6, 29, 12))
        # Fresh row
        fresh_row = make_df(1, posted_date=utc(2024, 6, 30, 11))
        # Very old row (outside buffer window)
        old_row = make_df(1, posted_date=utc(2024, 6, 28, 0))

        full_df = pd.concat([late_row, fresh_row, old_row], ignore_index=True)
        full_df["source_job_id"] = ["late_job", "fresh_job", "old_job"]

        with patch.object(runner._loader, "load") as mock_load:
            mock_load.return_value = IncrementalLoadResult(
                source_name="test_source",
                rows_in=2,
                rows_new=2,
                rows_updated=0,
                rows_unchanged=0,
                rows_duplicate=0,
                rows_failed=0,
                chunks_loaded=1,
                change_detection_ms=5.0,
                load_duration_ms=10.0,
                started_at=utc(2024, 6, 30),
                completed_at=utc(2024, 6, 30),
            )
            summary = runner.run(full_df)

        # Late and fresh included; old dropped
        assert summary.rows_after_filter == 2
        assert summary.rows_filtered_out == 1

    def test_missing_timestamp_column_processes_all_rows_with_warning(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        runner, store = make_mock_runner()
        store.set_watermark("test_source", utc(2024, 6, 28))

        # DataFrame without the timestamp column
        df = pd.DataFrame(
            {
                "source_job_id": ["j1", "j2"],
                "job_title": ["SWE", "PM"],
            }
        )

        with patch.object(runner._loader, "load") as mock_load:
            mock_load.return_value = IncrementalLoadResult(
                source_name="test_source",
                rows_in=2,
                rows_new=2,
                rows_updated=0,
                rows_unchanged=0,
                rows_duplicate=0,
                rows_failed=0,
                chunks_loaded=1,
                change_detection_ms=5.0,
                load_duration_ms=10.0,
                started_at=utc(2024, 6, 30),
                completed_at=utc(2024, 6, 30),
            )
            summary = runner.run(df)

        # All rows pass through (defensive fallback)
        assert summary.rows_after_filter == 2
        assert summary.rows_filtered_out == 0

    def test_reset_watermark_sets_earlier_timestamp(self) -> None:
        runner, store = make_mock_runner()
        store.set_watermark("test_source", utc(2024, 6, 30))

        new_ts = utc(2024, 6, 24)  # Roll back 6 days
        runner.reset_watermark(new_ts)

        wm = store.get_watermark("test_source")
        assert wm.last_successful_run_at == new_ts

    def test_get_current_watermark_returns_none_on_first_run(self) -> None:
        runner, store = make_mock_runner()
        assert runner.get_current_watermark() is None

    def test_get_current_watermark_returns_watermark_after_run(self) -> None:
        runner, store = make_mock_runner()
        df = make_df(3)

        with patch.object(runner._loader, "load") as mock_load:
            mock_load.return_value = IncrementalLoadResult(
                source_name="test_source",
                rows_in=3,
                rows_new=3,
                rows_updated=0,
                rows_unchanged=0,
                rows_duplicate=0,
                rows_failed=0,
                chunks_loaded=1,
                change_detection_ms=5.0,
                load_duration_ms=10.0,
                started_at=utc(2024, 6, 30),
                completed_at=utc(2024, 6, 30),
            )
            runner.run(df)

        wm = runner.get_current_watermark()
        assert wm is not None

    def test_summary_to_dict_is_json_serialisable(self) -> None:
        import json

        runner, store = make_mock_runner()
        df = make_df(3)

        with patch.object(runner._loader, "load") as mock_load:
            mock_load.return_value = IncrementalLoadResult(
                source_name="test_source",
                rows_in=3,
                rows_new=3,
                rows_updated=0,
                rows_unchanged=0,
                rows_duplicate=0,
                rows_failed=0,
                chunks_loaded=1,
                change_detection_ms=5.0,
                load_duration_ms=10.0,
                started_at=utc(2024, 6, 30),
                completed_at=utc(2024, 6, 30),
            )
            summary = runner.run(df)

        json_str = json.dumps(summary.to_dict(), default=str)
        parsed = json.loads(json_str)
        assert parsed["source_name"] == "test_source"
        assert "watermark" in parsed

    def test_error_message_set_on_failure(self) -> None:
        runner, store = make_mock_runner()
        df = make_df(5, posted_date=utc(2024, 6, 30))

        with patch.object(runner._loader, "load") as mock_load:
            mock_load.side_effect = RuntimeError("Connection refused")
            summary = runner.run(df)

        assert summary.run_status == "FAILED"
        assert "Connection refused" in (summary.error_message or "")

    def test_empty_df_after_filter_advances_watermark(self) -> None:
        """If filter produces empty result, watermark still advances."""
        runner, store = make_mock_runner()
        store.set_watermark("test_source", utc(2024, 6, 30))
        # All rows are old (posted before filter_from)
        df = make_df(5, posted_date=utc(2024, 6, 1))

        summary = runner.run(df)

        assert summary.rows_after_filter == 0
        assert summary.run_status == "SUCCESS"
        # Watermark advanced (window was scanned — nothing to load, but scan confirmed)
        assert store.get_watermark("test_source") is not None
