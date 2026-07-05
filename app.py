"""
app.py — JobPulse Enterprise Streamlit entry point.

Adds the src/ directory to sys.path BEFORE any jobpulse imports occur,
ensuring the database engine can be found regardless of how Streamlit
is launched.
"""
import sys
from pathlib import Path

# ── Critical path fix ────────────────────────────────────────────────────────
# Streamlit's working directory is the project root, but it does NOT add src/
# to sys.path automatically. Without this, all `from jobpulse...` imports fail
# silently and the frontend reports "Database Offline".
_ROOT = Path(__file__).resolve().parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
# ─────────────────────────────────────────────────────────────────────────────

import importlib
import traceback

import streamlit as st

st.set_page_config(
    page_title="JobPulse Enterprise",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

from frontend.theme.styles import apply_enterprise_theme
apply_enterprise_theme()

# ── Page Registry ─────────────────────────────────────────────────────────────
PAGES = {
    "Analytics": {
        "Executive Dashboard":   "frontend.pages.dashboard",
        "Jobs Explorer":         "frontend.pages.live_jobs",
        "Companies":             "frontend.pages.companies",
        "Skills Analytics":      "frontend.pages.skills",
        "Salary Analytics":      "frontend.pages.salary",
        "Geographic Analytics":  "frontend.pages.geographic",
    },
    "Data Engineering": {
        "Live Pipeline Monitor": "frontend.pages.pipeline",
        "Validation Dashboard":  "frontend.pages.validation",
        "Warehouse Explorer":    "frontend.pages.warehouse",
        "Database Explorer":     "frontend.pages.db_explorer",
        "SQL Playground":        "frontend.pages.sql_playground",
        "Airflow Monitor":       "frontend.pages.airflow",
        "Operational Logs":      "frontend.pages.logs",
    },
    "System": {
        "Profile":   "frontend.pages.profile",
        "Settings":  "frontend.pages.settings",
        "About":     "frontend.pages.about",
        "Help":      "frontend.pages.help_page",
    },
}

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        "<h2 style='margin-bottom:0'>⚡ JobPulse</h2>"
        "<p style='color:#8b949e;font-size:0.8rem;margin-top:0'>"
        "Enterprise Data Platform</p>",
        unsafe_allow_html=True,
    )

    # Live DB status badge in sidebar
    from frontend.services.database_service import check_connection
    _health = check_connection()
    if _health["connected"]:
        st.success(f"🟢 PostgreSQL Online · {_health['latency_ms']} ms")
    else:
        st.error(f"🔴 DB Offline · {_health.get('error', '')[:40]}")

    st.divider()

    for category, pages in PAGES.items():
        st.markdown(f"**{category.upper()}**")
        for page_name in pages:
            if st.button(page_name, use_container_width=True, key=page_name):
                st.session_state.current_page = page_name
        st.write("")  # spacing

if "current_page" not in st.session_state:
    st.session_state.current_page = "Executive Dashboard"

selection = st.session_state.current_page

# ── Find & Render Module ──────────────────────────────────────────────────────
module_path = None
for cat in PAGES.values():
    if selection in cat:
        module_path = cat[selection]
        break

try:
    if module_path:
        page_module = importlib.import_module(module_path)
        if hasattr(page_module, "render"):
            page_module.render()
        else:
            st.error(f"Page '{selection}' is missing a render() function.")
    else:
        st.warning(f"Page '{selection}' not found in registry.")
except Exception:
    st.error(f"Failed to render page: **{selection}**")
    with st.expander("🔍 Technical Details (click to expand)"):
        st.code(traceback.format_exc(), language="python")
