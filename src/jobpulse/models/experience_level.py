"""jobpulse.models.experience_level — ORM model for experience_levels."""

from sqlalchemy import Integer, String, DateTime, text
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

from jobpulse.models.base import Base

class ExperienceLevel(Base):
    __tablename__ = "experience_levels"

    experience_level_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    level_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    level_label: Mapped[str] = mapped_column(String(100), nullable=False)
    min_years_experience: Mapped[int | None] = mapped_column(Integer)
    max_years_experience: Mapped[int | None] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
