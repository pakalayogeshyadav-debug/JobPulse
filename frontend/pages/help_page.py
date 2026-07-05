import streamlit as st


def render():
    st.title("Help & Documentation")
    st.markdown("Resources for using the JobPulse Enterprise Platform.")
    
    with st.expander("How do I use the SQL Playground?"):
        st.markdown("""
        The SQL playground allows for direct `SELECT` queries against the data warehouse. 
        All destructive commands (`DROP`, `DELETE`, etc.) are actively blocked by the application layer.
        Results can be exported directly to CSV.
        """)
        
    with st.expander("How often is data refreshed?"):
        st.markdown("""
        The ETL pipeline runs on a scheduled cron job (or Airflow DAG). When data is ingested, 
        it is validated and upserted. The frontend caches results for 10 minutes to minimize database load.
        """)
        
    with st.expander("What happens if the database is offline?"):
        st.markdown("""
        The application is resilient. If the PostgreSQL database becomes unreachable, all data fetching components 
        will gracefully fail, showing an 'Offline' badge instead of crashing the interface. 
        """)
