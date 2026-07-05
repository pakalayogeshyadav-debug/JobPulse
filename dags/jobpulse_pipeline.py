"""
jobpulse_pipeline.py - The main production DAG for JobPulse ETL.
"""
from datetime import datetime

from airflow import DAG
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import PythonOperator

# Using SQLExecuteQueryOperator for DB tasks (PostgresOperator was deprecated)
from airflow.providers.common.sql.operators.sql import SQLExecuteQueryOperator
from airflow.utils.task_group import TaskGroup

from jobpulse.airflow.callbacks import on_failure_callback, on_success_callback
from jobpulse.airflow.config import DEFAULT_ARGS, DEFAULT_POOL
from jobpulse.airflow.operators import (
    JobPulseExtractOperator,
    JobPulseLoadOperator,
    JobPulseTransformOperator,
    JobPulseValidateOperator,
)


def _generate_daily_report(**context):
    from jobpulse.config.settings import get_settings
    from jobpulse.database.engine import create_db_engine
    from jobpulse.observability.db_store import PostgresMetricStore
    from jobpulse.observability.report_generator import ReportGenerator
    
    settings = get_settings()
    engine = create_db_engine(settings)
    store = PostgresMetricStore(engine)
    generator = ReportGenerator(store)
    
    report = generator.generate_daily_report()
    generator.save_daily_report()
    print(report.as_text())

with DAG(
    dag_id="jobpulse_daily_etl",
    default_args=DEFAULT_ARGS,
    description="Main JobPulse ETL Pipeline",
    schedule="@daily",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["jobpulse", "production", "etl"],
    on_failure_callback=on_failure_callback,
    on_success_callback=on_success_callback,
) as dag:

    start = EmptyOperator(task_id="start")
    end = EmptyOperator(task_id="end")
    
    # 1. Health Check
    health_check = SQLExecuteQueryOperator(
        task_id="health_check_db",
        conn_id="jobpulse_db",
        sql="SELECT 1;",
        pool=DEFAULT_POOL
    )
    
    # 2. Extract
    extract = JobPulseExtractOperator(
        task_id="extract_data",
        pool=DEFAULT_POOL
    )
    
    # 3. Transform
    transform = JobPulseTransformOperator(
        task_id="transform_data",
        upstream_task_id="extract_data",
        pool=DEFAULT_POOL
    )
    
    # 4. Validate
    validate = JobPulseValidateOperator(
        task_id="validate_data",
        upstream_task_id="transform_data",
        pool=DEFAULT_POOL
    )
    
    # 5. Load
    load = JobPulseLoadOperator(
        task_id="load_db",
        upstream_task_id="validate_data",
        pool=DEFAULT_POOL
    )
    
    # 6. Warehouse ELT (TaskGroup)
    with TaskGroup("warehouse_elt") as warehouse_elt:
        update_dimensions = SQLExecuteQueryOperator(
            task_id="update_dimensions",
            conn_id="jobpulse_db",
            sql="CALL refresh_dimensions();"
        )
        update_facts = SQLExecuteQueryOperator(
            task_id="update_facts",
            conn_id="jobpulse_db",
            sql="CALL refresh_fact_jobs();"
        )
        update_dimensions >> update_facts
        
    # 7. Reports
    generate_reports = PythonOperator(
        task_id="generate_reports",
        python_callable=_generate_daily_report
    )

    # Dependencies
    start >> health_check >> extract >> transform >> validate >> load >> warehouse_elt >> generate_reports >> end
