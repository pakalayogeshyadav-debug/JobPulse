"""
db_health.py — Database health check component.
Renders a live status strip on any page.
"""
import streamlit as st
from frontend.services.database_service import check_connection


@st.cache_data(ttl=15)
def check_db_health() -> dict:
    """Returns DB health dict. Cached 15 seconds."""
    return check_connection()


def render_db_health():
    """Render a horizontal DB health status strip."""
    health = check_db_health()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if health["connected"]:
            st.success("✅ PostgreSQL Online")
        else:
            st.error("🔴 PostgreSQL Offline")
    with col2:
        if health["connected"]:
            st.success(f"✅ {health.get('db_name', 'jobpulse')}")
        else:
            err = health.get("error", "Unknown error")
            st.error(f"🔴 {err[:40]}")
    with col3:
        if health["connected"]:
            st.info(f"⚡ {health['latency_ms']} ms latency")
        else:
            st.warning("⚡ Latency: N/A")
    with col4:
        if health["connected"]:
            st.info(f"🏊 Pool: {health.get('pool_size', 5)} connections")
        else:
            st.warning("🏊 Pool: N/A")
