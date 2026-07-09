"""
analytics_service.py — Core analytics queries for JobPulse dashboard.

Queries rewritten for the normalized 3NF PostgreSQL warehouse schema.
"""
import pandas as pd
import streamlit as st

from frontend.services.database_service import fetch_data


@st.cache_data(ttl=300)
def get_home_kpis() -> dict:
    """Aggregate top-level KPIs from the normalized schema."""
    query = """
        SELECT
            (SELECT COUNT(*) FROM jobs) AS total_jobs,
            (SELECT COUNT(*) FROM companies) AS total_companies,
            (SELECT COUNT(*) FROM locations) AS total_locations,
            (SELECT COUNT(*) FROM skills) AS total_skills,
            (SELECT AVG(salary_midpoint) FROM salary_ranges) AS avg_salary,
            (SELECT COUNT(*) FROM jobs WHERE is_remote = TRUE) AS remote_jobs,
            (SELECT COUNT(*) FROM jobs WHERE is_active = TRUE) AS active_jobs
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
    """Return latest job listings ordered by posting date using normalized schema."""
    query = """
        SELECT
            j.job_title,
            c.company_name,
            COALESCE(l.city || ', ' || l.state_code, l.country_name, 'Unknown') AS location_name,
            j.is_remote,
            j.work_arrangement,
            sr.salary_min,
            sr.salary_max,
            sr.currency_code AS salary_currency,
            j.posted_date,
            j.posting_url
        FROM jobs j
        LEFT JOIN companies c ON j.company_id = c.company_id
        LEFT JOIN locations l ON j.location_id = l.location_id
        LEFT JOIN salary_ranges sr ON j.job_id = sr.job_id
        WHERE j.is_active = TRUE
        ORDER BY COALESCE(j.posted_date, j.created_at::date) DESC NULLS LAST
        LIMIT :limit
    """
    return fetch_data(query, {"limit": limit})


@st.cache_data(ttl=300)
def get_top_skills(limit: int = 30) -> pd.DataFrame:
    """Return the most demanded skills from job_skills + skills tables."""
    query = """
        SELECT
            s.skill_name,
            s.skill_category,
            COUNT(js.job_id) AS job_count
        FROM job_skills js
        JOIN skills s ON js.skill_id = s.skill_id
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
            c.company_name,
            COUNT(j.job_id) AS active_postings,
            COUNT(j.job_id) FILTER (WHERE j.is_remote = TRUE) AS remote_roles,
            AVG(sr.salary_midpoint) AS avg_salary
        FROM companies c
        JOIN jobs j ON c.company_id = j.company_id
        LEFT JOIN salary_ranges sr ON j.job_id = sr.job_id
        WHERE j.is_active = TRUE
        GROUP BY c.company_name
        ORDER BY active_postings DESC
        LIMIT :limit
    """
    return fetch_data(query, {"limit": limit})


@st.cache_data(ttl=300)
def get_salary_by_role(limit: int = 20) -> pd.DataFrame:
    """Return salary benchmarks aggregated by job title."""
    query = """
        SELECT
            j.canonical_title AS role,
            j.job_title,
            COUNT(j.job_id) AS total_jobs,
            ROUND(AVG(sr.salary_min)::numeric, 0) AS avg_salary_min,
            ROUND(AVG(sr.salary_max)::numeric, 0) AS avg_salary_max,
            ROUND(AVG(sr.salary_midpoint)::numeric, 0) AS avg_salary_midpoint,
            ROUND(MIN(sr.salary_min)::numeric, 0) AS lowest_salary,
            ROUND(MAX(sr.salary_max)::numeric, 0) AS highest_salary,
            MAX(sr.currency_code) AS salary_currency
        FROM jobs j
        JOIN salary_ranges sr ON j.job_id = sr.job_id
        WHERE sr.salary_min IS NOT NULL
          AND sr.salary_max IS NOT NULL
          AND sr.salary_min > 0
        GROUP BY j.canonical_title, j.job_title
        HAVING COUNT(j.job_id) > 1
        ORDER BY total_jobs DESC
        LIMIT :limit
    """
    return fetch_data(query, {"limit": limit})


@st.cache_data(ttl=300)
def get_pipeline_health() -> pd.DataFrame:
    """Return pipeline execution history from the pipeline_runs and data_sources schema."""
    query = """
        SELECT
            ds.display_name AS source_name,
            ds.source_name AS source_key,
            COUNT(pr.run_id) AS total_runs,
            COUNT(pr.run_id) FILTER (WHERE UPPER(pr.status) = 'SUCCESS') AS success_runs,
            COUNT(pr.run_id) FILTER (WHERE UPPER(pr.status) = 'FAILED')  AS failed_runs,
            COUNT(pr.run_id) FILTER (WHERE UPPER(pr.status) NOT IN ('SUCCESS','FAILED')) AS other_runs,
            ROUND(
                COUNT(pr.run_id) FILTER (WHERE UPPER(pr.status) = 'SUCCESS') * 100.0
                / NULLIF(COUNT(pr.run_id), 0), 1
            ) AS success_rate_pct,
            MAX(pr.completed_at) AS last_run_completed,
            MAX(pr.pipeline_version) AS latest_version
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
            posted_date AS date,
            COUNT(*) AS job_count,
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
            COUNT(*) AS job_count
        FROM jobs
        GROUP BY work_arrangement
        ORDER BY job_count DESC
    """
    return fetch_data(query)
