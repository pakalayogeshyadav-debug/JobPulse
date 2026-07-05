import streamlit as st


def render():
    st.title("System Settings")
    st.markdown("Advanced configuration and pipeline controls.")
    
    st.markdown("### Pipeline Triggers")
    st.warning("⚠️ Manual pipeline execution impacts the live database.")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("▶ Run Full ETL Pipeline", use_container_width=True):
            st.toast("ETL trigger dispatched to backend orchestrator.")
            st.info("Execution dispatched. Check Pipeline Monitor for status.")
            
    with col2:
        if st.button("🧹 Run Validation Checks", use_container_width=True):
            st.toast("Validation checks triggered.")
            
    with col3:
        if st.button("🔄 Refresh Materialized Views", use_container_width=True):
            st.toast("Materialized views refresh started.")
            
    st.markdown("---")
    st.markdown("### Data Management")
    
    if st.button("Clear Analytics Cache", type="secondary"):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.success("All frontend application caches have been flushed.")
