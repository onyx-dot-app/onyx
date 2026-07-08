"""Feature gating tests.

`is_craft_enabled_for_user` decides whether a user sees Craft. The decision
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

from onyx.db.enums import AccountType
from onyx.feature_flags.interface import FeatureFlagProvider
from onyx.feature_flags.interface import NoOpFeatureFlagProvider
from onyx.server.features.build import utils as build_utils
from onyx.server.features.build.utils import is_craft_enabled_for_user
from onyx.server.settings.models import Settings


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
    """Build a minimal stand-in for `User` - only `.id`, `.email`,
    `.account_type`, and `.craft_enabled` are read."""
    user = MagicMock()
    user.id = uuid4()
    user.email = "user@tenant-dev.example"
    user.account_type = AccountType.STANDARD
    user.craft_enabled = True
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

    assert is_craft_enabled_for_user(_make_user()) is False


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

    assert is_craft_enabled_for_user(_make_user()) is True


def test_no_override_follows_workspace_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """craft_enabled=None means "inherit the workspace default": enabled when
    the default is on, disabled when it is off — always a strict bool."""
    monkeypatch.setattr(build_utils, "ENABLE_CRAFT", True)
    monkeypatch.setattr(
        build_utils,
        "get_default_feature_flag_provider",
        lambda: NoOpFeatureFlagProvider(),
    )

    user = _make_user()
    user.craft_enabled = None

    monkeypatch.setattr(
        build_utils,
        "load_settings",
        lambda: Settings(craft_default_enabled=True),
    )
    assert is_craft_enabled_for_user(user) is True

    monkeypatch.setattr(
        build_utils,
        "load_settings",
        lambda: Settings(craft_default_enabled=False),
    )
    assert is_craft_enabled_for_user(user) is False


def test_override_beats_workspace_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit per-user override wins over the workspace default (in both
    directions), without reading settings at all."""
    monkeypatch.setattr(build_utils, "ENABLE_CRAFT", True)
    monkeypatch.setattr(
        build_utils,
        "get_default_feature_flag_provider",
        lambda: NoOpFeatureFlagProvider(),
    )
    monkeypatch.setattr(
        build_utils,
        "load_settings",
        lambda: pytest.fail("settings should not be read for overridden users"),
    )

    user = _make_user()
    user.craft_enabled = True
    assert is_craft_enabled_for_user(user) is True

    user.craft_enabled = False
    assert is_craft_enabled_for_user(user) is False


def test_anonymous_user_never_gets_craft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared anonymous identity is excluded regardless of the deployment
    gate, without consulting the flag provider."""
    monkeypatch.setattr(build_utils, "ENABLE_CRAFT", True)
    monkeypatch.setattr(
        build_utils,
        "get_default_feature_flag_provider",
        lambda: pytest.fail(
            "the flag provider should not be consulted for the anonymous user"
        ),
    )

    user = _make_user()
    user.account_type = AccountType.ANONYMOUS
    user.craft_enabled = None
    assert is_craft_enabled_for_user(user) is False


def test_admin_disabled_user_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User.craft_enabled=False wins over any deployment-level enablement,
    without consulting the flag provider."""
    monkeypatch.setattr(build_utils, "ENABLE_CRAFT", True)
    monkeypatch.setattr(
        build_utils,
        "get_default_feature_flag_provider",
        lambda: pytest.fail(
            "the flag provider should not be consulted for a disabled user"
        ),
    )

    user = _make_user()
    user.craft_enabled = False
    assert is_craft_enabled_for_user(user) is False


def test_posthog_flag_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real provider's verdict wins regardless of ENABLE_CRAFT."""
    monkeypatch.setattr(build_utils, "ENABLE_CRAFT", False)
    monkeypatch.setattr(build_utils, "get_current_tenant_id", lambda: "tenant_dev")
    provider = _StubPostHogProvider(enabled=True)
    monkeypatch.setattr(
        build_utils, "get_default_feature_flag_provider", lambda: provider
    )

    user = _make_user()
    assert is_craft_enabled_for_user(user) is True
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
    assert is_craft_enabled_for_user(user) is False
    assert provider.calls == [
        (
            "onyx-craft-enabled",
            user.id,
            {"tenant_id": "tenant_other", "email": "user@tenant-dev.example"},
        )
    ]
