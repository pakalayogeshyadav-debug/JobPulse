"""jobpulse.airflow.operators - Custom Airflow Operators for JobPulse ETL."""

from typing import Any

from airflow.models import BaseOperator

from jobpulse.airflow.config import RAW_DIR, STAGING_DIR
from jobpulse.airflow.utils import (
    load_dataframe_from_staging,
    save_dataframe_to_staging,
)
from jobpulse.config.settings import get_settings
from jobpulse.database.engine import create_db_engine, get_session_factory
from jobpulse.extraction.directory_extractor import DirectoryExtractor
from jobpulse.loading.postgres_loader import PostgresLoader
from jobpulse.transformation.job_listing_transformer import JobListingTransformer
from jobpulse.validation.validator import DataValidator


class JobPulseExtractOperator(BaseOperator):
    """Extracts raw data using DirectoryExtractor and saves to Parquet."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def execute(self, context: Any) -> str:
        self.log.info("Starting Extraction")
        extractor = DirectoryExtractor(
            directory=RAW_DIR, glob_pattern="*.csv", recursive=True
        )
        df_raw = extractor.extract()

        if df_raw.empty:
            self.log.warning("No data extracted.")
            return ""

        run_id = context["run_id"]
        file_path = save_dataframe_to_staging(df_raw, run_id, "extract", STAGING_DIR)

        # Log metrics
        self.log.info(f"Extracted {len(df_raw)} rows.")
        context["ti"].xcom_push(key="rows_extracted", value=len(df_raw))

        return file_path


class JobPulseTransformOperator(BaseOperator):
    """Transforms raw data and saves to Parquet."""

    def __init__(self, upstream_task_id: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.upstream_task_id = upstream_task_id

    def execute(self, context: Any) -> str:
        self.log.info("Starting Transformation")

        ti = context["ti"]
        input_path = ti.xcom_pull(task_ids=self.upstream_task_id)

        if not input_path:
            self.log.warning("No input path received from upstream task. Skipping.")
            return ""

        df_raw = load_dataframe_from_staging(input_path)
        transformer = JobListingTransformer()
        df_clean, transform_report = transformer.run(df_raw)

        if df_clean.empty:
            self.log.warning("All rows filtered out during transformation.")
            return ""

        run_id = context["run_id"]
        file_path = save_dataframe_to_staging(
            df_clean, run_id, "transform", STAGING_DIR
        )

        self.log.info(f"Transformed {len(df_clean)} rows.")
        ti.xcom_push(key="rows_transformed", value=len(df_clean))

        return file_path


class JobPulseValidateOperator(BaseOperator):
    """Validates transformed data and saves to Parquet."""

    def __init__(self, upstream_task_id: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.upstream_task_id = upstream_task_id

    def execute(self, context: Any) -> str:
        self.log.info("Starting Validation")

        ti = context["ti"]
        input_path = ti.xcom_pull(task_ids=self.upstream_task_id)

        if not input_path:
            self.log.warning("No input path received from upstream task. Skipping.")
            return ""

        df_clean = load_dataframe_from_staging(input_path)
        validator = DataValidator()
        df_valid, validation_report = validator.validate(df_clean)

        if df_valid.empty:
            self.log.warning("All rows failed critical validation.")
            return ""

        run_id = context["run_id"]
        file_path = save_dataframe_to_staging(df_valid, run_id, "validate", STAGING_DIR)

        self.log.info(
            f"Validated {len(df_valid)} rows. Invalid: {validation_report.rows_invalid}"
        )
        ti.xcom_push(key="rows_validated", value=validation_report.rows_valid)
        ti.xcom_push(key="validation_failures", value=validation_report.rows_invalid)

        return file_path


class JobPulseLoadOperator(BaseOperator):
    """Loads validated data into PostgreSQL."""

    def __init__(self, upstream_task_id: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.upstream_task_id = upstream_task_id

    def execute(self, context: Any) -> dict:
        self.log.info("Starting Load to DB")

        ti = context["ti"]
        input_path = ti.xcom_pull(task_ids=self.upstream_task_id)

        if not input_path:
            self.log.warning("No input path received from upstream task. Skipping.")
            return {}

        df_valid = load_dataframe_from_staging(input_path)

        engine = create_db_engine(get_settings())
        SessionFactory = get_session_factory(engine)
        loader = PostgresLoader(
            session_factory=SessionFactory,
            chunk_size=1000,
            pipeline_version="airflow_1.0",
        )
        load_report = loader.run(df_valid)

        self.log.info(f"Loaded {load_report.rows_loaded} rows.")
        ti.xcom_push(key="rows_loaded", value=load_report.rows_loaded)

        return {
            "rows_inserted": load_report.rows_inserted,
            "rows_updated": load_report.rows_updated,
        }
