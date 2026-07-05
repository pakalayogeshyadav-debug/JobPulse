from datetime import UTC, datetime
from unittest.mock import MagicMock

from src.jobpulse.config.settings import Settings
from src.jobpulse.observability.health_check import (
    ComponentHealth,
    ConfigChecker,
    DatabaseChecker,
    DiskChecker,
    HealthChecker,
    MemoryChecker,
    OverallHealth,
    PipelineStatusChecker,
)


def test_component_health():
    h = ComponentHealth(name="db", status="UP", latency_ms=10)
    assert h.is_healthy
    assert h.to_dict()["status"] == "UP"


def test_overall_health():
    now = datetime.now(UTC)
    c1 = ComponentHealth(name="1", status="UP")
    c2 = ComponentHealth(name="2", status="WARN")

    o = OverallHealth(checked_at=now, components=[c1])
    assert o.status == "HEALTHY"
    assert o.is_healthy

    o = OverallHealth(checked_at=now, components=[c1, c2])
    assert o.status == "DEGRADED"
    assert not o.is_healthy

    c3 = ComponentHealth(name="3", status="DOWN")
    o = OverallHealth(checked_at=now, components=[c1, c2, c3])
    assert o.status == "UNHEALTHY"


def test_database_checker_up():
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    engine.url.host = "localhost"
    engine.url.database = "jobpulse"
    engine.pool.size.return_value = 10
    engine.pool.checkedout.return_value = 1

    # 1st call is SELECT 1, which just executes
    # 2nd call is table exists -> scalar() returns 1
    # 3rd call is active conns -> scalar() returns 5
    conn.execute.return_value.scalar.side_effect = [1, 5]

    checker = DatabaseChecker(engine)
    h = checker.check()
    assert h.status == "UP"
    assert h.details["jobs_table_exists"] is True
    assert h.details["active_connections"] == 5


def test_database_checker_down():
    engine = MagicMock()
    engine.connect.side_effect = Exception("DB error")

    checker = DatabaseChecker(engine)
    h = checker.check()
    assert h.status == "DOWN"
    assert "DB error" in h.error


def test_disk_checker(tmp_path):
    checker = DiskChecker(data_dir=tmp_path, logs_dir=tmp_path)
    h = checker.check()
    assert h.status in ("UP", "WARN", "DOWN")
    assert "data_dir" in h.details
    assert "logs_dir" in h.details


def test_memory_checker():
    checker = MemoryChecker()
    h = checker.check()
    # Depending on OS / psutil it might be UP or WARN or DOWN, but it shouldn't crash
    assert h.status in ("UP", "WARN", "DOWN")
    assert "memory" == h.name


def test_config_checker_valid():
    settings = MagicMock(spec=Settings)
    settings.db_password = "real_password"
    settings.environment = "production"
    settings.batch_size = 1000
    settings.db_host = "localhost"
    settings.db_port = 5432
    settings.db_name = "test"
    settings.db_pool_size = 5
    settings.log_level = "INFO"

    checker = ConfigChecker(settings)
    h = checker.check()
    assert h.status == "UP"


def test_config_checker_invalid():
    settings = MagicMock(spec=Settings)
    settings.db_password = "your_strong_password_here"
    settings.environment = "invalid"
    settings.batch_size = -1
    settings.db_host = "localhost"
    settings.db_port = 5432
    settings.db_name = "test"
    settings.db_pool_size = 5
    settings.log_level = "INFO"

    checker = ConfigChecker(settings)
    h = checker.check()
    assert h.status == "DOWN"
    assert "placeholder" in h.error
    assert "invalid" in h.error
    assert "range" in h.error


def test_pipeline_status_checker_no_table():
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    conn.execute.return_value.scalar.return_value = 0  # table doesn't exist

    checker = PipelineStatusChecker(engine)
    h = checker.check()
    assert h.status == "WARN"
    assert "not yet created" in h.details["note"]


def test_health_checker_build():
    engine = MagicMock()
    settings = MagicMock(spec=Settings)
    checker = HealthChecker.build(engine, settings)
    assert len(checker._checkers) == 5

    h = checker.check_all()
    assert len(h.components) == 5

    js = checker.check_all_as_json()
    assert "status" in js
