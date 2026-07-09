"""jobpulse.models.employment_type — ORM model for employment_types."""

from sqlalchemy import Integer, String, DateTime, text
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

from jobpulse.models.base import Base

class EmploymentType(Base):
    __tablename__ = "employment_types"

    employment_type_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    type_label: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
