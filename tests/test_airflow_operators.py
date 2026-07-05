from unittest.mock import MagicMock, patch

import pandas as pd
from src.jobpulse.airflow.operators import (
    JobPulseExtractOperator,
    JobPulseLoadOperator,
    JobPulseTransformOperator,
    JobPulseValidateOperator,
)


def test_extract_operator_execute():
    operator = JobPulseExtractOperator(task_id="extract_test")
    context = {"ti": MagicMock(), "run_id": "test_run_123"}

    with patch(
        "src.jobpulse.airflow.operators.DirectoryExtractor"
    ) as mock_extractor_cls:
        mock_extractor = MagicMock()
        df = pd.DataFrame({"dummy": [1, 2]})
        mock_extractor.extract.return_value = df
        mock_extractor_cls.return_value = mock_extractor

        with patch(
            "src.jobpulse.airflow.operators.save_dataframe_to_staging"
        ) as mock_save:
            mock_save.return_value = "path/to/extracted.parquet"
            result = operator.execute(context)

            assert result == "path/to/extracted.parquet"
            mock_save.assert_called_once()
            context["ti"].xcom_push.assert_called_with(key="rows_extracted", value=2)


def test_transform_operator_execute():
    operator = JobPulseTransformOperator(
        task_id="transform_test", upstream_task_id="extract_test"
    )
    context = {"ti": MagicMock(), "run_id": "test_run_123"}
    context["ti"].xcom_pull.return_value = "path/to/extracted.parquet"

    with patch(
        "src.jobpulse.airflow.operators.load_dataframe_from_staging"
    ) as mock_load:
        mock_load.return_value = pd.DataFrame({"title": ["dev"]})

        with patch(
            "src.jobpulse.airflow.operators.JobListingTransformer"
        ) as mock_transformer_cls:
            mock_transformer = MagicMock()
            mock_transformer.run.return_value = (
                pd.DataFrame({"title": ["Developer"]}),
                MagicMock(),
            )
            mock_transformer_cls.return_value = mock_transformer

            with patch(
                "src.jobpulse.airflow.operators.save_dataframe_to_staging"
            ) as mock_save:
                mock_save.return_value = "path/to/transformed.parquet"

                result = operator.execute(context)
                assert result == "path/to/transformed.parquet"


def test_validate_operator_execute():
    operator = JobPulseValidateOperator(
        task_id="validate_test", upstream_task_id="transform_test"
    )
    context = {"ti": MagicMock(), "run_id": "test_run_123"}
    context["ti"].xcom_pull.return_value = "path/to/transformed.parquet"

    with patch(
        "src.jobpulse.airflow.operators.load_dataframe_from_staging"
    ) as mock_load:
        mock_load.return_value = pd.DataFrame({"title": ["dev"]})

        with patch(
            "src.jobpulse.airflow.operators.DataValidator"
        ) as mock_validator_cls:
            mock_validator = MagicMock()
            report = MagicMock(rows_valid=1, rows_invalid=0)
            mock_validator.validate.return_value = (
                pd.DataFrame({"title": ["dev"]}),
                report,
            )
            mock_validator_cls.return_value = mock_validator

            with patch(
                "src.jobpulse.airflow.operators.save_dataframe_to_staging"
            ) as mock_save:
                mock_save.return_value = "path/to/validated.parquet"

                result = operator.execute(context)
                assert result == "path/to/validated.parquet"


def test_load_operator_execute():
    operator = JobPulseLoadOperator(
        task_id="load_test", upstream_task_id="validate_test"
    )
    context = {"ti": MagicMock(), "run_id": "test_run_123"}
    context["ti"].xcom_pull.return_value = "path/to/validated.parquet"

    with patch(
        "src.jobpulse.airflow.operators.load_dataframe_from_staging"
    ) as mock_load:
        mock_load.return_value = pd.DataFrame({"title": ["dev"]})

        with (
            patch("src.jobpulse.airflow.operators.create_db_engine"),
            patch("src.jobpulse.airflow.operators.get_session_factory"),
        ):
            with patch(
                "src.jobpulse.airflow.operators.PostgresLoader"
            ) as mock_loader_cls:
                mock_loader = MagicMock()
                mock_loader.run.return_value = MagicMock(
                    rows_loaded=1, rows_inserted=1, rows_updated=0
                )
                mock_loader_cls.return_value = mock_loader

                result = operator.execute(context)
                assert result == {"rows_inserted": 1, "rows_updated": 0}
