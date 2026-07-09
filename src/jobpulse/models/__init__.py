"""jobpulse.models — SQLAlchemy ORM table definitions.

Fully normalised 3NF schema. All models match the actual PostgreSQL tables.

Usage:
    from jobpulse.models import Base, Job, DataSource, PipelineRun

    # Create all tables
    Base.metadata.create_all(engine)
"""

from jobpulse.models.base import Base, TimestampMixin
from jobpulse.models.company import Company
from jobpulse.models.data_source import DataSource
from jobpulse.models.employment_type import EmploymentType
from jobpulse.models.experience_level import ExperienceLevel
from jobpulse.models.job_listing import Job
from jobpulse.models.job_skill import JobSkill
from jobpulse.models.location import Location
from jobpulse.models.pipeline_run import PipelineRun
from jobpulse.models.salary_range import SalaryRange
from jobpulse.models.skill import Skill

__all__ = [
    "Base",
    "TimestampMixin",
    "Company",
    "DataSource",
    "EmploymentType",
    "ExperienceLevel",
    "Job",
    "JobSkill",
    "Location",
    "PipelineRun",
    "SalaryRange",
    "Skill",
]
