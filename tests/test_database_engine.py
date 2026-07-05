from unittest.mock import MagicMock, patch

import pytest
from src.jobpulse.config.settings import Settings
from src.jobpulse.database.engine import create_db_engine, get_session_factory
from src.jobpulse.database.engine import test_connection as db_test_connection


@pytest.fixture
def test_settings():
    return Settings(
        db_host="localhost",
        db_port=5432,
        db_name="testdb",
        db_user="testuser",
        db_password="testpassword",
        environment="development",
        log_level="DEBUG"
    )

@patch("src.jobpulse.database.engine.create_engine")
def test_create_db_engine(mock_create_engine, test_settings):
    mock_engine = MagicMock()
    mock_create_engine.return_value = mock_engine
    
    engine = create_db_engine(test_settings)
    
    assert engine == mock_engine
    mock_create_engine.assert_called_once()
    kwargs = mock_create_engine.call_args.kwargs
    assert kwargs["url"] == test_settings.database_url
    assert kwargs["pool_size"] == test_settings.db_pool_size
    assert kwargs["max_overflow"] == test_settings.db_max_overflow

def test_get_session_factory():
    mock_engine = MagicMock()
    factory = get_session_factory(mock_engine)
    assert factory.kw["bind"] == mock_engine
    assert factory.kw["autocommit"] == False

def test_test_connection_success():
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    
    result = db_test_connection(mock_engine)
    
    assert result is True
    # Verify execute was called with a text clause
    assert mock_conn.execute.call_count == 1
    call_arg = mock_conn.execute.call_args[0][0]
    assert call_arg.text == "SELECT 1"

def test_test_connection_failure():
    mock_engine = MagicMock()
    mock_engine.connect.side_effect = Exception("DB Error")
    
    result = db_test_connection(mock_engine)
    
    assert result is False
