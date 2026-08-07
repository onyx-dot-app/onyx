"""`get_opencode_disabled_tools` decides which opencode tools are disabled in a
sandbox session. The decision collapses two inputs: the `OPENCODE_DISABLED_TOOLS`
env var (used when no real feature flag provider is configured, or the flag's
payload is absent/malformed) and the PostHog `onyx-craft-opencode-disabled-tools`
flag payload (used otherwise). These tests pin the precedence and the payload
validation.
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
    """A non-NoOp provider that returns a fixed payload for the disabled-tools
    flag.

    Inherits the base `feature_payload_for_user_tenant`, which is the method
    the resolver calls — so `calls` captures the `user_properties` (including
    `tenant_id`) that get forwarded to PostHog.
    """

    def __init__(self, payload: Any) -> None:
        self._payload = payload
        self.calls: list[tuple[str, UUID, dict[str, Any] | None]] = []

    def feature_enabled(
        self,
        flag_key: str,
        user_id: UUID,
        user_properties: dict[str, Any] | None = None,
    ) -> bool:
        raise NotImplementedError("not exercised by these tests")

    def feature_payload(
        self,
        flag_key: str,
        user_id: UUID,
        user_properties: dict[str, Any] | None = None,
    ) -> Any | None:
        self.calls.append((flag_key, user_id, user_properties))
        return self._payload


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


def test_env_default_when_payload_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build_utils, "OPENCODE_DISABLED_TOOLS", ["question"])
    monkeypatch.setattr(build_utils, "get_current_tenant_id", lambda: "tenant_dev")
    provider = _StubPostHogProvider(payload=None)
    monkeypatch.setattr(
        build_utils, "get_default_feature_flag_provider", lambda: provider
    )

    assert get_opencode_disabled_tools(_make_user()) == ["question"]


def test_posthog_payload_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build_utils, "OPENCODE_DISABLED_TOOLS", ["question"])
    monkeypatch.setattr(build_utils, "get_current_tenant_id", lambda: "tenant_dev")
    provider = _StubPostHogProvider(payload=["webfetch", "bash"])
    monkeypatch.setattr(
        build_utils, "get_default_feature_flag_provider", lambda: provider
    )

    user = _make_user()
    assert get_opencode_disabled_tools(user) == ["webfetch", "bash"]
    assert provider.calls == [
        (
            "onyx-craft-opencode-disabled-tools",
            user.id,
            {"tenant_id": "tenant_dev", "email": "user@tenant-dev.example"},
        )
    ]


def test_empty_posthog_payload_disables_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit `[]` payload is a deliberate admin choice, not "unset" —
    it must not fall back to the env default."""
    monkeypatch.setattr(build_utils, "OPENCODE_DISABLED_TOOLS", ["question"])
    monkeypatch.setattr(build_utils, "get_current_tenant_id", lambda: "tenant_dev")
    provider = _StubPostHogProvider(payload=[])
    monkeypatch.setattr(
        build_utils, "get_default_feature_flag_provider", lambda: provider
    )

    assert get_opencode_disabled_tools(_make_user()) == []


@pytest.mark.parametrize(
    "malformed_payload",
    [
        {"tools": ["question"]},
        "question",
        ["question", 5],
        5,
    ],
)
def test_malformed_payload_falls_back_to_env(
    monkeypatch: pytest.MonkeyPatch, malformed_payload: Any
) -> None:
    monkeypatch.setattr(build_utils, "OPENCODE_DISABLED_TOOLS", ["question"])
    monkeypatch.setattr(build_utils, "get_current_tenant_id", lambda: "tenant_dev")
    provider = _StubPostHogProvider(payload=malformed_payload)
    monkeypatch.setattr(
        build_utils, "get_default_feature_flag_provider", lambda: provider
    )

    assert get_opencode_disabled_tools(_make_user()) == ["question"]
