"""Configuration loader for LadderBot.

Loads config.yaml, merges with defaults, validates required fields.
Provides a first-run wizard if config.yaml is missing.
"""
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """Raised when configuration is invalid."""
    pass


# Default configuration -- all optional fields with sensible values
DEFAULT_CONFIG: dict[str, Any] = {
    "odds_api_key": "",
    "discord_webhook_url": "",
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

# Placeholder values that indicate the user hasn't configured the field
_PLACEHOLDERS = {
    "odds_api_key": {"your-key-here", ""},
    "discord_webhook_url": {"https://discord.com/api/webhooks/...", ""},
}

# Default config file path (project root)
_DEFAULT_CONFIG_PATH = str(Path(__file__).parent.parent / "config.yaml")


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Override values win."""
    result = deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: str | None = None) -> dict[str, Any]:
    """Load config from YAML file and merge with defaults.

    Args:
        config_path: Path to config.yaml. Defaults to project root config.yaml.

    Returns:
        Merged configuration dictionary.

    Raises:
        FileNotFoundError: If config file does not exist.
    """
    if config_path is None:
        config_path = _DEFAULT_CONFIG_PATH

    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(path) as f:
        user_config = yaml.safe_load(f) or {}

    return _deep_merge(DEFAULT_CONFIG, user_config)


def validate_config(config: dict[str, Any]) -> None:
    """Validate that required fields are present and not placeholders.

    Args:
        config: Configuration dictionary to validate.

    Raises:
        ConfigError: If a required field is missing or still a placeholder.
    """
    # Check odds_api_key
    api_key = config.get("odds_api_key", "")
    if not api_key or api_key in _PLACEHOLDERS["odds_api_key"]:
        raise ConfigError(
            "odds_api_key is required. Get a free key at https://the-odds-api.com"
        )

    # Check discord_webhook_url
    webhook = config.get("discord_webhook_url", "")
    if not webhook or webhook in _PLACEHOLDERS["discord_webhook_url"]:
        raise ConfigError(
            "discord_webhook_url is required. Create a webhook in Discord: "
            "Server Settings -> Integrations -> Webhooks -> New Webhook -> Copy URL"
        )


def first_run_wizard(config_path: str | None = None) -> dict[str, Any]:
    """Interactive wizard to create config.yaml on first run.

    Prompts the user for required fields and writes the config file.

    Args:
        config_path: Where to write config.yaml. Defaults to project root.

    Returns:
        The created configuration dictionary.
    """
    if config_path is None:
        config_path = _DEFAULT_CONFIG_PATH

    print("=" * 60)
    print("  LADDERBOT -- First-Run Setup")
    print("=" * 60)
    print()
    print("No config.yaml found. Let's create one.")
    print()

    # Get API key
    print("1. The Odds API key (free at https://the-odds-api.com)")
    api_key = input("   API key: ").strip()
    while not api_key or api_key in _PLACEHOLDERS["odds_api_key"]:
        print("   Please enter a valid API key.")
        api_key = input("   API key: ").strip()

    print()

    # Get Discord webhook
    print("2. Discord webhook URL")
    print("   (Server Settings -> Integrations -> Webhooks -> New Webhook -> Copy URL)")
    webhook = input("   Webhook URL: ").strip()
    while not webhook or webhook in _PLACEHOLDERS["discord_webhook_url"]:
        print("   Please enter a valid webhook URL.")
        webhook = input("   Webhook URL: ").strip()

    print()

    # Build config
    config = deepcopy(DEFAULT_CONFIG)
    config["odds_api_key"] = api_key
    config["discord_webhook_url"] = webhook

    # Write file
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    print(f"Config written to {config_path}")
    print("Edit this file to customize ladder, parlay, and model settings.")
    print()

    return config


def get_config(config_path: str | None = None, interactive: bool = True) -> dict[str, Any]:
    """High-level config loader: load, validate, or run wizard.

    Args:
        config_path: Path to config.yaml.
        interactive: If True and config missing, run first-run wizard.
                     If False and config missing, raise FileNotFoundError.

    Returns:
        Validated configuration dictionary.
    """
    if config_path is None:
        config_path = _DEFAULT_CONFIG_PATH

    if not Path(config_path).exists():
        if interactive:
            return first_run_wizard(config_path)
        else:
            raise FileNotFoundError(f"Config file not found: {config_path}")

    config = load_config(config_path)
    validate_config(config)
    return config
