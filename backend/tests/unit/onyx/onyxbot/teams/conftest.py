"""Fixtures for Teams bot unit tests."""

import random
from collections.abc import Callable
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_team_config_enabled() -> MagicMock:
    """Team config that is enabled."""
    config = MagicMock()
    config.id = 1
    config.team_id = "team-abc-123"
    config.enabled = True
    config.default_persona_id = 1
    return config


@pytest.fixture
def mock_team_config_disabled() -> MagicMock:
    """Team config that is disabled."""
    config = MagicMock()
    config.id = 2
    config.team_id = "team-abc-123"
    config.enabled = False
    config.default_persona_id = None
    return config


@pytest.fixture
def mock_channel_config_factory() -> Callable[..., MagicMock]:
    """Factory fixture for creating channel configs with various settings."""

    def _make_config(
        enabled: bool = True,
        require_bot_mention: bool = True,
        persona_override_id: int | None = None,
    ) -> MagicMock:
        config = MagicMock()
        config.id = random.randint(1, 1000)
        config.channel_id = "19:channel-xyz@thread.tacv2"
        config.enabled = enabled
        config.require_bot_mention = require_bot_mention
        config.persona_override_id = persona_override_id
        return config

    return _make_config


@pytest.fixture
def sample_activity_dict() -> dict:
    """Sample Teams Activity as a dict."""
    return {
        "type": "message",
        "text": "<at>Onyx</at> What is our deployment process?",
        "from": {
            "id": "29:user-id-123",
            "name": "Test User",
        },
        "recipient": {
            "id": "28:bot-id-456",
            "name": "Onyx",
        },
        "channelData": {
            "team": {
                "id": "team-abc-123",
                "name": "Engineering",
            },
            "channel": {
                "id": "19:channel-xyz@thread.tacv2",
                "name": "general",
            },
        },
        "entities": [
            {
                "type": "mention",
                "mentioned": {
                    "id": "28:bot-id-456",
                    "name": "Onyx",
                },
                "text": "<at>Onyx</at>",
            }
        ],
    }


@pytest.fixture
def sample_dm_activity_dict() -> dict:
    """Sample Teams DM Activity (no team context)."""
    return {
        "type": "message",
        "text": "Hello bot",
        "from": {
            "id": "29:user-id-123",
            "name": "Test User",
        },
        "recipient": {
            "id": "28:bot-id-456",
            "name": "Onyx",
        },
        "channelData": {},
        "entities": [],
    }
