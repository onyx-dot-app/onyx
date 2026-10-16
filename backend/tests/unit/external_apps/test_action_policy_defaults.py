"""Per-action ``default_policy`` on ``EndpointSpec`` and how the registry uses it.

A provider declares the out-of-the-box policy for each catalog action (defaults
to ``ASK``). The write path persists only deviations from that default
(``normalize_action_policies``); the policy views resolve missing rows back to it.
"""

from __future__ import annotations

import pytest

from onyx.db.enums import ActionPolicy, ExternalAppType
from onyx.external_apps.providers import registry
from onyx.external_apps.providers.actions import (
    EndpointSpec,
    ExternalAppAction,
    RestRoute,
)


class _TestAction(ExternalAppAction):
    READ = "test.read"
    WRITE = "test.write"


def _spec(
    action: _TestAction, default_policy: ActionPolicy | None = None
) -> EndpointSpec:
    kwargs = {} if default_policy is None else {"default_policy": default_policy}
    return EndpointSpec(
        id=action,
        normalised_name=action.value,
        description="d",
        matches=(RestRoute(method="GET", path="/x"),),
        **kwargs,
    )


def test_endpoint_spec_defaults_to_ask() -> None:
    assert _spec(_TestAction.READ).default_policy == ActionPolicy.ASK


def test_endpoint_spec_accepts_override() -> None:
    spec = _spec(_TestAction.WRITE, ActionPolicy.ALWAYS)
    assert spec.default_policy == ActionPolicy.ALWAYS


def test_normalize_action_policies_keeps_only_overrides() -> None:
    assert registry.normalize_action_policies(
        {"read": ActionPolicy.ALWAYS, "write": ActionPolicy.DENY},
        {"read": ActionPolicy.ALWAYS, "write": ActionPolicy.ASK},
    ) == {"write": ActionPolicy.DENY}


def test_action_policy_views_seed_from_each_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = [
        _spec(_TestAction.READ, ActionPolicy.ALWAYS),
        _spec(_TestAction.WRITE),  # omitted → ASK
    ]
    monkeypatch.setattr(registry, "get_endpoint_catalog", lambda _app_type: catalog)

    states = {
        v.action_id: v.state
        for v in registry.action_policy_views(ExternalAppType.SLACK, stored={})
    }
    assert states[_TestAction.READ] == ActionPolicy.ALWAYS
    assert states[_TestAction.WRITE] == ActionPolicy.ASK
