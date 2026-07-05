"""jobpulse.airflow.utils - Helper functions for Airflow integration."""

import os
from pathlib import Path

import pandas as pd


def save_dataframe_to_staging(
    df: pd.DataFrame, run_id: str, stage: str, staging_dir: Path
) -> str:
    """Saves a Pandas DataFrame to Parquet and returns the file path.
    This avoids passing large DataFrames through XCom.
    """
    staging_dir.mkdir(parents=True, exist_ok=True)
    file_path = staging_dir / f"{stage}_{run_id}.parquet"
    df.to_parquet(file_path, index=False)
    return str(file_path)


def load_dataframe_from_staging(file_path: str) -> pd.DataFrame:
    """Loads a Pandas DataFrame from a Parquet file."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Staging file not found: {file_path}")
    return pd.read_parquet(file_path)
