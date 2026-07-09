"""jobpulse.utils.dir_manager — Runtime directory manager.

Provides functionality to ensure all necessary runtime directories exist.
"""

from __future__ import annotations

import os
from pathlib import Path

from jobpulse.config.settings import Settings
from jobpulse.logging.logger import get_logger

logger = get_logger(__name__)


def ensure_runtime_directories(settings: Settings) -> None:
    """Ensure all configured runtime directories exist.

    Creates the directories if they do not exist. Logs the creation.

    Args:
        settings: The application settings containing path configurations.
    """
    directories = [
        settings.log_dir,
        settings.report_dir,
        settings.data_dir,
        settings.raw_data_dir,
        settings.processed_data_dir,
    ]

    for dir_path_str in directories:
        dir_path = Path(dir_path_str)
        if not dir_path.exists():
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created runtime directory: {dir_path}")
            except Exception as e:
                logger.error(f"Failed to create runtime directory '{dir_path}': {e}")
                # We do not raise here because some environments may be read-only,
                # and we rely on the specific components to handle missing dirs/files if fatal.
