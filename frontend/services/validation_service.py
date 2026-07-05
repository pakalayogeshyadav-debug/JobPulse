"""
validation_service.py — Data quality and pipeline validation queries.

All queries verified against the actual PostgreSQL schema:
  pipeline_runs: run_id, data_source_id, status, started_at, completed_at, pipeline_version
  jobs: job_id, company_name, location_raw, salary_min, salary_max, is_remote, posted_date, ...
"""
import pandas as pd
import streamlit as st

from frontend.services.database_service import fetch_data


@st.cache_data(ttl=300)
def get_validation_summary() -> dict:
    """
    Derives validation metrics from the jobs table directly since pipeline_runs
    does not store row-level transformation counts.
    
    Returns counts of valid vs invalid records based on data quality rules.
    """
    query = """
        SELECT
            COUNT(*) AS total_jobs,
            COUNT(CASE WHEN company_name IS NOT NULL
                         AND job_title IS NOT NULL
                         AND location_raw IS NOT NULL
                    THEN 1 END) AS valid_records,
            COUNT(CASE WHEN company_name IS NULL
                         OR job_title IS NULL
                         OR location_raw IS NULL
                    THEN 1 END) AS invalid_records,
            COUNT(CASE WHEN salary_min IS NOT NULL AND salary_max IS NOT NULL THEN 1 END) AS with_salary,
            COUNT(CASE WHEN is_remote = TRUE THEN 1 END) AS remote_jobs
        FROM jobs
    """
    df = fetch_data(query)
    if not df.empty:
        row = df.iloc[0]
        total = int(row["total_jobs"] or 0)
        valid = int(row["valid_records"] or 0)
        invalid = int(row["invalid_records"] or 0)
        pct = (valid / total * 100) if total > 0 else 0.0
        return {
            "total_validated": total,
            "passed_records": valid,
            "failed_records": invalid,
            "validation_percentage": round(pct, 2),
            "with_salary": int(row["with_salary"] or 0),
            "remote_jobs": int(row["remote_jobs"] or 0),
        }
    return {
        "total_validated": 0,
        "passed_records": 0,
        "failed_records": 0,
        "validation_percentage": 0.0,
        "with_salary": 0,
        "remote_jobs": 0,
    }


@st.cache_data(ttl=300)
def get_data_quality_stats() -> pd.DataFrame:
    """
    Returns per-rule data quality statistics derived from the jobs table.
    """
    query = """
        SELECT rule, occurrences, severity,
               ROUND(occurrences::numeric / NULLIF(total, 0) * 100, 2) AS pct_affected
        FROM (
            SELECT 'Missing Company Name'  AS rule,
                   COUNT(*) FILTER (WHERE company_name IS NULL)       AS occurrences,
                   COUNT(*)                                            AS total,
                   'WARNING'                                           AS severity
            FROM jobs
            UNION ALL
            SELECT 'Missing Job Title',
                   COUNT(*) FILTER (WHERE job_title IS NULL),
                   COUNT(*), 'ERROR'
            FROM jobs
            UNION ALL
            SELECT 'Missing Location',
                   COUNT(*) FILTER (WHERE location_raw IS NULL),
                   COUNT(*), 'WARNING'
            FROM jobs
            UNION ALL
            SELECT 'Missing Salary (min+max)',
                   COUNT(*) FILTER (WHERE salary_min IS NULL AND salary_max IS NULL),
                   COUNT(*), 'INFO'
            FROM jobs
            UNION ALL
            SELECT 'Duplicate Source Job IDs',
                   COUNT(*) - COUNT(DISTINCT source_job_id),
                   COUNT(*), 'WARNING'
            FROM jobs
        ) t
        ORDER BY occurrences DESC
    """
    return fetch_data(query)


@st.cache_data(ttl=300)
def get_validation_history() -> pd.DataFrame:
    """
    Returns pipeline run history with status from actual pipeline_runs schema.
    Columns: run_id, data_source_id, status, started_at, completed_at, pipeline_version
    """
    query = """
        SELECT
            pr.run_id,
            ds.source_name,
            pr.status,
            pr.started_at AS run_date,
            pr.completed_at,
            pr.pipeline_version,
            EXTRACT(EPOCH FROM (pr.completed_at - pr.started_at))::int AS duration_seconds,
            COUNT(j.job_id) AS jobs_in_run
        FROM pipeline_runs pr
        LEFT JOIN data_sources ds ON pr.data_source_id = ds.data_source_id
        LEFT JOIN jobs j ON j.pipeline_run_id = pr.run_id
        GROUP BY pr.run_id, ds.source_name, pr.status, pr.started_at,
                 pr.completed_at, pr.pipeline_version
        ORDER BY pr.started_at DESC
        LIMIT 30
    """
    return fetch_data(query)
