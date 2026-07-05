"""jobpulse.models.company — Company ORM model.

Maps to the ``companies`` table in PostgreSQL.
Employer dimension — stores company metadata once, referenced by many jobs.
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jobpulse.models.base import Base, TimestampMixin


class Company(TimestampMixin, Base):
    """ORM model for the ``companies`` table.

    One row per unique employer/company. Referenced by many job postings.
    Separating company metadata from jobs eliminates the need to store
    'Google | Technology | 10001+' in every Google job row.

    Attributes:
        company_id:   Surrogate primary key.
        company_name: Normalised company name.
        industry:     Industry vertical (e.g., 'Technology').
        company_size: Headcount band (e.g., '1001-5000').
        location_id:  FK to locations table (HQ location).
        website_url:  Official company website.
        linkedin_url: LinkedIn company page URL.
        is_verified:  Whether the record has been manually enriched.
    """

    __tablename__ = "companies"
    __table_args__ = {"comment": "Normalised employer dimension table."}

    company_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company_name: Mapped[str] = mapped_column(String(500), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(200), nullable=True)
    company_size: Mapped[str | None] = mapped_column(String(20), nullable=True)

    location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.location_id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
        index=True,
    )

    website_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Relationships
    location: Mapped[Location | None] = relationship("Location", back_populates="companies")  # type: ignore[name-defined]  # noqa: F821
    jobs: Mapped[list[Job]] = relationship("Job", back_populates="company")  # type: ignore[name-defined]  # noqa: F821

    def __repr__(self) -> str:
        return f"<Company id={self.company_id!r} name={self.company_name!r}>"
