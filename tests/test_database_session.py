from unittest.mock import MagicMock

import pytest
from src.jobpulse.database.session import db_session


def test_db_session_success():
    mock_session = MagicMock()
    mock_factory = MagicMock(return_value=mock_session)

    with db_session(mock_factory) as session:
        assert session == mock_session

    mock_session.commit.assert_called_once()
    mock_session.rollback.assert_not_called()
    mock_session.close.assert_called_once()


def test_db_session_failure():
    mock_session = MagicMock()
    mock_factory = MagicMock(return_value=mock_session)

    with pytest.raises(ValueError):
        with db_session(mock_factory) as session:
            assert session == mock_session
            raise ValueError("Test Error")

    mock_session.commit.assert_not_called()
    mock_session.rollback.assert_called_once()
    mock_session.close.assert_called_once()
