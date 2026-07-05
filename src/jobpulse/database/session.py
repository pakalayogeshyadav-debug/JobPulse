"""jobpulse.database.session — Session lifecycle context manager.

Provides a safe context manager for database session management.
Handles commit on success, rollback on exception, and guaranteed close.

Why a context manager?
    Without it, developers must remember to commit, rollback, and close
    sessions manually — a common source of connection leaks and data corruption.

    ✅ Good pattern (using this module):
        with db_session(SessionFactory) as session:
            session.add(record)
        # Automatically committed and closed

    ❌ Bad pattern (avoid):
        session = SessionFactory()
        session.add(record)
        session.commit()   # Forgotten if exception occurs above!

Usage:
    >>> from jobpulse.database.session import db_session
    >>> with db_session(SessionFactory) as session:
    ...     session.execute(text("INSERT INTO ..."))
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy.orm import Session, sessionmaker

from jobpulse.logging.logger import get_logger

logger = get_logger(__name__)


@contextmanager
def db_session(
    session_factory: sessionmaker[Session],
) -> Generator[Session, None, None]:
    """Context manager providing a safe database session lifecycle.

    On normal exit:  commits the transaction and closes the session.
    On exception:    rolls back the transaction, closes the session,
                     and re-raises the exception.

    Args:
        session_factory: A SQLAlchemy sessionmaker instance bound to an engine.

    Yields:
        Session: An active SQLAlchemy session for database operations.

    Raises:
        Exception: Re-raises any exception after rolling back the transaction.

    Example:
        >>> with db_session(SessionFactory) as session:
        ...     session.add(JobListing(title="Data Engineer"))
        ...     # Auto-committed on exit
    """
    session: Session = session_factory()
    try:
        yield session
        session.commit()
        logger.debug("Session committed successfully.")
    except Exception as exc:
        session.rollback()
        logger.error("Session rolled back due to exception: %s", exc)
        raise
    finally:
        session.close()
        logger.debug("Session closed.")
