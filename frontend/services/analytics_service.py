"""
analytics_service.py — Core analytics queries for JobPulse dashboard.

All queries verified against actual schema:
  jobs: job_id, job_title, company_name, location_raw, salary_min, salary_max,
        salary_currency, is_remote, work_arrangement, posted_date, created_at
  dim_skill, bridge_job_skill, fact_jobs, dim_company, dim_location, dim_date
  pipeline_runs: run_id, data_source_id, status, started_at, completed_at, pipeline_version
  data_sources: data_source_id, source_name, display_name, is_active
"""
import pandas as pd
import streamlit as st

from frontend.services.database_service import fetch_data


@st.cache_data(ttl=300)
def get_home_kpis() -> dict:
    """Aggregate top-level KPIs from the jobs operational table."""
    query = """
        SELECT
            COUNT(*)                                                AS total_jobs,
            COUNT(DISTINCT company_name)
                FILTER (WHERE company_name IS NOT NULL)            AS total_companies,
            COUNT(DISTINCT location_raw)
                FILTER (WHERE location_raw IS NOT NULL)            AS total_locations,
            COUNT(DISTINCT sk_skill_id)                            AS total_skills,
            AVG((salary_min + salary_max) / 2.0)
                FILTER (WHERE salary_min IS NOT NULL
                          AND salary_max IS NOT NULL)              AS avg_salary,
            COUNT(*) FILTER (WHERE is_remote = TRUE)               AS remote_jobs,
            COUNT(*) FILTER (WHERE is_active = TRUE)               AS active_jobs
        FROM jobs
        LEFT JOIN bridge_job_skill bjs ON bjs.sk_fact_job_id = jobs.job_id
    """
    df = fetch_data(query)
    if not df.empty:
        row = df.iloc[0]
        return {
            "total_jobs": int(row["total_jobs"] or 0),
            "total_companies": int(row["total_companies"] or 0),
            "total_locations": int(row["total_locations"] or 0),
            "total_skills": int(row["total_skills"] or 0),
            "avg_salary": float(row["avg_salary"] or 0.0),
            "remote_jobs": int(row["remote_jobs"] or 0),
            "active_jobs": int(row["active_jobs"] or 0),
        }
    return {
        "total_jobs": 0, "total_companies": 0, "total_locations": 0,
        "total_skills": 0, "avg_salary": 0.0, "remote_jobs": 0, "active_jobs": 0,
    }


@st.cache_data(ttl=300)
def get_live_jobs(limit: int = 100) -> pd.DataFrame:
    """Return latest job listings ordered by posting date."""
    query = """
        SELECT
            job_title,
            company_name,
            location_raw           AS location_name,
            is_remote,
            work_arrangement,
            salary_min,
            salary_max,
            salary_currency,
            posted_date,
            posting_url
        FROM jobs
        WHERE is_active = TRUE
        ORDER BY COALESCE(posted_date, created_at::date) DESC NULLS LAST
        LIMIT :limit
    """
    return fetch_data(query, {"limit": limit})


@st.cache_data(ttl=300)
def get_top_skills(limit: int = 30) -> pd.DataFrame:
    """Return the most demanded skills from bridge_job_skill + dim_skill."""
    query = """
        SELECT
            s.skill_name,
            s.skill_category,
            COUNT(b.sk_fact_job_id) AS job_count
        FROM bridge_job_skill b
        JOIN dim_skill s ON b.sk_skill_id = s.sk_skill_id
        GROUP BY s.skill_name, s.skill_category
        ORDER BY job_count DESC
        LIMIT :limit
    """
    return fetch_data(query, {"limit": limit})


@st.cache_data(ttl=300)
def get_company_hiring(limit: int = 25) -> pd.DataFrame:
    """Return companies ranked by number of active job postings."""
    query = """
        SELECT
            company_name,
            COUNT(*)              AS active_postings,
            COUNT(*) FILTER (WHERE is_remote = TRUE) AS remote_roles,
            AVG((salary_min + salary_max) / 2.0)
                FILTER (WHERE salary_min IS NOT NULL AND salary_max IS NOT NULL)
                                  AS avg_salary
        FROM jobs
        WHERE company_name IS NOT NULL
          AND is_active = TRUE
        GROUP BY company_name
        ORDER BY active_postings DESC
        LIMIT :limit
    """
    return fetch_data(query, {"limit": limit})


