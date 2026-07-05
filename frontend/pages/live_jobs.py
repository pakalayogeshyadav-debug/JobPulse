"""
live_jobs.py — Jobs Explorer page.

Full-featured job listing browser with filtering, search, and export.
"""
import streamlit as st

from frontend.services.analytics_service import get_live_jobs, get_work_arrangement_breakdown
from frontend.services.database_service import fetch_data


def render():
    st.title("Jobs Explorer")
    st.markdown("Browse all active job postings loaded from the ETL pipeline.")

    # Filters row
    col_a, col_b, col_c, col_d = st.columns([2, 2, 1, 1])
    with col_a:
        search_title = st.text_input("Search Job Title", placeholder="e.g. Data Engineer")
    with col_b:
        search_company = st.text_input("Search Company", placeholder="e.g. Microsoft")
    with col_c:
        remote_filter = st.selectbox("Work Type", ["All", "Remote Only", "On-Site"])
    with col_d:
        limit = st.slider("Max Results", 25, 500, 100)

    # Build dynamic query
    conditions = ["is_active = TRUE"]
    params: dict = {"limit": limit}

    if search_title:
        conditions.append("job_title ILIKE :title_search")
        params["title_search"] = f"%{search_title}%"
    if search_company:
        conditions.append("company_name ILIKE :company_search")
        params["company_search"] = f"%{search_company}%"
    if remote_filter == "Remote Only":
        conditions.append("is_remote = TRUE")
    elif remote_filter == "On-Site":
        conditions.append("is_remote = FALSE")

    where = " AND ".join(conditions)
    query = f"""
        SELECT
            job_title,
            company_name,
            location_raw          AS location,
            work_arrangement,
            salary_min,
            salary_max,
            salary_currency,
            is_remote,
            posted_date,
            posting_url
        FROM jobs
        WHERE {where}
        ORDER BY COALESCE(posted_date, created_at::date) DESC NULLS LAST
        LIMIT :limit
    """

    df = fetch_data(query, params)

    st.markdown(f"**{len(df):,} results** (filtered from {fetch_data('SELECT COUNT(*) as c FROM jobs WHERE is_active=TRUE').iloc[0]['c']:,} active jobs)")

    if not df.empty:
        st.dataframe(
            df,
            use_container_width=True,
            column_config={
                "job_title": "Job Title",
                "company_name": "Company",
                "location": "Location",
                "work_arrangement": "Arrangement",
                "salary_min": st.column_config.NumberColumn("Min Salary", format="$%,.0f"),
                "salary_max": st.column_config.NumberColumn("Max Salary", format="$%,.0f"),
                "salary_currency": "Currency",
                "is_remote": st.column_config.CheckboxColumn("Remote"),
                "posted_date": st.column_config.DateColumn("Posted", format="YYYY-MM-DD"),
                "posting_url": st.column_config.LinkColumn("Link"),
            },
        )

        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="⬇ Export to CSV",
            data=csv,
            file_name="jobpulse_jobs.csv",
            mime="text/csv",
            type="primary",
        )
    else:
        st.info("No jobs match your filter criteria.")
