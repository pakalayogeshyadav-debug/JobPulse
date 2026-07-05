import pandas as pd
from src.jobpulse.validation.base_check import BaseCheck
from src.jobpulse.validation.models import CheckSeverity, CheckStatus, ValidationConfig


class MockCheck(BaseCheck):
    check_name = "mock.check"
    severity = CheckSeverity.CRITICAL

    def _run(self, df):
        if df.empty:
            return 0, 0, []

        failed_indices = df[df["val"] < 0].index.tolist()
        return len(df), len(failed_indices), failed_indices


def test_base_check_run_success():
    config = ValidationConfig()
    check = MockCheck(config)
    df = pd.DataFrame({"val": [1, 2, 3]})

    result = check.run(df)
    assert result.status == CheckStatus.PASS
    assert result.records_checked == 3
    assert result.records_failed == 0


def test_base_check_run_fail():
    config = ValidationConfig()
    check = MockCheck(config)
    df = pd.DataFrame({"val": [1, -2, -3]})

    result = check.run(df)
    assert (
        result.status == CheckStatus.PASS
    )  # Defaults to pass unless thresholds override

    # Let's mock the fail threshold
    check._fail_threshold_pct = lambda: 50.0
    result2 = check.run(df)
    assert result2.status == CheckStatus.FAIL
    assert result2.records_failed == 2


class GuardedCheck(BaseCheck):
    check_name = "guarded.check"
    severity = CheckSeverity.WARNING
    column_required = "mandatory_col"

    def _run(self, df):
        return len(df), 0, []


def test_base_check_column_guard_skips():
    config = ValidationConfig()
    check = GuardedCheck(config)
    df = pd.DataFrame({"other_col": [1]})

    result = check.run(df)
    assert result.status == CheckStatus.SKIP
    assert result.records_checked == 0


class ErrorCheck(BaseCheck):
    check_name = "error.check"
    severity = CheckSeverity.WARNING

    def _run(self, df):
        raise ValueError("Boom")


def test_base_check_handles_exceptions():
    config = ValidationConfig()
    check = ErrorCheck(config)
    df = pd.DataFrame({"val": [1]})

    result = check.run(df)
    assert result.status == CheckStatus.ERROR
    assert "ValueError: Boom" in result.details
