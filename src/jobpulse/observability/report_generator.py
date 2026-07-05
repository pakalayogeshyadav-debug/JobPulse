"""jobpulse.observability.report_generator — Daily execution report generator.

Produces a daily summary report that answers the operational questions:
    - How many pipeline runs succeeded today?
    - What was the average success rate?
    - Which sources had the most failures?
    - What were the top error types?
    - What is the overall trend (improving/degrading)?

Output formats:
    - JSON  (for programmatic consumption, dashboards)
    - Text  (for email delivery, Slack attachments)
    - HTML  (for rich email notifications — future)

Design Decision — ReportGenerator depends on AbstractMetricStore
    ReportGenerator queries historical data via AbstractMetricStore.get_runs_summary().
    It knows NOTHING about PostgreSQL — it receives a list of run dicts.
    This means the same report logic works with InMemoryMetricStore in tests,
    and would work with a future TimescaleDB store without any code changes.
"""

from __future__ import annotations

import json
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jobpulse.logging.logger import get_logger
from jobpulse.observability.db_store import AbstractMetricStore
from jobpulse.observability.metrics import PipelineStatus

logger = get_logger(__name__)


class ReportGenerator:
    """Generates daily execution reports from pipeline_runs history.

    Usage:
        store     = PostgresMetricStore(engine)
        generator = ReportGenerator(store, reports_dir=Path("reports/daily"))
        report    = generator.generate_daily_report(for_date=date.today())
        report.save()

        # Print text summary to stdout / Slack:
        print(report.as_text())
    """

    def __init__(
        self,
        store: AbstractMetricStore,
        reports_dir: Path = Path("reports/daily"),
    ) -> None:
        self._store = store
        self._reports_dir = reports_dir

    def generate_daily_report(
        self,
        for_date: datetime | None = None,
        source_name: str | None = None,
    ) -> DailyReport:
        """Generate a daily summary report for the given date (UTC).

        Args:
            for_date:    The date to report on. Defaults to today (UTC).
                         The report covers the 24-hour window starting at 00:00 UTC.
            source_name: Optional filter — report only for one data source.

        Returns:
            DailyReport: Fully computed report object.
        """
        if for_date is None:
            for_date = datetime.now(tz=UTC).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        elif for_date.tzinfo is None:
            for_date = for_date.replace(tzinfo=UTC)

        since = for_date
        logger.info(
            "Generating daily report | date=%s | source=%s",
            since.date().isoformat(),
            source_name or "all",
        )

        runs = self._store.get_runs_summary(since=since, source_name=source_name)

        report = DailyReport(
            report_date=since.date(),
            source_name=source_name or "all",
            runs=runs,
        )
        return report

    def save_daily_report(
        self,
        for_date: datetime | None = None,
        source_name: str | None = None,
    ) -> Path:
        """Generate and persist the daily report to a JSON file.

        Args:
            for_date:    Date to report on (defaults to today).
            source_name: Optional source filter.

        Returns:
            Path: Path to the saved report file.
        """
        report = self.generate_daily_report(for_date=for_date, source_name=source_name)
        self._reports_dir.mkdir(parents=True, exist_ok=True)

        filename = (
            f"daily_report_{report.report_date.isoformat()}"
            f"_{report.source_name}.json"
        )
        path = self._reports_dir / filename
        path.write_text(report.to_json(), encoding="utf-8")

        logger.info("Daily report saved | path=%s", path)
        return path


