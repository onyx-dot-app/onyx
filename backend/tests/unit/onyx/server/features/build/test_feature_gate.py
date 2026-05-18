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
    """A non-NoOp provider that returns a fixed answer for the craft flag."""

    def __init__(self, enabled: bool) -> None:
        self._enabled = enabled
        self.calls: list[tuple[str, UUID]] = []

    def feature_enabled(
        self,
        flag_key: str,
        user_id: UUID,
        user_properties: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> bool:
        self.calls.append((flag_key, user_id))
        return self._enabled


def _make_user() -> MagicMock:
    """Build a minimal stand-in for `User` - only `.id` is read."""
    user = MagicMock()
    user.id = uuid4()
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

    assert is_onyx_craft_enabled(_make_user()) is True


def test_posthog_flag_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real provider's verdict wins regardless of ENABLE_CRAFT."""
    monkeypatch.setattr(build_utils, "ENABLE_CRAFT", False)
    provider = _StubPostHogProvider(enabled=True)
    monkeypatch.setattr(
        build_utils, "get_default_feature_flag_provider", lambda: provider
    )

    user = _make_user()
    assert is_onyx_craft_enabled(user) is True
    # The provider was consulted with the craft-enabled flag key for this user.
    assert provider.calls == [("onyx-craft-enabled", user.id)]
