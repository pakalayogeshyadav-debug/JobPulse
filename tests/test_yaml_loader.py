
import pytest
import yaml
from src.jobpulse.config.yaml_loader import load_yaml_config


def test_load_yaml_config_success(tmp_path):
    config_file = tmp_path / "settings.yaml"
    config_file.write_text("pipeline:\n  name: Test Pipeline", encoding="utf-8")
    
    config = load_yaml_config(config_file)
    assert config["pipeline"]["name"] == "Test Pipeline"

def test_load_yaml_config_not_found(tmp_path):
    config_file = tmp_path / "non_existent.yaml"
    with pytest.raises(FileNotFoundError):
        load_yaml_config(config_file)

def test_load_yaml_config_empty(tmp_path):
    config_file = tmp_path / "empty.yaml"
    config_file.write_text("", encoding="utf-8")
    config = load_yaml_config(config_file)
    assert config == {}

def test_load_yaml_config_malformed(tmp_path):
    config_file = tmp_path / "bad.yaml"
    config_file.write_text("bad: yaml: format: [", encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        load_yaml_config(config_file)
