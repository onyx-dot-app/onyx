"""Tests for PostHog client initialization behavior."""

import importlib
import os

from ee.onyx.configs import app_configs
from ee.onyx.utils import posthog_client

_MISSING = object()


def _reload_posthog_modules() -> None:
    importlib.reload(app_configs)
    importlib.reload(posthog_client)


def _restore_posthog_api_key(original_value: object) -> None:
    if original_value is _MISSING:
        os.environ.pop("POSTHOG_API_KEY", None)
    else:
        os.environ["POSTHOG_API_KEY"] = str(original_value)


def test_posthog_is_noop_when_api_key_missing() -> None:
    """PostHog should be a no-op client when POSTHOG_API_KEY is not provided."""
    original_value: object = os.environ.get("POSTHOG_API_KEY", _MISSING)
    os.environ.pop("POSTHOG_API_KEY", None)

    try:
        _reload_posthog_modules()

        assert app_configs.POSTHOG_API_KEY is None
        assert posthog_client.POSTHOG_ENABLED is False
        assert isinstance(posthog_client.posthog, posthog_client.NoOpPosthogClient)

        # No-op client calls should return immediately and not raise.
        posthog_client.posthog.capture("test-user", "test-event", {"k": "v"})
        posthog_client.posthog.flush()
        assert posthog_client.posthog.feature_enabled("test-flag", "test-user") is True
        assert (
            posthog_client.posthog.feature_enabled("onyx-craft-enabled", "test-user")
            is False
        )
        assert (
            posthog_client.posthog.feature_enabled(
                "craft-has-usage-limits", "test-user"
            )
            is False
        )
    finally:
        _restore_posthog_api_key(original_value)
        _reload_posthog_modules()


def test_posthog_is_noop_when_api_key_is_whitespace() -> None:
    """Whitespace POSTHOG_API_KEY should be treated as unset."""
    original_value: object = os.environ.get("POSTHOG_API_KEY", _MISSING)
    os.environ["POSTHOG_API_KEY"] = "   "

    try:
        _reload_posthog_modules()

        assert app_configs.POSTHOG_API_KEY is None
        assert posthog_client.POSTHOG_ENABLED is False
        assert isinstance(posthog_client.posthog, posthog_client.NoOpPosthogClient)
    finally:
        _restore_posthog_api_key(original_value)
        _reload_posthog_modules()
