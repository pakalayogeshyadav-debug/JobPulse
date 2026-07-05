# API Documentation

*(Note: Currently, JobPulse primarily acts as an ETL consumer. This document outlines the planned internal API for interacting with the Pipeline Orchestrator natively outside of Airflow.)*

## Internal Pipeline API

You can programmatically trigger parts of the pipeline via Python.

### `PipelineOrchestrator`

The central class coordinating the ETL lifecycle.

```python
from jobpulse.config.settings import get_settings
from jobpulse.pipeline import PipelineOrchestrator

settings = get_settings()
orchestrator = PipelineOrchestrator(settings)

# Run full pipeline for all configured sources
orchestrator.run()
```

### `IncrementalRunner`

Bypasses extraction/transformation to handle loading directly.

```python
from jobpulse.incremental.runner import IncrementalRunner
from jobpulse.incremental.watermark import PostgresWatermarkStore

runner = IncrementalRunner(
    engine=db_engine,
    session_factory=db_session_factory,
    watermark_store=PostgresWatermarkStore(db_engine),
    source_name="adzuna_api",
    run_id="manual_trigger_01",
    timestamp_col="posted_date"
)

# summary contains metrics: rows_new, rows_updated, rows_skipped
summary = runner.run(transformed_dataframe)
print(summary.to_dict())
```

### Planned REST API (Future)
A FastAPI layer is planned for v2 to expose health metrics and trigger ad-hoc ingestion runs externally.

```http
GET /health
Response: 200 OK
{
  "status": "healthy",
  "database": "connected",
  "last_run": "2024-06-30T03:00:00Z"
}

POST /trigger?source=csv_kaggle
Response: 202 Accepted
{
  "run_id": "run_982bca",
  "status": "queued"
}
```
