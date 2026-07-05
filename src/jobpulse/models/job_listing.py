"""jobpulse.models.job — Job ORM model (Simplified for Phase 1).

Maps to the ``jobs`` table in PostgreSQL.
Central entity of the schema.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jobpulse.models.base import Base, TimestampMixin


class Job(TimestampMixin, Base):
    """ORM model for the ``jobs`` table (Phase 1 Simplified).

    One row per unique job posting per data source.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint(
            "source_job_id",
            "data_source_id",
            name="uq_jobs_source_job_id_per_source",
        ),
        CheckConstraint("salary_min <= salary_max", name="chk_jobs_salary_range"),
        {"comment": "Central entity. One row per unique job posting per data source."},
    )

    job_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Source provenance
    source_job_id: Mapped[str] = mapped_column(String(500), nullable=False)
    data_source_id: Mapped[int] = mapped_column(
        ForeignKey(
            "data_sources.data_source_id", ondelete="RESTRICT", onupdate="CASCADE"
        ),
        nullable=False,
        index=True,
    )
    pipeline_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_runs.run_id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
        index=True,
    )

    # Core job attributes
    job_title: Mapped[str] = mapped_column(String(500), nullable=False)

    # Denormalized dimensions for Phase 1
    company_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    location_raw: Mapped[str | None] = mapped_column(String(500), nullable=True)

    salary_min: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    salary_max: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)

    # Work arrangement
    is_remote: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    work_arrangement: Mapped[str] = mapped_column(
        String(20), nullable=False, default="UNSPECIFIED"
    )

    # Content
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    posting_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # Lifecycle
    posted_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True
    )

    # Relationships
    data_source: Mapped[DataSource] = relationship("DataSource", back_populates="jobs")  # type: ignore[name-defined]  # noqa: F821
    pipeline_run: Mapped[PipelineRun] = relationship("PipelineRun", back_populates="jobs")  # type: ignore[name-defined]  # noqa: F821

    def __repr__(self) -> str:
        return (
            f"<Job id={self.job_id!r} "
            f"title={self.job_title!r} "
            f"source={self.source_job_id!r}>"
        )
