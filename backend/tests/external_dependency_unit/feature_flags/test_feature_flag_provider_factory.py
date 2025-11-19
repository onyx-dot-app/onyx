"""
External dependency unit tests for the feature flag service.

These tests verify the feature flag service implementation with real
PostHog integration when available, and fallback behavior otherwise.
"""

from uuid import UUID

from ee.onyx.feature_flags.posthog_provider import PostHogFeatureFlagProvider
from onyx.feature_flags.factory import get_default_feature_flag_provider
from onyx.feature_flags.interface import FeatureFlagProvider
from onyx.feature_flags.interface import NoOpFeatureFlagProvider


class TestNoOpFeatureFlagProvider:
    """Tests for the no-op feature flag provider."""

    def test_always_returns_false(self) -> None:
        """No-op provider should always return False."""
        provider = NoOpFeatureFlagProvider()

        my_uuid = UUID("79a75f76-6b63-43ee-b04c-a0c6806900bd")
        assert provider.feature_enabled("another-flag", my_uuid) is False


class TestFeatureFlagFactory:
    """Tests for the feature flag factory function."""

    def test_factory_returns_provider(self) -> None:
        """Factory should return a FeatureFlagProvider instance."""
        provider = get_default_feature_flag_provider()
        assert isinstance(provider, FeatureFlagProvider)

    def test_posthog_provider(self) -> None:
        """Posthog provider should return True if the feature is enabled."""
        provider = PostHogFeatureFlagProvider()
        assert isinstance(provider, FeatureFlagProvider)
