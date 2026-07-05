from datetime import UTC, datetime

from jobpulse.validation.models import (
    CheckResult,
    CheckSeverity,
    CheckStatus,
    ValidationConfig,
    ValidationReport,
    ValidationStage,
)


def test_check_result_instantiation():
    result = CheckResult(
        validation_name="test.rule",
        status=CheckStatus.PASS,
        severity=CheckSeverity.CRITICAL,
        records_checked=100,
        records_failed=0,
        failure_percentage=0.0,
        execution_time_ms=15.5,
    )
    assert result.passed is True
    assert result.is_critical_failure is False


def test_validation_report_instantiation():
    dt = datetime.now(UTC)
    result = CheckResult(
        validation_name="test.rule",
        status=CheckStatus.FAIL,
        severity=CheckSeverity.CRITICAL,
        records_checked=100,
        records_failed=10,
        failure_percentage=10.0,
        execution_time_ms=15.5,
    )
    report = ValidationReport(
        stage=ValidationStage.POST_TRANSFORM,
        source_name="test_source",
        run_id="run_123",
        started_at=dt,
        results=[result],
        total_rows=100,
    )
    assert report.overall_status == CheckStatus.FAIL
    assert report.pipeline_should_halt is True
    assert report.failed_count == 1
    assert report.passed_count == 0


def test_validation_config_instantiation():
    config = ValidationConfig.for_production()
    assert config.missing_values_fail_pct == 20.0

    dev_config = ValidationConfig.for_development()
    assert dev_config.missing_values_fail_pct == 50.0
