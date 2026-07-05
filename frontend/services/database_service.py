"""
database_service.py — Central data access layer for JobPulse frontend.

All SQL queries must go through this module. Never execute SQL directly
in Streamlit page files.

The engine is cached as a resource (one per Streamlit process).
Data queries are cached with a 5-minute TTL to avoid expensive re-renders.
"""
import sys
import os
from pathlib import Path

# Ensure the src directory is on the path regardless of how Streamlit is launched.
# This is the root fix for the "Database Offline" error in Streamlit context.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import traceback

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import text


def _load_engine():
    """Create SQLAlchemy engine. Called once and cached by Streamlit."""
    load_dotenv(override=True)
    # Import AFTER sys.path is set
    from jobpulse.config.settings import Settings
    from jobpulse.database.engine import create_db_engine
    settings = Settings()
    return create_db_engine(settings)


@st.cache_resource
def get_db_engine():
    """Return the singleton SQLAlchemy engine (Streamlit resource cache)."""
    return _load_engine()


def fetch_data(query: str, params: dict | None = None) -> pd.DataFrame:
    """
    Execute a SQL query and return results as a DataFrame.
    
    Returns an empty DataFrame on failure. Errors are logged but
    never raised directly — callers must check df.empty.
    """
    try:
        engine = get_db_engine()
        with engine.connect() as conn:
            if params:
                result = conn.execute(text(query), params)
            else:
                result = conn.execute(text(query))
            rows = result.fetchall()
            cols = list(result.keys())
            return pd.DataFrame(rows, columns=cols)
    except Exception as exc:
        # Log to stderr (visible in terminal), but don't pollute Streamlit UI
        print(f"[database_service] Query failed: {exc}", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        return pd.DataFrame()


def check_connection() -> dict:
    """
    Verify database connectivity. Returns a status dict — never raises.
    """
    import time
    load_dotenv(override=True)
    
    # Fresh import after path is set
    if str(_SRC_DIR) not in sys.path:
        sys.path.insert(0, str(_SRC_DIR))
    
    try:
        from jobpulse.config.settings import Settings
        from jobpulse.database.engine import create_db_engine
        settings = Settings()
        engine = create_db_engine(settings)

        t0 = time.time()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        latency_ms = round((time.time() - t0) * 1000, 1)

        return {
            "connected": True,
            "status": "Online",
            "latency_ms": latency_ms,
            "host": settings.db_host,
            "port": settings.db_port,
            "db_name": settings.db_name,
            "pool_size": settings.db_pool_size,
        }
    except Exception as exc:
        return {
            "connected": False,
            "status": "Offline",
            "latency_ms": 0,
            "error": str(exc),
        }
