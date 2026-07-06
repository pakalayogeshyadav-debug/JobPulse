"""
tests/test_config.py — Unit tests for configuration management.

Tests:
    - Settings loads correctly with valid environment variables
    - Settings raises ValueError for invalid log level in production
    - YAML loader reads settings.yaml correctly
    - get_settings() returns cached singleton
"""

from __future__ import annotations

import pytest
from jobpulse.config.settings import Settings, get_settings
from jobpulse.config.yaml_loader import load_yaml_config


class TestSettings:
    """Tests for the Settings Pydantic model."""

    @pytest.fixture(autouse=True)
    def mock_env(self, monkeypatch):
        """Provide minimal required environment variables for Settings."""
        monkeypatch.setenv("DB_PASSWORD", "test_password")

    def test_default_environment_is_development(self) -> None:
        """Settings should default to 'development' environment."""
        settings = Settings()
        assert settings.environment == "development"

    def test_database_url_is_constructed_correctly(self) -> None:
        """database_url property should combine host, port, name, user, password."""
        settings = Settings(
            db_host="myhost",
            db_port=5432,
            db_name="mydb",
            db_user="myuser",
            db_password="mypass",
        )
        expected = "postgresql+psycopg2://myuser:mypass@myhost:5432/mydb"
        assert settings.database_url == expected

    def test_production_blocks_debug_log_level(self, monkeypatch) -> None:
        """Settings should raise ValueError if LOG_LEVEL=DEBUG in production."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        with pytest.raises(
            ValueError, match="LOG_LEVEL=DEBUG is not allowed in production"
        ):
            Settings()

    def test_get_settings_returns_same_instance(self) -> None:
        """get_settings() should return the same cached instance."""
        # Clear the lru_cache for get_settings to avoid test pollution
        get_settings.cache_clear()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2


class TestYamlLoader:
    """Tests for the YAML configuration file loader."""

    def test_load_yaml_config_returns_dict(self, tmp_path) -> None:
        """load_yaml_config() should return a dictionary from a valid YAML file."""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text("pipeline:\n  name: test\n")
        result = load_yaml_config(config_path=config_file)
        assert result["pipeline"]["name"] == "test"

    def test_load_yaml_raises_for_missing_file(self, tmp_path) -> None:
        """load_yaml_config() should raise FileNotFoundError for missing files."""
        with pytest.raises(FileNotFoundError):
            load_yaml_config(config_path=tmp_path / "nonexistent.yaml")
