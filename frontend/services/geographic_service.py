import pandas as pd
import streamlit as st

from frontend.services.database_service import fetch_data


@st.cache_data(ttl=600)
def get_location_distribution() -> pd.DataFrame:
    query = """
        SELECT 
            location_raw as location_name,
            COUNT(*) as job_count,
            AVG(salary_min) as avg_min_salary,
            AVG(salary_max) as avg_max_salary,
            SUM(CASE WHEN is_remote = TRUE THEN 1 ELSE 0 END) as remote_count
        FROM jobs
        WHERE location_raw IS NOT NULL
        GROUP BY location_raw
        ORDER BY job_count DESC
        LIMIT 50
    """
    return fetch_data(query)

@st.cache_data(ttl=600)
def get_remote_vs_onsite() -> pd.DataFrame:
    query = """
        SELECT 
            CASE WHEN is_remote = TRUE THEN 'Remote' ELSE 'On-Site/Hybrid' END as work_type,
            COUNT(*) as job_count
        FROM jobs
        GROUP BY is_remote
    """
    return fetch_data(query)