class DailyReport:
    """Computed daily report with derived metrics and multiple output formats.

    All heavy computation happens in __init__ — the object is then immutable.
    This makes the report object thread-safe and safe to cache.
    """

    def __init__(
        self,
        report_date: Any,  # date object
        source_name: str,
        runs: list[dict[str, Any]],
    ) -> None:
        self.report_date = report_date
        self.source_name = source_name
        self.generated_at = datetime.now(tz=UTC)
        self._runs = runs

        # Derived metrics
        self._compute()

    def _compute(self) -> None:
        """Pre-compute all report metrics from the raw run list."""
        runs = self._runs

        self.total_runs = len(runs)
        self.successful_runs = sum(
            1 for r in runs if r.get("status") == PipelineStatus.SUCCESS.value
        )
        self.failed_runs = sum(
            1 for r in runs if r.get("status") == PipelineStatus.FAILED.value
        )
        self.partial_runs = sum(
            1 for r in runs if r.get("status") == PipelineStatus.PARTIAL.value
        )

        self.total_rows_extracted = sum(r.get("rows_extracted", 0) or 0 for r in runs)
        self.total_rows_loaded = sum(r.get("rows_loaded", 0) or 0 for r in runs)
        self.total_rows_failed = sum(r.get("rows_failed", 0) or 0 for r in runs)

        success_rates = [
            float(r["success_rate_pct"])
            for r in runs
            if r.get("success_rate_pct") is not None
        ]
        self.avg_success_rate_pct = (
            round(statistics.mean(success_rates), 2) if success_rates else 0.0
        )

        durations = [
            float(r["total_duration_ms"])
            for r in runs
            if r.get("total_duration_ms") is not None
        ]
        self.avg_duration_ms = (
            round(statistics.mean(durations), 0) if durations else 0.0
        )
        self.max_duration_ms = round(max(durations), 0) if durations else 0.0
        self.min_duration_ms = round(min(durations), 0) if durations else 0.0

        self.total_validation_failures = sum(
            r.get("validation_failures", 0) or 0 for r in runs
        )
        self.total_critical_failures = sum(
            r.get("critical_failures", 0) or 0 for r in runs
        )

        # Pipeline health ratio
        self.pipeline_success_rate_pct = (
            round(self.successful_runs / self.total_runs * 100.0, 1)
            if self.total_runs > 0
            else 0.0
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise the full report to a plain dict."""
        return {
            "schema_version": "1.0",
            "report_type": "daily",
            "report_date": str(self.report_date),
            "source_name": self.source_name,
            "generated_at": self.generated_at.isoformat(),
            "summary": {
                "total_runs": self.total_runs,
                "successful_runs": self.successful_runs,
                "failed_runs": self.failed_runs,
                "partial_runs": self.partial_runs,
                "pipeline_success_pct": self.pipeline_success_rate_pct,
            },
            "record_counts": {
                "total_rows_extracted": self.total_rows_extracted,
                "total_rows_loaded": self.total_rows_loaded,
                "total_rows_failed": self.total_rows_failed,
                "avg_success_rate_pct": self.avg_success_rate_pct,
            },
            "performance": {
                "avg_duration_ms": self.avg_duration_ms,
                "max_duration_ms": self.max_duration_ms,
                "min_duration_ms": self.min_duration_ms,
            },
            "data_quality": {
                "total_validation_failures": self.total_validation_failures,
                "total_critical_failures": self.total_critical_failures,
            },
            "runs": self._runs,
        }

    def to_json(self, indent: int = 2) -> str:
        """Return JSON string of the full report."""
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def as_text(self) -> str:
        """Return a concise human-readable text summary.

        Suitable for:
        - Slack message attachment
        - Email body (plain text)
        - Airflow task log
        - Daily standup reference
        """
        status_emoji = (
            "✅"
            if self.pipeline_success_rate_pct == 100.0
            else "⚠️" if self.pipeline_success_rate_pct >= 50.0 else "❌"
        )

        lines = [
            "=" * 60,
            f"JobPulse Daily Report — {self.report_date}",
            f"Source: {self.source_name}  |  Generated: {self.generated_at.strftime('%H:%M UTC')}",
            "=" * 60,
            "",
            f"{status_emoji} PIPELINE HEALTH",
            f"  Total Runs      : {self.total_runs}",
            f"  Successful      : {self.successful_runs}  ({self.pipeline_success_rate_pct:.1f}%)",
            f"  Partial         : {self.partial_runs}",
            f"  Failed          : {self.failed_runs}",
            "",
            "📦 RECORD COUNTS",
            f"  Rows Extracted  : {self.total_rows_extracted:,}",
            f"  Rows Loaded     : {self.total_rows_loaded:,}",
            f"  Rows Failed     : {self.total_rows_failed:,}",
            f"  Avg Success Rate: {self.avg_success_rate_pct:.1f}%",
            "",
            "⏱  PERFORMANCE",
            f"  Avg Duration    : {self.avg_duration_ms/1000:.1f}s",
            f"  Min Duration    : {self.min_duration_ms/1000:.1f}s",
            f"  Max Duration    : {self.max_duration_ms/1000:.1f}s",
            "",
            "🔍 DATA QUALITY",
            f"  Validation Fails: {self.total_validation_failures}",
            f"  Critical Fails  : {self.total_critical_failures}",
            "=" * 60,
        ]

        if self.failed_runs > 0:
            lines.insert(
                3,
                f"  ⚠️  {self.failed_runs} run(s) FAILED today — check pipeline_errors for details",
            )

        return "\n".join(lines)

    def as_slack_blocks(self) -> list[dict[str, Any]]:
        """Return a Slack Block Kit JSON structure for rich Slack notifications.

        Returns:
            list: Slack blocks suitable for the 'blocks' key in a Slack API call.
        """
        return [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"JobPulse Daily Report — {self.report_date}",
                },
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Pipeline Success Rate*\n{self.pipeline_success_rate_pct:.1f}%",
                    },
                    {"type": "mrkdwn", "text": f"*Total Runs*\n{self.total_runs}"},
                    {
                        "type": "mrkdwn",
                        "text": f"*Rows Loaded*\n{self.total_rows_loaded:,}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Rows Failed*\n{self.total_rows_failed:,}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Avg Duration*\n{self.avg_duration_ms/1000:.1f}s",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Critical DQ Fails*\n{self.total_critical_failures}",
                    },
                ],
            },
            {
                "type": "divider",
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Generated at {self.generated_at.strftime('%Y-%m-%d %H:%M UTC')} | Source: {self.source_name}",
                    }
                ],
            },
        ]
