"""
jobpulse_backfill.py - Backfill DAG for JobPulse ETL.
"""
from datetime import datetime

from airflow import DAG
from airflow.operators.empty import EmptyOperator

from jobpulse.airflow.callbacks import on_failure_callback
from jobpulse.airflow.config import DEFAULT_ARGS

with DAG(
    dag_id="jobpulse_backfill_etl",
    default_args=DEFAULT_ARGS,
    description="Backfill JobPulse ETL Pipeline",
    schedule="@once", # Triggered manually
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["jobpulse", "backfill"],
    on_failure_callback=on_failure_callback,
) as dag:
    # Placeholder for backfill logic
    start = EmptyOperator(task_id="start")
    end = EmptyOperator(task_id="end")
    start >> end
