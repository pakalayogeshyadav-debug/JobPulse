"""jobpulse.models.salary_range — SalaryRange ORM model.

Maps to the ``salary_ranges`` table in PostgreSQL.
Salary information stored separately from jobs for normalisation
and to support versioning of salary data over time.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, FetchedValue
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jobpulse.models.base import Base, TimestampMixin


class SalaryRange(TimestampMixin, Base):
    """ORM model for the ``salary_ranges`` table.

    One-to-many with jobs (one job can have multiple salary records
    if the posting is refreshed with an updated range over time).

    Attributes:
        salary_id:       Surrogate primary key.
        job_id:          FK → jobs (cascade delete).
        salary_min:      Minimum salary bound (NUMERIC for precision).
        salary_max:      Maximum salary bound.
        currency_code:   ISO 4217 three-letter code (e.g., 'USD').
        salary_period:   Pay period: HOURLY | DAILY | WEEKLY | MONTHLY | ANNUAL.
        salary_type:     Type: BASE | TOTAL_COMP | OTE | UNSPECIFIED.
        is_estimated:    TRUE if inferred, not explicitly stated.
    """

    __tablename__ = "salary_ranges"
    __table_args__ = {"comment": "Salary information for job postings."}

    salary_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.job_id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )

    salary_min: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=14, scale=2), nullable=True
    )
    salary_max: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=14, scale=2), nullable=True
    )
    salary_midpoint: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=14, scale=2), nullable=True, server_default=FetchedValue()
    )

    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    salary_period: Mapped[str] = mapped_column(
        String(20), nullable=False, default="ANNUAL"
    )
    salary_type: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default="BASE"
    )
    is_estimated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Relationships
    job: Mapped[Job] = relationship("Job", back_populates="salary_ranges")  # type: ignore[name-defined]  # noqa: F821

    def __repr__(self) -> str:
        return (
            f"<SalaryRange id={self.salary_id!r} "
            f"job_id={self.job_id!r} "
            f"{self.salary_min!r}–{self.salary_max!r} {self.currency_code!r}>"
        )
