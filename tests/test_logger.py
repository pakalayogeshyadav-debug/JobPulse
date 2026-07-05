import logging
from pathlib import Path

import pytest

# Important: Need to import the module so we can reset global state
import src.jobpulse.logging.logger as logger_module


@pytest.fixture(autouse=True)
def reset_logging_state():
    # Save original state
    orig_configured = logger_module._logging_configured
    orig_handlers = logging.getLogger().handlers[:]

    # Save 3rd party levels
    sqla_logger = logging.getLogger("sqlalchemy.engine")
    urllib3_logger = logging.getLogger("urllib3")
    requests_logger = logging.getLogger("requests")
    orig_sqla_level = sqla_logger.level
    orig_urllib3_level = urllib3_logger.level
    orig_requests_level = requests_logger.level

    # Reset for test
    logger_module._logging_configured = False
    logging.getLogger().handlers = []
    sqla_logger.setLevel(logging.NOTSET)
    urllib3_logger.setLevel(logging.NOTSET)
    requests_logger.setLevel(logging.NOTSET)

    yield

    # Restore original state
    logger_module._logging_configured = orig_configured
    logging.getLogger().handlers = orig_handlers
    sqla_logger.setLevel(orig_sqla_level)
    urllib3_logger.setLevel(orig_urllib3_level)
    requests_logger.setLevel(orig_requests_level)


def test_setup_logging_invalid_level():
    with pytest.raises(ValueError) as exc:
        logger_module.setup_logging(level="INVALID_LEVEL")
    assert "Invalid log level" in str(exc.value)


def test_setup_logging_basic():
    logger_module.setup_logging(level="DEBUG")
    assert logger_module._logging_configured is True
    root_logger = logging.getLogger()
    assert root_logger.level == logging.DEBUG
    # Should have at least 1 StreamHandler added by us
    assert any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers)

    # 3rd party loggers silenced if level > DEBUG (but here it's DEBUG, so not silenced)
    assert logging.getLogger("sqlalchemy.engine").level == logging.NOTSET  # default


def test_setup_logging_with_file(tmp_path):
    log_file = tmp_path / "logs" / "test.log"
    logger_module.setup_logging(level="INFO", log_file=log_file)

    assert logger_module._logging_configured is True
    root_logger = logging.getLogger()
    assert root_logger.level == logging.INFO

    file_handler = next(
        (
            h
            for h in root_logger.handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
        ),
        None,
    )
    assert file_handler is not None
    assert Path(file_handler.baseFilename) == log_file

    # Check silencing
    assert logging.getLogger("sqlalchemy.engine").level == logging.WARNING
    assert logging.getLogger("urllib3").level == logging.WARNING
    assert logging.getLogger("requests").level == logging.WARNING


def test_setup_logging_idempotent():
    logger_module.setup_logging(level="INFO")
    assert logger_module._logging_configured is True
    root_logger = logging.getLogger()
    handlers_count = len(root_logger.handlers)

    # Call again
    logger_module.setup_logging(level="INFO")
    # Count shouldn't change
    assert len(root_logger.handlers) == handlers_count


def test_get_logger():
    log = logger_module.get_logger("test_module")
    assert log.name == "test_module"
