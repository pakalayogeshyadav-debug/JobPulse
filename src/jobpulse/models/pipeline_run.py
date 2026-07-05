"""jobpulse.models.pipeline_run — PipelineRun ORM model.

Maps to the ``pipeline_runs`` table in PostgreSQL.
Tracks the execution metadata of the ETL pipeline.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jobpulse.models.base import Base


class PipelineRun(Base):
    """ORM model for the ``pipeline_runs`` table.

    Attributes:
        run_id:           Surrogate primary key.
        data_source_id:   FK → data_sources (which source was pulled).
        status:           RUNNING, SUCCESS, FAILED.
        started_at:       Timestamp of execution start.
        completed_at:     Timestamp of execution end.
        pipeline_version: Code version tracking.
    """

    __tablename__ = "pipeline_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('RUNNING', 'SUCCESS', 'FAILED', 'PARTIAL')",
            name="chk_pipeline_runs_status",
        ),
        {"comment": "Audit log of ETL pipeline executions."},
    )

    run_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    data_source_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True
    )  # Soft FK for phase 1
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pipeline_version: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Relationships
    jobs: Mapped[list[Job]] = relationship("Job", back_populates="pipeline_run")  # type: ignore[name-defined]  # noqa: F821

    def __repr__(self) -> str:
        return f"<PipelineRun id={self.run_id!r} status={self.status!r}>"
