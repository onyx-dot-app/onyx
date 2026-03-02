"""Tests for configuration loading and saving."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from onyx_cli.config import (
    ENV_API_KEY,
    ENV_API_KEY_LEGACY,
    ENV_PERSONA_ID,
    ENV_SERVER_URL,
    OnyxCliConfig,
    load_config,
    save_config,
)


class TestOnyxCliConfig:
    """Tests for the config model."""

    def test_defaults(self) -> None:
        config = OnyxCliConfig()
        assert config.server_url == "http://localhost:3000"
        assert config.api_key == ""
        assert config.default_persona_id == 0

    def test_is_configured_false_without_api_key(self) -> None:
        config = OnyxCliConfig()
        assert config.is_configured() is False

    def test_is_configured_true_with_api_key(self) -> None:
        config = OnyxCliConfig(api_key="some-key")
        assert config.is_configured() is True


class TestLoadConfig:
    """Tests for config loading with env var overrides."""

    def test_load_defaults_when_no_file(self, tmp_path: Path) -> None:
        with patch("onyx_cli.config.CONFIG_FILE", tmp_path / "nonexistent.json"):
            config = load_config()
        assert config.server_url == "http://localhost:3000"
        assert config.api_key == ""

    def test_load_from_file(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "server_url": "https://my-onyx.example.com",
            "api_key": "test-key-123",
            "default_persona_id": 5,
        }))

        with patch("onyx_cli.config.CONFIG_FILE", config_file):
            config = load_config()

        assert config.server_url == "https://my-onyx.example.com"
        assert config.api_key == "test-key-123"
        assert config.default_persona_id == 5

    def test_load_handles_corrupt_file(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text("not valid json {{{")

        with patch("onyx_cli.config.CONFIG_FILE", config_file):
            config = load_config()

        # Should fall back to defaults
        assert config.server_url == "http://localhost:3000"

    def test_env_override_server_url(self, tmp_path: Path) -> None:
        with (
            patch("onyx_cli.config.CONFIG_FILE", tmp_path / "nonexistent.json"),
            patch.dict(os.environ, {ENV_SERVER_URL: "https://env-override.com"}),
        ):
            config = load_config()
        assert config.server_url == "https://env-override.com"

    def test_env_override_api_key(self, tmp_path: Path) -> None:
        with (
            patch("onyx_cli.config.CONFIG_FILE", tmp_path / "nonexistent.json"),
            patch.dict(os.environ, {ENV_API_KEY: "env-key"}),
        ):
            config = load_config()
        assert config.api_key == "env-key"

    def test_env_override_legacy_api_key(self, tmp_path: Path) -> None:
        with (
            patch("onyx_cli.config.CONFIG_FILE", tmp_path / "nonexistent.json"),
            patch.dict(os.environ, {ENV_API_KEY_LEGACY: "legacy-key"}, clear=False),
        ):
            # Make sure ONYX_API_KEY is not set
            env = os.environ.copy()
            env.pop(ENV_API_KEY, None)
            env[ENV_API_KEY_LEGACY] = "legacy-key"
            with patch.dict(os.environ, env, clear=True):
                config = load_config()
        assert config.api_key == "legacy-key"

    def test_env_override_persona_id(self, tmp_path: Path) -> None:
        with (
            patch("onyx_cli.config.CONFIG_FILE", tmp_path / "nonexistent.json"),
            patch.dict(os.environ, {ENV_PERSONA_ID: "42"}),
        ):
            config = load_config()
        assert config.default_persona_id == 42

    def test_env_override_invalid_persona_id(self, tmp_path: Path) -> None:
        with (
            patch("onyx_cli.config.CONFIG_FILE", tmp_path / "nonexistent.json"),
            patch.dict(os.environ, {ENV_PERSONA_ID: "not-a-number"}),
        ):
            config = load_config()
        assert config.default_persona_id == 0  # default

    def test_env_overrides_file_values(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "server_url": "https://file-url.com",
            "api_key": "file-key",
        }))

        with (
            patch("onyx_cli.config.CONFIG_FILE", config_file),
            patch.dict(os.environ, {ENV_SERVER_URL: "https://env-url.com"}),
        ):
            config = load_config()

        # Env overrides file for server_url
        assert config.server_url == "https://env-url.com"
        # File value kept for api_key (no env override)
        assert config.api_key == "file-key"


class TestSaveConfig:
    """Tests for config saving."""

    def test_save_and_reload(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"

        config = OnyxCliConfig(
            server_url="https://saved.example.com",
            api_key="saved-key",
            default_persona_id=10,
        )

        with patch("onyx_cli.config.CONFIG_FILE", config_file):
            save_config(config)

        assert config_file.exists()
        data = json.loads(config_file.read_text())
        assert data["server_url"] == "https://saved.example.com"
        assert data["api_key"] == "saved-key"
        assert data["default_persona_id"] == 10

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        config_file = tmp_path / "deep" / "nested" / "config.json"

        with patch("onyx_cli.config.CONFIG_FILE", config_file):
            save_config(OnyxCliConfig(api_key="test"))

        assert config_file.exists()
