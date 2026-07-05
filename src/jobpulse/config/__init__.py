"""jobpulse.config — Configuration management sub-package.

This sub-package is responsible for:
    - Loading environment variables from .env files
    - Parsing YAML/TOML configuration files
    - Exposing a validated, type-safe Settings object via Pydantic

Design Philosophy:
    - ALL configuration lives here — never scattered across modules.
    - Settings are loaded once and passed down (dependency injection).
    - Secrets (passwords, API keys) come ONLY from environment variables.
    - Non-secret runtime config (batch sizes, paths) can live in YAML.

Typical Usage:
    from jobpulse.config.settings import get_settings

    settings = get_settings()
    print(settings.db_host)
"""
