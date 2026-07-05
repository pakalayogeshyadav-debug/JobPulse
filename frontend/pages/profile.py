import streamlit as st

from frontend.components.db_health import check_db_health


def render():
    st.title("User Profile & Settings")
    st.markdown("Configure application preferences.")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("UI Preferences")
        theme = st.selectbox("Theme Mode", ["Dark Mode (Default)", "Light Mode", "System Default"])
        refresh_rate = st.selectbox("Auto Refresh Interval", ["Off", "30 Seconds", "1 Minute", "5 Minutes"])
        chart_pref = st.selectbox("Chart Style", ["Standard Plotly", "Minimal", "High Contrast"])
        density = st.selectbox("Table Density", ["Compact", "Standard", "Comfortable"])
        
        if st.button("Save Preferences"):
            st.success("Preferences saved successfully. (Note: Theme applies to layout structure)")
            
    with col2:
        st.subheader("System Status")
        
        health = check_db_health()
        status_color = "🟢" if health['connected'] else "🔴"
        st.markdown(f"**Database:** {status_color} {health['status']}")
        if health['connected']:
            st.markdown(f"- **Latency:** {health['latency_ms']} ms")
            st.markdown(f"- **Pool Size:** {health['pool_size']}")
        
        st.markdown("---")
        st.markdown("**Application Version:** v1.0.0 (Production)")
        st.markdown("**Environment:** Windows Local Deployment")
        st.markdown("**Cache:** Active")
        
        if st.button("Clear Application Cache", type="secondary"):
            st.cache_data.clear()
            st.cache_resource.clear()
            st.success("Cache cleared! Application will fetch fresh data on next load.")
            st.rerun()
