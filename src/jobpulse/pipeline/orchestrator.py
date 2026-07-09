"""jobpulse.pipeline.orchestrator — End-to-End Pipeline Orchestrator.

Manages the execution flow, exception handling, and metric aggregation
for the entire Extract -> Transform -> Load lifecycle.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from jobpulse.config.settings import Settings
from jobpulse.extraction.directory_extractor import DirectoryExtractor
from jobpulse.loading.base import DataLoadingError
from jobpulse.loading.postgres_loader import PostgresLoader
from jobpulse.logging.logger import get_logger
from jobpulse.pipeline.report import ETLReport
from jobpulse.transformation.job_listing_transformer import JobListingTransformer
from jobpulse.validation.history import save_validation_history
from jobpulse.validation.html_report import generate_html_report
from jobpulse.validation.validator import DataValidator
from jobpulse.database.bootstrap import bootstrap_database
from jobpulse.utils.dir_manager import ensure_runtime_directories
from jobpulse.exceptions import PipelineFatalError, DatabaseError, ReportingError

logger = get_logger(__name__)


class PipelineOrchestrator:
    """Coordinates the full ETL execution lifecycle.

    Attributes:
        settings: Pipeline configuration object.
        raw_data_dir: Path to the directory containing raw CSVs.
    """

    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        raw_data_dir: Path | str | None = None,
    ) -> None:
        """Initialise the orchestrator and its component factories.

        Args:
            settings: Configuration settings for DB, Batch size, etc.
            session_factory: SQLAlchemy sessionmaker.
            raw_data_dir: Optional override for the raw data directory.
        """
        self.settings = settings

        # Ensure directories exist
        ensure_runtime_directories(settings)

        # Determine raw data directory
        if raw_data_dir:
            self.raw_data_dir = Path(raw_data_dir)
        else:
            self.raw_data_dir = Path(settings.raw_data_dir)

        # Component instantiation
        self.extractor = DirectoryExtractor(
            directory=self.raw_data_dir,
            glob_pattern="*.csv",
            recursive=True,
            schema_mode="union",
        )
        self.transformer = JobListingTransformer()
        self.validator = DataValidator()
        self.loader = PostgresLoader(
            session_factory=session_factory,
            chunk_size=settings.batch_size,
            pipeline_version="1.0.0",
        )

    def run(self) -> ETLReport:
        """Execute the complete Extract -> Transform -> Load pipeline.

        Returns:
            ETLReport: Aggregated summary of the execution.

        Raises:
            Exception: If Extraction or Transformation stages fail entirely.
        """
        pipeline_start = datetime.now(tz=UTC)
        logger.info("Starting pipeline execution")

        files_processed = 0
        rows_extracted = 0
        transform_report = None
        validation_report = None
        load_report = None
        status = "SUCCESS"
        warnings = []
        reports_generated = False

        try:
            # ---------------------------------------------------------
            # Phase 0: BOOTSTRAP DATABASE
            # ---------------------------------------------------------
            logger.info("--- [STAGE: BOOTSTRAP] ---")
            with self.loader.session_factory.kw["bind"].connect() as conn:
                engine = conn.engine
            bootstrap_database(engine)
            logger.info("Bootstrap completed")

            # ---------------------------------------------------------
            # Phase 1: EXTRACTION
            # ---------------------------------------------------------
            logger.info("--- [STAGE: EXTRACTION] ---")
            t0 = time.perf_counter()
            df_raw = self.extractor.extract()
            t_extract = time.perf_counter() - t0

            # The directory extractor logs file processing count. We approximate it
            # by tracking CSVs matching the pattern.
            files_processed = len(list(self.raw_data_dir.rglob("*.csv")))
            rows_extracted = len(df_raw)
            logger.info(
                "Extraction completed in %.2fs. Extracted %d rows.",
                t_extract,
                rows_extracted,
            )

            if df_raw.empty:
                logger.warning("No data extracted. Aborting subsequent stages.")
                return ETLReport.from_reports(
                    start_time=pipeline_start,
                    end_time=datetime.now(tz=UTC),
                    files_processed=files_processed,
                    rows_extracted=rows_extracted,
                    transform_report=None,
                    validation_report=None,
                    load_report=None,
                    status="SUCCESS",
                    warnings=warnings,
                    reports_generated=reports_generated,
                )
            logger.info("Extraction completed")

            # ---------------------------------------------------------
            # Phase 2: TRANSFORMATION
            # ---------------------------------------------------------
            logger.info("--- [STAGE: TRANSFORMATION] ---")
            t0 = time.perf_counter()
            df_clean, transform_report = self.transformer.run(df_raw)
            t_transform = time.perf_counter() - t0
            logger.info("Transformation completed in %.2fs.", t_transform)

            if df_clean.empty:
                logger.warning(
                    "All records were filtered out during transformation. Aborting validation and load."
                )
                return ETLReport.from_reports(
                    start_time=pipeline_start,
                    end_time=datetime.now(tz=UTC),
                    files_processed=files_processed,
                    rows_extracted=rows_extracted,
                    transform_report=transform_report,
                    validation_report=None,
                    load_report=None,
                    status="SUCCESS",
                    warnings=warnings,
                    reports_generated=reports_generated,
                )
            logger.info("Transformation completed")

            # ---------------------------------------------------------
            # Phase 2.5: VALIDATION
            # ---------------------------------------------------------
            logger.info("--- [STAGE: VALIDATION] ---")
            t0 = time.perf_counter()
            df_valid, validation_report = self.validator.validate(df_clean)
            t_validate = time.perf_counter() - t0
            logger.info("Validation completed in %.2fs.", t_validate)

            if df_valid.empty:
                logger.warning("All records failed critical validation. Aborting load.")
                return ETLReport.from_reports(
                    start_time=pipeline_start,
                    end_time=datetime.now(tz=UTC),
                    files_processed=files_processed,
                    rows_extracted=rows_extracted,
                    transform_report=transform_report,
                    validation_report=validation_report,
                    load_report=None,
                    status="SUCCESS",
                    warnings=warnings,
                    reports_generated=reports_generated,
                )
            logger.info("Validation completed")

            # ---------------------------------------------------------
            # Phase 3: LOADING
            # ---------------------------------------------------------
            logger.info("--- [STAGE: LOADING] ---")
            t0 = time.perf_counter()
            try:
                load_report = self.loader.run(df_valid)

                # Check for partial failures
                if load_report.rows_failed > 0:
                    if load_report.rows_loaded == 0:
                        status = "FAILURE"
                    else:
                        status = "PARTIAL SUCCESS"
            except DataLoadingError as e:
                # Catching total load failures
                logger.error("Loading stage aborted due to critical error: %s", e)
                status = "FAILURE"
                raise

            t_load = time.perf_counter() - t0
            logger.info("Loading completed in %.2fs.", t_load)
            logger.info("Database load completed successfully")

            # ---------------------------------------------------------
            # Phase 4: REPORTING
            # ---------------------------------------------------------
            logger.info("--- [STAGE: REPORTING] ---")
            try:
                run_id = pipeline_start.strftime("%Y%m%d_%H%M%S")
                generate_html_report(
                    validation_report,
                    output_dir=self.settings.report_dir,
                )
                save_validation_history(
                    validation_report,
                    run_id=run_id,
                    output_dir=self.settings.data_dir,
                )
                reports_generated = True
                logger.info("Report generation completed")
            except Exception as e:
                reports_generated = False
                logger.exception("Report generation failed: %s", e)
                warnings.append(f"Report generation failed: {e}")
                if status == "SUCCESS":
                    status = "SUCCESS_WITH_REPORT_WARNING"

        except (PipelineFatalError, DatabaseError) as e:
            logger.exception("Pipeline execution aborted due to unhandled fatal error: %s", e)
            status = "FAILURE"
            raise e
        except Exception as e:
            logger.exception("Pipeline execution aborted due to unhandled error: %s", e)
            status = "FAILURE"
            raise e

        finally:
            pipeline_end = datetime.now(tz=UTC)
            report = ETLReport.from_reports(
                start_time=pipeline_start,
                end_time=pipeline_end,
                files_processed=files_processed,
                rows_extracted=rows_extracted,
                transform_report=transform_report,
                validation_report=validation_report,
                load_report=load_report,
                status=status,  # type: ignore
                warnings=warnings,
                reports_generated=reports_generated,
            )

            if status == "SUCCESS":
                logger.info("Pipeline completed successfully")
            elif status == "SUCCESS_WITH_REPORT_WARNING":
                logger.info("Pipeline completed with warnings")
            else:
                logger.info("Pipeline execution finished with status: %s", status)

            logger.info(report.render_console_summary())

            return report
