"""
dags/jobpulse/dag_config.py — DAG configuration schema and validation.

Centralises all Airflow Variable names and their expected types.
Acts as a "schema" for the Variables table — prevents typos in Variable keys
and documents every knob the DAG exposes without reading the DAG source code.

Usage by Ops team:
    1. Go to Airflow UI → Admin → Variables
    2. Import the variables from docs/airflow_variables.json
    3. Override individual values as needed per environment

Usage in code:
    from jobpulse.dag_config import VARIABLE_SCHEMA, get_dag_config
    config = get_dag_config()
    batch_size = config["batch_size"]
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from airflow.models import Variable

# =============================================================================
# Variable Schema Registry
# =============================================================================

@dataclass(frozen=True)
class VariableSpec:
    """Defines one Airflow Variable used by the JobPulse DAG."""
    airflow_key: str       # Key in Airflow Variables table
    default: Any           # Default value if the Variable is not set
    type_: type            # Expected Python type (for coercion)
    description: str       # What this variable controls


VARIABLE_SCHEMA: list[VariableSpec] = [
    VariableSpec(
        airflow_key="JOBPULSE_ALERT_EMAILS",
        default="data-engineering@yourcompany.com",
        type_=str,
        description="Comma-separated email addresses for pipeline failure alerts.",
    ),
    VariableSpec(
        airflow_key="JOBPULSE_SLACK_WEBHOOK_URL",
        default="",
        type_=str,
        description=(
            "Slack Incoming Webhook URL for pipeline notifications. "
            "Leave blank to disable Slack alerts."
        ),
    ),
    VariableSpec(
        airflow_key="JOBPULSE_BATCH_SIZE",
        default=1000,
        type_=int,
        description=(
            "Number of rows per PostgreSQL bulk insert chunk. "
            "Larger values = fewer round trips but more memory per worker. "
            "Recommended: 500–2000."
        ),
    ),
    VariableSpec(
        airflow_key="JOBPULSE_MAX_NULL_PCT",
        default=30.0,
        type_=float,
        description=(
            "Maximum allowed null percentage (0–100) in critical columns "
            "(job_title, company_name) before the validate task fails. "
            "Default: 30.0 (30%)."
        ),
    ),
    VariableSpec(
        airflow_key="JOBPULSE_MIN_ROWS",
        default=1,
        type_=int,
        description=(
            "Minimum number of rows the extract task must return. "
            "If the source returns fewer rows, the validate task fails. "
            "Default: 1 (any data is acceptable)."
        ),
    ),
    VariableSpec(
        airflow_key="JOBPULSE_STAGING_KEEP_DAYS",
        default=3,
        type_=int,
        description=(
            "Number of days to keep staging Parquet files after a pipeline run. "
            "Files older than this are deleted by the cleanup task. "
            "Default: 3 days."
        ),
    ),
    VariableSpec(
        airflow_key="JOBPULSE_MAX_DROP_RATE_PCT",
        default=50.0,
        type_=float,
        description=(
            "Maximum allowed row drop rate (0–100) in the transform task. "
            "If the transformer drops more than this % of input rows, "
            "the task fails. Default: 50.0 (50%)."
        ),
    ),
    VariableSpec(
        airflow_key="JOBPULSE_MAX_LOAD_FAILURE_RATE_PCT",
        default=10.0,
        type_=float,
        description=(
            "Maximum allowed load failure rate (0–100). "
            "If more than this % of rows fail to load, "
            "the load task fails. Default: 10.0 (10%)."
        ),
    ),
]


def get_dag_config() -> dict[str, Any]:
    """
    Read all JobPulse Airflow Variables and return as a typed config dict.

    Variables not set in Airflow fall back to their default values.
    Type coercion is applied (e.g., "1000" → 1000 for int types).

    Returns:
        dict: All DAG configuration values, keyed by a short name.
    """
    config: dict[str, Any] = {}
    for spec in VARIABLE_SCHEMA:
        try:
            raw_value = Variable.get(spec.airflow_key, default_var=spec.default)
        except Exception:
            raw_value = spec.default

        try:
            config[spec.airflow_key] = spec.type_(raw_value)
        except (ValueError, TypeError):
            config[spec.airflow_key] = spec.default

    return config


def export_variables_json() -> str:
    """
    Export all Variable specs as a JSON string for bulk import into Airflow.

    Usage:
        python -c "from dag_config import export_variables_json; print(export_variables_json())"
        → Paste output into Airflow UI → Admin → Variables → Import

    Returns:
        str: JSON array of {key, val, description} objects.
    """
    import json
    return json.dumps(
        [
            {
                "key": spec.airflow_key,
                "val": str(spec.default),
                "description": spec.description,
            }
            for spec in VARIABLE_SCHEMA
        ],
        indent=2,
    )
