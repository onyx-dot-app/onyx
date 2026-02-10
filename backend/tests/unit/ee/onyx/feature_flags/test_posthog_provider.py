from typing import Any
from uuid import UUID

from ee.onyx.feature_flags.factory import get_posthog_feature_flag_provider
from ee.onyx.feature_flags.posthog_provider import PostHogFeatureFlagProvider
from onyx.feature_flags.interface import NoOpFeatureFlagProvider


def test_factory_returns_noop_provider_when_posthog_disabled(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr("ee.onyx.feature_flags.factory.POSTHOG_API_KEY", None)

    provider = get_posthog_feature_flag_provider()
    assert isinstance(provider, NoOpFeatureFlagProvider)


def test_posthog_provider_returns_false_when_client_not_configured(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr("ee.onyx.feature_flags.posthog_provider.posthog", None)

    provider = PostHogFeatureFlagProvider()
    assert (
        provider.feature_enabled(
            flag_key="feature-test",
            user_id=UUID("79a75f76-6b63-43ee-b04c-a0c6806900bd"),
            user_properties={"tenant_id": "tenant_1"},
        )
        is False
    )
