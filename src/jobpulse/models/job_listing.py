"""jobpulse.models.job_listing — Job ORM model (3NF Normalised).

Maps to the ``jobs`` table in PostgreSQL.
Central entity of the schema — fully normalised with FK references
to dimension tables (companies, locations, employment_types, experience_levels).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jobpulse.models.base import Base, TimestampMixin


class Job(TimestampMixin, Base):
    """ORM model for the ``jobs`` table (3NF Normalised).

    One row per unique job posting per data source.
    All dimension attributes (company, location, employment type,
    experience level) are resolved to FK references during loading.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint(
            "source_job_id",
            "data_source_id",
            name="uq_jobs_source_job_id_per_source",
        ),
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
    canonical_title: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # FK references to dimension tables
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.company_id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
        index=True,
    )
    location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.location_id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
        index=True,
    )
    employment_type_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "employment_types.employment_type_id",
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        nullable=True,
        index=True,
    )
    experience_level_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "experience_levels.experience_level_id",
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        nullable=True,
        index=True,
    )

    # Work arrangement
    is_remote: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    work_arrangement: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default="UNSPECIFIED"
    )

    # Content
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    posting_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # Lifecycle
    posted_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True
    )
    closed_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Relationships
    data_source: Mapped[DataSource] = relationship("DataSource", back_populates="jobs")  # type: ignore[name-defined]  # noqa: F821
    pipeline_run: Mapped[PipelineRun] = relationship("PipelineRun", back_populates="jobs")  # type: ignore[name-defined]  # noqa: F821
    company: Mapped[Company | None] = relationship("Company", back_populates="jobs")  # type: ignore[name-defined]  # noqa: F821
    location: Mapped[Location | None] = relationship("Location", back_populates="jobs")  # type: ignore[name-defined]  # noqa: F821
    salary_ranges: Mapped[list[SalaryRange]] = relationship("SalaryRange", back_populates="job", cascade="all, delete-orphan")  # type: ignore[name-defined]  # noqa: F821
    job_skills: Mapped[list[JobSkill]] = relationship("JobSkill", back_populates="job", cascade="all, delete-orphan")  # type: ignore[name-defined]  # noqa: F821

    def __repr__(self) -> str:
        return (
            f"<Job id={self.job_id!r} "
            f"title={self.job_title!r} "
            f"source={self.source_job_id!r}>"
        )
