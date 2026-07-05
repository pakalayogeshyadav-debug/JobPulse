"""jobpulse.models.base — SQLAlchemy Declarative Base.

All ORM models inherit from the ``Base`` class defined here.
This allows SQLAlchemy to track all table definitions and enables:
    - Base.metadata.create_all(engine)    — Create all tables
    - Base.metadata.drop_all(engine)      — Drop all tables (dev/test only)
    - Alembic auto-migration generation

Additionally defines a mixin (TimestampMixin) that adds standard
audit columns (created_at, updated_at) to any model.

Usage:
    from jobpulse.models.base import Base, TimestampMixin

    class MyModel(TimestampMixin, Base):
        __tablename__ = "my_table"
        id = mapped_column(Integer, primary_key=True)
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """SQLAlchemy Declarative Base class.

    All ORM models must inherit from this class. SQLAlchemy uses
    the class registry to resolve relationships between models.
    """

    pass


class TimestampMixin:
    """Mixin that adds audit timestamp columns to any ORM model.

    Columns:
        created_at: UTC timestamp when the row was first inserted.
                    Set automatically by the database server.
        updated_at: UTC timestamp of the most recent update.
                    Updated automatically on each UPDATE statement.

    Usage:
        class JobListing(TimestampMixin, Base):
            __tablename__ = "job_listings"
            # created_at and updated_at are included automatically
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="UTC timestamp when the row was first inserted.",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="UTC timestamp of the most recent update.",
    )
