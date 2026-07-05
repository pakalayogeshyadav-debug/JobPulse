"""jobpulse.observability — Pipeline observability and monitoring package.

Public API:
    PipelineMonitor      — Context-manager that tracks a full pipeline run
    HealthChecker        — Aggregates component health status
    ReportGenerator      — Generates daily execution summaries
    JsonStructuredLogger — Emits machine-readable structured JSON logs
    PrometheusExporter   — Formats metrics in Prometheus text exposition format

Usage:
    from jobpulse.observability import PipelineMonitor, HealthChecker

    with PipelineMonitor(run_id="run-001", source_name="csv") as monitor:
        monitor.record_extraction(rows_extracted=5000)
        monitor.record_transformation(rows_in=5000, rows_out=4850)
        monitor.record_loading(rows_inserted=4800, rows_updated=50, rows_failed=0)
        monitor.record_validation_failure("completeness.job_title", critical=True)
"""

from jobpulse.observability.health_check import (
    ComponentHealth,
    HealthChecker,
    OverallHealth,
)
from jobpulse.observability.json_logger import JsonStructuredLogger
from jobpulse.observability.metrics import (
    PipelineError,
    PipelineRunMetrics,
    PipelineStatus,
    StageMetrics,
)
from jobpulse.observability.pipeline_monitor import PipelineMonitor
from jobpulse.observability.report_generator import ReportGenerator

__all__ = [
    "PipelineMonitor",
    "HealthChecker",
    "ComponentHealth",
    "OverallHealth",
    "ReportGenerator",
    "JsonStructuredLogger",
    "PipelineRunMetrics",
    "PipelineError",
    "StageMetrics",
    "PipelineStatus",
]
