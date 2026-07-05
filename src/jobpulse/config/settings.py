"""jobpulse.config.settings — Application settings management.

Uses Pydantic BaseSettings to:
    1. Read values from environment variables (and .env file)
    2. Validate and coerce types at startup
    3. Expose a single, importable Settings instance

Security Rules:
    - Passwords and API keys come ONLY from environment variables.
    - Settings are validated at import time — fail fast on misconfiguration.
    - The DATABASE_URL is constructed from components if not set directly.

Pydantic BaseSettings reads environment variables in this order:
    1. Directly set environment variables (highest priority)
    2. Values in the .env file
    3. Default values defined in the model (lowest priority)

Example:
    >>> from jobpulse.config.settings import get_settings
    >>> settings = get_settings()
    >>> settings.db_host
    'localhost'
    >>> settings.database_url
    'postgresql+psycopg2://user:password@localhost:5432/jobpulse_dw'
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root: two levels up from this file (src/jobpulse/config/settings.py)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """Validated application settings loaded from environment variables.

    All fields map 1:1 to variables in .env.example.
    Pydantic validates types, applies defaults, and raises clear errors
    if required values are missing.

    Attributes:
        environment:        Deployment environment (development/staging/production).
        log_level:          Python logging level name.
        db_host:            PostgreSQL hostname.
        db_port:            PostgreSQL port.
        db_name:            PostgreSQL database name.
        db_user:            PostgreSQL username.
        db_password:        PostgreSQL password (secret).
        db_schema:          PostgreSQL schema name.
        db_pool_size:       SQLAlchemy connection pool size.
        db_max_overflow:    Max connections above pool_size.
        db_pool_timeout:    Seconds to wait for a connection.
        batch_size:         Number of rows per ETL batch.
        max_retries:        Max retry attempts for transient failures.
        retry_delay_seconds: Seconds between retries.
    """

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,  # DB_HOST and db_host are equivalent
        extra="ignore",  # Silently ignore unknown env vars
    )

    # -------------------------------------------------------------------------
    # Pipeline Environment
    # -------------------------------------------------------------------------
    environment: Literal["development", "staging", "production"] = Field(
        default="development",
        description="Deployment environment.",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Python logging level name.",
    )

    # -------------------------------------------------------------------------
    # PostgreSQL Connection
    # -------------------------------------------------------------------------
    db_host: str = Field(default="localhost", description="PostgreSQL hostname.")
    db_port: int = Field(default=5432, ge=1, le=65535, description="PostgreSQL port.")
    db_name: str = Field(default="jobpulse", description="PostgreSQL database name.")
    db_user: str = Field(default="postgres", description="PostgreSQL username.")
    db_password: str = Field(description="PostgreSQL password.")
    db_schema: str = Field(default="public", description="PostgreSQL schema.")
    db_pool_size: int = Field(default=5, ge=1, description="Connection pool size.")
    db_max_overflow: int = Field(default=10, ge=0, description="Max extra connections.")
    db_pool_timeout: int = Field(
        default=30, ge=1, description="Pool timeout (seconds)."
    )

    # -------------------------------------------------------------------------
    # Pipeline Tuning
    # -------------------------------------------------------------------------
    batch_size: int = Field(default=1000, ge=1, description="Rows processed per batch.")
    max_retries: int = Field(
        default=3, ge=0, description="Retry attempts on transient failure."
    )
    retry_delay_seconds: int = Field(
        default=5, ge=0, description="Seconds between retry attempts."
    )

    # -------------------------------------------------------------------------
    # Computed / Derived Fields
    # -------------------------------------------------------------------------
    @computed_field  # type: ignore[misc]
    @property
    def database_url(self) -> str:
        """Construct the full SQLAlchemy connection URL from component fields.

        Returns:
            str: A valid PostgreSQL SQLAlchemy connection string.
        """
        from urllib.parse import quote_plus

        encoded_password = quote_plus(self.db_password)
        return (
            f"postgresql+psycopg2://{self.db_user}:{encoded_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @computed_field  # type: ignore[misc]
    @property
    def is_production(self) -> bool:
        """Check whether the pipeline is running in production mode.

        Returns:
            bool: True if environment is 'production'.
        """
        return self.environment == "production"

    @model_validator(mode="after")
    def validate_production_settings(self) -> Settings:
        """Apply stricter validation rules for production deployments.

        In production:
            - Log level must not be DEBUG (too verbose, potential data leakage)
            - db_password must not be the placeholder default value

        Returns:
            Settings: The validated Settings instance.

        Raises:
            ValueError: If production settings are invalid.
        """
        if self.is_production:
            if self.log_level == "DEBUG":
                raise ValueError(
                    "LOG_LEVEL=DEBUG is not allowed in production. "
                    "Use INFO or WARNING."
                )
            if self.db_password in ("", "password"):
                raise ValueError(
                    "DB_PASSWORD appears to be a placeholder. "
                    "Set a strong password for production."
                )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance (cached after first call).

    Uses functools.lru_cache so the .env file is only parsed once per
    process lifetime, regardless of how many modules call get_settings().

    Returns:
        Settings: Validated, immutable settings object.

    Example:
        >>> settings = get_settings()
        >>> settings.environment
        'development'
    """
    return Settings() # type: ignore[call-arg]
