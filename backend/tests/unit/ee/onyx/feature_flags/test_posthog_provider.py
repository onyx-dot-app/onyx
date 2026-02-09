"""Tests for PostHog feature flag provider fallback behavior."""

import importlib
import os
from uuid import UUID

from ee.onyx.configs import app_configs
from ee.onyx.feature_flags import posthog_provider
from ee.onyx.utils import posthog_client

_MISSING = object()


def _reload_feature_flag_modules() -> None:
    importlib.reload(app_configs)
    importlib.reload(posthog_client)
    importlib.reload(posthog_provider)


def _restore_posthog_api_key(original_value: object) -> None:
    if original_value is _MISSING:
        os.environ.pop("POSTHOG_API_KEY", None)
    else:
        os.environ["POSTHOG_API_KEY"] = str(original_value)


def test_defaults_when_posthog_disabled() -> None:
    """When PostHog is disabled, most flags default on but craft flags default off."""
    original_value: object = os.environ.get("POSTHOG_API_KEY", _MISSING)
    os.environ.pop("POSTHOG_API_KEY", None)

    try:
        _reload_feature_flag_modules()
        provider = posthog_provider.PostHogFeatureFlagProvider()
        user_id = UUID("79a75f76-6b63-43ee-b04c-a0c6806900bd")

        assert provider.feature_enabled("test-flag", user_id) is True
        assert provider.feature_enabled("onyx-craft-enabled", user_id) is False
        assert provider.feature_enabled("craft-has-usage-limits", user_id) is False
    finally:
        _restore_posthog_api_key(original_value)
        _reload_feature_flag_modules()
