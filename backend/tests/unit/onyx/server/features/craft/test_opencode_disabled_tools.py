"""`get_opencode_disabled_tools` decides which opencode tools are disabled in a
sandbox session. It is deployment-wide, not per-user: the decision collapses
two inputs: the `OPENCODE_DISABLED_TOOLS` env var (used when no real feature
flag provider is configured, or the flag's variant is unset/unrecognized) and
the PostHog `onyx-craft-opencode-disabled-tools` multivariate flag, keyed on
tenant_id rather than a per-user rollout — each variant key maps to a fixed
tools list in `OPENCODE_DISABLED_TOOLS_VARIANTS`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from onyx.feature_flags.interface import FeatureFlagProvider, NoOpFeatureFlagProvider
from onyx.server.features.build import utils as build_utils
from onyx.server.features.build.utils import get_opencode_disabled_tools


class _StubPostHogProvider(FeatureFlagProvider):
    """A non-NoOp provider that returns a fixed variant for the disabled-tools
    flag.

    Overrides `feature_variant_for_tenant` directly (the method the resolver
    calls), so `calls` captures the exact (flag_key, tenant_id) forwarded to
    PostHog.
    """

    def __init__(self, variant: str | bool | None) -> None:
        self._variant = variant
        self.calls: list[tuple[str, str]] = []

    def feature_enabled(
        self,
        flag_key: str,
        user_id: UUID,
        user_properties: dict[str, Any] | None = None,
    ) -> bool:
        raise NotImplementedError("not exercised by these tests")

    def feature_variant_for_tenant(
        self, flag_key: str, tenant_id: str
    ) -> str | bool | None:
        self.calls.append((flag_key, tenant_id))
        return self._variant


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

    assert get_opencode_disabled_tools() == ["question"]


def test_env_default_when_variant_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build_utils, "OPENCODE_DISABLED_TOOLS", ["question"])
    monkeypatch.setattr(build_utils, "get_current_tenant_id", lambda: "tenant_dev")
    provider = _StubPostHogProvider(variant=None)
    monkeypatch.setattr(
        build_utils, "get_default_feature_flag_provider", lambda: provider
    )

    assert get_opencode_disabled_tools() == ["question"]


def test_none_variant_disables_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The "none" variant is a deliberate admin choice to disable nothing —
    it must not fall back to the env default."""
    monkeypatch.setattr(build_utils, "OPENCODE_DISABLED_TOOLS", ["question"])
    monkeypatch.setattr(build_utils, "get_current_tenant_id", lambda: "tenant_dev")
    provider = _StubPostHogProvider(variant="none")
    monkeypatch.setattr(
        build_utils, "get_default_feature_flag_provider", lambda: provider
    )

    assert get_opencode_disabled_tools() == []
    assert provider.calls == [("onyx-craft-opencode-disabled-tools", "tenant_dev")]


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

    assert get_opencode_disabled_tools() == ["question"]
