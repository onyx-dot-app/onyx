"""Feature gating tests.

`is_onyx_craft_enabled` decides whether a user sees Craft. The decision
collapses two inputs: the `ENABLE_CRAFT` env var (used when no real feature
flag provider is configured) and the PostHog `onyx-craft-enabled` flag
(used otherwise). These tests pin the precedence: PostHog wins when present,
env is the fallback when no provider is wired up.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import UUID
from uuid import uuid4

import pytest

from onyx.feature_flags.interface import FeatureFlagProvider
from onyx.feature_flags.interface import NoOpFeatureFlagProvider
from onyx.server.features.build import utils as build_utils
from onyx.server.features.build.utils import is_onyx_craft_enabled


class _StubPostHogProvider(FeatureFlagProvider):
    """A non-NoOp provider that returns a fixed answer for the craft flag.

    Inherits the base `feature_enabled_for_user_tenant`, which is the method the
    gate calls — so `calls` captures the `user_properties` (including
    `tenant_id`) that get forwarded to PostHog.
    """

    def __init__(self, enabled: bool) -> None:
        self._enabled = enabled
        self.calls: list[tuple[str, UUID, dict[str, Any] | None]] = []

    def feature_enabled(
        self,
        flag_key: str,
        user_id: UUID,
        user_properties: dict[str, Any] | None = None,
    ) -> bool:
        self.calls.append((flag_key, user_id, user_properties))
        return self._enabled


def _make_user() -> MagicMock:
    """Build a minimal stand-in for `User` - only `.id` and `.email` are read."""
    user = MagicMock()
    user.id = uuid4()
    user.email = "user@tenant-dev.example"
    return user


def test_disabled_when_env_and_flag_both_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No PostHog provider and ENABLE_CRAFT=False -> Craft is disabled."""
    monkeypatch.setattr(build_utils, "ENABLE_CRAFT", False)
    monkeypatch.setattr(
        build_utils,
        "get_default_feature_flag_provider",
        lambda: NoOpFeatureFlagProvider(),
    )

    assert is_onyx_craft_enabled(_make_user()) is False


def test_enabled_via_env_when_no_flag_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No PostHog provider and ENABLE_CRAFT=True -> Craft is enabled via env."""
    monkeypatch.setattr(build_utils, "ENABLE_CRAFT", True)
    monkeypatch.setattr(
        build_utils,
        "get_default_feature_flag_provider",
        lambda: NoOpFeatureFlagProvider(),
    )
    # The env/NoOp path must not touch the tenant contextvar, which can raise
    # in multi-tenant mode when no tenant is set.
    monkeypatch.setattr(
        build_utils,
        "get_current_tenant_id",
        lambda: pytest.fail(
            "get_current_tenant_id should not be called on the env path"
        ),
    )

    assert is_onyx_craft_enabled(_make_user()) is True


def test_posthog_flag_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real provider's verdict wins regardless of ENABLE_CRAFT."""
    monkeypatch.setattr(build_utils, "ENABLE_CRAFT", False)
    monkeypatch.setattr(build_utils, "get_current_tenant_id", lambda: "tenant_dev")
    provider = _StubPostHogProvider(enabled=True)
    monkeypatch.setattr(
        build_utils, "get_default_feature_flag_provider", lambda: provider
    )

    user = _make_user()
    assert is_onyx_craft_enabled(user) is True
    # The provider was consulted with the craft-enabled flag key for this user.
    assert provider.calls == [
        (
            "onyx-craft-enabled",
            user.id,
            {"tenant_id": "tenant_dev", "email": "user@tenant-dev.example"},
        )
    ]


def test_posthog_flag_disables_when_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real provider returning False disables Craft even if ENABLE_CRAFT=True."""
    monkeypatch.setattr(build_utils, "ENABLE_CRAFT", True)
    monkeypatch.setattr(build_utils, "get_current_tenant_id", lambda: "tenant_other")
    provider = _StubPostHogProvider(enabled=False)
    monkeypatch.setattr(
        build_utils, "get_default_feature_flag_provider", lambda: provider
    )

    user = _make_user()
    assert is_onyx_craft_enabled(user) is False
    assert provider.calls == [
        (
            "onyx-craft-enabled",
            user.id,
            {"tenant_id": "tenant_other", "email": "user@tenant-dev.example"},
        )
    ]
