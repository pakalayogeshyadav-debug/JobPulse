"""jobpulse.loading.postgres_loader — PostgreSQL data loader.

Loads validated, transformed DataFrames into PostgreSQL using SQLAlchemy.
Implements the UPSERT loading strategy with dynamic data source resolution,
tenacity retries for transient errors, and robust pipeline run tracking.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sqlalchemy import select
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
from jobpulse.models.data_source import DataSource
from jobpulse.models.job_listing import Job
from jobpulse.models.pipeline_run import PipelineRun

logger = get_logger(__name__)


def is_transient_db_error(exception: BaseException) -> bool:
    """Determine if a DB error should be retried (e.g. connection drop, deadlock)."""
    return isinstance(exception, OperationalError)


class PostgresLoader(BaseLoader):
    """Loads DataFrames into PostgreSQL tables using SQLAlchemy.

    Attributes:
        session_factory: SQLAlchemy sessionmaker bound to the engine.
        pipeline_version: Version string for the ETL pipeline.
        _source_cache:   In-memory cache mapping source_name -> data_source_id.
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

        # Cache for dynamic data_source resolution
        self._source_cache: dict[str, int] = {}

        # State for current pipeline run
        self._current_run_id: int | None = None

    def run(self, df: pd.DataFrame) -> LoadReport:
        """Execute the load operation.

        Wraps the base loader's run algorithm with pipeline_run lifecycle
        management (create RUNNING run, transition to SUCCESS/FAILED).
        """
        self.extra = {"duplicate_rows": 0, "retry_count": 0}

        if df.empty:
            # Fall back to base class for empty validation
            return super().run(df)

        with self.session_factory() as session:
            # 1. Prepare pipeline run
            run = PipelineRun(
                data_source_id=1,  # Placeholder, will update later if multiple sources
                status="RUNNING",
                pipeline_version=self.pipeline_version,
            )
            session.add(run)
            session.commit()
            self._current_run_id = run.run_id

            # Resolve data source dynamically based on the first record (or distinct)
            if "source_system" in df.columns:
                primary_source = (
                    df["source_system"].dropna().iloc[0]
                    if not df["source_system"].empty
                    else "unknown"
                )
                resolved_id = self._resolve_data_source(session, str(primary_source))

                # Update pipeline run's main source
                run.data_source_id = resolved_id
                session.commit()

        # 2. Execute chunked load via BaseLoader
        try:
            report = super().run(df)
        except Exception as e:
            # Mark run as FAILED on critical abort
            with self.session_factory() as session:
                if self._current_run_id:
                    run_to_fail = session.get(PipelineRun, self._current_run_id)
                    if run_to_fail:
                        run_to_fail.status = "FAILED"
                        run_to_fail.completed_at = datetime.now(tz=UTC)
                        session.commit()
            raise e

        # 3. Finalize pipeline run
        with self.session_factory() as session:
            final_run = session.get(PipelineRun, self._current_run_id)
            if final_run:
                # If everything failed but didn't crash, mark as failed
                if report.rows_loaded == 0 and report.rows_failed > 0:
                    final_run.status = "FAILED"
                elif report.rows_failed > 0:
                    final_run.status = "PARTIAL"
                else:
                    final_run.status = "SUCCESS"

                final_run.completed_at = report.completed_at
                session.commit()

        self._current_run_id = None
        return report

    def _resolve_data_source(self, session: Session, source_name: str) -> int:
        """Look up data_source_id by name, creating it if it doesn't exist."""
        if source_name in self._source_cache:
            return self._source_cache[source_name]

        source = session.scalar(
            select(DataSource).where(DataSource.source_name == source_name)
        )
        if not source:
            source = DataSource(
                source_name=source_name,
                display_name=source_name.title(),
                is_active=True,
            )
            session.add(source)
            session.commit()

        self._source_cache[source_name] = source.data_source_id
        return source.data_source_id

    @retry(
        retry=retry_if_exception_type(OperationalError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _execute_upsert(
        self, session: Session, chunk: list[dict[str, Any]]
    ) -> tuple[int, int, int]:
        """Executes the actual SQLAlchemy ON CONFLICT DO UPDATE inside the session.
        This is separated to allow tenacity @retry on OperationalErrors.
        """
        # Ensure data_source_id is injected and unwanted columns are stripped
        clean_chunk = []
        for row in chunk:
            source_name = row.get("source_system", "unknown")
            ds_id = self._resolve_data_source(session, source_name)

            clean_row = {
                "source_job_id": row.get("source_job_id"),
                "data_source_id": ds_id,
                "pipeline_run_id": self._current_run_id,
                "job_title": row.get("job_title"),
                "company_name": row.get("company_name"),
                "location_raw": row.get("location_raw"),
                "salary_min": row.get("salary_min"),
                "salary_max": row.get("salary_max"),
                "salary_currency": row.get("currency_code"),
                "is_remote": row.get("is_remote"),
                "work_arrangement": row.get("work_arrangement", "UNSPECIFIED"),
                "description": row.get("description"),
                "posting_url": row.get("posting_url"),
                "posted_date": row.get("posted_date"),
                "is_active": row.get("is_active", True),
            }
            clean_chunk.append(clean_row)

        # Build PostgreSQL INSERT statement
        stmt = pg_insert(Job).values(clean_chunk)

        # Identify columns that should be updated on conflict
        mutable_columns = [
            "pipeline_run_id",
            "job_title",
            "company_name",
            "location_raw",
            "salary_min",
            "salary_max",
            "salary_currency",
            "is_remote",
            "work_arrangement",
            "description",
            "posting_url",
            "is_active",
            "updated_at",
        ]

        update_dict = {col: getattr(stmt.excluded, col) for col in mutable_columns}

        # ON CONFLICT DO UPDATE
        upsert_stmt = stmt.on_conflict_do_update(
            index_elements=["source_job_id", "data_source_id"], set_=update_dict
        )

        # Execute the UPSERT
        # In SQLAlchemy 2.0 with psycopg2/psycopg3, this uses execute_values or batching under the hood
        result = session.execute(upsert_stmt)

        # Since INSERT ... ON CONFLICT DO UPDATE doesn't trivially return the counts of
        # specifically inserted vs updated rows through standard rowcount (it varies by driver),
        # we will approximate. If a row was passed in, it was either inserted or updated.
        # Strict exact counting would require RETURNING xmax which adds latency.
        # For this requirement, we treat all as upserted (updated).
        # We can simulate skipping for completely identical rows if we added WHERE clauses to the DO UPDATE,
        # but standard DO UPDATE touches all.
        rows_processed = len(chunk)
        return (0, rows_processed, 0)

    def load_chunk(self, records: list[dict[str, Any]]) -> tuple[int, int, int]:
        """Write one chunk of records to PostgreSQL using UPSERT.

        Executes within its own transaction. Will automatically rollback the
        current batch on failure without affecting prior successful batches.
        """
        try:
            with self.session_factory() as session:
                with session.begin():
                    # The transaction is automatically committed on successful exit of begin(),
                    # and automatically rolled back if an exception is raised.
                    inserted, updated, skipped = self._execute_upsert(session, records)
                    return inserted, updated, skipped

        except OperationalError as e:
            # This happens if tenacity exhausted all retries
            self.extra["retry_count"] += 3
            raise DataLoadingError(
                self.table_name, "Transient database error exhausted retries", cause=e
            )
        except IntegrityError as e:
            # Immediate failure, constraint violation
            raise DataLoadingError(
                self.table_name, "Integrity constraint violation", cause=e
            )
        except SQLAlchemyError as e:
            raise DataLoadingError(
                self.table_name, "SQLAlchemy error during load", cause=e
            )
        except Exception as e:
            raise DataLoadingError(
                self.table_name, "Unexpected error during load", cause=e
            )
