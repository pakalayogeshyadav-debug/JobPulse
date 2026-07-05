import glob
import os

import pandas as pd
import streamlit as st


def get_available_log_files() -> list:
    """Returns a list of log files sorted by newest first."""
    files = glob.glob('logs/**/*.log', recursive=True)
    files.sort(key=os.path.getmtime, reverse=True)
    return files

@st.cache_data(ttl=60)
def parse_log_file(filepath: str) -> pd.DataFrame:
    """Parses a log file into a structured DataFrame."""
    try:
        with open(filepath, encoding='utf-8') as f:
            lines = f.readlines()
            
        parsed = []
        for line in lines:
            parts = line.split(" | ", 3)
            if len(parts) >= 3:
                parsed.append({
                    "timestamp": parts[0].strip(),
                    "level": parts[1].strip(),
                    "logger": parts[2].strip(),
                    "message": parts[3].strip() if len(parts) > 3 else ""
                })
            else:
                # Unstructured line (e.g. traceback)
                parsed.append({
                    "timestamp": "",
                    "level": "INFO",
                    "logger": "",
                    "message": line.strip()
                })
        
        df = pd.DataFrame(parsed)
        return df
    except Exception as e:
        return pd.DataFrame([{"timestamp": "", "level": "ERROR", "logger": "system", "message": f"Could not read log file: {str(e)}"}])
