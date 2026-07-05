"""jobpulse.logging — Structured logging sub-package.

This sub-package configures logging for the entire JobPulse application.
All modules obtain their logger via:

    from jobpulse.logging.logger import get_logger
    logger = get_logger(__name__)

Design Decisions:
    - Uses Python's stdlib logging (no external dependency required for basics).
    - Configures both a console handler and a rotating file handler.
    - Log format includes timestamp, level, module name, and message.
    - Log level is driven by settings.log_level (from .env).
    - setup_logging() must be called ONCE at startup (in main.py).
    - Child loggers inherit the root logger's configuration automatically.

Log File Location:
    logs/jobpulse.log  (rotates at 10 MB, keeps 5 backups)
"""
