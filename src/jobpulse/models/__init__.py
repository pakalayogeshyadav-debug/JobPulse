"""jobpulse.models — SQLAlchemy ORM table definitions.

Simplified for Phase 1 Sprint. Contains only the core tables required to get the ETL pipeline working.

Usage:
    from jobpulse.models import Base, Job, DataSource, PipelineRun

    # Create all tables
    Base.metadata.create_all(engine)
"""

from jobpulse.models.base import Base, TimestampMixin
from jobpulse.models.data_source import DataSource
from jobpulse.models.job_listing import Job
from jobpulse.models.pipeline_run import PipelineRun

__all__ = [
    "Base",
    "TimestampMixin",
    "DataSource",
    "PipelineRun",
    "Job",
]
