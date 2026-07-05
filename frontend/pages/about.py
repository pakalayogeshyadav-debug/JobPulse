"""
about.py — About page. Removed graphviz dependency (not installed).
Uses Streamlit native columns and text instead.
"""
import streamlit as st

from frontend.services.analytics_service import get_home_kpis, get_pipeline_health
from frontend.services.validation_service import get_validation_summary


def render():
    st.title("About JobPulse")
    st.markdown("### Enterprise Data Engineering Portfolio Project")

    st.markdown("""
    **JobPulse** is a production-ready, end-to-end Data Engineering platform designed to ingest,
    transform, validate, and serve real-time job market analytics. The architecture demonstrates
    modern data engineering best practices including idempotent data loading, robust schema validation,
    Kimball dimensional modelling, and incremental processing.
    """)

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Technology Stack")
        st.markdown("""
        | Layer | Technology |
        |---|---|
        | Language | Python 3.10+ |
        | Database | PostgreSQL 17 |
        | Orchestration | Apache Airflow / Native |
        | Data Processing | Pandas / SQLAlchemy |
        | Frontend | Streamlit + Plotly |
        | Testing | Pytest (89% Coverage) |
        | Schema Validation | Pydantic v2 |
        | Retry Logic | Tenacity |
        """)

    with col2:
        st.subheader("Live Project Statistics")
        kpis = get_home_kpis()
        val = get_validation_summary()
        pipe = get_pipeline_health()
        total_runs = int(pipe["total_runs"].sum()) if not pipe.empty else 0

        st.markdown(f"""
        | Metric | Value |
        |---|---|
        | Total Jobs Processed | {kpis['total_jobs']:,} |
        | Companies Tracked | {kpis['total_companies']:,} |
        | Skills Indexed | {kpis['total_skills']:,} |
        | Pipeline Runs | {total_runs} |
        | Validation Score | {val['validation_percentage']:.2f}% |
        | Remote Jobs Available | {kpis['remote_jobs']:,} |
        """)

    st.divider()
    st.subheader("Architecture & Data Flow")

    # Native Streamlit architecture diagram
    st.markdown("""
    ```
    ┌──────────────────────────────────────────────────────────────────────┐
    │                      External Data Sources                            │
    │        Adzuna API · Arbeitnow API · USAJobs · Remotive               │
    └─────────────────────────┬────────────────────────────────────────────┘
                              │  HTTP/JSON
                              ▼
    ┌──────────────────────────────────────────────────────────────────────┐
    │                       Extraction Layer                                │
    │        ApiExtractor · CsvExtractor · DirectoryExtractor              │
    │                   Rate Limiting · Retry Logic                        │
    └─────────────────────────┬────────────────────────────────────────────┘
                              │  Raw DataFrames
                              ▼
    ┌──────────────────────────────────────────────────────────────────────┐
    │                    Transformation Layer                               │
    │         JobListingTransformer · Normalisation · Deduplication        │
    └─────────────────────────┬────────────────────────────────────────────┘
                              │  Clean DataFrames
                              ▼
    ┌──────────────────────────────────────────────────────────────────────┐
    │                      Validation Layer                                 │
    │          Schema Checks · Type Checks · Business Rules                │
    └─────────────────────────┬────────────────────────────────────────────┘
                              │  Validated Records
                              ▼
    ┌──────────────────────────────────────────────────────────────────────┐
    │                   PostgreSQL Operational DB                           │
    │         jobs · pipeline_runs · data_sources                          │
    │                   Upsert / Idempotent Loading                        │
    └─────────────────────────┬────────────────────────────────────────────┘
                              │  ELT
                              ▼
    ┌──────────────────────────────────────────────────────────────────────┐
    │               Kimball Data Warehouse (Star Schema)                   │
    │    fact_jobs · dim_company · dim_location · dim_skill · dim_date     │
    │                    bridge_job_skill                                   │
    └─────────────────────────┬────────────────────────────────────────────┘
                              │  SQLAlchemy
                              ▼
    ┌──────────────────────────────────────────────────────────────────────┐
    │                  Streamlit Frontend (This App)                        │
    │      Dashboard · Jobs · Skills · Salary · Pipeline Monitor           │
    └──────────────────────────────────────────────────────────────────────┘
    ```
    """)

    st.divider()
    st.subheader("Author")
    st.markdown("""
    Created by **P Yogesh Yadav**.

    This project was built to demonstrate proficiency in building resilient, scalable,
    and production-quality data platforms — suitable for portfolio presentation at companies
    like Snowflake, Databricks, Microsoft, Amazon, and Palantir.

    🔗 [GitHub Repository](https://github.com) &nbsp;|&nbsp; 🔗 [LinkedIn Profile](https://linkedin.com)
    """)
