"""Configuration loading, saving, and interactive setup for Onyx CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path

from platformdirs import user_config_dir
from pydantic import BaseModel


CONFIG_DIR = Path(user_config_dir("onyx-cli", ensure_exists=True))
CONFIG_FILE = CONFIG_DIR / "config.json"

# Environment variable names
ENV_SERVER_URL = "ONYX_SERVER_URL"
ENV_API_KEY = "ONYX_API_KEY"
ENV_API_KEY_LEGACY = "DANSWER_API_KEY"
ENV_PERSONA_ID = "ONYX_PERSONA_ID"


class OnyxCliConfig(BaseModel):
    server_url: str = "http://localhost:3000"
    api_key: str = ""
    default_persona_id: int = 0

    def is_configured(self) -> bool:
        return bool(self.api_key)


def load_config() -> OnyxCliConfig:
    """Load config from file, then apply environment variable overrides."""
    config = OnyxCliConfig()

    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
            config = OnyxCliConfig(**data)
        except (json.JSONDecodeError, ValueError):
            pass

    # Environment overrides take precedence
    if env_url := os.environ.get(ENV_SERVER_URL):
        config.server_url = env_url
    if env_key := os.environ.get(ENV_API_KEY):
        config.api_key = env_key
    elif env_key_legacy := os.environ.get(ENV_API_KEY_LEGACY):
        config.api_key = env_key_legacy
    if env_persona := os.environ.get(ENV_PERSONA_ID):
        try:
            config.default_persona_id = int(env_persona)
        except ValueError:
            pass

    return config


def save_config(config: OnyxCliConfig) -> None:
    """Save config to disk."""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(config.model_dump_json(indent=2))


def config_exists() -> bool:
    """Check if a config file exists on disk."""
    return CONFIG_FILE.exists()
