# JobPulse Airflow Orchestration

This document details the Apache Airflow setup for the JobPulse Data Engineering Pipeline.

## Architecture
JobPulse utilizes Airflow solely as an orchestrator, meaning the core ETL logic remains decoupled in the `src/jobpulse` Python package.
The pipeline spans several key tasks in the main DAG (`jobpulse_daily_etl`):
1. **Health Check**: Ping the PostgreSQL Data Warehouse.
2. **Extract**: Fetch latest CSVs using `DirectoryExtractor`. Writes intermediate output to `.parquet`.
3. **Transform**: Cleans the data using `JobListingTransformer`. Writes output to `.parquet`.
4. **Validate**: Ensures data quality against rigorous rules in `DataValidator`.
5. **Load**: Upserts the validated data into PostgreSQL via `PostgresLoader`.
6. **Warehouse ELT**: Updates dimensional models and analytical views.
7. **Reports**: Emits success and failure notifications.

### XCom and State
Instead of passing huge Pandas DataFrames through XCom (which crashes the metadata DB), operators save intermediate states to `data/staging/` as Parquet files, and only the `file_path` is passed downstream via XCom.

## Deployment Steps
1. Navigate to the project root.
2. Initialize Airflow and Start the Cluster:
   ```bash
   docker-compose up airflow-init
   docker-compose up -d
   ```
3. Open `http://localhost:8080`. (Default login: `airflow` / `airflow`)

## Configuration
All Airflow-specific configurations (Retries, Timeouts, Owners, Alerts) are managed centrally in `src/jobpulse/airflow/config.py`. To tweak them dynamically without altering DAG code, you can inject environment variables:
- `AIRFLOW_TASK_RETRIES`
- `AIRFLOW_EXECUTION_TIMEOUT_MIN`
- `AIRFLOW_ALERT_EMAIL_LIST`

## Callbacks
We employ robust Task/DAG-level callbacks defined in `src/jobpulse/airflow/callbacks.py`. On failure, the system captures the stack trace, attempts an update on the operational `pipeline_runs` table, and conditionally sends an HTML email alert with direct links to the Airflow logs.
