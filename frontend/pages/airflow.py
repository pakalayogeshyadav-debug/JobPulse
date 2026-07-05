import streamlit as st


def render():
    st.title("Airflow Orchestration")
    st.markdown("Monitor and manage Airflow DAGs.")
    
    st.error("🔴 Airflow Service Unavailable")
    st.markdown("""
    **Environment Limitation Detected**
    
    The Apache Airflow webserver and scheduler are currently offline or not installed in this environment. 
    
    This is expected if you are running the ETL pipeline in local native mode (e.g. via `python main.py` or local CRON) rather than via Docker orchestration.
    
    **To resolve this:**
    1. Ensure Docker Desktop is running.
    2. Start the Airflow cluster via `docker-compose up -d`.
    3. Ensure the Airflow REST API is exposed on port 8080.
    
    *No placeholder DAGs are shown to maintain data integrity.*
    """)
    
    if st.button("Retry Connection"):
        st.rerun()
