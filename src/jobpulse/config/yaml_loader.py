"""jobpulse.config.yaml_loader — YAML configuration file loader.

Reads the non-secret runtime configuration from config/settings.yaml
and returns it as a typed Python dictionary.

This is intentionally separate from settings.py (Pydantic/env-based)
to maintain a clear boundary:
    - settings.py  → secrets & env-specific values (.env)
    - yaml_loader  → non-secret runtime config (settings.yaml)

Example:
    >>> from jobpulse.config.yaml_loader import load_yaml_config
    >>> cfg = load_yaml_config()
    >>> cfg["pipeline"]["name"]
    'JobPulse ETL Pipeline'
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# Resolve path relative to this file: src/jobpulse/config/ → project root
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config" / "settings.yaml"


def load_yaml_config(
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Load and parse the YAML runtime configuration file.

    Args:
        config_path: Absolute path to the YAML config file.
                     Defaults to ``config/settings.yaml`` in the project root.

    Returns:
        dict[str, Any]: Parsed YAML content as a nested dictionary.

    Raises:
        FileNotFoundError: If the config file does not exist at the given path.
        yaml.YAMLError: If the YAML content is malformed.

    Example:
        >>> cfg = load_yaml_config()
        >>> cfg["extraction"]["http_timeout_seconds"]
        30
    """
    path = config_path or _DEFAULT_CONFIG_PATH

    if not path.exists():
        raise FileNotFoundError(
            f"YAML configuration file not found: {path}\n"
            "Ensure config/settings.yaml exists in the project root."
        )

    with path.open(encoding="utf-8") as file_handle:
        config: dict[str, Any] = yaml.safe_load(file_handle) or {}

    return config
