"""jobpulse.models.location — Location ORM model.

Maps to the ``locations`` table in PostgreSQL.
Normalised geographic dimension — eliminates transitive dependency
(state is determined by city, country is determined by state).
"""

from __future__ import annotations

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jobpulse.models.base import Base, TimestampMixin


class Location(TimestampMixin, Base):
    """ORM model for the ``locations`` table.

    Each row represents a unique geographic location identified by
    the combination of city + state_code + country_code.

    Attributes:
        location_id:  Surrogate primary key.
        city:         City name (nullable for country-only records).
        state_code:   ISO 3166-2 subdivision code (e.g., 'NY').
        state_name:   Full state/province name.
        country_code: ISO 3166-1 alpha-2 code (required).
        country_name: Full country name.
        region:       Continent or broad region (e.g., 'North America').
    """

    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint(
            "city", "state_code", "country_code", name="uq_locations_city_state_country"
        ),
        {"comment": "Normalised geographic dimension table."},
    )

    location_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    city: Mapped[str | None] = mapped_column(String(200), nullable=True)
    state_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    state_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    country_name: Mapped[str] = mapped_column(String(100), nullable=False)
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Relationships
    companies: Mapped[list[Company]] = relationship("Company", back_populates="location")  # type: ignore[name-defined]  # noqa: F821
    jobs: Mapped[list[Job]] = relationship("Job", back_populates="location")  # type: ignore[name-defined]  # noqa: F821

    def __repr__(self) -> str:
        return (
            f"<Location id={self.location_id!r} "
            f"{self.city!r}, {self.state_code!r}, {self.country_code!r}>"
        )
