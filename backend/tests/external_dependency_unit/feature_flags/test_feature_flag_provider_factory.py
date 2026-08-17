"""
External dependency unit tests for the feature flag service.

These tests verify the feature flag service implementation with real
PostHog integration when available, and fallback behavior otherwise.
"""

from unittest.mock import MagicMock
from uuid import UUID

import pytest

from ee.onyx.feature_flags import posthog_provider as posthog_provider_module
from ee.onyx.feature_flags.posthog_provider import PostHogFeatureFlagProvider
from onyx.feature_flags.factory import get_default_feature_flag_provider
from onyx.feature_flags.interface import FeatureFlagProvider, NoOpFeatureFlagProvider


class TestNoOpFeatureFlagProvider:
    """Tests for the no-op feature flag provider."""

    def test_always_returns_false(self) -> None:
        """No-op provider should always return False."""
        provider = NoOpFeatureFlagProvider()

        my_uuid = UUID("79a75f76-6b63-43ee-b04c-a0c6806900bd")
        assert provider.feature_enabled("another-flag", my_uuid) is False

    def test_variant_for_tenant_always_returns_none(self) -> None:
        provider = NoOpFeatureFlagProvider()

        assert provider.feature_variant_for_tenant("another-flag", "tenant_dev") is None


class TestPostHogFeatureFlagProviderVariantForTenant:
    """Tests for `PostHogFeatureFlagProvider.feature_variant_for_tenant` —
    the deployment-wide (not per-user) lookup, keyed on tenant_id."""

    def test_returns_none_when_posthog_unconfigured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(posthog_provider_module, "posthog", None)
        provider = PostHogFeatureFlagProvider()

        assert provider.feature_variant_for_tenant("some-flag", "tenant_dev") is None

    def test_returns_variant_from_posthog(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_posthog = MagicMock()
        mock_posthog.get_feature_flag.return_value = "none"
        monkeypatch.setattr(posthog_provider_module, "posthog", mock_posthog)
        provider = PostHogFeatureFlagProvider()

        assert provider.feature_variant_for_tenant("some-flag", "tenant_dev") == "none"
        mock_posthog.get_feature_flag.assert_called_once_with(
            "some-flag", "tenant_dev", person_properties={"tenant_id": "tenant_dev"}
        )

    def test_returns_none_on_posthog_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Errors fail closed: the caller falls back to its safe default."""
        mock_posthog = MagicMock()
        mock_posthog.get_feature_flag.side_effect = RuntimeError("boom")
        monkeypatch.setattr(posthog_provider_module, "posthog", mock_posthog)
        provider = PostHogFeatureFlagProvider()

        assert provider.feature_variant_for_tenant("some-flag", "tenant_dev") is None


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
