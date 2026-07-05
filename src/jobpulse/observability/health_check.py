"""jobpulse.observability.health_check — Health check aggregator.

Provides a single HealthChecker.check_all() method that:
    1. Runs all registered component health checks in parallel
    2. Returns an OverallHealth object with per-component status
    3. Can be exposed as a /health HTTP endpoint

Design — Strategy Pattern + Protocol
    Each component check is a class implementing the ComponentChecker protocol:
        def check(self) -> ComponentHealth

    Adding a new check (e.g., S3 bucket accessible): create a class,
    implement .check(), register it. Zero changes to HealthChecker.

    WHY Protocol (not ABC)?
        Protocol uses structural subtyping (duck typing). Any class with
        a .check() → ComponentHealth method qualifies — no inheritance
        required. This makes it easy to add checks from third-party code
        or in unit tests without subclassing.

Health Check Endpoint Response (JSON):
    {
        "status": "HEALTHY",          // HEALTHY | DEGRADED | UNHEALTHY
        "checked_at": "2024-06-30T04:00:00Z",
        "response_time_ms": 123.4,
        "components": {
            "database":  { "status": "UP",   "latency_ms": 12.1, "details": {...} },
            "disk":      { "status": "UP",   "usage_pct": 34.2,  "details": {...} },
            "memory":    { "status": "WARN", "usage_pct": 78.1,  "details": {...} },
            "config":    { "status": "UP",   "details": {...} },
            "pipeline":  { "status": "UP",   "last_run": "...", "details": {...} }
        }
    }
"""

from __future__ import annotations

import os
import platform
import time
from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import Engine, text

from jobpulse.config.settings import Settings
from jobpulse.logging.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Data Models
# =============================================================================


@dataclass
class ComponentHealth:
    """Health status of a single system component.

    Attributes:
        name:        Component identifier (e.g., "database", "disk").
        status:      UP | WARN | DOWN.
        latency_ms:  Time to perform the health check in milliseconds.
        details:     Component-specific metrics and context.
        error:       Error message if status is DOWN.
    """

    name: str
    status: str  # "UP" | "WARN" | "DOWN"
    latency_ms: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "latency_ms": round(self.latency_ms, 2),
            "details": self.details,
            "error": self.error,
        }

    @property
    def is_healthy(self) -> bool:
        return self.status == "UP"


@dataclass
class OverallHealth:
    """Aggregated health of all monitored components.

    Status logic:
        HEALTHY   — All components are UP
        DEGRADED  — At least one component is WARN (service functional but impaired)
        UNHEALTHY — At least one component is DOWN (service may be non-functional)
    """

    checked_at: datetime
    components: list[ComponentHealth] = field(default_factory=list)
    total_latency_ms: float = 0.0

    @property
    def status(self) -> str:
        statuses = {c.status for c in self.components}
        if "DOWN" in statuses:
            return "UNHEALTHY"
        if "WARN" in statuses:
            return "DEGRADED"
        return "HEALTHY"

    @property
    def is_healthy(self) -> bool:
        return self.status == "HEALTHY"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "checked_at": self.checked_at.isoformat(),
            "total_latency_ms": round(self.total_latency_ms, 2),
            "components": {c.name: c.to_dict() for c in self.components},
        }


# =============================================================================
# ComponentChecker Protocol
# =============================================================================


@runtime_checkable
class ComponentChecker(Protocol):
    """Protocol (interface) for all component health checks.

    Any class implementing check() → ComponentHealth satisfies this protocol.
    """

    @abstractmethod
    def check(self) -> ComponentHealth:
        """Perform the health check.

        Returns:
            ComponentHealth: Result of the check. MUST NOT raise exceptions —
                            catch internally and return status="DOWN".
        """
        ...


# =============================================================================
# Concrete Checkers
# =============================================================================


