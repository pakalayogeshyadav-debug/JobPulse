"""jobpulse.models.data_source — DataSource ORM model.

Maps to the ``data_sources`` table in PostgreSQL.
Stores the catalog of all external sources from which job data is ingested.
"""

from __future__ import annotations

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jobpulse.models.base import Base, TimestampMixin


class DataSource(TimestampMixin, Base):
    """ORM model for the ``data_sources`` table.

    Represents a single external source of job posting data
    (e.g., Adzuna API, USAJobs, a Kaggle dataset).

    Attributes:
        data_source_id: Surrogate primary key.
        source_name:    Machine-readable key (e.g., 'adzuna').
        display_name:   Human-readable label for dashboards.
        base_url:       Root URL of the source.
        is_active:      Whether the ETL pipeline pulls from this source.
        notes:          Free-text caveats about this source.
    """

    __tablename__ = "data_sources"
    __table_args__ = {"comment": "Catalog of all external job data sources."}

    data_source_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    jobs: Mapped[list[Job]] = relationship("Job", back_populates="data_source")  # type: ignore[name-defined]  # noqa: F821

    def __repr__(self) -> str:
        return f"<DataSource id={self.data_source_id!r} name={self.source_name!r}>"
