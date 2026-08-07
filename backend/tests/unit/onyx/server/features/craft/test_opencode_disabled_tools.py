"""`get_opencode_disabled_tools` decides which opencode tools are disabled in a
sandbox session. The decision collapses two inputs: the `OPENCODE_DISABLED_TOOLS`
env var (used when no real feature flag provider is configured, or the flag's
variant is unset/unrecognized) and the PostHog `onyx-craft-opencode-disabled-tools`
multivariate flag (used otherwise) — each variant key maps to a fixed tools
list in `OPENCODE_DISABLED_TOOLS_VARIANTS`.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from onyx.feature_flags.interface import FeatureFlagProvider, NoOpFeatureFlagProvider
from onyx.server.features.build import utils as build_utils
from onyx.server.features.build.utils import get_opencode_disabled_tools


class _StubPostHogProvider(FeatureFlagProvider):
    """A non-NoOp provider that returns a fixed variant for the disabled-tools
    flag.

    Inherits the base `feature_variant_for_user_tenant`, which is the method
    the resolver calls — so `calls` captures the `user_properties` (including
    `tenant_id`) that get forwarded to PostHog.
    """

    def __init__(self, variant: str | bool | None) -> None:
        self._variant = variant
        self.calls: list[tuple[str, UUID, dict[str, Any] | None]] = []

    def feature_enabled(
        self,
        flag_key: str,
        user_id: UUID,
        user_properties: dict[str, Any] | None = None,
    ) -> bool:
        raise NotImplementedError("not exercised by these tests")

    def feature_variant(
        self,
        flag_key: str,
        user_id: UUID,
        user_properties: dict[str, Any] | None = None,
    ) -> str | bool | None:
        self.calls.append((flag_key, user_id, user_properties))
        return self._variant


def _make_user() -> MagicMock:
    """Build a minimal stand-in for `User` - only `.id` and `.email` are read."""
    user = MagicMock()
    user.id = uuid4()
    user.email = "user@tenant-dev.example"
    return user


def test_env_default_when_no_flag_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build_utils, "OPENCODE_DISABLED_TOOLS", ["question"])
    monkeypatch.setattr(
        build_utils,
        "get_default_feature_flag_provider",
        lambda: NoOpFeatureFlagProvider(),
    )
    # The NoOp path must not touch the tenant contextvar.
    monkeypatch.setattr(
        build_utils,
        "get_current_tenant_id",
        lambda: pytest.fail(
            "get_current_tenant_id should not be called on the NoOp path"
        ),
    )

    assert get_opencode_disabled_tools(_make_user()) == ["question"]


def test_env_default_when_variant_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build_utils, "OPENCODE_DISABLED_TOOLS", ["question"])
    monkeypatch.setattr(build_utils, "get_current_tenant_id", lambda: "tenant_dev")
    provider = _StubPostHogProvider(variant=None)
    monkeypatch.setattr(
        build_utils, "get_default_feature_flag_provider", lambda: provider
    )

    assert get_opencode_disabled_tools(_make_user()) == ["question"]


def test_none_variant_disables_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The "none" variant is a deliberate admin choice to disable nothing —
    it must not fall back to the env default."""
    monkeypatch.setattr(build_utils, "OPENCODE_DISABLED_TOOLS", ["question"])
    monkeypatch.setattr(build_utils, "get_current_tenant_id", lambda: "tenant_dev")
    provider = _StubPostHogProvider(variant="none")
    monkeypatch.setattr(
        build_utils, "get_default_feature_flag_provider", lambda: provider
    )

    user = _make_user()
    assert get_opencode_disabled_tools(user) == []
    assert provider.calls == [
        (
            "onyx-craft-opencode-disabled-tools",
            user.id,
            {"tenant_id": "tenant_dev", "email": "user@tenant-dev.example"},
        )
    ]


@pytest.mark.parametrize("unrecognized_variant", ["not-a-real-variant", True, False])
def test_unrecognized_variant_falls_back_to_env(
    monkeypatch: pytest.MonkeyPatch, unrecognized_variant: str | bool
) -> None:
    monkeypatch.setattr(build_utils, "OPENCODE_DISABLED_TOOLS", ["question"])
    monkeypatch.setattr(build_utils, "get_current_tenant_id", lambda: "tenant_dev")
    provider = _StubPostHogProvider(variant=unrecognized_variant)
    monkeypatch.setattr(
        build_utils, "get_default_feature_flag_provider", lambda: provider
    )

    assert get_opencode_disabled_tools(_make_user()) == ["question"]
