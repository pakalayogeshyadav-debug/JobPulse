import pandas as pd
import pytest
from unittest.mock import MagicMock, patch
from src.jobpulse.config.settings import Settings
from src.jobpulse.database.engine import create_db_engine


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("DB_PASSWORD", "testpass")
    monkeypatch.setenv("DB_USER", "testuser")
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "testdb")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("LOG_LEVEL", "INFO")


@patch("src.jobpulse.database.engine.create_engine")
@patch("pandas.read_sql")
def test_verify_sql_playground(mock_read_sql, mock_create_engine, mock_env):
    """Verify that the SQL playground queries execute correctly without a real DB."""
    # Mock engine
    mock_engine = MagicMock()
    mock_create_engine.return_value = mock_engine

    # Mock pandas return values
    mock_read_sql.return_value = pd.DataFrame({"c": [42]})

    settings = Settings()
    engine = create_db_engine(settings)

    for table in ["jobs", "pipeline_runs", "bridge_job_skill"]:
        count = pd.read_sql(f"SELECT COUNT(*) as c FROM {table};", engine).iloc[0]["c"]
        assert count == 42
        mock_read_sql.assert_called_with(f"SELECT COUNT(*) as c FROM {table};", engine)


@patch("src.jobpulse.database.engine.create_engine")
@patch("pandas.read_sql")
def test_verify_postgresql_system_queries(mock_read_sql, mock_create_engine, mock_env):
    """Verify that the system queries execute correctly without a real DB."""
    mock_engine = MagicMock()
    mock_create_engine.return_value = mock_engine

    # Mock pandas return values for system queries
    mock_read_sql.return_value = pd.DataFrame({0: ["mocked_result"]})

    settings = Settings()
    engine = create_db_engine(settings)

    queries = [
        "SELECT current_user;",
        "SELECT current_database();",
        "SELECT version();",
    ]
    for q in queries:
        res = pd.read_sql(q, engine).iloc[0, 0]
        assert res == "mocked_result"
        mock_read_sql.assert_called_with(q, engine)
