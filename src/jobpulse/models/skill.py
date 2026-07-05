"""jobpulse.models.skill — Skill ORM model.

Maps to the ``skills`` table in PostgreSQL.
Master catalog of all technical and soft skills extracted from postings.
"""

from __future__ import annotations

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jobpulse.models.base import Base, TimestampMixin


class Skill(TimestampMixin, Base):
    """ORM model for the ``skills`` table.

    One row per canonical skill. Connected to jobs via the job_skills
    junction table (many-to-many relationship).

    Attributes:
        skill_id:       Surrogate primary key.
        skill_name:     Canonical skill name (e.g., 'Python', 'Apache Spark').
        skill_category: Grouping (e.g., 'Programming Language', 'Cloud Platform').
        aliases:        Pipe-separated aliases for ETL normalisation.
        is_active:      Whether the skill is actively tracked.
    """

    __tablename__ = "skills"
    __table_args__ = {
        "comment": "Master catalog of skills extracted from job postings."
    }

    skill_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    skill_name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    skill_category: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )
    aliases: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    job_skills: Mapped[list[JobSkill]] = relationship("JobSkill", back_populates="skill")  # type: ignore[name-defined]  # noqa: F821

    def __repr__(self) -> str:
        return f"<Skill id={self.skill_id!r} name={self.skill_name!r}>"
