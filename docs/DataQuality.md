# Data Quality Framework

JobPulse treats Data Quality as a first-class citizen. Bad data is inevitable when consuming third-party APIs and CSVs. The framework follows the philosophy: **"Fail the row, not the pipeline."**

## Core Concepts

- **Validation Rules**: Granular checks applied to a DataFrame (e.g., `NotNullRule`, `ValidSalaryRangeRule`).
- **Validation Runner**: Executes rules and aggregates results.
- **Quarantine**: Rows that fail critical checks are logged and dropped from the execution context, allowing the healthy rows to proceed.

## Implemented Checks

| Check Name | Type | Action on Failure | Description |
|------------|------|-------------------|-------------|
| **Missing Primary Keys** | Critical | Drop Row | Job ID or essential identifiers are missing. |
| **Invalid Dates** | Warning | Nullify | `posted_date` is in the future or severely malformed. |
| **Salary Outliers** | Warning | Nullify | `salary_min` > `salary_max` or astronomical values. |
| **Invalid Country Codes** | Warning | Standardize | Uses unrecognised or malformed country/state combinations. |
| **Empty Descriptions** | Warning | Flag | Job posting has no text body. |

## Threshold-Based Aborts

While individual bad rows are dropped, massive systemic failures indicate an upstream issue (e.g., an API endpoint changed its JSON schema).

Airflow Variables control pipeline abort thresholds:
- `JOBPULSE_MAX_NULL_PCT`: If > 30% of critical columns are null, fail the extraction task.
- `JOBPULSE_MAX_DROP_RATE_PCT`: If the Transformer drops > 50% of the dataset, fail the transformation task.
- `JOBPULSE_MAX_LOAD_FAILURE_RATE_PCT`: If > 10% of rows fail database insertion (e.g., constraint violations), fail the load task.

## Observability

All validation failures are logged to the `pipeline_errors` table in PostgreSQL, allowing Data Engineers to build dashboards monitoring data health trends over time (e.g., "Source X has increased its null salary rate by 40% this week").
