"""
tests/test_observability.py — Comprehensive unit tests for the observability layer.

Test coverage:
    ✅ PipelineRunMetrics — computed properties, Prometheus format, serialisation
    ✅ StageMetrics       — success_rate, rows_dropped, duration conversions
    ✅ PipelineError      — serialisation, UUID uniqueness
    ✅ InMemoryMetricStore — upsert, insert_error, get_runs_summary
    ✅ PipelineMonitor    — context manager lifecycle, all record_* methods
    ✅ JsonStructuredLogger — install/uninstall, emit_event
    ✅ DailyReport        — computed metrics, text output, JSON output
    ✅ ComponentHealth    — status aggregation
    ✅ OverallHealth      — HEALTHY/DEGRADED/UNHEALTHY logic
    ✅ ConfigChecker      — valid config, invalid config
    ✅ MemoryChecker      — runs without psutil

Design — All tests are pure unit tests (no PostgreSQL required):
    We use InMemoryMetricStore for all PipelineMonitor tests.
    Database-dependent checkers are tested with mock engines.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from jobpulse.observability.db_store import InMemoryMetricStore
from jobpulse.observability.health_check import (
    ComponentHealth,
    ConfigChecker,
    MemoryChecker,
    OverallHealth,
)
from jobpulse.observability.json_logger import JsonFormatter, JsonStructuredLogger
from jobpulse.observability.metrics import (
    ErrorSeverity,
    PipelineError,
    PipelineRunMetrics,
    PipelineStatus,
    StageMetrics,
)
from jobpulse.observability.pipeline_monitor import PipelineMonitor
from jobpulse.observability.report_generator import DailyReport

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture()
def sample_run_metrics() -> PipelineRunMetrics:
    """A completed pipeline run with realistic metrics."""
    return PipelineRunMetrics(
        run_id="test-run-001",
        source_name="csv_kaggle_jobs",
        pipeline_version="v1.2.0",
        environment="development",
        status=PipelineStatus.SUCCESS,
        started_at=datetime(2024, 6, 30, 3, 0, 0, tzinfo=UTC),
        completed_at=datetime(2024, 6, 30, 3, 12, 0, tzinfo=UTC),
        rows_extracted=5000,
        rows_transformed=4850,
        rows_loaded=4800,
        rows_failed=50,
        validation_failures=2,
        critical_failures=0,
        extract_duration_ms=10_000.0,
        transform_duration_ms=25_000.0,
        load_duration_ms=15_000.0,
        db_execution_time_ms=16_000.0,
    )


@pytest.fixture()
def in_memory_store() -> InMemoryMetricStore:
    """Fresh in-memory metric store for each test."""
    return InMemoryMetricStore()


@pytest.fixture()
def monitor(in_memory_store: InMemoryMetricStore, tmp_path: Path) -> PipelineMonitor:
    """PipelineMonitor wired to in-memory store with temp log dir."""
    return PipelineMonitor(
        run_id="test-run-001",
        source_name="csv_kaggle_jobs",
        metric_store=in_memory_store,
        log_dir=tmp_path / "logs",
        pipeline_version="v1.0.0",
        environment="development",
    )


@pytest.fixture()
def mock_settings():
    """Mock Settings object with valid defaults."""
    s = MagicMock()
    s.db_password = "correct_strong_password"
    s.environment = "development"
    s.batch_size = 1000
    s.db_host = "localhost"
    s.db_port = 5432
    s.db_name = "jobpulse_dw"
    s.db_pool_size = 5
    s.log_level = "INFO"
    return s


# =============================================================================
# Test: PipelineRunMetrics
# =============================================================================


class TestPipelineRunMetrics:
    """Unit tests for the PipelineRunMetrics dataclass."""

    def test_total_duration_ms_computed_correctly(
        self, sample_run_metrics: PipelineRunMetrics
    ) -> None:
        """Duration should equal (completed_at - started_at) in ms."""
        expected_ms = 12 * 60 * 1000.0  # 12 minutes = 720_000 ms
        assert sample_run_metrics.total_duration_ms == expected_ms

    def test_total_duration_seconds_rounds_correctly(
        self, sample_run_metrics: PipelineRunMetrics
    ) -> None:
        assert sample_run_metrics.total_duration_seconds == 720.0

    def test_success_rate_pct_computed_from_loaded_vs_extracted(
        self, sample_run_metrics: PipelineRunMetrics
    ) -> None:
        expected = round(4800 / 5000 * 100.0, 2)
        assert sample_run_metrics.success_rate_pct == expected

    def test_success_rate_pct_is_zero_when_no_rows_extracted(self) -> None:
        metrics = PipelineRunMetrics(
            run_id="zero-run",
            source_name="empty_source",
            rows_extracted=0,
            rows_loaded=0,
        )
        assert metrics.success_rate_pct == 0.0

    def test_drop_rate_pct(self, sample_run_metrics: PipelineRunMetrics) -> None:
        expected = round(50 / 5000 * 100.0, 2)
        assert sample_run_metrics.drop_rate_pct == expected

    def test_is_healthy_true_for_success(
        self, sample_run_metrics: PipelineRunMetrics
    ) -> None:
        assert sample_run_metrics.is_healthy is True

    def test_is_healthy_false_for_failed(self) -> None:
        metrics = PipelineRunMetrics(
            run_id="fail-run",
            source_name="src",
            status=PipelineStatus.FAILED,
        )
        assert metrics.is_healthy is False

    def test_total_duration_ms_is_zero_when_not_completed(self) -> None:
        metrics = PipelineRunMetrics(run_id="running", source_name="src")
        assert metrics.total_duration_ms == 0.0

    def test_to_dict_contains_required_keys(
        self, sample_run_metrics: PipelineRunMetrics
    ) -> None:
        d = sample_run_metrics.to_dict()
        required_keys = {
            "run_id",
            "source_name",
            "status",
            "started_at",
            "record_counts",
            "validation",
            "timing_ms",
        }
        assert required_keys.issubset(d.keys())

    def test_to_json_is_valid_json(
        self, sample_run_metrics: PipelineRunMetrics
    ) -> None:
        json_str = sample_run_metrics.to_json()
        parsed = json.loads(json_str)
        assert parsed["run_id"] == "test-run-001"

    def test_prometheus_metrics_contains_all_metric_names(
        self, sample_run_metrics: PipelineRunMetrics
    ) -> None:
        prom = sample_run_metrics.to_prometheus_metrics()
        expected_metrics = [
            "jobpulse_rows_extracted",
            "jobpulse_rows_loaded",
            "jobpulse_rows_failed",
            "jobpulse_success_rate_pct",
            "jobpulse_validation_failures",
            "jobpulse_pipeline_status",
            "jobpulse_extract_duration_ms",
            "jobpulse_db_execution_time_ms",
        ]
        for metric in expected_metrics:
            assert metric in prom, f"Missing Prometheus metric: {metric}"

    def test_prometheus_metrics_success_status_is_1(
        self, sample_run_metrics: PipelineRunMetrics
    ) -> None:
        prom = sample_run_metrics.to_prometheus_metrics()
        assert "jobpulse_pipeline_status" in prom
        # Find the line and check value
        for line in prom.split("\n"):
            if line.startswith("jobpulse_pipeline_status{"):
                value = float(line.split(" ")[1])
                assert value == 1.0
                break

    def test_prometheus_metrics_failed_status_is_0(self) -> None:
        metrics = PipelineRunMetrics(
            run_id="fail", source_name="src", status=PipelineStatus.FAILED
        )
        prom = metrics.to_prometheus_metrics()
        for line in prom.split("\n"):
            if line.startswith("jobpulse_pipeline_status{"):
                value = float(line.split(" ")[1])
                assert value == 0.0
                break


# =============================================================================
# Test: StageMetrics
# =============================================================================


class TestStageMetrics:
    """Unit tests for StageMetrics computed properties."""

    def test_rows_dropped_computed_from_in_minus_out_minus_failed(self) -> None:
        stage = StageMetrics(
            stage_name="transform",
            started_at=datetime.now(tz=UTC),
            rows_in=1000,
            rows_out=900,
            rows_failed=50,
        )
        assert stage.rows_dropped == 50  # 1000 - 900 - 50

    def test_rows_dropped_never_negative(self) -> None:
        stage = StageMetrics(
            stage_name="transform",
            started_at=datetime.now(tz=UTC),
            rows_in=100,
            rows_out=100,
            rows_failed=0,
        )
        assert stage.rows_dropped == 0

    def test_success_rate_pct(self) -> None:
        stage = StageMetrics(
            stage_name="load",
            started_at=datetime.now(tz=UTC),
            rows_in=1000,
            rows_out=950,
        )
        assert stage.success_rate_pct == 95.0

    def test_success_rate_pct_is_100_when_no_rows(self) -> None:
        stage = StageMetrics(
            stage_name="extract",
            started_at=datetime.now(tz=UTC),
            rows_in=0,
            rows_out=0,
        )
        assert stage.success_rate_pct == 100.0

    def test_duration_seconds_converts_from_ms(self) -> None:
        stage = StageMetrics(
            stage_name="extract",
            started_at=datetime.now(tz=UTC),
            duration_ms=5000.0,
        )
        assert stage.duration_seconds == 5.0

    def test_to_dict_contains_all_fields(self) -> None:
        stage = StageMetrics(
            stage_name="extract",
            started_at=datetime.now(tz=UTC),
            rows_out=500,
            duration_ms=1234.5,
        )
        d = stage.to_dict()
        assert "stage_name" in d
        assert "success_rate_pct" in d
        assert "rows_dropped" in d
        assert "duration_seconds" in d


# =============================================================================
# Test: PipelineError
# =============================================================================


class TestPipelineError:
    """Unit tests for PipelineError dataclass."""

    def test_error_id_is_unique_per_instance(self) -> None:
        err1 = PipelineError(
            run_id="r1", stage="extract", error_type="IOError", message="m"
        )
        err2 = PipelineError(
            run_id="r1", stage="extract", error_type="IOError", message="m"
        )
        assert err1.error_id != err2.error_id

    def test_to_dict_contains_all_required_fields(self) -> None:
        err = PipelineError(
            run_id="run-001",
            stage="load",
            error_type="SQLAlchemyError",
            message="Connection refused",
            severity=ErrorSeverity.CRITICAL,
        )
        d = err.to_dict()
        required = {
            "error_id",
            "run_id",
            "stage",
            "error_type",
            "message",
            "severity",
            "occurred_at",
        }
        assert required.issubset(d.keys())

    def test_severity_defaults_to_warning(self) -> None:
        err = PipelineError(run_id="r1", stage="s", error_type="E", message="m")
        assert err.severity == ErrorSeverity.WARNING

    def test_occurred_at_is_utc(self) -> None:
        err = PipelineError(run_id="r1", stage="s", error_type="E", message="m")
        assert err.occurred_at.tzinfo is not None


# =============================================================================
# Test: InMemoryMetricStore
# =============================================================================


class TestInMemoryMetricStore:
    """Unit tests for the in-memory metric store."""

    def test_ensure_tables_is_a_no_op(
        self, in_memory_store: InMemoryMetricStore
    ) -> None:
        in_memory_store.ensure_tables()  # Should not raise

    def test_upsert_run_appends_new_run(
        self,
        in_memory_store: InMemoryMetricStore,
        sample_run_metrics: PipelineRunMetrics,
    ) -> None:
        in_memory_store.upsert_run(sample_run_metrics)
        assert len(in_memory_store.runs) == 1

    def test_upsert_run_updates_existing_run_by_run_id(
        self,
        in_memory_store: InMemoryMetricStore,
        sample_run_metrics: PipelineRunMetrics,
    ) -> None:
        in_memory_store.upsert_run(sample_run_metrics)
        # Update status to FAILED
        updated = PipelineRunMetrics(
            run_id=sample_run_metrics.run_id,
            source_name=sample_run_metrics.source_name,
            status=PipelineStatus.FAILED,
        )
        in_memory_store.upsert_run(updated)
        assert len(in_memory_store.runs) == 1
        assert in_memory_store.runs[0].status == PipelineStatus.FAILED

    def test_insert_error_appends_to_errors_list(
        self, in_memory_store: InMemoryMetricStore
    ) -> None:
        err = PipelineError(run_id="r1", stage="load", error_type="E", message="m")
        in_memory_store.insert_error(err)
        assert len(in_memory_store.errors) == 1

    def test_get_runs_summary_filters_by_since(
        self,
        in_memory_store: InMemoryMetricStore,
    ) -> None:
        old_run = PipelineRunMetrics(
            run_id="old",
            source_name="src",
            started_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        new_run = PipelineRunMetrics(
            run_id="new",
            source_name="src",
            started_at=datetime(2024, 6, 30, tzinfo=UTC),
        )
        in_memory_store.upsert_run(old_run)
        in_memory_store.upsert_run(new_run)

        since = datetime(2024, 6, 1, tzinfo=UTC)
        results = in_memory_store.get_runs_summary(since=since)
        assert len(results) == 1

    def test_get_runs_summary_filters_by_source_name(
        self,
        in_memory_store: InMemoryMetricStore,
    ) -> None:
        run_a = PipelineRunMetrics(
            run_id="a",
            source_name="csv",
            started_at=datetime(2024, 6, 30, tzinfo=UTC),
        )
        run_b = PipelineRunMetrics(
            run_id="b",
            source_name="api",
            started_at=datetime(2024, 6, 30, tzinfo=UTC),
        )
        in_memory_store.upsert_run(run_a)
        in_memory_store.upsert_run(run_b)

        results = in_memory_store.get_runs_summary(
            since=datetime(2024, 1, 1, tzinfo=UTC),
            source_name="csv",
        )
        assert len(results) == 1
        assert results[0]["source_name"] == "csv"


# =============================================================================
# Test: PipelineMonitor (context manager)
# =============================================================================


class TestPipelineMonitor:
    """Integration-level unit tests for PipelineMonitor (no real DB)."""

    def test_context_manager_sets_success_status_on_clean_exit(
        self,
        monitor: PipelineMonitor,
        in_memory_store: InMemoryMetricStore,
    ) -> None:
        with monitor:
            monitor.record_extraction(rows_extracted=100)
            monitor.record_transformation(rows_in=100, rows_out=100)
            monitor.record_loading(rows_inserted=100, rows_failed=0)

        assert in_memory_store.runs[-1].status == PipelineStatus.SUCCESS

    def test_context_manager_sets_failed_status_on_exception(
        self,
        monitor: PipelineMonitor,
        in_memory_store: InMemoryMetricStore,
    ) -> None:
        with pytest.raises(ValueError):
            with monitor:
                raise ValueError("ETL exploded")

        assert in_memory_store.runs[-1].status == PipelineStatus.FAILED

    def test_context_manager_records_error_on_exception(
        self,
        monitor: PipelineMonitor,
        in_memory_store: InMemoryMetricStore,
    ) -> None:
        with pytest.raises(RuntimeError):
            with monitor:
                raise RuntimeError("Pipeline crashed")

        assert len(in_memory_store.errors) >= 1
        assert in_memory_store.errors[0].error_type == "RuntimeError"
        assert in_memory_store.errors[0].severity == ErrorSeverity.CRITICAL

    def test_record_extraction_updates_metrics(
        self,
        monitor: PipelineMonitor,
        in_memory_store: InMemoryMetricStore,
    ) -> None:
        with monitor:
            monitor.record_extraction(rows_extracted=5000, duration_ms=1234.5)

        metrics = in_memory_store.runs[-1]
        assert metrics.rows_extracted == 5000
        assert metrics.extract_duration_ms == 1234.5

    def test_record_transformation_updates_metrics(
        self,
        monitor: PipelineMonitor,
        in_memory_store: InMemoryMetricStore,
    ) -> None:
        with monitor:
            monitor.record_extraction(rows_extracted=1000)
            monitor.record_transformation(
                rows_in=1000, rows_out=900, rows_dropped=100, duration_ms=500.0
            )

        metrics = in_memory_store.runs[-1]
        assert metrics.rows_transformed == 900
        assert metrics.transform_duration_ms == 500.0

    def test_record_loading_tracks_failed_rows(
        self,
        monitor: PipelineMonitor,
        in_memory_store: InMemoryMetricStore,
    ) -> None:
        with monitor:
            monitor.record_loading(rows_inserted=900, rows_updated=50, rows_failed=25)

        metrics = in_memory_store.runs[-1]
        assert metrics.rows_loaded == 950  # inserted + updated
        assert metrics.rows_failed == 25

    def test_partial_status_when_some_records_failed(
        self,
        monitor: PipelineMonitor,
        in_memory_store: InMemoryMetricStore,
    ) -> None:
        with monitor:
            monitor.record_loading(rows_inserted=900, rows_failed=10)

        assert in_memory_store.runs[-1].status == PipelineStatus.PARTIAL

    def test_record_validation_failure_increments_counters(
        self,
        monitor: PipelineMonitor,
        in_memory_store: InMemoryMetricStore,
    ) -> None:
        with monitor:
            monitor.record_validation_failure(
                "completeness.job_title", critical=True, records_failed=50
            )
            monitor.record_validation_failure(
                "validity.invalid_url", critical=False, records_failed=5
            )

        metrics = in_memory_store.runs[-1]
        assert metrics.validation_failures == 2
        assert metrics.critical_failures == 1

    def test_record_db_time_accumulates(
        self,
        monitor: PipelineMonitor,
        in_memory_store: InMemoryMetricStore,
    ) -> None:
        with monitor:
            monitor.record_loading(rows_inserted=100, duration_ms=1000.0)
            monitor.record_db_time(duration_ms=500.0)

        metrics = in_memory_store.runs[-1]
        assert metrics.db_execution_time_ms == 1500.0

    def test_record_error_persists_to_store(
        self,
        monitor: PipelineMonitor,
        in_memory_store: InMemoryMetricStore,
    ) -> None:
        with monitor:
            monitor.record_error(
                stage="extract",
                error_type="ConnectionError",
                message="API timeout",
                severity=ErrorSeverity.WARNING,
            )

        assert len(in_memory_store.errors) == 1
        assert in_memory_store.errors[0].stage == "extract"

    def test_monitor_metrics_property_returns_current_snapshot(
        self,
        monitor: PipelineMonitor,
    ) -> None:
        with monitor:
            monitor.record_extraction(rows_extracted=999)
            assert monitor.metrics.rows_extracted == 999

    def test_prometheus_metrics_returns_string(
        self,
        monitor: PipelineMonitor,
    ) -> None:
        with monitor:
            monitor.record_extraction(rows_extracted=100)
        prom = monitor.prometheus_metrics()
        assert isinstance(prom, str)
        assert "jobpulse_rows_extracted" in prom

    def test_monitoring_failure_does_not_crash_pipeline(self, tmp_path: Path) -> None:
        """If the metric store raises, the pipeline should still complete."""
        broken_store = MagicMock(spec=InMemoryMetricStore)
        broken_store.ensure_tables.side_effect = RuntimeError("DB is down")
        broken_store.upsert_run.side_effect = RuntimeError("DB is down")
        broken_store.insert_error.side_effect = RuntimeError("DB is down")

        monitor = PipelineMonitor(
            run_id="test",
            source_name="src",
            metric_store=broken_store,
            log_dir=tmp_path / "logs",
        )
        # Should NOT raise even though the store is broken
        try:
            with monitor:
                pass  # Pipeline code runs normally
        except Exception:
            pytest.fail("PipelineMonitor should not propagate monitoring failures")


# =============================================================================
# Test: JsonStructuredLogger
# =============================================================================


class TestJsonStructuredLogger:
    """Tests for the JSON logging handler."""

    def test_install_creates_log_file(self, tmp_path: Path) -> None:
        logger = JsonStructuredLogger(
            log_dir=tmp_path / "logs",
            run_id="test-run",
            source_name="csv",
        )
        log_path = logger.install()
        assert log_path.parent.exists()
        logger.uninstall()

    def test_uninstall_is_safe_without_install(self, tmp_path: Path) -> None:
        logger = JsonStructuredLogger(
            log_dir=tmp_path / "logs",
            run_id="test-run",
            source_name="csv",
        )
        logger.uninstall()  # Should not raise

    def test_install_is_idempotent(self, tmp_path: Path) -> None:
        logger = JsonStructuredLogger(
            log_dir=tmp_path / "logs",
            run_id="test-run",
            source_name="csv",
        )
        path1 = logger.install()
        path2 = logger.install()  # Second call
        assert path1 == path2
        logger.uninstall()


class TestJsonFormatter:
    """Tests for the JSON log formatter."""

    def test_format_produces_valid_json(self) -> None:
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["message"] == "Test message"
        assert parsed["level"] == "INFO"

    def test_format_includes_timestamp(self) -> None:
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="Error occurred",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "timestamp" in parsed

    def test_format_includes_extra_fields(self) -> None:
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="With extras",
            args=(),
            exc_info=None,
        )
        record.run_id = "run-123"  # type: ignore[attr-defined]
        record.stage = "extract"  # type: ignore[attr-defined]
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed.get("run_id") == "run-123"
        assert parsed.get("stage") == "extract"


# =============================================================================
# Test: HealthChecker components
# =============================================================================


class TestComponentHealth:
    """Tests for ComponentHealth data model."""

    def test_is_healthy_true_when_status_up(self) -> None:
        h = ComponentHealth(name="db", status="UP")
        assert h.is_healthy is True

    def test_is_healthy_false_when_status_warn(self) -> None:
        h = ComponentHealth(name="db", status="WARN")
        assert h.is_healthy is False

    def test_is_healthy_false_when_status_down(self) -> None:
        h = ComponentHealth(name="db", status="DOWN")
        assert h.is_healthy is False

    def test_to_dict_contains_required_keys(self) -> None:
        h = ComponentHealth(name="disk", status="UP", latency_ms=5.2)
        d = h.to_dict()
        assert {"name", "status", "latency_ms", "details", "error"} == set(d.keys())


class TestOverallHealth:
    """Tests for OverallHealth status aggregation logic."""

    def test_healthy_when_all_components_up(self) -> None:
        health = OverallHealth(
            checked_at=datetime.now(tz=UTC),
            components=[
                ComponentHealth(name="db", status="UP"),
                ComponentHealth(name="disk", status="UP"),
            ],
        )
        assert health.status == "HEALTHY"

    def test_degraded_when_one_component_warns(self) -> None:
        health = OverallHealth(
            checked_at=datetime.now(tz=UTC),
            components=[
                ComponentHealth(name="db", status="UP"),
                ComponentHealth(name="memory", status="WARN"),
            ],
        )
        assert health.status == "DEGRADED"

    def test_unhealthy_when_any_component_down(self) -> None:
        health = OverallHealth(
            checked_at=datetime.now(tz=UTC),
            components=[
                ComponentHealth(name="db", status="DOWN"),
                ComponentHealth(name="disk", status="WARN"),
            ],
        )
        assert health.status == "UNHEALTHY"

    def test_to_dict_is_json_serialisable(self) -> None:
        health = OverallHealth(
            checked_at=datetime.now(tz=UTC),
            components=[ComponentHealth(name="db", status="UP")],
        )
        json_str = json.dumps(health.to_dict(), default=str)
        assert "HEALTHY" in json_str


class TestConfigChecker:
    """Tests for ConfigChecker — no external dependencies."""

    def test_returns_up_for_valid_config(self, mock_settings) -> None:
        checker = ConfigChecker(mock_settings)
        result = checker.check()
        assert result.status == "UP"
        assert result.error is None

    def test_returns_down_for_placeholder_password(self, mock_settings) -> None:
        mock_settings.db_password = "your_strong_password_here"
        checker = ConfigChecker(mock_settings)
        result = checker.check()
        assert result.status == "DOWN"
        assert "placeholder" in result.error.lower()

    def test_returns_down_for_invalid_environment(self, mock_settings) -> None:
        mock_settings.environment = "prod"  # Should be "production"
        checker = ConfigChecker(mock_settings)
        result = checker.check()
        assert result.status == "DOWN"

    def test_returns_down_for_invalid_batch_size(self, mock_settings) -> None:
        mock_settings.batch_size = 0
        checker = ConfigChecker(mock_settings)
        result = checker.check()
        assert result.status == "DOWN"

    def test_details_include_environment_and_db_host(self, mock_settings) -> None:
        checker = ConfigChecker(mock_settings)
        result = checker.check()
        assert "environment" in result.details
        assert "db_host" in result.details


class TestMemoryChecker:
    """Tests for MemoryChecker — verifies it runs without crashing."""

    def test_check_returns_component_health(self) -> None:
        checker = MemoryChecker()
        result = checker.check()
        assert isinstance(result, ComponentHealth)
        assert result.name == "memory"
        assert result.status in ("UP", "WARN", "DOWN")

    def test_check_does_not_raise(self) -> None:
        checker = MemoryChecker()
        try:
            checker.check()
        except Exception as e:
            pytest.fail(f"MemoryChecker.check() raised {e}")


# =============================================================================
# Test: DailyReport
# =============================================================================


class TestDailyReport:
    """Tests for the DailyReport computation and output methods."""

    @pytest.fixture()
    def sample_runs(self) -> list[dict]:
        return [
            {
                "run_id": "r1",
                "source_name": "csv",
                "status": "SUCCESS",
                "started_at": datetime(2024, 6, 30, 3, 0, tzinfo=UTC),
                "completed_at": datetime(2024, 6, 30, 3, 10, tzinfo=UTC),
                "total_duration_ms": 600_000.0,
                "rows_extracted": 5000,
                "rows_loaded": 4900,
                "rows_failed": 100,
                "success_rate_pct": 98.0,
                "validation_failures": 1,
                "critical_failures": 0,
            },
            {
                "run_id": "r2",
                "source_name": "csv",
                "status": "FAILED",
                "started_at": datetime(2024, 6, 30, 4, 0, tzinfo=UTC),
                "completed_at": datetime(2024, 6, 30, 4, 5, tzinfo=UTC),
                "total_duration_ms": 300_000.0,
                "rows_extracted": 1000,
                "rows_loaded": 0,
                "rows_failed": 1000,
                "success_rate_pct": 0.0,
                "validation_failures": 5,
                "critical_failures": 2,
            },
        ]

    def test_total_runs_counted_correctly(self, sample_runs) -> None:
        report = DailyReport(
            report_date="2024-06-30",
            source_name="csv",
            runs=sample_runs,
        )
        assert report.total_runs == 2

    def test_successful_and_failed_runs_counted(self, sample_runs) -> None:
        report = DailyReport(
            report_date="2024-06-30", source_name="csv", runs=sample_runs
        )
        assert report.successful_runs == 1
        assert report.failed_runs == 1

    def test_total_rows_extracted_summed(self, sample_runs) -> None:
        report = DailyReport(
            report_date="2024-06-30", source_name="csv", runs=sample_runs
        )
        assert report.total_rows_extracted == 6000

    def test_avg_duration_computed(self, sample_runs) -> None:
        report = DailyReport(
            report_date="2024-06-30", source_name="csv", runs=sample_runs
        )
        assert report.avg_duration_ms == 450_000.0  # (600k + 300k) / 2

    def test_pipeline_success_rate_pct(self, sample_runs) -> None:
        report = DailyReport(
            report_date="2024-06-30", source_name="csv", runs=sample_runs
        )
        assert report.pipeline_success_rate_pct == 50.0

    def test_to_json_is_parseable(self, sample_runs) -> None:
        report = DailyReport(
            report_date="2024-06-30", source_name="csv", runs=sample_runs
        )
        parsed = json.loads(report.to_json())
        assert parsed["report_type"] == "daily"

    def test_as_text_contains_key_sections(self, sample_runs) -> None:
        report = DailyReport(
            report_date="2024-06-30", source_name="csv", runs=sample_runs
        )
        text = report.as_text()
        assert "PIPELINE HEALTH" in text
        assert "RECORD COUNTS" in text
        assert "PERFORMANCE" in text
        assert "DATA QUALITY" in text

    def test_as_text_shows_failed_run_warning(self, sample_runs) -> None:
        report = DailyReport(
            report_date="2024-06-30", source_name="csv", runs=sample_runs
        )
        text = report.as_text()
        assert "FAILED" in text

    def test_as_slack_blocks_returns_list_of_dicts(self, sample_runs) -> None:
        report = DailyReport(
            report_date="2024-06-30", source_name="csv", runs=sample_runs
        )
        blocks = report.as_slack_blocks()
        assert isinstance(blocks, list)
        assert all(isinstance(b, dict) for b in blocks)
        assert any(b.get("type") == "header" for b in blocks)

    def test_empty_runs_produces_zero_metrics(self) -> None:
        report = DailyReport(report_date="2024-06-30", source_name="all", runs=[])
        assert report.total_runs == 0
        assert report.avg_success_rate_pct == 0.0
        assert report.avg_duration_ms == 0.0
