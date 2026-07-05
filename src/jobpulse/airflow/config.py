"""jobpulse.airflow.config - Default configurations for JobPulse DAGs."""

import os
from datetime import timedelta
from pathlib import Path

# Airflow configurations loaded dynamically or from environment
DAG_OWNER = os.getenv("AIRFLOW_DAG_OWNER", "data_engineering")
EMAIL_ON_FAILURE = os.getenv("AIRFLOW_EMAIL_ON_FAILURE", "True").lower() == "true"
EMAIL_ON_RETRY = os.getenv("AIRFLOW_EMAIL_ON_RETRY", "False").lower() == "true"
ALERT_EMAIL_LIST = os.getenv(
    "AIRFLOW_ALERT_EMAIL_LIST", "data-alerts@example.com"
).split(",")

# Base Directories
PROJECT_ROOT = Path(os.getenv("JOBPULSE_PROJECT_ROOT", "/opt/airflow"))
DATA_DIR = PROJECT_ROOT / "data"
STAGING_DIR = DATA_DIR / "staging"
RAW_DIR = DATA_DIR / "raw"

# Create directories if they don't exist
STAGING_DIR.mkdir(parents=True, exist_ok=True)
RAW_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_ARGS = {
    "owner": DAG_OWNER,
    "depends_on_past": False,
    "email": ALERT_EMAIL_LIST,
    "retries": int(os.getenv("AIRFLOW_TASK_RETRIES", 2)),
    "retry_delay": timedelta(minutes=int(os.getenv("AIRFLOW_RETRY_DELAY_MIN", 5))),
    "execution_timeout": timedelta(
        minutes=int(os.getenv("AIRFLOW_EXECUTION_TIMEOUT_MIN", 30))
    ),
}

DEFAULT_POOL = "default_pool"
ETL_POOL = os.getenv("AIRFLOW_ETL_POOL", "etl_pool")
