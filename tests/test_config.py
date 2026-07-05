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


class TestSettings:
    """Tests for the Settings Pydantic model."""

    def test_default_environment_is_development(self) -> None:
        """Settings should default to 'development' environment."""
        # TODO: Implement after settings.py is importable
        # from jobpulse.config.settings import Settings
        # settings = Settings(db_password="test_password")
        # assert settings.environment == "development"
        pytest.skip("Implement when settings.py dependencies are installed.")

    def test_database_url_is_constructed_correctly(self) -> None:
        """database_url property should combine host, port, name, user, password."""
        # TODO: from jobpulse.config.settings import Settings
        # settings = Settings(
        #     db_host="myhost", db_port=5432, db_name="mydb",
        #     db_user="myuser", db_password="mypass"
        # )
        # expected = "postgresql+psycopg2://myuser:mypass@myhost:5432/mydb"
        # assert settings.database_url == expected
        pytest.skip("Implement when dependencies are installed.")

    def test_production_blocks_debug_log_level(self) -> None:
        """Settings should raise ValueError if LOG_LEVEL=DEBUG in production."""
        # TODO:
        # with pytest.raises(ValueError, match="DEBUG is not allowed in production"):
        #     Settings(environment="production", log_level="DEBUG", db_password="x")
        pytest.skip("Implement when dependencies are installed.")

    def test_get_settings_returns_same_instance(self) -> None:
        """get_settings() should return the same cached instance."""
        # TODO:
        # from jobpulse.config.settings import get_settings
        # s1 = get_settings()
        # s2 = get_settings()
        # assert s1 is s2
        pytest.skip("Implement when dependencies are installed.")


class TestYamlLoader:
    """Tests for the YAML configuration file loader."""

    def test_load_yaml_config_returns_dict(self, tmp_path) -> None:
        """load_yaml_config() should return a dictionary from a valid YAML file."""
        # TODO:
        # from jobpulse.config.yaml_loader import load_yaml_config
        # config_file = tmp_path / "test_config.yaml"
        # config_file.write_text("pipeline:\n  name: test\n")
        # result = load_yaml_config(config_path=config_file)
        # assert result["pipeline"]["name"] == "test"
        pytest.skip("Implement when dependencies are installed.")

    def test_load_yaml_raises_for_missing_file(self, tmp_path) -> None:
        """load_yaml_config() should raise FileNotFoundError for missing files."""
        # TODO:
        # from jobpulse.config.yaml_loader import load_yaml_config
        # with pytest.raises(FileNotFoundError):
        #     load_yaml_config(config_path=tmp_path / "nonexistent.yaml")
        pytest.skip("Implement when dependencies are installed.")