@st.cache_data(ttl=300)
def get_salary_by_role(limit: int = 20) -> pd.DataFrame:
    """Return salary benchmarks aggregated by job title."""
    query = """
        SELECT
            job_title                                               AS role,
            job_title,
            COUNT(*)                                               AS total_jobs,
            ROUND(AVG(salary_min)::numeric, 0)                    AS avg_salary_min,
            ROUND(AVG(salary_max)::numeric, 0)                    AS avg_salary_max,
            ROUND(AVG((salary_min + salary_max) / 2.0)::numeric, 0)
                                                                   AS avg_salary_midpoint,
            ROUND(MIN(salary_min)::numeric, 0)                    AS lowest_salary,
            ROUND(MAX(salary_max)::numeric, 0)                    AS highest_salary,
            MAX(salary_currency)                                   AS salary_currency
        FROM jobs
        WHERE salary_min IS NOT NULL
          AND salary_max IS NOT NULL
          AND salary_min > 0
        GROUP BY job_title
        HAVING COUNT(*) > 1
        ORDER BY total_jobs DESC
        LIMIT :limit
    """
    return fetch_data(query, {"limit": limit})


@st.cache_data(ttl=300)
def get_pipeline_health() -> pd.DataFrame:
    """
    Return pipeline execution history from the actual pipeline_runs schema.
    Columns: run_id, data_source_id, status, started_at, completed_at, pipeline_version
    """
    query = """
        SELECT
            ds.display_name                                         AS source_name,
            ds.source_name                                         AS source_key,
            COUNT(pr.run_id)                                       AS total_runs,
            COUNT(pr.run_id) FILTER (WHERE UPPER(pr.status) = 'SUCCESS') AS success_runs,
            COUNT(pr.run_id) FILTER (WHERE UPPER(pr.status) = 'FAILED')  AS failed_runs,
            COUNT(pr.run_id) FILTER (WHERE UPPER(pr.status) NOT IN ('SUCCESS','FAILED'))
                                                                          AS other_runs,
            ROUND(
                COUNT(pr.run_id) FILTER (WHERE UPPER(pr.status) = 'SUCCESS') * 100.0
                / NULLIF(COUNT(pr.run_id), 0), 1
            )                                                              AS success_rate_pct,
            MAX(pr.completed_at)                                   AS last_run_completed,
            MAX(pr.pipeline_version)                               AS latest_version
        FROM data_sources ds
        LEFT JOIN pipeline_runs pr ON pr.data_source_id = ds.data_source_id
        GROUP BY ds.data_source_id, ds.display_name, ds.source_name
        ORDER BY last_run_completed DESC NULLS LAST
    """
    return fetch_data(query)


@st.cache_data(ttl=300)
def get_jobs_over_time() -> pd.DataFrame:
    """Return daily job posting counts for trend charts."""
    query = """
        SELECT
            posted_date      AS date,
            COUNT(*)         AS job_count,
            COUNT(*) FILTER (WHERE is_remote = TRUE) AS remote_count
        FROM jobs
        WHERE posted_date IS NOT NULL
          AND posted_date >= CURRENT_DATE - INTERVAL '90 days'
        GROUP BY posted_date
        ORDER BY posted_date
    """
    return fetch_data(query)


@st.cache_data(ttl=300)
def get_work_arrangement_breakdown() -> pd.DataFrame:
    """Return work arrangement distribution."""
    query = """
        SELECT
            COALESCE(work_arrangement, 'Unspecified') AS work_type,
            COUNT(*)                                   AS job_count
        FROM jobs
        GROUP BY work_arrangement
        ORDER BY job_count DESC
    """
    return fetch_data(query)
