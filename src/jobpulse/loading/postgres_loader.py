"""jobpulse.loading.postgres_loader — PostgreSQL data loader (3NF Normalised).

Loads validated, transformed DataFrames into PostgreSQL using SQLAlchemy.
Resolves dimension tables (companies, locations, employment_types,
experience_levels) via atomic upserts, then inserts jobs, salary_ranges,
and job_skills into the normalised schema.

Architecture:
    1. Resolve DataSource (atomic upsert with ON CONFLICT)
    2. Create PipelineRun (AFTER DataSource exists)
    3. For each chunk of jobs:
        a. Resolve dimensions (company, location, etc.)
        b. Insert/update jobs via ON CONFLICT DO UPDATE
        c. Insert salary_ranges and job_skills
    4. Finalize PipelineRun with metrics

Idempotency:
    - Data source resolution: ON CONFLICT (source_name) DO UPDATE
    - Job upsert: ON CONFLICT (source_job_id, data_source_id) DO UPDATE
    - Salary/skills: deleted and re-inserted per job (simplest correct approach)
    - Safe to run 100 times against the same dataset
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from jobpulse.loading.base import BaseLoader, DataLoadingError, LoadReport
from jobpulse.logging.logger import get_logger
from jobpulse.models.company import Company
from jobpulse.models.data_source import DataSource
from jobpulse.models.job_listing import Job
from jobpulse.models.location import Location
from jobpulse.models.pipeline_run import PipelineRun
from jobpulse.models.salary_range import SalaryRange
from jobpulse.models.skill import Skill

logger = get_logger(__name__)


def is_transient_db_error(exception: BaseException) -> bool:
    """Determine if a DB error should be retried (e.g. connection drop, deadlock)."""
    return isinstance(exception, OperationalError)


class PostgresLoader(BaseLoader):
    """Loads DataFrames into PostgreSQL tables using SQLAlchemy.

    Designed for the 3NF normalised schema. Resolves dimension tables
    (companies, locations, employment_types, experience_levels) on the fly,
    then upserts jobs and related tables.

    Attributes:
        session_factory: SQLAlchemy sessionmaker bound to the engine.
        pipeline_version: Version string for the ETL pipeline.
        _source_cache:   In-memory cache mapping source_name -> data_source_id.
        _company_cache:  In-memory cache mapping company_name -> company_id.
        _location_cache: In-memory cache mapping (city, state_code, country_code) -> location_id.
        _employment_type_cache: In-memory cache mapping type_code -> employment_type_id.
        _experience_level_cache: In-memory cache mapping level_code -> experience_level_id.
        _skill_cache:    In-memory cache mapping skill_name -> skill_id.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        chunk_size: int = 1000,
        pipeline_version: str = "1.0.0",
    ) -> None:
        """Initialise the PostgreSQL loader.

        Args:
            session_factory:  SQLAlchemy sessionmaker for creating sessions.
            chunk_size:       Number of rows per bulk operation batch.
            pipeline_version: Semantic version of the code loading this data.
        """
        super().__init__(table_name="jobs", chunk_size=chunk_size, strategy="upsert")
        self.session_factory = session_factory
        self.pipeline_version = pipeline_version

        # Dimension caches
        self._source_cache: dict[str, int] = {}
        self._company_cache: dict[str, int] = {}
        self._location_cache: dict[tuple[str | None, str | None, str], int] = {}
        self._employment_type_cache: dict[str, int] = {}
        self._experience_level_cache: dict[str, int] = {}
        self._skill_cache: dict[str, int] = {}

        # Pipeline run state
        self._current_run_id: int | None = None

    def run(self, df: pd.DataFrame) -> LoadReport:
        """Execute the load operation.

        Correct ordering:
            1. Resolve DataSource (atomic upsert)
            2. Create PipelineRun (with real data_source_id)
            3. Execute chunked load
            4. Finalize PipelineRun
        """
        self.extra = {"duplicate_rows": 0, "retry_count": 0}

        if df.empty:
            return super().run(df)

        # Pre-warm dimension caches to reduce per-row lookups
        self._warm_caches()

        # Step 1: Resolve data source BEFORE creating pipeline run
        source_name = "unknown"
        if "source_system" in df.columns:
            source_name = str(
                df["source_system"].dropna().iloc[0]
                if not df["source_system"].dropna().empty
                else "unknown"
            )

        with self.session_factory() as session:
            with session.begin():
                resolved_ds_id = self._resolve_data_source(session, source_name)

        # Step 2: Create PipelineRun with the REAL data_source_id
        with self.session_factory() as session:
            with session.begin():
                run = PipelineRun(
                    data_source_id=resolved_ds_id,
                    status="RUNNING",
                    pipeline_version=self.pipeline_version,
                )
                session.add(run)
                session.flush()  # Get the run_id before commit
                self._current_run_id = run.run_id

        logger.info(
            "Created PipelineRun id=%s for data_source=%r (id=%s)",
            self._current_run_id,
            source_name,
            resolved_ds_id,
        )

        # Step 3: Execute chunked load via BaseLoader
        try:
            report = super().run(df)
        except Exception as e:
            # Mark run as FAILED on critical abort
            self._finalize_run("FAILED", error_message=str(e))
            raise

        # Step 4: Finalize pipeline run
        if report.rows_loaded == 0 and report.rows_failed > 0:
            self._finalize_run("FAILED", report=report)
        elif report.rows_failed > 0:
            self._finalize_run("PARTIAL", report=report)
        else:
            self._finalize_run("SUCCESS", report=report)

        self._current_run_id = None
        return report

    def _warm_caches(self) -> None:
        """Pre-load dimension table IDs into caches to minimise DB lookups."""
        with self.session_factory() as session:
            # Employment types
            for row in session.execute(
                select(
                    text("type_code"),
                    text("employment_type_id"),
                ).select_from(text("employment_types"))
            ):
                self._employment_type_cache[row[0]] = row[1]

            # Experience levels
            for row in session.execute(
                select(
                    text("level_code"),
                    text("experience_level_id"),
                ).select_from(text("experience_levels"))
            ):
                self._experience_level_cache[row[0]] = row[1]

            # Skills
            for row in session.execute(
                select(
                    text("skill_name"),
                    text("skill_id"),
                ).select_from(text("skills"))
            ):
                self._skill_cache[row[0]] = row[1]

            logger.info(
                "Warm caches: %d employment_types, %d experience_levels, %d skills",
                len(self._employment_type_cache),
                len(self._experience_level_cache),
                len(self._skill_cache),
            )

    def _finalize_run(
        self,
        status: str,
        report: LoadReport | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update the PipelineRun record with final status and metrics."""
        if not self._current_run_id:
            return
        with self.session_factory() as session:
            with session.begin():
                final_run = session.get(PipelineRun, self._current_run_id)
                if final_run:
                    final_run.status = status
                    final_run.completed_at = datetime.now(tz=UTC)
                    if report:
                        final_run.rows_loaded = report.rows_loaded
                        final_run.rows_rejected = report.rows_failed
                    if error_message:
                        final_run.error_message = error_message[:4000]

    def _resolve_data_source(self, session: Session, source_name: str) -> int:
        """Resolve data_source_id by name using atomic upsert.

        Uses INSERT ... ON CONFLICT (source_name) DO UPDATE RETURNING data_source_id.
        Never raises UniqueViolation. Never creates duplicates.
        """
        if source_name in self._source_cache:
            return self._source_cache[source_name]

        stmt = (
            pg_insert(DataSource)
            .values(
                source_name=source_name,
                display_name=source_name.replace("_", " ").title(),
                is_active=True,
            )
            .on_conflict_do_update(
                index_elements=["source_name"],
                set_={"updated_at": func.now()},
            )
            .returning(DataSource.data_source_id)
        )
        result = session.execute(stmt)
        ds_id: int = result.scalar_one()

        self._source_cache[source_name] = ds_id
        logger.debug("Resolved data source %r -> id=%d", source_name, ds_id)
        return ds_id

    def _resolve_company(self, session: Session, company_name: str | None) -> int | None:
        """Resolve company_id by name, creating if not found."""
        if not isinstance(company_name, str) or company_name.strip() == "":
            return None

        company_name = company_name.strip()
        if company_name in self._company_cache:
            return self._company_cache[company_name]

        # Check existing
        existing = session.scalar(
            select(Company.company_id).where(Company.company_name == company_name)
        )
        if existing:
            self._company_cache[company_name] = existing
            return existing

        # Insert new
        company = Company(company_name=company_name, is_verified=False)
        session.add(company)
        session.flush()
        self._company_cache[company_name] = company.company_id
        return company.company_id

    def _resolve_location(
        self,
        session: Session,
        city: str | None,
        state_code: str | None,
        country_code: str | None,
    ) -> int | None:
        """Resolve location_id by (city, state_code, country_code)."""
        if not isinstance(country_code, str) or country_code.strip() == "":
            return None

        country_code = country_code.strip().upper()[:2]
        if len(country_code) != 2:
            return None

        city_clean = city.strip() if isinstance(city, str) and city.strip() else None
        state_clean = state_code.strip() if isinstance(state_code, str) and state_code.strip() else None

        cache_key = (city_clean, state_clean, country_code)
        if cache_key in self._location_cache:
            return self._location_cache[cache_key]

        # Check existing
        query = select(Location.location_id).where(
            Location.country_code == country_code
        )
        if city_clean:
            query = query.where(Location.city == city_clean)
        else:
            query = query.where(Location.city.is_(None))
        if state_clean:
            query = query.where(Location.state_code == state_clean)
        else:
            query = query.where(Location.state_code.is_(None))

        existing = session.scalar(query)
        if existing:
            self._location_cache[cache_key] = existing
            return existing

        # Insert new
        loc = Location(
            city=city_clean,
            state_code=state_clean,
            country_code=country_code,
            country_name=country_code,  # Placeholder — enrichment later
        )
        session.add(loc)
        session.flush()
        self._location_cache[cache_key] = loc.location_id
        return loc.location_id

    def _resolve_skill(self, session: Session, skill_name: str) -> int:
        """Resolve skill_id by name, creating if not found."""
        if not isinstance(skill_name, str):
            skill_name = str(skill_name)
        skill_name = skill_name.strip()
        if skill_name in self._skill_cache:
            return self._skill_cache[skill_name]

        existing = session.scalar(
            select(Skill.skill_id).where(Skill.skill_name == skill_name)
        )
        if existing:
            self._skill_cache[skill_name] = existing
            return existing

        skill = Skill(skill_name=skill_name, is_active=True)
        session.add(skill)
        session.flush()
        self._skill_cache[skill_name] = skill.skill_id
        return skill.skill_id

    @retry(
        retry=retry_if_exception_type(OperationalError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _execute_upsert(
        self, session: Session, chunk: list[dict[str, Any]]
    ) -> tuple[int, int, int]:
        """Execute the actual SQLAlchemy upsert for jobs + related tables.

        For each row in the chunk:
            1. Resolve dimension FKs (company, location, employment_type, experience_level)
            2. Upsert into jobs using ON CONFLICT (source_job_id, data_source_id)
            3. Insert salary_ranges if salary data exists
            4. Insert job_skills if extracted_skills exist
        """
        t0 = time.perf_counter()

        # Phase 1: Resolve all dimensions and build clean rows
        job_rows: list[dict[str, Any]] = []
        salary_data: list[dict[str, Any]] = []
        skills_data: list[dict[str, Any]] = []

        for row in chunk:
            source_name = row.get("source_system", "unknown")
            ds_id = self._resolve_data_source(session, source_name)
            company_id = self._resolve_company(session, row.get("company_name"))
            location_id = self._resolve_location(
                session,
                row.get("city"),
                row.get("state_code"),
                row.get("country_code"),
            )

            # Resolve employment type
            et_code = row.get("employment_type_code")
            et_id = self._employment_type_cache.get(et_code) if et_code else None

            # Resolve experience level
            el_code = row.get("experience_level_code")
            el_id = self._experience_level_cache.get(el_code) if el_code else None

            source_job_id = row.get("source_job_id", "")

            job_row = {
                "source_job_id": source_job_id,
                "data_source_id": ds_id,
                "pipeline_run_id": self._current_run_id,
                "job_title": row.get("job_title", "Unknown"),
                "canonical_title": row.get("canonical_title"),
                "company_id": company_id,
                "location_id": location_id,
                "employment_type_id": et_id,
                "experience_level_id": el_id,
                "is_remote": row.get("is_remote"),
                "work_arrangement": row.get("work_arrangement", "UNSPECIFIED"),
                "description": row.get("description"),
                "posting_url": row.get("posting_url"),
                "posted_date": row.get("posted_date"),
                "is_active": row.get("is_active", True),
            }
            job_rows.append(job_row)

            # Collect salary data
            salary_min = row.get("salary_min")
            salary_max = row.get("salary_max")
            if salary_min is not None or salary_max is not None:
                salary_data.append(
                    {
                        "source_job_id": source_job_id,
                        "ds_id": ds_id,
                        "salary_min": salary_min,
                        "salary_max": salary_max,
                        "currency_code": row.get("currency_code", "USD") or "USD",
                        "salary_period": row.get("salary_period", "ANNUAL") or "ANNUAL",
                    }
                )

            # Collect skills data
            skills_raw = row.get("extracted_skills", "")
            if skills_raw and isinstance(skills_raw, str) and skills_raw.strip():
                for skill_name in skills_raw.split("|"):
                    skill_name = skill_name.strip()
                    if skill_name:
                        skills_data.append(
                            {
                                "source_job_id": source_job_id,
                                "ds_id": ds_id,
                                "skill_name": skill_name,
                            }
                        )

        # Flush dimension inserts before the job upsert
        session.flush()

        # Phase 2: Upsert jobs
        if job_rows:
            stmt = pg_insert(Job).values(job_rows)
            mutable_columns = [
                "pipeline_run_id",
                "job_title",
                "canonical_title",
                "company_id",
                "location_id",
                "employment_type_id",
                "experience_level_id",
                "is_remote",
                "work_arrangement",
                "description",
                "posting_url",
                "is_active",
                "updated_at",
            ]
            update_dict = {col: getattr(stmt.excluded, col) for col in mutable_columns}
            upsert_stmt = stmt.on_conflict_do_update(
                index_elements=["source_job_id", "data_source_id"],
                set_=update_dict,
            ).returning(Job.job_id, Job.source_job_id, Job.data_source_id)

            result = session.execute(upsert_stmt)
            job_id_map: dict[tuple[str, int], int] = {}
            for row_result in result:
                job_id_map[(row_result[1], row_result[2])] = row_result[0]

        # Phase 3: Insert salary ranges
        if salary_data and job_id_map:
            salary_rows = []
            for s in salary_data:
                job_id = job_id_map.get((s["source_job_id"], s["ds_id"]))
                if job_id:
                    salary_rows.append(
                        {
                            "job_id": job_id,
                            "salary_min": s["salary_min"],
                            "salary_max": s["salary_max"],
                            "currency_code": s["currency_code"][:3],
                            "salary_period": s["salary_period"],
                            "salary_type": "BASE",
                            "is_estimated": False,
                        }
                    )
            if salary_rows:
                # Delete existing salary ranges for these jobs to avoid duplicates
                job_ids_with_salary = [r["job_id"] for r in salary_rows]
                session.execute(
                    SalaryRange.__table__.delete().where(
                        SalaryRange.job_id.in_(job_ids_with_salary)
                    )
                )
                session.execute(SalaryRange.__table__.insert(), salary_rows)

        # Phase 4: Insert job_skills
        if skills_data and job_id_map:
            from jobpulse.models.job_skill import JobSkill

            skill_rows = []
            seen: set[tuple[int, int]] = set()
            for s in skills_data:
                job_id = job_id_map.get((s["source_job_id"], s["ds_id"]))
                if job_id:
                    skill_id = self._resolve_skill(session, s["skill_name"])
                    if (job_id, skill_id) not in seen:
                        seen.add((job_id, skill_id))
                        skill_rows.append(
                            {
                                "job_id": job_id,
                                "skill_id": skill_id,
                                "is_required": True,
                            }
                        )
            if skill_rows:
                # Delete existing job_skills for these jobs to avoid duplicates
                job_ids_with_skills = list({r["job_id"] for r in skill_rows})
                session.execute(
                    JobSkill.__table__.delete().where(
                        JobSkill.job_id.in_(job_ids_with_skills)
                    )
                )
                session.execute(JobSkill.__table__.insert(), skill_rows)

        elapsed = time.perf_counter() - t0
        rows_processed = len(chunk)
        logger.debug(
            "Upserted %d jobs + %d salary_ranges + %d job_skills in %.3fs",
            rows_processed,
            len(salary_data),
            len(skills_data),
            elapsed,
        )

        return (0, rows_processed, 0)

    def load_chunk(self, records: list[dict[str, Any]]) -> tuple[int, int, int]:
        """Write one chunk of records to PostgreSQL using UPSERT.

        Executes within its own transaction. Will automatically rollback the
        current batch on failure without affecting prior successful batches.
        """
        try:
            with self.session_factory() as session:
                with session.begin():
                    inserted, updated, skipped = self._execute_upsert(session, records)
                    return inserted, updated, skipped

        except OperationalError as e:
            self.extra["retry_count"] += 3
            raise DataLoadingError(
                self.table_name, "Transient database error exhausted retries", cause=e
            )
        except IntegrityError as e:
            raise DataLoadingError(
                self.table_name, f"Integrity constraint violation: {e.orig}", cause=e
            )
        except SQLAlchemyError as e:
            raise DataLoadingError(
                self.table_name, f"SQLAlchemy error during load: {e}", cause=e
            )
        except Exception as e:
            raise DataLoadingError(
                self.table_name, f"Unexpected error during load: {e}", cause=e
            )
