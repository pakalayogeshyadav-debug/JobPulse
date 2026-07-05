"""jobpulse.database.engine — SQLAlchemy engine and session factory creation.

The SQLAlchemy Engine is the entry point to the database. It manages
a connection pool (psycopg2 connections to PostgreSQL) and is the most
expensive object to create — create it ONCE per process.

Connection Pooling:
    SQLAlchemy uses QueuePool by default.
    pool_size + max_overflow = max concurrent connections
    (e.g., 5 + 10 = 15 max connections under load)

Usage:
    >>> from jobpulse.config.settings import get_settings
    >>> from jobpulse.database.engine import create_db_engine, get_session_factory
    >>>
    >>> settings = get_settings()
    >>> engine = create_db_engine(settings)
    >>> SessionFactory = get_session_factory(engine)
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from jobpulse.config.settings import Settings
from jobpulse.logging.logger import get_logger

logger = get_logger(__name__)


def create_db_engine(settings: Settings) -> Engine:
    """Create and return a configured SQLAlchemy Engine.

    The engine uses psycopg2 as the PostgreSQL dialect and configures
    connection pool parameters from Settings.

    Args:
        settings: Validated application settings containing DB credentials
                  and pool configuration.

    Returns:
        Engine: A SQLAlchemy Engine instance with an active connection pool.

    Raises:
        sqlalchemy.exc.OperationalError: If the database is unreachable.

    Example:
        >>> engine = create_db_engine(get_settings())
    """
    logger.info(
        "Creating database engine: %s@%s:%s/%s",
        settings.db_user,
        settings.db_host,
        settings.db_port,
        settings.db_name,
    )

    engine = create_engine(
        url=settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_pre_ping=True,  # Verify connections are alive before use
        pool_recycle=3600,  # Recycle connections after 1 hour
        echo=False,  # Set to True to log all SQL (DEBUG only)
        future=True,  # Use SQLAlchemy 2.x style
    )

    logger.debug("Database engine created successfully.")
    return engine


def get_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create and return a SQLAlchemy session factory bound to the given engine.

    The factory is a callable that produces new Session objects.
    Sessions should be obtained via the ``db_session`` context manager
    (see jobpulse.database.session) to ensure proper commit/rollback.

    Args:
        engine: A configured SQLAlchemy Engine.

    Returns:
        sessionmaker[Session]: A factory for creating database sessions.

    Example:
        >>> SessionFactory = get_session_factory(engine)
        >>> with SessionFactory() as session:
        ...     session.execute(text("SELECT 1"))
    """
    return sessionmaker(
        bind=engine,
        autocommit=False,  # Explicit transaction management
        autoflush=False,  # Manual flush control for performance
        expire_on_commit=False,  # Avoid lazy-loading after commit
    )


def test_connection(engine: Engine) -> bool:
    """Test the database connection by executing a lightweight SQL query.

    Useful for health checks at pipeline startup.

    Args:
        engine: A configured SQLAlchemy Engine.

    Returns:
        bool: True if the connection succeeds, False otherwise.

    Example:
        >>> if not test_connection(engine):
        ...     raise RuntimeError("Database is unreachable.")
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection test: OK")
        return True
    except Exception as exc:
        logger.error("Database connection test FAILED: %s", exc)
        return False
