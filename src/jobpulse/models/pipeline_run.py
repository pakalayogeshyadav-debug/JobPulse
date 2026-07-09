"""jobpulse.models.pipeline_run — PipelineRun ORM model.

Maps to the ``pipeline_runs`` table in PostgreSQL.
Tracks the execution metadata of the ETL pipeline.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jobpulse.models.base import Base


class PipelineRun(Base):
    """ORM model for the ``pipeline_runs`` table.

    Attributes:
        run_id:            Surrogate primary key.
        data_source_id:    FK → data_sources (which source was pulled).
        status:            RUNNING, SUCCESS, FAILED, PARTIAL.
        started_at:        Timestamp of execution start.
        completed_at:      Timestamp of execution end.
        rows_extracted:    Row count from extraction stage.
        rows_transformed:  Row count from transformation stage.
        rows_loaded:       Row count from loading stage.
        rows_rejected:     Row count of rejected records.
        duration_seconds:  Total pipeline runtime.
        error_message:     Error description if FAILED.
        error_traceback:   Full traceback if FAILED.
        pipeline_version:  Code version tracking.
    """

    __tablename__ = "pipeline_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('RUNNING', 'SUCCESS', 'FAILED', 'PARTIAL')",
            name="chk_pipeline_runs_status",
        ),
        {"comment": "Audit log of ETL pipeline executions."},
    )

    run_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    data_source_id: Mapped[int] = mapped_column(
        ForeignKey(
            "data_sources.data_source_id", ondelete="RESTRICT", onupdate="CASCADE"
        ),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="RUNNING")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Row-level metrics
    rows_extracted: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rows_transformed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rows_loaded: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rows_rejected: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Duration
    duration_seconds: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    # Error details
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_traceback: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Version tracking
    pipeline_version: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # Audit timestamp — pipeline_runs only has created_at (no updated_at in DB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )

    # Relationships
    data_source: Mapped[DataSource] = relationship("DataSource")  # type: ignore[name-defined]  # noqa: F821
    jobs: Mapped[list[Job]] = relationship("Job", back_populates="pipeline_run")  # type: ignore[name-defined]  # noqa: F821

    def __repr__(self) -> str:
        return f"<PipelineRun id={self.run_id!r} status={self.status!r}>"
