"""jobpulse.models.job_skill — JobSkill ORM model (junction table).

Maps to the ``job_skills`` table in PostgreSQL.
Resolves the many-to-many relationship between jobs and skills.
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint, DateTime, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime

from jobpulse.models.base import Base


class JobSkill(Base):
    """ORM model for the ``job_skills`` junction table.

    Resolves the many-to-many relationship between Job and Skill.
    Includes relationship-level attributes (is_required, proficiency_level)
    that describe the specific job–skill pair, not either entity alone.

    Attributes:
        job_skill_id:      Surrogate primary key.
        job_id:            FK → jobs (cascade delete).
        skill_id:          FK → skills (cascade delete).
        is_required:       TRUE = required, FALSE = preferred/nice-to-have.
        proficiency_level: Expected proficiency: BEGINNER | INTERMEDIATE | ADVANCED | EXPERT.
        extracted_text:    Raw text that matched this skill (for NLP training).
    """

    __tablename__ = "job_skills"
    __table_args__ = (
        UniqueConstraint("job_id", "skill_id", name="uq_job_skills_job_skill"),
        {
            "comment": "Junction table: many-to-many relationship between jobs and skills."
        },
    )

    job_skill_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.job_id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    skill_id: Mapped[int] = mapped_column(
        ForeignKey("skills.skill_id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )

    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    proficiency_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )

    # Relationships
    job: Mapped[Job] = relationship("Job", back_populates="job_skills")  # type: ignore[name-defined]  # noqa: F821
    skill: Mapped[Skill] = relationship("Skill", back_populates="job_skills")  # type: ignore[name-defined]  # noqa: F821

    def __repr__(self) -> str:
        return (
            f"<JobSkill job_id={self.job_id!r} "
            f"skill_id={self.skill_id!r} "
            f"required={self.is_required!r}>"
        )
