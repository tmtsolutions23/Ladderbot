"""Tests for config loader."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from ladderbot.config import load_config, validate_config, ConfigError, DEFAULT_CONFIG


@pytest.fixture
def config_dir(tmp_path):
    """Provide a temp directory for config files."""
    return tmp_path


@pytest.fixture
def valid_config_file(config_dir):
    """Write a valid config.yaml and return its path."""
    config = {
        "odds_api_key": "test-key-12345",
        "discord_webhook_url": "https://discord.com/api/webhooks/123/abc",
        "ladder": {
            "starting_amount": 10.0,
            "target_amount": 1000.0,
            "max_attempts": 50,
        },
        "parlay": {
            "min_legs": 2,
            "max_legs": 2,
            "target_odds_min": 150,
            "target_odds_max": 300,
            "min_edge_per_leg": 0.02,
            "min_edge_cold_start": 0.03,
        },
        "model": {
            "rolling_window": 20,
            "use_xgboost": False,
            "cold_start_games": 20,
        },
        "sports": {
            "nba": True,
            "nhl": True,
        },
        "run_time": "11:00",
        "pre_game_refresh": 120,
        "scheduler": "manual",
    }
    path = config_dir / "config.yaml"
    path.write_text(yaml.dump(config))
    return str(path)


class TestLoadConfig:
    def test_loads_valid_config(self, valid_config_file):
        config = load_config(valid_config_file)
        assert config["odds_api_key"] == "test-key-12345"
        assert config["discord_webhook_url"] == "https://discord.com/api/webhooks/123/abc"

    def test_applies_defaults_for_missing_sections(self, config_dir):
        """A minimal config with just required fields should get defaults filled in."""
        minimal = {
            "odds_api_key": "key-123",
            "discord_webhook_url": "https://discord.com/api/webhooks/1/x",
        }
        path = config_dir / "config.yaml"
        path.write_text(yaml.dump(minimal))
        config = load_config(str(path))
        assert config["ladder"]["starting_amount"] == 10.0
        assert config["ladder"]["target_amount"] == 1000.0
        assert config["parlay"]["min_edge_per_leg"] == 0.02
        assert config["model"]["rolling_window"] == 20
        assert config["sports"]["nba"] is True
        assert config["scheduler"] == "manual"

    def test_file_not_found_raises(self, config_dir):
        with pytest.raises(FileNotFoundError):
            load_config(str(config_dir / "nonexistent.yaml"))

    def test_user_values_override_defaults(self, config_dir):
        custom = {
            "odds_api_key": "key-123",
            "discord_webhook_url": "https://discord.com/api/webhooks/1/x",
            "ladder": {"starting_amount": 25.0},
            "parlay": {"min_edge_per_leg": 0.05},
        }
        path = config_dir / "config.yaml"
        path.write_text(yaml.dump(custom))
        config = load_config(str(path))
        assert config["ladder"]["starting_amount"] == 25.0
        assert config["parlay"]["min_edge_per_leg"] == 0.05
        # Other defaults still present
        assert config["ladder"]["target_amount"] == 1000.0


class TestValidateConfig:
    def test_missing_odds_api_key(self, config_dir):
        bad = {"discord_webhook_url": "https://discord.com/api/webhooks/1/x"}
        path = config_dir / "config.yaml"
        path.write_text(yaml.dump(bad))
        config = load_config(str(path))
        with pytest.raises(ConfigError, match="odds_api_key"):
            validate_config(config)

    def test_missing_discord_webhook(self, config_dir):
        bad = {"odds_api_key": "key-123"}
        path = config_dir / "config.yaml"
        path.write_text(yaml.dump(bad))
        config = load_config(str(path))
        with pytest.raises(ConfigError, match="discord_webhook_url"):
            validate_config(config)

    def test_placeholder_api_key_rejected(self, config_dir):
        bad = {
            "odds_api_key": "your-key-here",
            "discord_webhook_url": "https://discord.com/api/webhooks/1/x",
        }
        path = config_dir / "config.yaml"
        path.write_text(yaml.dump(bad))
        config = load_config(str(path))
        with pytest.raises(ConfigError, match="odds_api_key"):
            validate_config(config)

    def test_placeholder_webhook_rejected(self, config_dir):
        bad = {
            "odds_api_key": "real-key",
            "discord_webhook_url": "https://discord.com/api/webhooks/...",
        }
        path = config_dir / "config.yaml"
        path.write_text(yaml.dump(bad))
        config = load_config(str(path))
        with pytest.raises(ConfigError, match="discord_webhook_url"):
            validate_config(config)

    def test_valid_config_passes(self, valid_config_file):
        config = load_config(valid_config_file)
        validate_config(config)  # Should not raise


class TestDefaultConfig:
    def test_default_config_has_all_sections(self):
        assert "ladder" in DEFAULT_CONFIG
        assert "parlay" in DEFAULT_CONFIG
        assert "model" in DEFAULT_CONFIG
        assert "sports" in DEFAULT_CONFIG
        assert "run_time" in DEFAULT_CONFIG
        assert "scheduler" in DEFAULT_CONFIG