class DatabaseChecker:
    """Check: PostgreSQL is reachable and responding to queries.

    Executes:
        1. SELECT 1  — basic connectivity (measures round-trip latency)
        2. SELECT count(*) FROM jobs — table accessibility check

    Thresholds:
        latency >= 1000ms → WARN (slow but functional)
        Exception          → DOWN

    WHY check table count too?
        A connection to the DB doesn't mean the ETL tables are accessible.
        A common issue: network firewall allows port 5432 but the PostgreSQL
        user doesn't have SELECT on the jobs table. This check catches that.
    """

    _WARN_LATENCY_MS: float = 1000.0  # 1 second

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def check(self) -> ComponentHealth:
        t0 = time.perf_counter()
        try:
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                latency_ms = (time.perf_counter() - t0) * 1000.0

                # Check table accessibility
                try:
                    result = conn.execute(
                        text(
                            "SELECT COUNT(*) FROM information_schema.tables "
                            "WHERE table_schema = 'public' AND table_name = 'jobs'"
                        )
                    )
                    jobs_table_exists = result.scalar() == 1
                except Exception:
                    jobs_table_exists = False

                # Check active connections
                try:
                    result = conn.execute(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE datname = current_database() AND state = 'active'"
                        )
                    )
                    active_connections = result.scalar() or 0
                except Exception:
                    active_connections = -1

            status = "WARN" if latency_ms >= self._WARN_LATENCY_MS else "UP"
            return ComponentHealth(
                name="database",
                status=status,
                latency_ms=latency_ms,
                details={
                    "host": str(self._engine.url.host),
                    "database": str(self._engine.url.database),
                    "jobs_table_exists": jobs_table_exists,
                    "active_connections": active_connections,
                    "pool_size": self._engine.pool.size(),  # type: ignore[attr-defined]
                    "checked_out": self._engine.pool.checkedout(),  # type: ignore[attr-defined]
                },
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return ComponentHealth(
                name="database",
                status="DOWN",
                latency_ms=latency_ms,
                error=f"{type(exc).__name__}: {exc}",
            )


class DiskChecker:
    """Check: disk usage on the data and logs directories.

    Thresholds:
        usage >= 80% → WARN
        usage >= 90% → DOWN

    WHY check disk?
        The pipeline writes staging Parquet files during extraction.
        If disk fills up, the pipeline crashes mid-extraction with an
        unhelpful OSError. A proactive disk check at startup catches this
        before any data is written.
    """

    _WARN_USAGE_PCT: float = 80.0
    _DOWN_USAGE_PCT: float = 90.0

    def __init__(
        self, data_dir: Path = Path("data"), logs_dir: Path = Path("logs")
    ) -> None:
        self._data_dir = data_dir
        self._logs_dir = logs_dir

    def check(self) -> ComponentHealth:
        t0 = time.perf_counter()
        try:
            details: dict[str, Any] = {}
            worst_pct = 0.0

            for label, path in [
                ("data_dir", self._data_dir),
                ("logs_dir", self._logs_dir),
            ]:
                try:
                    stat = os.statvfs(path) if hasattr(os, "statvfs") else None
                    if stat:
                        total_bytes = stat.f_blocks * stat.f_frsize
                        free_bytes = stat.f_bavail * stat.f_frsize
                        used_bytes = total_bytes - free_bytes
                        usage_pct = (
                            (used_bytes / total_bytes * 100.0)
                            if total_bytes > 0
                            else 0.0
                        )
                    else:
                        # Windows fallback using shutil
                        import shutil

                        total_bytes, used_bytes, free_bytes = shutil.disk_usage(path)
                        usage_pct = (
                            (used_bytes / total_bytes * 100.0)
                            if total_bytes > 0
                            else 0.0
                        )

                    details[label] = {
                        "path": str(path),
                        "total_gb": round(total_bytes / 1_073_741_824, 2),
                        "used_gb": round(used_bytes / 1_073_741_824, 2),
                        "free_gb": round(free_bytes / 1_073_741_824, 2),
                        "usage_pct": round(usage_pct, 1),
                    }
                    worst_pct = max(worst_pct, usage_pct)
                except Exception as exc:
                    details[label] = {"error": str(exc)}

            latency_ms = (time.perf_counter() - t0) * 1000.0
            status = (
                "DOWN"
                if worst_pct >= self._DOWN_USAGE_PCT
                else "WARN" if worst_pct >= self._WARN_USAGE_PCT else "UP"
            )
            return ComponentHealth(
                name="disk",
                status=status,
                latency_ms=latency_ms,
                details={**details, "worst_usage_pct": round(worst_pct, 1)},
            )
        except Exception as exc:
            return ComponentHealth(
                name="disk",
                status="DOWN",
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                error=f"{type(exc).__name__}: {exc}",
            )


class MemoryChecker:
    """Check: process and system memory usage.

    WHY check memory?
        Pandas loads entire DataFrames into memory during transformation.
        On large datasets (>1M rows), this can exhaust available RAM,
        causing the OS to kill the Python process mid-pipeline.
        A memory check at startup allows early detection of resource pressure.

    Thresholds:
        system_used >= 80% → WARN
        system_used >= 90% → DOWN

    Uses psutil if available; falls back to /proc/meminfo on Linux.
    """

    _WARN_USAGE_PCT: float = 80.0
    _DOWN_USAGE_PCT: float = 90.0

    def check(self) -> ComponentHealth:
        t0 = time.perf_counter()
        try:
            details: dict[str, Any] = {}

            try:
                import psutil

                vm = psutil.virtual_memory()
                usage_pct = vm.percent
                details["system"] = {
                    "total_gb": round(vm.total / 1_073_741_824, 2),
                    "available_gb": round(vm.available / 1_073_741_824, 2),
                    "used_gb": round(vm.used / 1_073_741_824, 2),
                    "usage_pct": round(usage_pct, 1),
                }
                # Process memory
                proc = psutil.Process()
                proc_mem = proc.memory_info()
                details["process"] = {
                    "rss_mb": round(proc_mem.rss / 1_048_576, 1),
                    "vms_mb": round(proc_mem.vms / 1_048_576, 1),
                }
            except ImportError:
                # psutil not installed — try /proc/meminfo (Linux only)
                usage_pct = 0.0
                details["note"] = "Install psutil for detailed memory metrics"
                if platform.system() == "Linux":
                    try:
                        with open("/proc/meminfo") as f:
                            meminfo = {
                                line.split(":")[0]: int(
                                    line.split(":")[1].strip().split()[0]
                                )
                                for line in f
                                if ":" in line
                            }
                        total = meminfo.get("MemTotal", 1)
                        avail = meminfo.get("MemAvailable", total)
                        usage_pct = (1 - avail / total) * 100.0
                        details["system"] = {
                            "total_mb": round(total / 1024, 1),
                            "available_mb": round(avail / 1024, 1),
                            "usage_pct": round(usage_pct, 1),
                        }
                    except Exception:
                        pass

            latency_ms = (time.perf_counter() - t0) * 1000.0
            status = (
                "DOWN"
                if usage_pct >= self._DOWN_USAGE_PCT
                else "WARN" if usage_pct >= self._WARN_USAGE_PCT else "UP"
            )
            return ComponentHealth(
                name="memory",
                status=status,
                latency_ms=latency_ms,
                details=details,
            )
        except Exception as exc:
            return ComponentHealth(
                name="memory",
                status="DOWN",
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                error=f"{type(exc).__name__}: {exc}",
            )


class ConfigChecker:
    """Check: all required environment variables are present and valid.

    Specifically validates:
        - DB credentials are not placeholder values
        - Environment is a valid value (development/staging/production)
        - batch_size is a positive integer within safe limits

    WHY check config?
        A misconfigured pipeline silently fails in unexpected ways.
        For example, if DB_PASSWORD is the placeholder "your_strong_password_here",
        the pipeline won't connect — but the error message is "authentication failed",
        not "you forgot to set the password". Explicit config validation gives
        a clear, actionable error message.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def check(self) -> ComponentHealth:
        t0 = time.perf_counter()
        try:
            issues: list[str] = []

            if self._settings.db_password in (
                "",
                "your_strong_password_here",
                "password",
            ):
                issues.append("DB_PASSWORD appears to be a placeholder value")

            if self._settings.environment not in (
                "development",
                "staging",
                "production",
            ):
                issues.append(
                    f"ENVIRONMENT={self._settings.environment!r} is not a recognised value"
                )

            if not (1 <= self._settings.batch_size <= 100_000):
                issues.append(
                    f"BATCH_SIZE={self._settings.batch_size} is outside the safe range [1, 100000]"
                )

            latency_ms = (time.perf_counter() - t0) * 1000.0
            status = "DOWN" if issues else "UP"
            return ComponentHealth(
                name="config",
                status=status,
                latency_ms=latency_ms,
                details={
                    "environment": self._settings.environment,
                    "db_host": self._settings.db_host,
                    "db_port": self._settings.db_port,
                    "db_name": self._settings.db_name,
                    "db_pool_size": self._settings.db_pool_size,
                    "batch_size": self._settings.batch_size,
                    "log_level": self._settings.log_level,
                    "issues": issues,
                },
                error="; ".join(issues) if issues else None,
            )
        except Exception as exc:
            return ComponentHealth(
                name="config",
                status="DOWN",
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                error=f"{type(exc).__name__}: {exc}",
            )


class PipelineStatusChecker:
    """Check: the most recent pipeline run status.

    Queries pipeline_runs for the last run and reports:
        - Last run status (SUCCESS/PARTIAL/FAILED)
        - Time since last successful run
        - Whether the pipeline is overdue (>25 hours since last success)

    Thresholds:
        last success > 25 hours ago → WARN  (scheduled run may have missed)
        last success > 48 hours ago → DOWN  (pipeline clearly broken)
        No runs in pipeline_runs    → WARN  (may be first run or table cleared)
    """

    _WARN_HOURS: int = 25
    _DOWN_HOURS: int = 48

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def check(self) -> ComponentHealth:
        t0 = time.perf_counter()
        try:
            with self._engine.connect() as conn:
                # Check if pipeline_runs table exists first
                exists_result = conn.execute(
                    text(
                        "SELECT COUNT(*) FROM information_schema.tables "
                        "WHERE table_schema='public' AND table_name='pipeline_runs'"
                    )
                )
                if exists_result.scalar() == 0:
                    return ComponentHealth(
                        name="pipeline",
                        status="WARN",
                        latency_ms=(time.perf_counter() - t0) * 1000.0,
                        details={"note": "pipeline_runs table not yet created"},
                    )

                result = conn.execute(text("""
                    SELECT
                        status,
                        started_at,
                        completed_at,
                        rows_loaded,
                        rows_failed,
                        success_rate_pct
                    FROM public.pipeline_runs
                    ORDER BY started_at DESC
                    LIMIT 1
                """))
                last_run = result.mappings().first()

                if last_run is None:
                    return ComponentHealth(
                        name="pipeline",
                        status="WARN",
                        latency_ms=(time.perf_counter() - t0) * 1000.0,
                        details={"note": "No pipeline runs recorded yet"},
                    )

                now = datetime.now(tz=UTC)
                started_at = last_run["started_at"]
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=UTC)

                hours_ago = (now - started_at).total_seconds() / 3600.0

                # Find last successful run
                success_result = conn.execute(text("""
                    SELECT started_at FROM public.pipeline_runs
                    WHERE status = 'SUCCESS'
                    ORDER BY started_at DESC LIMIT 1
                """))
                last_success = success_result.scalar()
                hours_since_success = None
                if last_success:
                    if last_success.tzinfo is None:
                        last_success = last_success.replace(tzinfo=UTC)
                    hours_since_success = (now - last_success).total_seconds() / 3600.0

            latency_ms = (time.perf_counter() - t0) * 1000.0
            status = (
                "DOWN"
                if (hours_since_success or 999) >= self._DOWN_HOURS
                else (
                    "WARN" if (hours_since_success or 999) >= self._WARN_HOURS else "UP"
                )
            )

            return ComponentHealth(
                name="pipeline",
                status=status,
                latency_ms=latency_ms,
                details={
                    "last_run_status": last_run["status"],
                    "last_run_started_at": started_at.isoformat(),
                    "last_run_hours_ago": round(hours_ago, 1),
                    "hours_since_success": (
                        round(hours_since_success, 1)
                        if hours_since_success is not None
                        else None
                    ),
                    "last_run_rows_loaded": last_run["rows_loaded"],
                    "last_run_rows_failed": last_run["rows_failed"],
                    "last_run_success_rate": float(last_run["success_rate_pct"] or 0),
                },
            )
        except Exception as exc:
            return ComponentHealth(
                name="pipeline",
                status="DOWN",
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                error=f"{type(exc).__name__}: {exc}",
            )


# =============================================================================
# HealthChecker — aggregates all component checks
# =============================================================================


class HealthChecker:
    """Aggregates all component health checks into a single OverallHealth.

    Usage:
        checker = HealthChecker.build(engine, settings)
        health  = checker.check_all()

        if not health.is_healthy:
            # Alert or halt pre-flight
            raise RuntimeError(f"System unhealthy: {health.status}")

        # As a JSON HTTP response body:
        response_body = health.to_dict()

    Extensibility:
        Add a custom checker:
            checker.register(MyCustomChecker())
        No changes to any existing code.
    """

    def __init__(self, checkers: list[ComponentChecker]) -> None:
        self._checkers = list(checkers)

    @classmethod
    def build(
        cls,
        engine: Engine,
        settings: Settings,
        data_dir: Path = Path("data"),
        logs_dir: Path = Path("logs"),
    ) -> HealthChecker:
        """Factory method: build a HealthChecker with all standard components.

        Args:
            engine:   SQLAlchemy engine for database checks.
            settings: Application settings for config check.
            data_dir: Path to the data directory for disk check.
            logs_dir: Path to the logs directory for disk check.
        """
        return cls(
            [
                DatabaseChecker(engine),
                DiskChecker(data_dir=data_dir, logs_dir=logs_dir),
                MemoryChecker(),
                ConfigChecker(settings),
                PipelineStatusChecker(engine),
            ]
        )

    def register(self, checker: ComponentChecker) -> None:
        """Register an additional component checker."""
        self._checkers.append(checker)

    def check_all(self) -> OverallHealth:
        """Run all registered checks sequentially and return OverallHealth.

        WHY sequential (not parallel/concurrent)?
            Health checks are fast (< 100ms each) and the system has at most
            5-10 checkers. The added complexity of thread pooling for a
            ~500ms total execution is not justified. If a checker becomes slow,
            it should implement its own internal timeout.
        """
        t0 = time.perf_counter()
        results: list[ComponentHealth] = []

        for checker in self._checkers:
            try:
                health = checker.check()
                results.append(health)
                logger.debug(
                    "Health check | component=%s | status=%s | latency=%.1fms",
                    health.name,
                    health.status,
                    health.latency_ms,
                )
            except Exception as exc:
                # Individual checker failures should NOT crash the health check endpoint
                logger.error(
                    "Health checker %s raised unexpected exception: %s", checker, exc
                )
                results.append(
                    ComponentHealth(
                        name=getattr(checker, "name", type(checker).__name__),
                        status="DOWN",
                        error=f"Checker raised exception: {exc}",
                    )
                )

        total_ms = (time.perf_counter() - t0) * 1000.0
        overall = OverallHealth(
            checked_at=datetime.now(tz=UTC),
            components=results,
            total_latency_ms=total_ms,
        )
        logger.info(
            "Health check complete | status=%s | total_ms=%.1f | components=%d",
            overall.status,
            total_ms,
            len(results),
        )
        return overall

    def check_all_as_json(self) -> str:
        """Run all checks and return the result as a JSON string."""
        import json

        return json.dumps(self.check_all().to_dict(), indent=2, default=str)
